"""Servicios públicos: contexto aislado por petición y generación global acotada."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import replace
from typing import TYPE_CHECKING

from .drafts import build_pack, validate_package
from .errors import Forbidden, Unprocessable, VersionConflict
from .models import GENERATION_LABELS, DraftProviderChoice, DraftRequest, GenerationMode, RulesRevision
from .public_models import (
    ArchivedEvidence,
    PublicContext,
    PublicDraftRequest,
    PublicDraftResponse,
    PublicValidationRequest,
    PublicValidationResponse,
)
from .security import looks_like_instruction
from .storage import CaseRecord, MemoryRepository, RulesRecord
from .util import now_utc

if TYPE_CHECKING:
    from .services import Services


class PublicApi:
    def __init__(self, services: Services) -> None:
        self.services = services
        self._cache: OrderedDict[str, tuple[float, PublicDraftResponse]] = OrderedDict()
        # Serializa la reserva/cache de generación, evitando consumir dos llamadas para
        # el mismo resultado cuando llegan solicitudes simultáneas.
        self._draft_lock = threading.Lock()

    def context(self, context: PublicContext, user: str, *, allow_archived: bool = False, seed: bool = True) -> Services:
        svc = self.services.request_view()
        if not allow_archived and context.snapshot_id != svc.corpus.snapshot_id:
            raise VersionConflict("El snapshot cambió; actualiza la agenda y conserva tu trabajo local.",
                                  details={"currentSnapshotId": svc.corpus.snapshot_id,
                                           "requestedSnapshotId": context.snapshot_id})
        svc.repo = MemoryRepository()
        svc._public_context = True
        if seed:
            self._seed(svc, context, user)
        return svc

    @staticmethod
    def _seed(svc: Services, context: PublicContext, user: str) -> None:
        if context.weights is not None:
            digest = hashlib.sha256(json.dumps(context.weights, sort_keys=True).encode()).hexdigest()[:8]
            svc.repo.save_rules(user, RulesRecord(history=[RulesRevision(
                version=0, rules_version=context.rules_version or f"scoring-local-{digest}",
                weights=context.weights, reason="Contexto del dispositivo", author="dispositivo", at=now_utc(),
            )]), 0)
        for override in context.topic_overrides:
            if override.topic_id not in svc.bases:
                continue  # casos archivados no afectan el ranking del snapshot nuevo
            base = svc._base(override.topic_id)
            if override.primary_source_confirmed and not (override.primary_source_reason or "").strip():
                raise Unprocessable("Confirmar una fuente primaria exige un motivo y la fuente.")
            if override.impact is not None:
                known = {a.id for a in base.articles} | {p.id for p in base.indicators}
                if not override.impact.evidence_ids or not set(override.impact.evidence_ids).issubset(known):
                    raise Unprocessable("El impacto debe citar evidencia del tema.")
                if len(override.impact.justification.strip()) < 20:
                    raise Unprocessable("El impacto exige una justificación de al menos 20 caracteres.")
            record = svc._new_record(base)
            for field in ("status", "evidence_confirmed", "evidence_confirmed_by", "primary_source_confirmed",
                          "primary_source_confirmed_by", "primary_source_reason", "impact"):
                setattr(record, field, getattr(override, field))
            svc.repo.save_case(user, record, 0)

    def draft(self, body: PublicDraftRequest, user: str) -> PublicDraftResponse:
        if body.provider in {DraftProviderChoice.chatgpt, DraftProviderChoice.claude}:
            raise Forbidden("Las conexiones personales solo están disponibles en la aplicación local.")
        if body.provider == DraftProviderChoice.recuperado:
            raise Unprocessable("Recupera el borrador anterior desde tu espacio de trabajo local.")
        svc = self.context(body.context, user)
        svc.limiter.check(user, "drafts", min(2, svc.settings.drafts_per_minute))
        payload = body.model_dump(mode="json") | {
            "model": svc.settings.gemini_model, "fallbackModel": svc.settings.gemini_fallback_model,
        }
        key = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._draft_lock:
            now = time.monotonic()
            while self._cache and now - next(iter(self._cache.values()))[0] > 3600:
                self._cache.popitem(last=False)
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] <= 3600:
                response = cached[1].model_copy(deep=True)
                response.draft.recovered_from_draft_id = response.draft.draft_id
                response.draft.draft_id = "d_" + uuid.uuid4().hex[:10]
                response.draft.generation_mode = GenerationMode.recuperado
                response.draft.generation_label = GENERATION_LABELS[GenerationMode.recuperado.value]
                response.draft.provider = "recuperado"
                response.draft.created_at = now_utc()
                response.draft.usage = None
                response.notices.append("Se reutilizó un resultado compatible; no se llamó de nuevo a Gemini.")
                return response
            result = svc.create_draft(user, body.topic_id, DraftRequest(provider=body.provider),
                                      client_is_local=False, consume_limit=False)
            detail = svc.topic_detail(user, body.topic_id)
            response = PublicDraftResponse(draft=result.draft, notices=result.notices, evidence=ArchivedEvidence(
                snapshot_id=detail.snapshot_id, topic_id=body.topic_id, articles=detail.articles,
                official_context=detail.official_context, cutoff_utc=detail.cutoff_utc,
            ))
            # Solo resultados del modelo, no datos importados/ediciones de un visitante.
            if response.draft.generation_mode == GenerationMode.modelo:
                self._cache[key] = (now, response.model_copy(deep=True))
                while len(self._cache) > 128:
                    self._cache.popitem(last=False)
            return response

    def with_evidence(self, context: PublicContext, evidence: ArchivedEvidence | None, user: str, topic_id: str) -> Services:
        svc = self.context(context, user, allow_archived=evidence is not None, seed=evidence is None)
        if evidence is not None:
            if evidence.topic_id != topic_id or evidence.snapshot_id != context.snapshot_id:
                raise Unprocessable("La evidencia archivada debe corresponder al tema y snapshot solicitados.")
            arts = {}
            for original in evidence.articles:
                if original.id in arts or original.cluster_id not in {None, topic_id}:
                    raise Unprocessable("Evidencia duplicada o ajena al tema.")
                article = original.model_copy(deep=True)
                article.suspicious_instructions = article.suspicious_instructions or looks_like_instruction(article.title)
                arts[article.id] = article
            if not arts:
                raise Unprocessable("La evidencia archivada debe incluir artículos.")
            cluster = {"clusterId": topic_id, "memberArticleIds": list(arts),
                       "representativeArticleId": next(iter(arts))}
            corpus = replace(svc.corpus, snapshot_id=evidence.snapshot_id, articles=arts,
                             indicators={p.id: p for p in evidence.official_context.indicators},
                             cutoff=evidence.cutoff_utc or svc.corpus.cutoff, clusters={topic_id: cluster})
            from .services import build_snapshot_state

            svc._state = build_snapshot_state(corpus)
            base = svc._base(topic_id)
            # Mantener exactamente el contexto oficial archivado; una nueva relación
            # léxica no puede sustituir citas guardadas en el dispositivo.
            base.indicators = evidence.official_context.indicators
            self._seed(svc, context, user)
        return svc

    def validate(self, body: PublicValidationRequest, user: str) -> PublicValidationResponse:
        svc = self.with_evidence(body.context, body.evidence, user, body.topic_id)
        base = svc._base(body.topic_id)
        cleaned, report = (validate_package(body.package, build_pack(base), proposed_claims=len(body.package.claims))
                           if body.package is not None else (None, None))
        candidate = None
        if body.review is not None:
            if body.case is None or body.case.topic_id != body.topic_id or body.case.case_id != "case-" + body.topic_id:
                raise Unprocessable("La revisión exige el caso local correspondiente al tema.")
            local_case = body.case.model_copy(deep=True)
            if local_case.snapshot_id != body.context.snapshot_id:
                raise Unprocessable("El caso y el contexto deben usar el mismo snapshot.")
            if local_case.primary_source_confirmed and not (local_case.primary_source_reason or "").strip():
                raise Unprocessable("La confirmación primaria del caso requiere motivo y fuente.")
            record = CaseRecord.model_validate(local_case.model_dump(exclude={"current_draft", "persisted", "allowed_transitions", "status_label"}) | {
                "created_at": local_case.created_at or now_utc(), "updated_at": local_case.updated_at or now_utc(),
            })
            if record.drafts:
                current = record.drafts[-1]
                # No confiar en validation.ok importado desde el navegador.
                current.package, current.validation = validate_package(
                    cleaned or current.package, build_pack(base),
                    proposed_claims=len((cleaned or current.package).claims),
                )
                if cleaned is not None and report is not None:
                    current.package, current.validation = cleaned, report
            elif cleaned is not None:
                raise Unprocessable("El caso debe incluir el borrador que se va a revisar.")
            svc.repo = MemoryRepository()
            self._seed(svc, body.context, user)
            existing = svc.repo.get_case(user, record.case_id)
            svc.repo.save_case(user, record, existing.version if existing else 0)
            candidate = svc.review(user, record.case_id, body.review)
        elif body.package is None:
            raise Unprocessable("Envía un paquete editorial o una revisión del caso.")
        return PublicValidationResponse(package=cleaned, validation=report, case=candidate)
