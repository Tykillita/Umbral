"""Orquestación: agenda, ficha, consultas, borradores, revisión y exportación."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from copy import copy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .auth import Authenticator
from .config import Settings
from .drafts import EvidencePack, build_pack, build_template_package, validate_package
from .errors import (
    Forbidden,
    InvalidTransition,
    NotFound,
    RateLimited,
    Unprocessable,
    VersionConflict,
)
from .export import export_markdown
from .models import (
    CATEGORY_LABELS,
    EVIDENCE_LABELS,
    GENERATION_LABELS,
    REVIEW_LABELS,
    CaseEvent,
    CaseView,
    Category,
    Claim,
    DraftEditRequest,
    DraftProviderChoice,
    DraftRecord,
    DraftRequest,
    DraftResponse,
    EditorialPackage,
    EvidenceStatus,
    ExportResponse,
    FallbackReason,
    GenerationMode,
    HealthResponse,
    ImpactAssignment,
    ImpactRequest,
    ProviderStatus,
    QueryRequest,
    QueryResponse,
    ReviewRequest,
    ReviewStatus,
    RulesRequest,
    RulesResponse,
    RulesRevision,
    ScoreBand,
    ScoreDetail,
    SnapshotInfoResponse,
    TopicDetail,
    TopicsResponse,
    TopicSummary,
)
from .providers import (
    SYSTEM_INSTRUCTIONS,
    DraftProvider,
    GeminiProvider,
    ProviderError,
    build_providers,
    build_user_content,
)
from .queries import QueryEngine
from .retrieval import Doc, SearchIndex
from .scoring import BANDS, CHANGELOG, RULE_TEXT, RULES_VERSION, WEIGHTS, ScoreInputs, score_topic, sort_key
from .snapshot import Corpus, load_corpus
from .storage import CaseRecord, PublicGeminiCounter, Repository, build_repository
from .topics import (
    HEADLINE_NOTICE,
    TopicBase,
    assess_evidence,
    build_reporters,
    build_topic,
    official_context,
)
from .util import fmt_date_pa, now_utc

TRANSITIONS: dict[ReviewStatus, list[ReviewStatus]] = {
    ReviewStatus.nuevo: [ReviewStatus.en_revision],
    ReviewStatus.en_revision: [
        ReviewStatus.requiere_evidencia,
        ReviewStatus.aprobado_como_borrador,
        ReviewStatus.descartado,
    ],
    ReviewStatus.requiere_evidencia: [ReviewStatus.en_revision, ReviewStatus.descartado],
    ReviewStatus.aprobado_como_borrador: [ReviewStatus.en_revision],
    ReviewStatus.descartado: [ReviewStatus.en_revision],
}
CASE_PREFIX = "case-"


@dataclass(frozen=True)
class SnapshotState:
    """Una sola referencia permite cambiar corpus e índices conjuntamente."""

    corpus: Corpus
    bases: dict[str, TopicBase]
    engine: QueryEngine
    topic_index: SearchIndex


def build_snapshot_state(corpus: Corpus) -> SnapshotState:
    bases = {}
    for cluster in corpus.clusters.values():
        base = build_topic(corpus, cluster)
        if base:
            bases[base.id] = base
    return SnapshotState(corpus, bases, QueryEngine(corpus, bases),
                         SearchIndex([Doc(b.id, "tema", b.search_text) for b in bases.values()]))


class RateLimiter:
    """Ventana deslizante por usuario y por cubo (en memoria; se reinicia con el proceso)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, user: str, bucket: str, limit: int, window_s: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= 10000 and (user, bucket) not in self._hits:
                self._hits = defaultdict(deque, {key: hits for key, hits in self._hits.items()
                                                if hits and now - hits[-1] <= window_s})
                if len(self._hits) >= 10000:
                    raise RateLimited("El servicio está ocupado; vuelve a intentar en un minuto.",
                                      headers={"Retry-After": "60"})
            q = self._hits[(user, bucket)]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(window_s - (now - q[0])) + 1)
                raise RateLimited(
                    f"Límite de {limit} solicitudes por minuto excedido para «{bucket}».",
                    details={"retryAfterSeconds": retry, "bucket": bucket},
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)


