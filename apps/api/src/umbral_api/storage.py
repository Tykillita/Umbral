"""Persistencia detrás de una misma interfaz: memoria (pruebas), SQLite (local), Firestore (web).

Cada usuario tiene su propio espacio. Las escrituras de casos usan compare-and-swap sobre ``version``
(control de concurrencia optimista): si la versión almacenada no coincide con la esperada se lanza ``VersionConflict``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .errors import Forbidden, ServiceUnavailable, VersionConflict
from .models import CaseEvent, DraftRecord, ImpactAssignment, ReviewStatus, RulesRevision, TopicDetail


class RulesRecord(BaseModel):
    version: int = 0
    history: list[RulesRevision] = Field(default_factory=list)


class CaseRecord(BaseModel):
    """Documento persistido de un caso (usuario × tema)."""

    case_id: str
    topic_id: str
    snapshot_id: str
    rules_version: str
    version: int = 0
    status: ReviewStatus = ReviewStatus.nuevo
    reviewer: str | None = None
    evidence_confirmed: bool | None = None
    evidence_confirmed_by: str | None = None
    primary_source_confirmed: bool | None = None
    primary_source_confirmed_by: str | None = None
    primary_source_reason: str | None = None
    impact: ImpactAssignment | None = None
    impact_history: list[ImpactAssignment] = Field(default_factory=list)
    drafts: list[DraftRecord] = Field(default_factory=list)
    history: list[CaseEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    evidence_detail: TopicDetail | None = None


class Repository(ABC):
    kind = "abstract"
    note: str | None = None  # aviso visible en /health

    @abstractmethod
    def get_case(self, user: str, case_id: str) -> CaseRecord | None: ...

    @abstractmethod
    def save_case(self, user: str, case: CaseRecord, expected_version: int) -> None:
        """Guarda ``case`` (con su nueva ``version``) si la versión almacenada es ``expected_version``
        (0 = no existe). Lanza ``VersionConflict`` en caso contrario."""

    @abstractmethod
    def list_cases(self, user: str) -> list[CaseRecord]: ...

    @abstractmethod
    def incr_counter(self, user: str, key: str, limit: int | None = None) -> tuple[bool, int]:
        """Incrementa un contador (p. ej. llamadas a Gemini por día). Si ``limit`` se da y el contador ya lo
        alcanzó, no incrementa y devuelve (False, valor). Devuelve (True, nuevo valor) si se incrementó."""

    @abstractmethod
    def get_rules(self, user: str) -> RulesRecord: ...

    @abstractmethod
    def save_rules(self, user: str, record: RulesRecord, expected_version: int) -> None: ...

    def close(self) -> None:  # noqa: B027  (opcional en subclases)
        pass

    def import_workspace(self, user: str, cases: list[CaseRecord], rules: RulesRecord) -> tuple[int, int]:
        raise Forbidden("Este almacenamiento no admite importar un espacio de trabajo local.")


def _conflict(case_id: str, expected: int, current: int) -> VersionConflict:
    return VersionConflict(
        f"El caso {case_id} cambió: versión esperada {expected}, versión actual {current}. Recarga y reintenta.",
        details={"currentVersion": current, "expectedVersion": expected, "caseId": case_id},
    )


class MemoryRepository(Repository):
    kind = "memory"

    def __init__(self) -> None:
        self._cases: dict[tuple[str, str], str] = {}
        self._counters: dict[tuple[str, str], int] = {}
        self._rules: dict[str, str] = {}
        self._lock = threading.Lock()

    def get_rules(self, user: str) -> RulesRecord:
        with self._lock:
            raw = self._rules.get(user)
        return RulesRecord.model_validate_json(raw) if raw else RulesRecord()

    def save_rules(self, user: str, record: RulesRecord, expected_version: int) -> None:
        with self._lock:
            raw = self._rules.get(user)
            current = RulesRecord.model_validate_json(raw).version if raw else 0
            if current != expected_version:
                raise _conflict("scoring-rules", expected_version, current)
            self._rules[user] = record.model_dump_json()

    def get_case(self, user: str, case_id: str) -> CaseRecord | None:
        with self._lock:
            raw = self._cases.get((user, case_id))
        return CaseRecord.model_validate_json(raw) if raw else None

    def save_case(self, user: str, case: CaseRecord, expected_version: int) -> None:
        with self._lock:
            raw = self._cases.get((user, case.case_id))
            current = CaseRecord.model_validate_json(raw).version if raw else 0
            if current != expected_version:
                raise _conflict(case.case_id, expected_version, current)
            self._cases[(user, case.case_id)] = case.model_dump_json()

    def list_cases(self, user: str) -> list[CaseRecord]:
        with self._lock:
            return [CaseRecord.model_validate_json(v) for (u, _), v in self._cases.items() if u == user]

    def incr_counter(self, user: str, key: str, limit: int | None = None) -> tuple[bool, int]:
        with self._lock:
            cur = self._counters.get((user, key), 0)
            if limit is not None and cur >= limit:
                return False, cur
            self._counters[(user, key)] = cur + 1
            return True, cur + 1

    def import_workspace(self, user: str, cases: list[CaseRecord], rules: RulesRecord) -> tuple[int, int]:
        with self._lock:
            existing = {case_id: CaseRecord.model_validate_json(raw) for (owner, case_id), raw in self._cases.items() if owner == user}
            current_rules = RulesRecord.model_validate_json(self._rules[user]) if user in self._rules else RulesRecord()
            fresh, identical = _merge_workspace(existing, current_rules, cases, rules)
            for case in fresh:
                self._cases[(user, case.case_id)] = case.model_dump_json()
            if not current_rules.history:
                self._rules[user] = rules.model_dump_json()
            return len(fresh), identical


class NoWorkspaceRepository(MemoryRepository):
    """Modo público: nunca conservar casos, reglas ni contadores en memoria compartida."""

    kind = "none"

    def save_case(self, user: str, case: CaseRecord, expected_version: int) -> None:
        raise Forbidden("El trabajo editorial público se guarda únicamente en tu dispositivo.")

    def save_rules(self, user: str, record: RulesRecord, expected_version: int) -> None:
        raise Forbidden("Los pesos públicos se guardan únicamente en tu dispositivo.")

    def incr_counter(self, user: str, key: str, limit: int | None = None) -> tuple[bool, int]:
        raise Forbidden("El contador público de Gemini requiere una transacción global en Firestore.")

    def import_workspace(self, user: str, cases: list[CaseRecord], rules: RulesRecord) -> tuple[int, int]:
        raise Forbidden("El espacio de trabajo público permanece en tu dispositivo.")


class SqliteRepository(Repository):
    kind = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases(
                user_id TEXT NOT NULL, case_id TEXT NOT NULL, version INTEGER NOT NULL,
                data TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, case_id));
            CREATE TABLE IF NOT EXISTS counters(
                user_id TEXT NOT NULL, key TEXT NOT NULL, value INTEGER NOT NULL,
                PRIMARY KEY(user_id, key));
            CREATE TABLE IF NOT EXISTS scoring_rules(
                user_id TEXT PRIMARY KEY, version INTEGER NOT NULL, data TEXT NOT NULL);
            """
        )

    def get_case(self, user: str, case_id: str) -> CaseRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM cases WHERE user_id=? AND case_id=?", (user, case_id)
            ).fetchone()
        return CaseRecord.model_validate_json(row[0]) if row else None

    def save_case(self, user: str, case: CaseRecord, expected_version: int) -> None:
        data = case.model_dump_json()
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT version FROM cases WHERE user_id=? AND case_id=?", (user, case.case_id)
                ).fetchone()
                current = row[0] if row else 0
                if current != expected_version:
                    self._conn.execute("ROLLBACK")
                    raise _conflict(case.case_id, expected_version, current)
                if row:
                    self._conn.execute(
                        "UPDATE cases SET version=?, data=?, updated_at=? WHERE user_id=? AND case_id=?",
                        (case.version, data, now, user, case.case_id),
                    )
                else:
                    self._conn.execute(
                        "INSERT INTO cases(user_id, case_id, version, data, updated_at) VALUES(?,?,?,?,?)",
                        (user, case.case_id, case.version, data, now),
                    )
                self._conn.execute("COMMIT")
            except VersionConflict:
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def list_cases(self, user: str) -> list[CaseRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM cases WHERE user_id=?", (user,)).fetchall()
        return [CaseRecord.model_validate_json(r[0]) for r in rows]

    def incr_counter(self, user: str, key: str, limit: int | None = None) -> tuple[bool, int]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT value FROM counters WHERE user_id=? AND key=?", (user, key)).fetchone()
                cur = row[0] if row else 0
                if limit is not None and cur >= limit:
                    self._conn.execute("ROLLBACK")
                    return False, cur
                self._conn.execute(
                    "INSERT INTO counters(user_id,key,value) VALUES(?,?,?) "
                    "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                    (user, key, cur + 1),
                )
                self._conn.execute("COMMIT")
                return True, cur + 1
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def import_workspace(self, user: str, cases: list[CaseRecord], rules: RulesRecord) -> tuple[int, int]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute("SELECT data FROM cases WHERE user_id=?", (user,)).fetchall()
                existing = {c.case_id: c for (raw,) in rows if (c := CaseRecord.model_validate_json(raw))}
                row = self._conn.execute("SELECT data FROM scoring_rules WHERE user_id=?", (user,)).fetchone()
                current_rules = RulesRecord.model_validate_json(row[0]) if row else RulesRecord()
                fresh, identical = _merge_workspace(existing, current_rules, cases, rules)
                for case in fresh:
                    self._conn.execute("INSERT INTO cases(user_id,case_id,version,data,updated_at) VALUES(?,?,?,?,?)",
                                       (user, case.case_id, case.version, case.model_dump_json(), case.updated_at.isoformat()))
                if not current_rules.history:
                    self._conn.execute("INSERT INTO scoring_rules(user_id,version,data) VALUES(?,?,?) "
                                       "ON CONFLICT(user_id) DO UPDATE SET version=excluded.version,data=excluded.data",
                                       (user, rules.version, rules.model_dump_json()))
                self._conn.execute("COMMIT")
                return len(fresh), identical
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_rules(self, user: str) -> RulesRecord:
        with self._lock:
            row = self._conn.execute("SELECT data FROM scoring_rules WHERE user_id=?", (user,)).fetchone()
        return RulesRecord.model_validate_json(row[0]) if row else RulesRecord()

    def save_rules(self, user: str, record: RulesRecord, expected_version: int) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT version FROM scoring_rules WHERE user_id=?", (user,)).fetchone()
                current = row[0] if row else 0
                if current != expected_version:
                    raise _conflict("scoring-rules", expected_version, current)
                self._conn.execute(
                    "INSERT INTO scoring_rules(user_id,version,data) VALUES(?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET version=excluded.version,data=excluded.data",
                    (user, record.version, record.model_dump_json()),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise


class FirestoreRepository(Repository):
    """Firestore (plan Spark). Requiere el extra `firebase` y credenciales de aplicación del servidor.

    Estructura: users/{uid}/cases/{caseId} y users/{uid}/counters/{key}. Las escrituras de casos usan
    transacciones con comparación de versión.
    """

    kind = "firestore"

    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore  # type: ignore[import-not-found]

        self._fs = firestore
        self._db = firestore.Client(project=project)
        # Como en memoria/SQLite, una instancia no compite consigo misma por el mismo documento.
        # La transacción Firestore sigue siendo la autoridad entre procesos/instancias.
        self._write_lock = threading.Lock()

    def _run_transaction(self, operation):  # noqa: ANN001, ANN202
        from google.api_core.exceptions import Aborted, GoogleAPICallError

        with self._write_lock:
            try:
                return operation(self._db.transaction())
            except ValueError as exc:
                # El decorador SDK envuelve Aborted tras agotar sus reintentos en ValueError.
                if not isinstance(exc.__cause__, Aborted):
                    raise
                raise ServiceUnavailable("Firestore tiene contención temporal; vuelve a intentar sin cambiar de almacenamiento.",
                    headers={"Retry-After": "1"}) from exc
            except GoogleAPICallError as exc:
                raise ServiceUnavailable("Firestore no está disponible temporalmente; las escrituras no se trasladaron a SQLite.",
                    headers={"Retry-After": "1"}) from exc

    def _case_ref(self, user: str, case_id: str):  # noqa: ANN202
        return self._db.collection("users").document(user).collection("cases").document(case_id)

    def get_rules(self, user: str) -> RulesRecord:
        snap = self._db.collection("users").document(user).collection("settings").document("scoring").get()
        return RulesRecord.model_validate_json(snap.to_dict()["data"]) if snap.exists else RulesRecord()

    def save_rules(self, user: str, record: RulesRecord, expected_version: int) -> None:
        ref = self._db.collection("users").document(user).collection("settings").document("scoring")

        @self._fs.transactional
        def write(txn):  # noqa: ANN001, ANN202
            snap = ref.get(transaction=txn)
            current = snap.to_dict()["version"] if snap.exists else 0
            if current != expected_version:
                raise _conflict("scoring-rules", expected_version, current)
            txn.set(ref, {"version": record.version, "data": record.model_dump_json()})

        self._run_transaction(write)

    def get_case(self, user: str, case_id: str) -> CaseRecord | None:
        snap = self._case_ref(user, case_id).get()
        return CaseRecord.model_validate_json(snap.to_dict()["data"]) if snap.exists else None

    def save_case(self, user: str, case: CaseRecord, expected_version: int) -> None:
        ref = self._case_ref(user, case.case_id)
        fs = self._fs

        @fs.transactional
        def _txn(txn):  # noqa: ANN001, ANN202
            snap = ref.get(transaction=txn)
            current = snap.to_dict()["version"] if snap.exists else 0
            if current != expected_version:
                raise _conflict(case.case_id, expected_version, current)
            txn.set(ref, {"version": case.version, "data": case.model_dump_json(), "updatedAt": fs.SERVER_TIMESTAMP})

        self._run_transaction(_txn)

    def list_cases(self, user: str) -> list[CaseRecord]:
        docs = self._db.collection("users").document(user).collection("cases").stream()
        return [CaseRecord.model_validate_json(d.to_dict()["data"]) for d in docs]

    def incr_counter(self, user: str, key: str, limit: int | None = None) -> tuple[bool, int]:
        ref = self._db.collection("users").document(user).collection("counters").document(key.replace("/", "_"))
        fs = self._fs

        @fs.transactional
        def _txn(txn):  # noqa: ANN001, ANN202
            snap = ref.get(transaction=txn)
            cur = snap.to_dict().get("value", 0) if snap.exists else 0
            if limit is not None and cur >= limit:
                return False, cur
            txn.set(ref, {"value": cur + 1})
            return True, cur + 1

        return self._run_transaction(_txn)


def build_repository(kind: str, sqlite_path: Path, firestore_project: str | None) -> Repository:
    """El almacenamiento solicitado debe estar disponible; nunca perder datos cambiando de motor."""
    if kind == "none":
        return NoWorkspaceRepository()
    if kind == "memory":
        return MemoryRepository()
    if kind == "firestore":
        try:
            repo: Repository = FirestoreRepository(firestore_project)
            repo.note = None
            return repo
        except Exception as exc:  # sin extra, sin credenciales o sin proyecto
            raise RuntimeError(
                f"Firestore no disponible ({type(exc).__name__}). Instala el extra firebase y configura "
                "GOOGLE_APPLICATION_CREDENTIALS y FIREBASE_PROJECT_ID; el arranque se detuvo para conservar datos."
            ) from exc
    if kind == "sqlite":
        return SqliteRepository(sqlite_path)
    raise RuntimeError("Motor de persistencia desconocido; no se usará SQLite implícitamente.")


def dumps(obj: BaseModel) -> str:  # utilidad
    return json.dumps(obj.model_dump(mode="json", by_alias=True), ensure_ascii=False)


class PublicGeminiCounter(FirestoreRepository):
    """Único dato global público: contador UTC transaccional, sin usuarios ni trabajo editorial."""

    def reserve(self, limit: int) -> tuple[bool, int]:
        from datetime import timedelta

        now = datetime.now(UTC)
        ref = self._db.collection("publicCounters").document(f"gemini-{now:%Y%m%d}")

        @self._fs.transactional
        def write(txn):  # noqa: ANN001, ANN202
            snap = ref.get(transaction=txn)
            used = int(snap.to_dict().get("value", 0)) if snap.exists else 0
            if used >= limit:
                return False, used
            txn.set(ref, {"value": used + 1, "expiresAt": now + timedelta(days=2)})
            return True, used + 1

        return self._run_transaction(write)


def _merge_workspace(existing: dict[str, CaseRecord], current_rules: RulesRecord,
                    cases: list[CaseRecord], rules: RulesRecord) -> tuple[list[CaseRecord], int]:
    fresh, identical = [], 0
    if current_rules.history and current_rules != rules:
        raise VersionConflict("Los pesos de la copia difieren de los del dispositivo; no se reemplazó el trabajo local.")
    for case in cases:
        previous = existing.get(case.case_id)
        if previous is None:
            fresh.append(case)
        elif previous.model_dump(exclude={"evidence_detail"}) == case.model_dump(exclude={"evidence_detail"}):
            identical += 1
        else:
            raise VersionConflict("La copia contiene una versión distinta de un caso local; no se importó ningún caso.",
                                  details={"caseId": case.case_id, "currentVersion": previous.version})
    return fresh, identical
