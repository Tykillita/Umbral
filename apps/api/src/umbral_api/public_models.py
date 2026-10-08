"""Contratos sin estado: el trabajo editorial se conserva en el dispositivo."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from .models import (
    ApiModel,
    CaseView,
    ComposeProvider,
    DraftProviderChoice,
    DraftRecord,
    EditorialPackage,
    EvidenceArticle,
    ImpactAssignment,
    OfficialContext,
    QueryRequest,
    ReviewRequest,
    ReviewStatus,
    RulesResponse,
    TopicDetail,
    ValidationReport,
)


class TopicOverride(ApiModel):
    topic_id: str = Field(min_length=1, max_length=128)
    status: ReviewStatus = ReviewStatus.nuevo
    evidence_confirmed: bool | None = None
    evidence_confirmed_by: str | None = Field(None, max_length=120)
    primary_source_confirmed: bool | None = None
    primary_source_confirmed_by: str | None = Field(None, max_length=120)
    primary_source_reason: str | None = Field(None, max_length=2000)
    impact: ImpactAssignment | None = None


class PublicContext(ApiModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    weights: dict[str, StrictInt] | None = None
    rules_version: str | None = Field(None, min_length=1, max_length=120)
    topic_overrides: list[TopicOverride] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def valid_context(self) -> PublicContext:
        if self.weights is not None:
            if set(self.weights) != {"R", "I", "U", "N", "E"}:
                raise ValueError("Se requieren los pesos R, I, U, N y E.")
            if any(w < 0 or w > 100 for w in self.weights.values()) or sum(self.weights.values()) != 100:
                raise ValueError("Los pesos deben estar entre 0 y 100 y sumar 100.")
        if len({t.topic_id for t in self.topic_overrides}) != len(self.topic_overrides):
            raise ValueError("No se pueden repetir temas en el contexto editorial.")
        return self


class AgendaFilters(ApiModel):
    limit: int = Field(5, ge=1, le=100)
    category: str | None = None
    evidence: str | None = None
    band: str | None = None
    review_status: str | None = None
    q: str | None = Field(None, max_length=500)
    include_components: bool = True
    scope: Literal["in_scope", "all"] = "in_scope"


class PublicTopicRequest(ApiModel):
    context: PublicContext
    evidence: ArchivedEvidence | None = None


class PublicAgendaRequest(PublicTopicRequest):
    filters: AgendaFilters = Field(default_factory=lambda: AgendaFilters(limit=5, q=None))


class PublicQueryRequest(QueryRequest):
    context: PublicContext


class PublicComposeRequest(PublicQueryRequest):
    provider: ComposeProvider = "gemini"


class PublicDraftRequest(PublicTopicRequest):
    topic_id: str = Field(min_length=1, max_length=128)
    provider: DraftProviderChoice = DraftProviderChoice.auto


class ArchivedEvidence(ApiModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    topic_id: str = Field(min_length=1, max_length=128)
    articles: list[EvidenceArticle] = Field(max_length=1000)
    official_context: OfficialContext
    cutoff_utc: datetime | None = None


class PublicDraftResponse(ApiModel):
    draft: DraftRecord
    notices: list[str]
    evidence: ArchivedEvidence


class PublicValidationRequest(PublicTopicRequest):
    topic_id: str = Field(min_length=1, max_length=128)
    package: EditorialPackage | None = None
    evidence: ArchivedEvidence | None = None
    case: CaseView | None = None
    review: ReviewRequest | None = None


class PublicValidationResponse(ApiModel):
    package: EditorialPackage | None
    validation: ValidationReport | None
    case: CaseView | None = None


class WorkspaceCase(ApiModel):
    case: CaseView
    detail: TopicDetail
    impact_history: list[ImpactAssignment] = Field(default_factory=list, max_length=10000)


class WorkspaceArchive(ApiModel):
    format: Literal["umbral-workspace"] = "umbral-workspace"
    version: Literal[1] = 1
    exported_at: datetime
    rules: RulesResponse
    cases: list[WorkspaceCase] = Field(default_factory=list, max_length=2000)


class WorkspaceImportResponse(ApiModel):
    imported: int
    identical: int


PublicTopicRequest.model_rebuild()
PublicAgendaRequest.model_rebuild()
PublicDraftRequest.model_rebuild()