class Services:
    def __init__(
        self,
        settings: Settings,
        *,
        corpus: Corpus | None = None,
        repo: Repository | None = None,
        providers: dict[str, DraftProvider] | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        current_corpus = corpus or load_corpus(settings)
        if settings.now_override:
            from .snapshot import parse_dt

            dt = parse_dt(settings.now_override)
            if dt:
                current_corpus.cutoff = dt
        self.repo = repo or build_repository(settings.persistence, settings.sqlite_path, settings.firestore_project)
        self.providers = providers or build_providers(settings)
        self.auth = Authenticator(settings.auth_mode, settings.firestore_project, trust_cloudflare_ip=settings.trust_cloudflare_ip)
        self.limiter = RateLimiter()
        self._state = build_snapshot_state(current_corpus)
        self._public_context = False
        self.public_gemini_counter: PublicGeminiCounter | None = None
        if settings.auth_mode == "public" and not settings.offline and settings.gemini_api_key and settings.firestore_project:
            try:
                self.public_gemini_counter = PublicGeminiCounter(settings.firestore_project)
            except Exception:
                # No cambiar a memoria ni exponer detalles de credenciales. El generador
                # devolverá una plantilla al no poder reservar la llamada global.
                pass
        from .public import PublicApi
        from .snapshot_feed import SnapshotFeed

        self.public = PublicApi(self)
        self.snapshot_feed = SnapshotFeed(self)

    @property
    def corpus(self) -> Corpus:
        return self._state.corpus

    @property
    def bases(self) -> dict[str, TopicBase]:
        return self._state.bases

    @property
    def engine(self) -> QueryEngine:
        return self._state.engine

    @property
    def _topic_index(self) -> SearchIndex:
        return self._state.topic_index

    def request_view(self) -> Services:
        """Cada petición usa íntegramente el snapshot vigente cuando comenzó."""
        return copy(self)

    def activate_snapshot(self, path: Path) -> str:
        corpus = load_corpus(replace(self.settings, snapshot_dir=Path(path), strict_integrity=True, allow_fixture=False))
        if corpus.contains_fixtures:
            raise RuntimeError("No se activará un snapshot con fixtures.")
        if corpus.classifier != "laya":
            raise RuntimeError("No se activará un snapshot que sustituya Laya por otro clasificador.")
        if not corpus.articles or not corpus.clusters:
            raise RuntimeError("El snapshot debe contener artículos y grupos.")
        self._state = build_snapshot_state(corpus)
        return corpus.snapshot_id

    # ------------------------------------------------------------------ puntaje y resúmenes
    def _impact_for(self, base: TopicBase, rec: CaseRecord | None) -> ImpactAssignment:
        return rec.impact if rec and rec.impact else base.proposed_impact

    @staticmethod
    def _primary_confirmed(rec: CaseRecord | None) -> bool:
        return bool(rec and rec.primary_source_confirmed)

    def _eff(self, base: TopicBase, rec: CaseRecord | None) -> EvidenceStatus:
        """Estado de evidencia vigente: el del sistema, ajustado si un revisor confirmó una fuente primaria."""
        return base.status_for(self._primary_confirmed(rec))[0]

    def _score(self, base: TopicBase, impact: ImpactAssignment, rec: CaseRecord | None = None, *, rules: RulesResponse | None = None) -> ScoreDetail:
        inp = ScoreInputs(
            geo=base.geo,
            geo_evidence_ids=base.geo_evidence_ids,
            geo_basis=[
                (a.id, a.title, a.geo_evidence)
                for a in base.usable_articles
                if a.geo_relevance == base.geo
            ][:2]
            or [(a.id, a.title, a.geo_evidence) for a in base.usable_articles[:1]],
            impact=impact,
            first_published=base.first_published,
            publish_date_issue=base.publish_date_issue,
            cutoff=self.corpus.cutoff,
            is_recirculation=base.is_recirculation,
            recirculation_reason=base.recirculation_reason,
            independent_provenances=base.independent,
            primary_source_linked=self._primary_confirmed(rec),
            primary_source_ids=base.primary_ids[:2] if self._primary_confirmed(rec) else [],
            has_outlet_original=base.has_outlet_original,
            provenance_known=base.provenance_known,
            article_ids=[a.id for a in base.usable_articles],
            sponsored=base.sponsored_only,
        )
        sc = score_topic(inp, weights=rules.weights if rules else None, rules_version=rules.rules_version if rules else RULES_VERSION)
        sc.id_tiebreak = base.id
        return sc

    def _summary(self, base: TopicBase, score: ScoreDetail, rec: CaseRecord | None, with_components: bool) -> TopicSummary:
        status = rec.status if rec else ReviewStatus.nuevo
        ev_status = self._eff(base, rec)
        needs = score.band == ScoreBand.alto and ev_status == EvidenceStatus.insuficiente
        top2 = sorted(score.components, key=lambda c: -c.points)[:2]
        reason = (
            f"Prioridad {score.band.value} ({score.total:.1f}); mayores aportes: "
            + ", ".join(f"{c.key} {c.points:g}" for c in top2)
            + f"; evidencia {ev_status.value}"
        )
        return TopicSummary(
            id=base.id,
            title=base.display_title,
            category=base.category,
            category_label=CATEGORY_LABELS[base.category.value],
            score=score.total,
            band=score.band,
            score_components=score.components if with_components else [],
            urgency=score.urgency_tiebreak,
            evidence_status=ev_status,
            evidence_status_label=EVIDENCE_LABELS[ev_status.value],
            article_count=len(base.articles),
            independent_provenances=base.independent,
            first_published_at=base.first_published,
            last_published_at=base.last_published,
            geo_relevance=base.geo,
            review_status=status,
            review_status_label=REVIEW_LABELS[status.value],
            has_contradictions=bool(base.contradictions),
            has_suspicious_source=bool(base.suspicious_ids),
            possible_sponsored=base.sponsored_only,
            headline_only=True,
            is_recirculation=base.is_recirculation,
            relevance_reason=next((c.justification for c in score.components if c.key == "R"), ""),
            out_of_scope=base.category == Category.indeterminado,
            needs_investigation=needs,
            top_reason=reason,
        )

    def _ranked(self, user: str) -> list[tuple[TopicBase, ScoreDetail, CaseRecord | None]]:
        rules = self.rules(user)
        cases = {c.topic_id: c for c in self.repo.list_cases(user)}
        rows = []
        for b in self.bases.values():
            rec = cases.get(b.id)
            rows.append((b, self._score(b, self._impact_for(b, rec), rec, rules=rules), rec))
        rows.sort(key=lambda r: sort_key(r[1].total, r[1].urgency_tiebreak, r[0].id))
        return rows

    # ------------------------------------------------------------------ estado
    def provider_statuses(self) -> list[ProviderStatus]:
        out = [p.status() for p in self.providers.values()]
        if self.settings.public_api_url and not self.settings.gemini_api_key:
            for status in out:
                if status.name == "gemini":
                    status.available = not self.settings.offline
                    status.reason = "Generación a través de la API pública con cuota global y respaldo por plantilla."
        if self.settings.auth_mode == "public" and self.public_gemini_counter is None:
            for status in out:
                if status.name == "gemini" and status.available:
                    status.available = False
                    status.reason = "El contador global seguro no está disponible; se conserva la plantilla con citas."
        out.append(
            ProviderStatus(name="recuperado", mode=GenerationMode.recuperado, external=False, local_only=False, available=True,
                           reason="Reutiliza el último borrador generado por un modelo en este caso."))
        out.append(
            ProviderStatus(name="plantilla", mode=GenerationMode.plantilla, external=False, local_only=False, available=True,
                           reason="Plantilla con citas; no requiere red."))
        return out

    def health(self) -> HealthResponse:
        c = self.corpus
        ok = c.integrity.manifest_verified and c.integrity.predictions_hash_verified is not False
        notes = list(c.notes)
        if self.repo.note:
            notes.append(self.repo.note)
        if self.settings.gemini_stub:
            notes.append(f"STUB de Gemini activo ({self.settings.gemini_stub}): solo pruebas, no es Gemini real.")
        if self.settings.offline:
            notes.append("Modo sin conexión: se bloquean las llamadas externas (Gemini, ChatGPT, Claude).")
        stale = (datetime.now(UTC) - c.cutoff).total_seconds() > self.settings.snapshot_stale_hours * 3600
        if stale:
            notes.append(f"El corte de datos supera {self.settings.snapshot_stale_hours} horas; se conserva el último snapshot válido.")
        if self.snapshot_feed.last_error:
            notes.append(self.snapshot_feed.last_error)
        return HealthResponse(
            status="ok" if ok else "degradado",
            api_version=__version__,
            snapshot_id=c.snapshot_id,
            data_mode=c.data_mode,
            provisional=c.provisional,
            contains_fixtures=c.contains_fixtures,
            classifier=c.classifier,
            rules_version=RULES_VERSION,
            cutoff_utc=c.cutoff,
            offline=self.settings.offline,
            local_mode=self.settings.local_mode,
            persistence=self.repo.kind,
            auth_mode=self.settings.auth_mode,
            counts=c.counts | {"topics": len(self.bases)},
            integrity=c.integrity,
            providers=self.provider_statuses(),
            server_time_utc=now_utc(),
            notes=notes,
            snapshot_stale=stale,
            snapshot_refresh_error=self.snapshot_feed.last_error,
            snapshot_last_checked_at=self.snapshot_feed.last_checked_at,
            deploy_commit=self.settings.deploy_commit,
        )

    def rules(self, user: str | None = None) -> RulesResponse:
        record = self.repo.get_rules(user) if user else None
        latest = record.history[-1] if record and record.history else None
        weights = latest.weights if latest else WEIGHTS
        return RulesResponse(
            rules_version=latest.rules_version if latest else RULES_VERSION,
            formula="P = " + " + ".join(f"{weights[k]}{k}" for k in WEIGHTS),
            weights=weights,
            bands=BANDS,
            rules=RULE_TEXT,
            changelog=CHANGELOG,
            version=record.version if record else 0,
            history=record.history if record else [],
        )

    def set_rules(self, user: str, request: RulesRequest) -> RulesResponse:
        record = self.repo.get_rules(user)
        if record.version != request.expected_version:
            raise VersionConflict("Las reglas cambiaron. Recarga y reintenta.", details={
                "currentVersion": record.version, "expectedVersion": request.expected_version,
            })
        revision = record.version + 1
        record.history.append(RulesRevision(
            version=revision, rules_version=f"scoring-v{revision + 1}", weights=request.weights,
            reason=request.reason.strip(), author=request.author.strip(), at=now_utc(),
        ))
        record.version = revision
        self.repo.save_rules(user, record, request.expected_version)
        return self.rules(user)

    def snapshot_info(self) -> SnapshotInfoResponse:
        c = self.corpus
        return SnapshotInfoResponse(
            snapshot_id=c.snapshot_id,
            data_mode=c.data_mode,
            manifest=c.manifest,
            quality_report=c.quality_report,
            sources=c.sources,
            metrics=c.metrics,
            integrity=c.integrity,
        )

    # ------------------------------------------------------------------ agenda / ficha
    def list_topics(
        self,
        user: str,
        *,
        limit: int,
        category: str | None,
        evidence: str | None,
        band: str | None,
        review_status: str | None,
        q: str | None,
        include_components: bool,
        scope: str = "in_scope",
    ) -> TopicsResponse:
        rows = self._ranked(user)
        applied: dict[str, object] = {"limit": limit}
        if q:
            hits, _, _ = self._topic_index.search(q, limit=len(self.bases))
            rel = {h.doc.doc_id: h.relevance for h in hits if h.coverage >= 0.6}
            rows = [r for r in rows if r[0].id in rel]
            rows.sort(key=lambda r: (-rel[r[0].id], sort_key(r[1].total, r[1].urgency_tiebreak, r[0].id)))
            applied["q"] = q
        facets: dict[str, dict[str, int]] = {"category": {}, "evidence": {}, "band": {}, "reviewStatus": {}}
        for b, sc, rec in rows:
            st = rec.status.value if rec else "nuevo"
            for k, v in (("category", b.category.value), ("evidence", self._eff(b, rec).value), ("band", sc.band.value), ("reviewStatus", st)):
                facets[k][v] = facets[k].get(v, 0) + 1
        if category:
            rows = [r for r in rows if r[0].category.value == category]
            applied["category"] = category
        if evidence:
            rows = [r for r in rows if self._eff(r[0], r[2]).value == evidence]
            applied["evidence"] = evidence
        if band:
            rows = [r for r in rows if r[1].band.value == band]
            applied["band"] = band
        if review_status:
            rows = [r for r in rows if (r[2].status.value if r[2] else "nuevo") == review_status]
            applied["reviewStatus"] = review_status
        applied["scope"] = scope
        out_count = 0
        if scope != "all" and category != "indeterminado":
            out_count = sum(1 for r in rows if r[0].category == Category.indeterminado)
            rows = [r for r in rows if r[0].category != Category.indeterminado]
        total = len(rows)
        items = []
        for i, (b, sc, rec) in enumerate(rows[:limit], 1):
            s = self._summary(b, sc, rec, include_components)
            s.rank = i
            items.append(s)
        return TopicsResponse(
            snapshot_id=self.corpus.snapshot_id,
            rules_version=self.rules(user).rules_version,
            data_mode=self.corpus.data_mode,
            cutoff_utc=self.corpus.cutoff,
            total=total,
            scope="all" if scope == "all" else "in_scope",
            out_of_scope_count=out_count,
            items=items,
            applied=applied,
            facets=facets,
        )

    def _base(self, topic_id: str) -> TopicBase:
        b = self.bases.get(topic_id)
        if not b:
            raise NotFound(f"El tema {topic_id} no existe en el snapshot {self.corpus.snapshot_id}.")
        return b

    def _topic_from_case_id(self, case_id: str) -> TopicBase:
        if not case_id.startswith(CASE_PREFIX):
            raise NotFound(f"Caso {case_id} no existe.")
        return self._base(case_id[len(CASE_PREFIX):])

    def _case_view(self, base: TopicBase, rec: CaseRecord | None, *, rules_version: str = RULES_VERSION) -> CaseView:
        status = rec.status if rec else ReviewStatus.nuevo
        drafts = list(rec.drafts) if rec else []
        return CaseView(
            case_id=CASE_PREFIX + base.id,
            topic_id=base.id,
            snapshot_id=rec.snapshot_id if rec else self.corpus.snapshot_id,
            rules_version=rec.rules_version if rec else rules_version,
            version=rec.version if rec else 0,
            persisted=rec is not None and not self._public_context,
            status=status,
            status_label=REVIEW_LABELS[status.value],
            allowed_transitions=TRANSITIONS[status],
            reviewer=rec.reviewer if rec else None,
            evidence_confirmed=rec.evidence_confirmed if rec else None,
            evidence_confirmed_by=rec.evidence_confirmed_by if rec else None,
            primary_source_confirmed=rec.primary_source_confirmed if rec else None,
            primary_source_confirmed_by=rec.primary_source_confirmed_by if rec else None,
            primary_source_reason=rec.primary_source_reason if rec else None,
            impact=rec.impact if rec else None,
            drafts=drafts,
            current_draft=drafts[-1] if drafts else None,
            history=list(rec.history) if rec else [],
            created_at=rec.created_at if rec else None,
            updated_at=rec.updated_at if rec else None,
        )

    def _recommended_action(self, base: TopicBase, score: ScoreDetail, rec: CaseRecord | None = None) -> str:
        parts: list[str] = []
        ev_status = self._eff(base, rec)
        if ev_status == EvidenceStatus.suficiente:
            parts.append("Revisar el borrador y confirmar la suficiencia de evidencia; aprobar como borrador no equivale a publicar.")
        elif ev_status == EvidenceStatus.parcial:
            parts.append("Completar las verificaciones pendientes antes de aprobar un borrador.")
        else:
            parts.append("Investigar antes de redactar: reunir una segunda procedencia independiente y la fuente primaria. No habilita publicación.")
        if base.sponsored_ids:
            parts.append("Posible contenido patrocinado: verifica el origen antes de usarlo como evidencia.")
        if score.band == ScoreBand.alto and ev_status == EvidenceStatus.insuficiente:
            parts.append("Prioridad alta con evidencia insuficiente: requiere investigación.")
        if base.contradictions:
            parts.append("Resolver las versiones incompatibles con una fuente primaria; no elegir una arbitrariamente.")
        if base.is_recirculation:
            parts.append("Verificar la fecha original: puede ser una noticia antigua recirculada.")
        if base.suspicious_ids:
            parts.append("Una fuente contiene instrucciones dirigidas a un agente: se excluyó y debe revisarse manualmente.")
        return " ".join(parts)

    def topic_detail(self, user: str, topic_id: str) -> TopicDetail:
        rec = self.repo.get_case(user, CASE_PREFIX + topic_id)
        if rec and rec.evidence_detail and rec.snapshot_id != self.corpus.snapshot_id:
            return self._archived_view(rec.evidence_detail).topic_detail(user, topic_id)
        base = self._base(topic_id)
        impact = self._impact_for(base, rec)
        score = self._score(base, impact, rec, rules=self.rules(user))
        summary = self._summary(base, score, rec, True)
        n_media = len({a.outlet for a in base.usable_articles})
        when = fmt_date_pa(base.first_published, unknown="fecha de publicación original desconocida")
        what = (
            f"{base.representative.outlet if not base.representative.suspicious_instructions else 'Una fuente no confiable'} reporta en su titular: «{base.display_title}». "
            f"{len(base.articles)} nota(s) de {n_media} medio(s), {base.independent} procedencia(s) independiente(s). "
            f"Publicación original: {when}. {HEADLINE_NOTICE}"
        )
        warnings: list[str] = []
        if self.corpus.data_mode.value != "congelado":
            warnings.append(f"Datos en modo {self.corpus.data_mode.value}: no es el paquete oficial congelado.")
        if rec and rec.snapshot_id != self.corpus.snapshot_id:
            warnings.append(f"El caso se creó con el snapshot {rec.snapshot_id}; el snapshot servido es {self.corpus.snapshot_id}.")
        if rec and rec.rules_version != score.rules_version:
            warnings.append(f"La última versión guardada del caso usó {rec.rules_version}; el puntaje actual usa {score.rules_version}.")
        if base.category == Category.indeterminado:
            warnings.append(
                "Fuera del alcance temático: el clasificador no lo asigna a ninguna de las seis categorías del reto "
                "(economía, logística/Canal, turismo, servicios públicos, eventos naturales, regulación). "
                "No aparece en la agenda por defecto; revisa manualmente la categoría."
            )
        if base.sponsored_ids:
            warnings.append(
                "Posible contenido patrocinado (la URL indica publirreportaje/patrocinado): no cuenta como procedencia "
                "independiente y E queda limitado a 0,33."
            )
        if base.suspicious_ids:
            warnings.append("Una o más fuentes contienen instrucciones; se trataron como contenido no confiable.")
        if base.publish_date_issue:
            warnings.append(base.publish_date_issue)
        ev = assess_evidence(
            base,
            rec.evidence_confirmed if rec else None,
            rec.evidence_confirmed_by if rec else None,
            self._primary_confirmed(rec),
        )
        return TopicDetail(
            summary=summary,
            snapshot_id=self.corpus.snapshot_id,
            rules_version=score.rules_version,
            data_mode=self.corpus.data_mode,
            cutoff_utc=self.corpus.cutoff,
            what_is_reported=what,
            reporters=build_reporters(base),
            articles=base.articles,
            official_context=official_context(base),
            supported_claims=base.claims,
            pending_verifications=base.pending,
            contradictions=base.contradictions,
            score=score,
            impact=impact,
            evidence=ev,
            recommended_action=self._recommended_action(base, score, rec),
            warnings=warnings,
            case=self._case_view(base, rec, rules_version=score.rules_version),
        )

    # ------------------------------------------------------------------ consultas
    def query(self, user: str, req: QueryRequest) -> QueryResponse:
        limit = min(30, self.settings.queries_per_minute) if self.settings.auth_mode == "public" else self.settings.queries_per_minute
        self.limiter.check(user, "queries", limit)
        agenda = [s for s in self.list_topics(
            user, limit=5, category=None, evidence=None, band=None, review_status=None, q=None, include_components=False
        ).items]
        response = self.engine.answer(req, agenda)
        response.rules_version = self.rules(user).rules_version
        return response

    # ------------------------------------------------------------------ casos
    def _new_record(self, base: TopicBase) -> CaseRecord:
        now = now_utc()
        return CaseRecord(
            case_id=CASE_PREFIX + base.id, topic_id=base.id, snapshot_id=self.corpus.snapshot_id,
            rules_version=RULES_VERSION, created_at=now, updated_at=now,
        )

    def _load_for_write(self, user: str, base: TopicBase, expected: int) -> CaseRecord:
        rec = self.repo.get_case(user, CASE_PREFIX + base.id)
        current = rec.version if rec else 0
        if current != expected:
            raise VersionConflict(
                f"El caso {CASE_PREFIX + base.id} cambió: versión esperada {expected}, versión actual {current}. Recarga y reintenta.",
                details={"currentVersion": current, "expectedVersion": expected, "caseId": CASE_PREFIX + base.id},
            )
        return rec or self._new_record(base)

    def _commit(self, user: str, rec: CaseRecord, expected: int, event: CaseEvent) -> CaseRecord:
        if not rec.evidence_detail and not self._public_context:
            rec.evidence_detail = self.topic_detail(user, rec.topic_id).model_copy(deep=True)
        rec.rules_version = self.rules(user).rules_version
        event.rules_version = rec.rules_version
        rec.version = expected + 1
        rec.updated_at = event.at
        event.version = rec.version
        rec.history.append(event)
        self.repo.save_case(user, rec, expected)
        return rec

    def get_case(self, user: str, case_id: str) -> CaseView:
        rec = self.repo.get_case(user, case_id)
        if rec and rec.evidence_detail and rec.snapshot_id != self.corpus.snapshot_id:
            return self._archived_view(rec.evidence_detail).get_case(user, case_id)
        base = self._topic_from_case_id(case_id)
        return self._case_view(base, rec, rules_version=self.rules(user).rules_version)

    def _archived_view(self, detail: TopicDetail) -> Services:
        """La evidencia de un caso permanece disponible aunque el tema salga del corte."""
        svc = self.request_view()
        cluster = {"clusterId": detail.summary.id, "memberArticleIds": [a.id for a in detail.articles],
                   "representativeArticleId": detail.articles[0].id,
                   "category": detail.summary.category.value,
                   "independentProvenanceCount": detail.evidence.independent_provenances,
                   "isRecirculation": detail.summary.is_recirculation,
                   "hasContradictionCandidate": bool(detail.contradictions)}
        corpus = replace(self.corpus, snapshot_id=detail.snapshot_id, data_mode=detail.data_mode,
                         cutoff=detail.cutoff_utc or self.corpus.cutoff,
                         articles={a.id: a for a in detail.articles},
                         indicators={p.id: p for p in detail.official_context.indicators},
                         clusters={detail.summary.id: cluster})
        svc._state = build_snapshot_state(corpus)
        base = svc._base(detail.summary.id)
        base.indicators = detail.official_context.indicators
        base.relation_rationale = detail.official_context.relation_rationale
        base.relation_limits = detail.official_context.limitations
        base.contradictions = detail.contradictions
        base.claims = detail.supported_claims
        base.pending = detail.pending_verifications
        return svc

    def set_impact(self, user: str, topic_id: str, req: ImpactRequest) -> CaseView:
        base = self._base(topic_id)
        if len(req.reason.strip()) < 3 or len(req.justification.strip()) < 20:
            raise Unprocessable("El cambio de impacto exige un motivo y una justificación con contenido (no solo espacios).")
        if not req.author.strip():
            raise Unprocessable("El cambio de impacto exige una persona responsable.")
        known = {a.id for a in base.articles} | {p.id for p in base.indicators}
        missing = [e for e in req.evidence_ids if e not in known]
        if missing:
            raise Unprocessable(
                "La justificación de impacto debe citar evidencia del tema; IDs inexistentes: " + ", ".join(missing),
                details={"unknownEvidenceIds": missing},
            )
        rec = self._load_for_write(user, base, req.expected_version)
        now = now_utc()
        assign = ImpactAssignment(
            level=req.level,
            justification=req.justification.strip(),
            evidence_ids=list(dict.fromkeys(req.evidence_ids)),
            origin="editorial",
            author=req.author.strip(),
            reason=req.reason.strip(),
            version=len(rec.impact_history) + 1,
            at=now,
        )
        rec.impact = assign
        rec.impact_history.append(assign)
        ev = CaseEvent(version=0, at=now, kind="impacto", actor=assign.author or "", comment=f"{assign.level.value}: {assign.reason}")
        rec = self._commit(user, rec, req.expected_version, ev)
        return self._case_view(base, rec)

    # ------------------------------------------------------------------ borradores
    def _validated_record(
        self, *, number: int, pkg: EditorialPackage, pack: EvidencePack, mode: GenerationMode, provider: str,
        model: str | None, reason: FallbackReason | None, detail: str | None, recovered_from: str | None = None,
        proposed_claims: int | None = None,
    ) -> DraftRecord:
        cleaned, report = validate_package(pkg, pack, proposed_claims=proposed_claims)
        return DraftRecord(
            draft_id="d_" + uuid.uuid4().hex[:10],
            number=number,
            generation_mode=mode,
            generation_label=GENERATION_LABELS[mode.value],
            provider=provider,
            model=model,
            fallback_reason=reason,
            fallback_detail=detail,
            recovered_from_draft_id=recovered_from,
            created_at=now_utc(),
            snapshot_id=self.corpus.snapshot_id,
            rules_version=RULES_VERSION,
            package=cleaned,
            validation=report,
        )

    def _model_package(self, base: TopicBase, out) -> EditorialPackage:  # noqa: ANN001
        claims = [
            Claim.model_validate({"id": c.id, "type": c.type, "text": c.text,
                                  "citations": [ct.model_dump() for ct in c.citations]})
            for c in out.claims
        ]
        return EditorialPackage(
            proposed_title=out.proposed_title.strip(),
            brief=out.brief_body.strip(),
            public_interest_angle=out.public_interest_angle.strip(),
            research_questions=out.research_questions,
            pending_verifications=out.pending_verifications or base.pending[:5],
            script=out.script.strip(),
            social_copy=out.social_copy.strip(),
            claims=claims,
            headline_only=True,
            headline_only_notice=HEADLINE_NOTICE,
            limitations=[
                "Basado únicamente en titular/metadatos.",
                "Las citas verifican estructura, no sustento: requieren revisión humana.",
            ],
        )

    def _reserve_gemini_call(self, user: str) -> None:
        if self.settings.auth_mode == "public":
            if self.public_gemini_counter is None:
                raise ProviderError(FallbackReason.contador_no_disponible,
                                    "El contador global seguro no está disponible; se usó una plantilla.")
            try:
                ok, used = self.public_gemini_counter.reserve(self.settings.gemini_global_calls_per_day)
            except Exception as exc:
                raise ProviderError(FallbackReason.contador_no_disponible,
                                    "No se pudo reservar una llamada en el contador global; se usó una plantilla.") from exc
            if not ok:
                raise ProviderError(FallbackReason.limite_global,
                                    f"Cuota global diaria de Gemini alcanzada ({used}/{self.settings.gemini_global_calls_per_day}).")
            return
        ok, used = self.repo.incr_counter(user, f"gemini:{datetime.now(UTC):%Y%m%d}", self.settings.gemini_calls_per_user_day)
        if not ok:
            raise ProviderError(FallbackReason.limite_por_usuario,
                f"Límite diario de llamadas a Gemini por usuario alcanzado ({used}/{self.settings.gemini_calls_per_user_day}).")

    def create_draft(self, user: str, topic_id: str, req: DraftRequest, *, client_is_local: bool, consume_limit: bool = True) -> DraftResponse:
        saved = self.repo.get_case(user, CASE_PREFIX + topic_id)
        if saved and saved.evidence_detail and saved.snapshot_id != self.corpus.snapshot_id:
            return self._archived_view(saved.evidence_detail).create_draft(
                user, topic_id, req, client_is_local=client_is_local, consume_limit=consume_limit)
        base = self._base(topic_id)
        choice = req.provider
        if choice in (DraftProviderChoice.chatgpt, DraftProviderChoice.claude) and not (
            self.settings.local_mode and client_is_local
        ):
            raise Forbidden(
                f"El adaptador «{choice.value}» solo está disponible en ejecución local (localhost).",
                details={"reason": FallbackReason.solo_localhost.value},
            )
        if consume_limit:
            self.limiter.check(user, "drafts", self.settings.drafts_per_minute)
        rec = self.repo.get_case(user, CASE_PREFIX + topic_id)
        expected = rec.version if rec else 0
        rec = rec or self._new_record(base)
        pack = build_pack(base)
        impact = self._impact_for(base, rec)
        score = self._score(base, impact, rec, rules=self.rules(user))
        notices: list[str] = []
        draft: DraftRecord | None = None
        reason: FallbackReason | None = None
        detail: str | None = None
        number = len(rec.drafts) + 1

        provider_name = {
            DraftProviderChoice.auto: "gemini",
            DraftProviderChoice.gemini: "gemini",
            DraftProviderChoice.chatgpt: "chatgpt",
            DraftProviderChoice.claude: "claude",
        }.get(choice)

        if provider_name == "gemini" and self.settings.public_api_url and not self.settings.gemini_api_key:
            try:
                draft, remote_notices = self._remote_draft(base, rec, user, number)
                notices.extend(remote_notices)
            except ProviderError as exc:
                reason, detail = exc.reason, exc.detail
                notices.append(f"No se usó la generación pública: {exc.detail}")
            provider_name = None

        if provider_name:
            prov = self.providers[provider_name]
            try:
                if self.settings.offline:
                    raise ProviderError(FallbackReason.modo_sin_conexion, "Modo sin conexión: llamadas externas bloqueadas.")
                st = prov.status()
                if not st.available:
                    raise ProviderError(
                        FallbackReason.proveedor_no_conectado if prov.local_only else FallbackReason.sin_credenciales,
                        st.reason or "Proveedor no disponible.",
                    )
                if provider_name == "gemini" and not isinstance(prov, GeminiProvider):
                    self._reserve_gemini_call(user)
                user_content = build_user_content(
                    base.display_title, pack,
                    {"snapshotId": self.corpus.snapshot_id, "rulesVersion": score.rules_version, "scope": "titular/metadatos"},
                )
                cand = None
                for attempt in (1, 2):
                    result = prov.generate(SYSTEM_INSTRUCTIONS, user_content,
                        before_call=lambda: self._reserve_gemini_call(user)) if isinstance(prov, GeminiProvider) else prov.generate(SYSTEM_INSTRUCTIONS, user_content)
                    pkg = self._model_package(base, result.output)
                    cand = self._validated_record(
                        number=number, pkg=pkg, pack=pack, mode=GenerationMode.modelo, provider=provider_name,
                        model=result.model, reason=None, detail=None, proposed_claims=len(pkg.claims),
                    )
                    cand.usage = result.usage
                    if cand.validation.ok:
                        draft = cand
                        break
                    errs = "; ".join(i.message for i in cand.validation.issues if i.severity == "error")[:400]
                    if attempt == 2:
                        raise ProviderError(FallbackReason.validacion_fallida, f"El borrador del modelo no pasó la validación: {errs}")
                    # un único reintento con la retroalimentación de la validación (cuenta contra el límite por usuario)
                    if provider_name == "gemini" and not isinstance(prov, GeminiProvider):
                        self._reserve_gemini_call(user)
                    user_content += (
                        "\n\nCORRECCIÓN: tu borrador anterior fue rechazado por estos errores de validación; "
                        "devuelve el paquete completo corregido respetando los límites: " + errs
                    )
            except ProviderError as exc:
                reason, detail = exc.reason, exc.detail
                notices.append(f"No se usó el proveedor «{provider_name}»: {exc.detail}")
        elif choice in (DraftProviderChoice.recuperado, DraftProviderChoice.plantilla):
            reason = FallbackReason.solicitado

        if draft is None and choice != DraftProviderChoice.plantilla:
            prev = next(
                (d for d in reversed(rec.drafts) if d.generation_mode in (GenerationMode.modelo, GenerationMode.recuperado)
                 and d.validation.ok),
                None,
            )
            if prev is not None:
                cand = self._validated_record(
                    number=number, pkg=prev.package, pack=pack, mode=GenerationMode.recuperado, provider="recuperado",
                    model=prev.model, reason=reason, detail=detail, recovered_from=prev.draft_id,
                    proposed_claims=len(prev.package.claims),
                )
                if cand.validation.ok:
                    draft = cand
                    notices.append("Borrador recuperado de una ejecución anterior (no se llamó a ningún modelo).")
            elif choice == DraftProviderChoice.recuperado:
                notices.append("No hay un borrador anterior generado por un modelo en este caso; se usó la plantilla.")
        if draft is None:
            pkg = build_template_package(base, score=score.total, band=score.band.value, status=self._eff(base, rec).value)
            draft = self._validated_record(
                number=number, pkg=pkg, pack=pack, mode=GenerationMode.plantilla, provider="plantilla", model=None,
                reason=reason, detail=detail, proposed_claims=len(pkg.claims),
            )
            notices.append("Borrador construido mediante plantilla con citas.")
        draft.rules_version = score.rules_version
        rec.drafts.append(draft)
        now = now_utc()
        ev = CaseEvent(
            version=0, at=now, kind="borrador", actor="sistema", draft_number=draft.number,
            comment=f"{draft.generation_label} ({draft.provider})" + (f"; respaldo: {reason.value}" if reason else ""),
        )
        rec = self._commit(user, rec, expected, ev)
        return DraftResponse(case=self._case_view(base, rec), draft=draft, notices=notices)

    def _remote_draft(self, base: TopicBase, rec: CaseRecord, user: str, number: int) -> tuple[DraftRecord, list[str]]:
        import httpx

        from .public_models import PublicDraftResponse

        public_url = self.settings.public_api_url
        if not public_url:
            raise ProviderError(FallbackReason.proveedor_no_disponible, "La API pública no está configurada.")
        if self.settings.offline:
            raise ProviderError(FallbackReason.modo_sin_conexion, "Modo sin conexión: se usó una plantilla local.")
        rules = self.rules(user)
        override = {"topicId": base.id, "status": rec.status.value, "impact": rec.impact.model_dump(mode="json", by_alias=True) if rec.impact else None,
                    "evidenceConfirmed": rec.evidence_confirmed, "primarySourceConfirmed": rec.primary_source_confirmed,
                    "primarySourceReason": rec.primary_source_reason}
        payload = {"topicId": base.id, "provider": "auto", "context": {
            "snapshotId": self.corpus.snapshot_id, "weights": rules.weights, "rulesVersion": rules.rules_version,
            "topicOverrides": [override],
        }}
        try:
            with httpx.Client(timeout=120, follow_redirects=False) as client:
                response = client.post(public_url.rstrip("/") + "/api/v1/public/drafts", json=payload)
                response.raise_for_status()
                result = PublicDraftResponse.model_validate(response.json())
        except Exception as exc:
            raise ProviderError(FallbackReason.proveedor_no_disponible,
                                "La generación pública no está disponible o usa otro corte; se conserva la plantilla local.") from exc
        if result.draft.snapshot_id != self.corpus.snapshot_id or result.evidence.topic_id != base.id:
            raise ProviderError(FallbackReason.validacion_fallida, "La generación pública devolvió un contexto diferente.")
        result.draft.package, result.draft.validation = validate_package(result.draft.package, build_pack(base),
                                                                        proposed_claims=len(result.draft.package.claims))
        if not result.draft.validation.ok:
            raise ProviderError(FallbackReason.validacion_fallida, "El paquete público no pasó la validación local de citas.")
        result.draft.number = number
        result.draft.rules_version = rules.rules_version
        return result.draft, result.notices

    def edit_draft(self, user: str, case_id: str, req: DraftEditRequest) -> CaseView:
        saved = self.repo.get_case(user, case_id)
        if saved and saved.evidence_detail and saved.snapshot_id != self.corpus.snapshot_id:
            return self._archived_view(saved.evidence_detail).edit_draft(user, case_id, req)
        base = self._topic_from_case_id(case_id)
        rec = self._load_for_write(user, base, req.expected_version)
        if not rec.drafts:
            raise NotFound("El caso no tiene borrador que editar.")
        cur = rec.drafts[-1]
        pkg = cur.package.model_copy(deep=True)
        for field in ("proposed_title", "brief", "public_interest_angle", "research_questions", "pending_verifications", "script", "social_copy"):
            v = getattr(req, field)
            if v is not None:
                setattr(pkg, field, v)
        if req.claims is not None:
            pkg.claims = [Claim.model_validate(c.model_dump()) for c in req.claims]
        pack = build_pack(base)
        cleaned, report = validate_package(pkg, pack, proposed_claims=len(pkg.claims))
        now = now_utc()
        if not req.editor.strip():
            raise Unprocessable("La edición exige una persona responsable.")
        cur = cur.model_copy(update={
            "draft_id": "d_" + uuid.uuid4().hex[:10], "number": len(rec.drafts) + 1,
            "previous_draft_id": cur.draft_id, "created_at": now,
            "package": cleaned, "validation": report, "edited_by": req.editor.strip(), "edited_at": now,
            "rules_version": self.rules(user).rules_version,
        })
        rec.drafts.append(cur)
        ev = CaseEvent(version=0, at=now, kind="edicion_borrador", actor=req.editor.strip(), draft_number=cur.number,
                       comment="Edición humana" + ("" if report.ok else " (con errores de validación)"))
        rec = self._commit(user, rec, req.expected_version, ev)
        return self._case_view(base, rec)

    # ------------------------------------------------------------------ revisión
    def review(self, user: str, case_id: str, req: ReviewRequest) -> CaseView:
        saved = self.repo.get_case(user, case_id)
        if saved and saved.evidence_detail and saved.snapshot_id != self.corpus.snapshot_id:
            return self._archived_view(saved.evidence_detail).review(user, case_id, req)
        base = self._topic_from_case_id(case_id)
        rec = self._load_for_write(user, base, req.expected_version)
        if not req.reviewer.strip():
            raise Unprocessable("La revisión exige una persona responsable.")
        cur = rec.status
        target = req.status
        if target not in TRANSITIONS[cur]:
            raise InvalidTransition(
                f"Transición no permitida: {cur.value} → {target.value}.",
                details={"from": cur.value, "to": target.value, "allowed": [s.value for s in TRANSITIONS[cur]]},
            )
        comment = (req.comment or "").strip()
        if target in (ReviewStatus.requiere_evidencia, ReviewStatus.descartado) and not comment:
            raise Unprocessable(f"El estado «{target.value}» requiere un comentario del revisor.")
        if target == ReviewStatus.aprobado_como_borrador:
            if not rec.drafts:
                raise Unprocessable("No se puede aprobar como borrador sin un borrador generado.")
            if not rec.drafts[-1].validation.ok:
                raise Unprocessable("El borrador vigente tiene errores de validación; corrígelos antes de aprobar.")
            confirmed = req.evidence_confirmed if req.evidence_confirmed is not None else rec.evidence_confirmed
            if confirmed is False:
                raise Unprocessable("El revisor niega la suficiencia de evidencia: use «requiere_evidencia».")
            if self._eff(base, rec) == EvidenceStatus.insuficiente and not (confirmed is True and comment):
                raise Unprocessable(
                    "La evidencia es insuficiente: solo puede aprobarse si el revisor confirma la suficiencia "
                    "(evidenceConfirmed=true) con un comentario. Aprobar un borrador no es publicar."
                )
            if base.suspicious_ids and not comment:
                raise Unprocessable("Hay una fuente con instrucciones excluida: se requiere un comentario que confirme su revisión.")
        if req.primary_source_confirmed is True and not comment:
            raise Unprocessable(
                "Confirmar una fuente primaria exige un comentario con el motivo y la fuente (qué documento o entidad respalda ESE hecho)."
            )
        now = now_utc()
        rec.status = target
        rec.reviewer = req.reviewer.strip()
        if req.primary_source_confirmed is not None:
            rec.primary_source_confirmed = req.primary_source_confirmed
            rec.primary_source_confirmed_by = req.reviewer.strip()
            rec.primary_source_reason = comment or None
        if req.evidence_confirmed is not None:
            rec.evidence_confirmed = req.evidence_confirmed
            rec.evidence_confirmed_by = req.reviewer.strip()
        ev = CaseEvent(version=0, at=now, kind="revision", actor=req.reviewer.strip(), from_status=cur, to_status=target,
                       comment=comment or None, draft_number=rec.drafts[-1].number if rec.drafts else None)
        rec = self._commit(user, rec, req.expected_version, ev)
        return self._case_view(base, rec)

    # ------------------------------------------------------------------ exportación
    def export(self, user: str, case_id: str) -> ExportResponse:
        saved = self.repo.get_case(user, case_id)
        if saved and saved.evidence_detail and saved.snapshot_id != self.corpus.snapshot_id:
            return self._archived_view(saved.evidence_detail).export(user, case_id)
        base = self._topic_from_case_id(case_id)
        detail = self.topic_detail(user, base.id)
        md = export_markdown(detail)
        return ExportResponse(
            case_id=case_id,
            filename=f"umbral-{base.id}.md",
            markdown=md,
            snapshot_id=self.corpus.snapshot_id,
            rules_version=detail.rules_version,
            generated_at=now_utc(),
        )

    def export_workspace(self, user: str):  # noqa: ANN202
        from .public_models import WorkspaceArchive, WorkspaceCase

        if not self.settings.local_mode or self.settings.auth_mode != "local":
            raise Forbidden("La copia del espacio de trabajo del servidor solo existe en la sesión local.")
        cases = []
        for record in self.repo.list_cases(user):
            detail = record.evidence_detail.model_copy(deep=True) if record.evidence_detail else self.topic_detail(user, record.topic_id)
            view = self.get_case(user, record.case_id)
            detail.case = view
            cases.append(WorkspaceCase(case=view, detail=detail, impact_history=record.impact_history))
        return WorkspaceArchive(exported_at=now_utc(), rules=self.rules(user), cases=cases)

    def import_workspace(self, user: str, archive):  # noqa: ANN001, ANN202
        from .public_models import WorkspaceImportResponse
        from .storage import RulesRecord

        if not self.settings.local_mode or self.settings.auth_mode != "local":
            raise Forbidden("La restauración del espacio de trabajo requiere una sesión local.")
        records = []
        ids = set()
        for entry in archive.cases:
            case, detail = entry.case, entry.detail
            if (case.case_id in ids or case.case_id != CASE_PREFIX + case.topic_id or detail.summary.id != case.topic_id
                or detail.snapshot_id != case.snapshot_id or not detail.articles):
                raise Unprocessable("La copia contiene un caso duplicado o evidencia de otro tema/snapshot.")
            ids.add(case.case_id)
            if case.version != len(case.history) or [e.version for e in case.history] != list(range(1, case.version + 1)):
                raise Unprocessable("El historial de cada caso debe corresponder a su versión.")
            detail = detail.model_copy(deep=True)
            record = CaseRecord.model_validate(case.model_dump(exclude={"current_draft", "persisted", "allowed_transitions", "status_label"}) | {
                "created_at": case.created_at or now_utc(), "updated_at": case.updated_at or now_utc(),
                "evidence_detail": detail,
                "impact_history": entry.impact_history or ([case.impact] if case.impact and case.impact.origin == "editorial" else []),
            })
            if record.impact_history:
                first_version = record.impact_history[0].version
                if first_version < 1 or [impact.version for impact in record.impact_history] != list(range(first_version, first_version + len(record.impact_history))):
                    raise Unprocessable("El historial de impacto debe conservar sus versiones consecutivas.")
                if record.impact_history[-1] != record.impact:
                    raise Unprocessable("El impacto vigente debe coincidir con la última asignación guardada.")
                known = {a.id for a in detail.articles} | {p.id for p in detail.official_context.indicators}
                for impact in record.impact_history:
                    if (impact.origin != "editorial" or not (impact.author or "").strip() or len((impact.reason or "").strip()) < 3
                        or len(impact.justification.strip()) < 20 or not impact.evidence_ids or not set(impact.evidence_ids).issubset(known)):
                        raise Unprocessable("El historial de impacto exige autor, motivo, justificación y evidencia original válida.")
            view = self._archived_view(detail)
            for draft in record.drafts:
                draft.package, draft.validation = validate_package(draft.package, build_pack(view._base(case.topic_id)),
                                                                   proposed_claims=len(draft.package.claims))
            records.append(record)
        rules = archive.rules
        if rules.version != len(rules.history) or [r.version for r in rules.history] != list(range(1, rules.version + 1)):
            raise Unprocessable("El historial de pesos debe corresponder a su versión.")
        for revision in rules.history:
            RulesRequest(expected_version=0, weights=revision.weights, reason=revision.reason, author=revision.author)
        if not rules.history and rules.weights != WEIGHTS:
            raise Unprocessable("Los pesos modificados deben incluir su historial.")
        imported, identical = self.repo.import_workspace(user, records, RulesRecord(version=rules.version, history=rules.history))
        return WorkspaceImportResponse(imported=imported, identical=identical)


def build_services(settings: Settings) -> Services:
    return Services(settings)
