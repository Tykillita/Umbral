"""Infraestructura de pruebas: arranca el backend REAL como subproceso contra un snapshot controlado.

Variables útiles:
  UMBRAL_TESTS_STRICT=1   Si el servidor no arranca, FALLA (en vez de saltar). CI lo activa.
  UMBRAL_TESTS_API_URL    Usa un servidor ya levantado en vez de lanzar uno (no se pueden forzar modos).
"""

from __future__ import annotations

import json
import hashlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from support.build_snapshot import build_snapshot  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# Navegadores de Playwright dentro del proyecto (no se instala nada fuera de tests/).
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(__file__).resolve().parent / ".browsers"))
API_DIR = REPO / "apps" / "api"
STRICT = os.environ.get("UMBRAL_TESTS_STRICT", "") in {"1", "true", "yes"}
RESULTS = Path(__file__).parent / ".results"
FAKE_GEMINI_KEY = "TESTKEY_NOT_A_REAL_KEY_0123456789"  # centinela: nunca debe aparecer en una respuesta


def _free_port() -> int:
    # Chromium rejects several otherwise valid server ports, and some Windows
    # configurations include 4045 in the ephemeral range. Stay in the high
    # dynamic range; under xdist, each worker gets a disjoint range to avoid
    # port races when their API servers start concurrently.
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    worker_index = int(worker[2:]) if worker.startswith("gw") and worker[2:].isdigit() else 0
    worker_count = max(int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", str(worker_index + 1))), 1)
    first = 49152
    port_count = 65536 - first
    start = first + worker_index * port_count // worker_count
    stop = first + (worker_index + 1) * port_count // worker_count
    for port in range(start, stop):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError("No hay puertos locales libres en el rango dinámico seguro para Chromium.")


def _unavailable(msg: str):
    if STRICT:
        pytest.fail(msg, pytrace=False)
    pytest.skip(msg)


class ApiServer:
    """Servidor uvicorn (backend real) en un puerto libre."""

    def __init__(self, env: dict[str, str], log_path: Path):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = env
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None

    def start(self, timeout: float = 90.0) -> None:
        env = {**os.environ, **self.env}
        env.setdefault("PYTHONUTF8", "1")
        env.pop("VIRTUAL_ENV", None)  # que `uv run` use el .venv de apps/api
        self.log = self.log_path.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            ["uv", "run", "uvicorn", "umbral_api.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=API_DIR, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                break
            try:
                if httpx.get(self.url + "/api/v1/health", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.4)
        tail = self.log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
        self.stop()
        _unavailable(f"el servidor del backend no arrancó (¿falta apps/api/src/umbral_api/main.py?). Registro:\n{tail}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            if os.name == "nt":  # `uv run` lanza uvicorn como hijo: hay que matar el árbol completo
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "log", None):
            self.log.close()

    def client(self, user: str | None = "tester", **kw) -> httpx.Client:
        headers = {"X-Umbral-User": user} if user else {}
        return httpx.Client(base_url=self.url + "/api/v1", headers=headers, timeout=60, **kw)


@pytest.fixture(scope="session")
def snapshot(tmp_path_factory) -> dict:
    """Snapshot sintético controlado. Devuelve {dir, index, id}."""
    root = tmp_path_factory.mktemp("snap")
    d = build_snapshot(root)
    index = json.loads((root / f"{d.name}.index.json").read_text(encoding="utf-8"))
    return {"dir": d, "index": index, "id": d.name, "root": root}


@pytest.fixture(scope="session")
def server_factory(snapshot, tmp_path_factory) -> Iterator[Callable[..., ApiServer]]:
    """`with server_factory(**env) as srv:` -> ApiServer ya arrancado; se detiene al salir."""
    servers: list[ApiServer] = []
    counter = {"n": 0}

    @contextmanager
    def make(*, snapshot_dir: Path | None = None, sqlite: Path | None = None, netblock: bool = False,
             web_dist: Path | None = None, unset: tuple[str, ...] = (), **env: str) -> Iterator[ApiServer]:
        counter["n"] += 1
        work = tmp_path_factory.mktemp(f"srv{counter['n']}")
        base = {
            "UMBRAL_SNAPSHOT_DIR": str(snapshot_dir or snapshot["dir"]),
            "UMBRAL_AUTH_MODE": "dev-header",
            "UMBRAL_LOCAL_MODE": "1",
            "UMBRAL_PERSISTENCE": "sqlite",
            "UMBRAL_SQLITE_PATH": str(sqlite or (work / "umbral.sqlite")),
            "UMBRAL_ALLOW_FIXTURE": "0",
            "UMBRAL_WEB_DIST": str(web_dist or (work / "sin-web")),
            "UMBRAL_QUERIES_PER_MINUTE": "1000",
            "UMBRAL_DRAFTS_PER_MINUTE": "1000",
            "GEMINI_API_KEY": "",
            "UMBRAL_GEMINI_STUB": "",
            "GEMINI_CALLS_PER_USER_DAY": "20",
        }
        base.update(env)
        if netblock:
            base["PYTHONPATH"] = str(Path(__file__).parent / "support" / "netblock")
            base["UMBRAL_NETBLOCK_LOG"] = str(work / "netblock.log")
        merged = {k: v for k, v in base.items() if k not in unset}
        srv = ApiServer(merged, work / "server.log")
        srv.workdir = work  # type: ignore[attr-defined]
        srv.start()
        servers.append(srv)
        try:
            yield srv
        finally:
            srv.stop()

    yield make
    for s in servers:
        s.stop()


@pytest.fixture(scope="session")
def api(server_factory) -> Iterator[ApiServer]:
    """Servidor estándar: dev-header, SQLite temporal, sin Gemini (plantilla), con red normal."""
    url = os.environ.get("UMBRAL_TESTS_API_URL")
    if url:
        srv = ApiServer({}, Path(os.devnull))
        srv.url = url.rstrip("/")
        yield srv
        return
    with server_factory() as srv:
        yield srv


# --------------------------------------------------------------------------- utilidades de prueba


class Topics:
    """Ayuda para localizar temas por los artículos sintéticos conocidos (clave -> articleId)."""

    def __init__(self, srv: ApiServer, snapshot: dict):
        self.srv = srv
        self.snap = snapshot
        self._by_article: dict[str, dict] | None = None

    def all_details(self, user: str = "tester") -> list[dict]:
        with self.srv.client(user) as c:
            items = c.get("/topics", params={"limit": 100, "scope": "all"}).json()["items"]
            return [c.get(f"/topics/{t['id']}").json() for t in items]

    def of(self, article_key: str, user: str = "tester") -> dict:
        """Detalle (TopicDetail) del tema que contiene el artículo sintético `article_key`."""
        aid = self.snap["index"]["articleIds"][article_key]
        if self._by_article is None:
            self._by_article = {}
            for d in self.all_details(user):
                for a in d["articles"]:
                    self._by_article[a["id"]] = d
        assert aid in self._by_article, f"el artículo {article_key} ({aid}) no aparece en ningún tema"
        return self._by_article[aid]


@pytest.fixture(scope="session")
def topics(api, snapshot) -> Topics:
    return Topics(api, snapshot)


def words(text: str) -> int:
    return len([w for w in text.split() if w])


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ANN001
    # xdist's controller aggregates results and writes one complete summary;
    # workers must not race to replace the same artifact with partial reports.
    if hasattr(config, "workerinput"):
        return
    tr = terminalreporter
    summary = {k: len(tr.stats.get(k, [])) for k in ("passed", "failed", "skipped", "xfailed", "xpassed", "error")}
    summary["fecha_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary["exitstatus"] = int(exitstatus)
    summary["pytestArgs"] = list(config.invocation_params.args)
    summary["pythonVersion"] = sys.version.split()[0]
    summary["sourceSha256"] = {
        p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for base in (REPO / "apps" / "api" / "src", Path(__file__).parent / "integration",
                     Path(__file__).parent / "e2e", Path(__file__).parent / "support")
        for p in sorted(base.rglob("*.py"))
    }
    current = REPO / "data" / "snapshots" / "CURRENT"
    if current.exists():
        snapshot_id = current.read_text(encoding="utf-8").strip()
        manifest = current.parent / snapshot_id / "manifest.json"
        if manifest.is_file():
            summary["deliveredSnapshot"] = {
                "snapshotId": snapshot_id,
                "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }
    summary["noPasaron"] = [
        {"id": r.nodeid, "resultado": r.outcome, "motivo": (str(getattr(r, "longrepr", ""))[:300])}
        for k in ("failed", "skipped", "error") for r in tr.stats.get(k, []) if hasattr(r, "nodeid")
    ]
    try:
        RESULTS.mkdir(exist_ok=True)
        report = json.dumps(summary, ensure_ascii=False, indent=2)
        (RESULTS / "ultimo-resumen.json").write_text(report, encoding="utf-8")
        selection = "e2e" if "e2e" in config.invocation_params.args else "integration" if "integration" in config.invocation_params.args else "selected"
        name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + selection + ".json"
        (RESULTS / name).write_text(report, encoding="utf-8")
    except OSError:
        pass
