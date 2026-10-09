"""Modelos Pydantic del contrato público (JSON camelCase bajo /api/v1).

Todo cambio aquí es un cambio de contrato: regenerar ``openapi.json`` y avisar a frontend y calidad.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, json_schema_serialization_defaults_required=True
    )


# --------------------------------------------------------------------------- enums


class Category(StrEnum):
    economia = "economia"
    logistica_canal = "logistica_canal"
    turismo = "turismo"
    servicios_publicos = "servicios_publicos"
    eventos_naturales = "eventos_naturales"
    regulacion = "regulacion"
    indeterminado = "indeterminado"


CATEGORY_LABELS: dict[str, str] = {
    "economia": "Economía",
    "logistica_canal": "Logística / Canal",
    "turismo": "Turismo",
    "servicios_publicos": "Servicios públicos",
    "eventos_naturales": "Eventos naturales",
    "regulacion": "Regulación",
    "indeterminado": "Indeterminado",
}


class GeoRelevance(StrEnum):
    """Mismos valores que ``predictions.geoRelevance`` del snapshot."""

    panama = "panama"
    regional = "regional"
    none = "none"
    indeterminate = "indeterminate"


GEO_LABELS = {
    "panama": "Panamá",
    "regional": "Relación regional",
    "none": "Sin relación",
    "indeterminate": "Indeterminada",
}


class EvidenceStatus(StrEnum):
    insuficiente = "insuficiente"
    parcial = "parcial"
    suficiente = "suficiente"


EVIDENCE_LABELS = {
    "insuficiente": "Insuficiente",
    "parcial": "Parcial",
    "suficiente": "Suficiente para el borrador",
}


class ScoreBand(StrEnum):
    bajo = "bajo"
    medio = "medio"
    alto = "alto"


class ImpactLevel(StrEnum):
    bajo = "bajo"
    medio = "medio"
    alto = "alto"


class ReviewStatus(StrEnum):
    nuevo = "nuevo"
    en_revision = "en_revision"
    requiere_evidencia = "requiere_evidencia"
    aprobado_como_borrador = "aprobado_como_borrador"
    descartado = "descartado"


REVIEW_LABELS = {
    "nuevo": "Nuevo",
    "en_revision": "En revisión",
    "requiere_evidencia": "Requiere evidencia",
    "aprobado_como_borrador": "Aprobado como borrador",
    "descartado": "Descartado",
}


class ClaimType(StrEnum):
    hecho = "hecho"
    declaracion = "declaracion"
    inferencia = "inferencia"
    hipotesis = "hipotesis"


class GenerationMode(StrEnum):
    modelo = "modelo"  # generado por un modelo (Gemini / ChatGPT / Claude)
    recuperado = "recuperado"  # recuperado de una ejecución anterior
    plantilla = "plantilla"  # construido mediante plantilla con citas


GENERATION_LABELS = {
    "modelo": "Generado por un modelo",
    "recuperado": "Recuperado de una ejecución anterior",
    "plantilla": "Construido mediante plantilla",
}


class DraftProviderChoice(StrEnum):
    auto = "auto"
    gemini = "gemini"
    recuperado = "recuperado"
    plantilla = "plantilla"
    chatgpt = "chatgpt"  # solo localhost
    claude = "claude"  # solo localhost


class FallbackReason(StrEnum):
    modo_sin_conexion = "modo_sin_conexion"
    cuota_agotada = "cuota_agotada"
    limite_por_usuario = "limite_por_usuario"
    proveedor_no_disponible = "proveedor_no_disponible"
    proveedor_no_conectado = "proveedor_no_conectado"
    sin_credenciales = "sin_credenciales"
    validacion_fallida = "validacion_fallida"
    solo_localhost = "solo_localhost"
    solicitado = "solicitado"
    contador_no_disponible = "contador_no_disponible"
    limite_global = "limite_global"
    sin_evidencia = "sin_evidencia"


class DataMode(StrEnum):
    fixture = "fixture"
    provisional = "provisional"
    congelado = "congelado"


class AnswerStatus(StrEnum):
    respondida = "respondida"
    parcial = "parcial"
    contradiccion = "contradiccion"
    abstencion = "abstencion"


class QueryIntent(StrEnum):
    agenda = "agenda"
    contexto_economico = "contexto_economico"
    verificaciones = "verificaciones"
    busqueda = "busqueda"
    eventos_sismicos = "eventos_sismicos"
    resumen_periodo = "resumen_periodo"


# --------------------------------------------------------------------------- evidencia


class EvidenceArticle(ApiModel):
    kind: str = "articulo"
    id: str
    title: str
    url: str
    domain: str | None = None
    outlet: str
    is_tvn: bool = False
    language: str | None = None
    published_at: datetime | None = Field(
        None, description="Publicación original (UTC). Nula si falta (GDELT) o es inválida."
    )
    published_at_basis: str | None = Field(None, description="rss_pubdate | url_pattern | unknown")
    detected_at: datetime | None = Field(
        None, description="Detección (p. ej. seendate de GDELT); NO es fecha de publicación."
    )
    extracted_at: datetime | None = None
    category: Category = Category.indeterminado
    category_probability: float | None = Field(None, description="Probabilidad del clasificador; sin calibrar.")
    classifier: str | None = Field(None, description="laya | baseline")
    geo_relevance: GeoRelevance = GeoRelevance.indeterminate
    geo_evidence: list[str] = Field(
        default_factory=list,
        description="Evidencia del clasificador para la relevancia geográfica (p. ej. 'laya:panama=0.669' o términos del titular)",
    )
    origin: str = Field(description="Procedencia legible (agencia/medio). 'desconocido' se conserva identificado.")
    origin_known: bool = True
    origin_key: str = Field(description="Clave de independencia: una agencia replicada cuenta como una procedencia.")
    cluster_id: str | None = None
    scope_text: str = Field("titular/metadatos", description="Alcance del texto disponible.")
    data_origin: str = Field("real", description="real | fixture")
    sponsored_content: bool = Field(
        False,
        description="La URL indica posible contenido patrocinado (/publirreportajes/, /publireportaje/, /patrocinado/, /sponsored/): "
        "no cuenta como procedencia independiente.",
    )
    suspicious_instructions: bool = Field(
        False, description="El texto contiene instrucciones dirigidas a un agente (T07); se trata como dato no confiable."
    )
    flags: list[str] = Field(default_factory=list)


class IndicatorPoint(ApiModel):
    kind: str = "indicador"
    id: str
    country_iso3: str
    country_name: str | None = None
    indicator_id: str
    indicator_name: str
    year: int
    value: float | None = None
    unit: str | None = None
    source_url: str | None = None
    extracted_at: datetime | None = None
    license: str | None = None
    is_missing: bool = False
    data_origin: str = "real"
    note: str = Field("", description="Limitación visible: dato anual de referencia, no una medición de hoy.")


class OfficialContext(ApiModel):
    indicators: list[IndicatorPoint] = Field(default_factory=list)
    relation_rationale: str = ""
    limitations: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- puntaje


class ScoreComponent(ApiModel):
    key: str = Field(description="R, I, U, N o E")
    label: str
    weight: int
    value: float = Field(description="Normalizado 0-1")
    points: float
    rule: str = Field(description="Regla de scoring-v1 aplicada")
    justification: str
    limits: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ScoreDetail(ApiModel):
    total: float
    band: ScoreBand
    rules_version: str
    formula: str = "P = 30R + 25I + 20U + 15N + 10E"
    components: list[ScoreComponent]
    urgency_tiebreak: float
    id_tiebreak: str
    disclaimer: str = (
        "Puntaje de atención: herramienta de ordenamiento, no una probabilidad de verdad. "
        "Una prioridad alta no habilita publicación."
    )


class ImpactAssignment(ApiModel):
    level: ImpactLevel
    justification: str
    evidence_ids: list[str] = Field(default_factory=list)
    origin: str = Field(description="'propuesta_automatica' (requiere confirmación editorial) o 'editorial'")
    author: str | None = None
    reason: str | None = None
    version: int = 0
    at: datetime | None = None


class Gap(ApiModel):
    code: str
    message: str


class EvidenceAssessment(ApiModel):
    status: EvidenceStatus
    status_label: str
    independent_provenances: int
    primary_source_linked: bool = Field(
        description="True solo si un revisor CONFIRMÓ una fuente primaria pertinente (con motivo). Una serie oficial vinculada "
        "por palabra clave es solo contexto (`officialContextLinked`) y no sube E ni el estado."
    )
    official_context_linked: bool = Field(False, description="Hay una serie oficial vinculada por tema/palabra clave (solo contexto)")
    possible_sponsored: bool = False
    headline_only: bool
    gaps: list[Gap] = Field(default_factory=list)
    rationale: str
    reviewer_confirmed: bool | None = Field(
        None, description="Confirmación humana de suficiencia (puede diferir del sistema)."
    )
    reviewer_confirmed_by: str | None = None


class ContradictionVersion(ApiModel):
    evidence_id: str
    statement: str
    scope: str
    outlet: str
    published_at: datetime | None = None
    detected_at: datetime | None = None
    url: str | None = None


class Contradiction(ApiModel):
    id: str
    description: str
    versions: list[ContradictionVersion]
    status: str = "revision_pendiente"
    pending_verification: str


class Citation(ApiModel):
    evidence_id: str
    field: str = Field(description="Campo del ítem de evidencia que respalda (title, value, year…)")
    passage: str | None = Field(None, description="Pasaje literal dentro del campo")


class Claim(ApiModel):
    id: str
    type: ClaimType
    text: str
    citations: list[Citation] = Field(default_factory=list)


class CitationInput(ApiModel):
    evidence_id: str
    field: str
    passage: str | None = None


class ClaimInput(ApiModel):
    id: str
    type: ClaimType
    text: str = Field(min_length=1, max_length=1200)
    citations: list[CitationInput] = Field(default_factory=list)


class Reporter(ApiModel):
    outlet: str
    origin: str
    origin_known: bool
    role: str = Field(description="'original' o 'replica'")
    evidence_ids: list[str]


# --------------------------------------------------------------------------- tema / ficha


class TopicSummary(ApiModel):
    id: str
    rank: int | None = None
    title: str
    category: Category
    category_label: str
    score: float
    band: ScoreBand
    score_components: list[ScoreComponent] = Field(default_factory=list)
    urgency: float
    evidence_status: EvidenceStatus
    evidence_status_label: str
    article_count: int
    independent_provenances: int
    first_published_at: datetime | None = None
    last_published_at: datetime | None = None
    geo_relevance: GeoRelevance
    review_status: ReviewStatus = ReviewStatus.nuevo
    review_status_label: str = "Nuevo"
    has_contradictions: bool = False
    has_suspicious_source: bool = False
    headline_only: bool = True
    is_recirculation: bool = False
    relevance_reason: str = Field(
        "",
        description="Por qué R vale lo que vale: regla aplicada + evidencia del clasificador + fragmento del titular que la "
        "justifica, para que un editor pueda detectar y corregir un falso positivo.",
    )
    possible_sponsored: bool = Field(
        False, description="Posible contenido patrocinado (URL /publirreportajes/…): E máximo 0,33 y advertencia visible"
    )
    out_of_scope: bool = Field(
        False,
        description="Categoría indeterminada: fuera del alcance temático del reto. Se oculta de la agenda por defecto "
        "(scope=in_scope) pero sigue accesible por ID, por consulta y con scope=all.",
    )
    needs_investigation: bool = Field(
        False, description="Prioridad alta con evidencia insuficiente: requiere investigación; no habilita publicación."
    )
    top_reason: str = ""


class TopicsResponse(ApiModel):
    snapshot_id: str
    rules_version: str
    data_mode: DataMode
    cutoff_utc: datetime
    total: int
    scope: str = Field("in_scope", description="in_scope (por defecto, excluye category=indeterminado) | all")
    out_of_scope_count: int = Field(
        0, description="Temas de categoría indeterminada ocultos por scope=in_scope (con el resto de filtros aplicados)"
    )
    items: list[TopicSummary]
    applied: dict[str, Any] = Field(default_factory=dict)
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)


class TopicDetail(ApiModel):
    summary: TopicSummary
    snapshot_id: str
    rules_version: str
    data_mode: DataMode
    cutoff_utc: datetime | None = None
    what_is_reported: str
    reporters: list[Reporter]
    articles: list[EvidenceArticle]
    official_context: OfficialContext
    supported_claims: list[Claim]
    pending_verifications: list[str]
    contradictions: list[Contradiction]
    score: ScoreDetail
    impact: ImpactAssignment
    evidence: EvidenceAssessment
    recommended_action: str
    warnings: list[str] = Field(default_factory=list)
    case: CaseView


# --------------------------------------------------------------------------- consultas


_ShortId = Annotated[str, Field(min_length=1, max_length=128)]


class QueryContext(ApiModel):
    """Contexto estructurado mínimo de una respuesta anterior para resolver preguntas de seguimiento.

    Solo contiene identificadores y valores de catálogo; nunca el texto de respuestas ni de fuentes.
    """

    snapshot_id: str = Field(min_length=1, max_length=128)
    intent: QueryIntent
    topic_ids: list[_ShortId] = Field(default_factory=list, max_length=5)
    evidence_ids: list[_ShortId] = Field(default_factory=list, max_length=10)
    countries: list[Annotated[str, Field(min_length=3, max_length=3)]] = Field(default_factory=list, max_length=6)
    indicators: list[_ShortId] = Field(default_factory=list, max_length=6)
    years: list[Annotated[int, Field(ge=1900, le=2100)]] = Field(default_factory=list, max_length=15)


class QueryRequest(ApiModel):
    question: str = Field(min_length=3, max_length=500)
    topic_id: str | None = Field(None, description="Limita la consulta a un tema")
    limit: int = Field(5, ge=1, le=10)
    follow_up: QueryContext | None = Field(
        None, description="`followUpContext` de la respuesta anterior; sin él cada pregunta es independiente"
    )


ComposeProvider = Literal["gemini", "chatgpt", "claude"]


class ComposeRequest(QueryRequest):
    provider: ComposeProvider = Field(
        "gemini", description="Proveedor que redacta la respuesta; ChatGPT y Claude solo existen en ejecución local"
    )


class QueryHit(ApiModel):
    evidence_id: str
    kind: str
    title: str
    url: str | None = None
    outlet: str | None = None
    published_at: datetime | None = None
    snippet: str
    bm25: float
    fuzzy: float
    relevance: float
    cluster_id: str | None = None
    suspicious_instructions: bool = False
    retrieval_origin: str = Field("lexical", description="lexical, semantic_neighbor, lexical+semantic_neighbor o usgs_catalog")
    semantic_similarity: float | None = None
    semantic_anchor_id: str | None = None
    rrf_score: float | None = None
    literal_coverage: float = Field(0.0, description="Cobertura literal del propio documento; no se hereda del ancla semántica")


class QueryCitation(Citation):
    title: str | None = None
    url: str | None = None


class RetrievalInfo(ApiModel):
    method: str = "bm25+rapidfuzz"
    corpus_size: int
    took_ms: float
    matched_terms: list[str] = Field(default_factory=list)
    coverage: float = 0.0
    semantic_model: str | None = None
    semantic_expansion: bool = False
    rrf_k: int | None = None


class QueryResponse(ApiModel):
    query_id: str
    question: str
    intent: QueryIntent
    answer_status: AnswerStatus
    answer: str
    abstention_reason: str | None = None
    citations: list[QueryCitation] = Field(default_factory=list)
    hits: list[QueryHit] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    related_topic_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    snapshot_id: str
    rules_version: str
    data_mode: DataMode
    retrieval: RetrievalInfo
    resolved_question: str | None = Field(None, description="Pregunta autónoma que se ejecutó cuando `question` era un seguimiento")
    follow_up_context: QueryContext | None = None
    follow_up_suggestions: list[str] = Field(default_factory=list, max_length=4)


# --------------------------------------------------------------------------- borradores


class EditorialPackage(ApiModel):
    proposed_title: str
    brief: str = Field(description="≤250 palabras; los marcadores [c1] remiten a claims")
    public_interest_angle: str
    research_questions: list[str] = Field(description="Exactamente 3")
    pending_verifications: list[str]
    script: str = Field(description="Texto separado bajo GUION y NOTAS DE PRODUCCIÓN; solo GUION se estima a 45-60 s (≈112-150 palabras)")
    social_copy: str = Field(description="≤80 palabras")
    claims: list[Claim]
    headline_only: bool = True
    headline_only_notice: str | None = None
    limitations: list[str] = Field(default_factory=list)


class ValidationIssue(ApiModel):
    code: str
    severity: str  # error | warning
    message: str
    claim_id: str | None = None


class ValidationReport(ApiModel):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    rejected_claim_ids: list[str] = Field(default_factory=list)
    word_counts: dict[str, int] = Field(default_factory=dict)
    script_seconds_estimate: float = 0.0
    citation_coverage: float = Field(0.0, description="Afirmaciones con cita válida / todas las propuestas (incluye inferencias e hipótesis)")
    factual_citation_coverage: float | None = Field(
        None,
        description="Métrica oficial (PDF §9): afirmaciones factuales (hecho + declaración) con cita válida / propuestas. "
        "Nulo si no se propuso ninguna afirmación factual.",
    )
    note: str = "Una cita estructuralmente válida no prueba sustento: requiere revisión humana."


class GenerationUsage(ApiModel):
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    thinking_tokens: int | None = None
    latency_ms: float | None = None
    scope: str = "Respuesta exitosa del proveedor; no incluye llamadas fallidas ni cargos anteriores."
    cost_usd: float | None = None
    cost_note: str = "El SDK no declara costo monetario; el proyecto está configurado para Free Tier sin salto a pago."


class ComposeResponse(ApiModel):
    """Resultado de redactar con IA una respuesta con fuentes. Si el modelo falla, `response` conserva la respuesta por reglas."""

    response: QueryResponse = Field(description="Respuesta que se muestra: la redactada o, si falló, la determinista")
    answer_mode: Literal["reglas", "modelo"]
    rules_answer: str = Field(description="Texto de la respuesta determinista (siempre disponible)")
    provider: str | None = None
    model: str | None = None
    fallback_reason: FallbackReason | None = None
    fallback_detail: str | None = None
    usage: GenerationUsage | None = None
    attempts: int = Field(0, description="Llamadas al modelo hechas para esta redacción (0 si no se llegó a llamar; 2 si hubo reintento)")
    notices: list[str] = Field(default_factory=list)


class DraftRecord(ApiModel):
    draft_id: str
    number: int
    generation_mode: GenerationMode
    generation_label: str
    provider: str
    model: str | None = None
    fallback_reason: FallbackReason | None = None
    fallback_detail: str | None = None
    recovered_from_draft_id: str | None = None
    previous_draft_id: str | None = None
    usage: GenerationUsage | None = None
    created_at: datetime
    edited_by: str | None = None
    edited_at: datetime | None = None
    snapshot_id: str
    rules_version: str
    package: EditorialPackage
    validation: ValidationReport


class DraftRequest(ApiModel):
    provider: DraftProviderChoice = DraftProviderChoice.auto


class DraftResponse(ApiModel):
    case: CaseView
    draft: DraftRecord
    notices: list[str] = Field(default_factory=list)


class DraftEditRequest(ApiModel):
    expected_version: int = Field(ge=0)
    editor: str = Field(min_length=1, max_length=120)
    proposed_title: str | None = None
    brief: str | None = None
    public_interest_angle: str | None = None
    research_questions: list[str] | None = None
    pending_verifications: list[str] | None = None
    script: str | None = None
    social_copy: str | None = None
    claims: list[ClaimInput] | None = None


# --------------------------------------------------------------------------- revisión


class ReviewRequest(ApiModel):
    expected_version: int = Field(ge=0, description="Versión del caso que el cliente vio; si difiere, 409")
    status: ReviewStatus
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str | None = Field(None, max_length=2000)
    evidence_confirmed: bool | None = Field(
        None, description="El revisor confirma (true) o niega (false) la suficiencia de evidencia"
    )
    primary_source_confirmed: bool | None = Field(
        None,
        description="El revisor confirma (true) que existe una fuente primaria pertinente que respalda ESE hecho (requiere "
        "comentario con el motivo y la fuente). Solo así E puede llegar a 1,0. false la retira.",
    )


class CaseEvent(ApiModel):
    version: int
    at: datetime
    kind: str
    actor: str
    from_status: ReviewStatus | None = None
    to_status: ReviewStatus | None = None
    comment: str | None = None
    draft_number: int | None = None
    rules_version: str | None = None


class CaseView(ApiModel):
    case_id: str
    topic_id: str
    snapshot_id: str
    rules_version: str
    version: int
    persisted: bool
    status: ReviewStatus
    status_label: str
    allowed_transitions: list[ReviewStatus]
    reviewer: str | None = None
    evidence_confirmed: bool | None = None
    evidence_confirmed_by: str | None = None
    primary_source_confirmed: bool | None = None
    primary_source_confirmed_by: str | None = None
    primary_source_reason: str | None = None
    impact: ImpactAssignment | None = None
    drafts: list[DraftRecord] = Field(default_factory=list)
    current_draft: DraftRecord | None = None
    history: list[CaseEvent] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ImpactRequest(ApiModel):
    expected_version: int = Field(ge=0)
    level: ImpactLevel
    justification: str = Field(min_length=20, max_length=1500)
    evidence_ids: list[str] = Field(min_length=1)
    author: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=3, max_length=500, description="Motivo del cambio (se conserva con la versión)")


class ExportResponse(ApiModel):
    case_id: str
    filename: str
    markdown: str
    snapshot_id: str
    rules_version: str
    generated_at: datetime


class NotionStatusResponse(ApiModel):
    """Estado booleano de configuración; nunca expone valores de configuración."""

    configured: bool


class NotionExportResponse(ApiModel):
    page_id: str
    url: str
    title: str


class ConnectorProviderState(ApiModel):
    available: bool
    connected: bool
    workspace_name: str | None = None
    destination_id: str | None = None
    destination_title: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None


class ConnectorProviderStates(ApiModel):
    notion: ConnectorProviderState
    slack: ConnectorProviderState


class SlackNotificationState(ApiModel):
    enabled: bool = False
    statuses: list[ReviewStatus] = Field(default_factory=list)


class ConnectorOverviewResponse(ApiModel):
    configured: bool
    providers: ConnectorProviderStates
    slack_notifications: SlackNotificationState


class ConnectorStartResponse(ApiModel):
    authorization_url: str


class ConnectorDisconnectedResponse(ApiModel):
    disconnected: bool


class ConnectorPage(ApiModel):
    id: str
    title: str
    url: str


class ConnectorPagesResponse(ApiModel):
    items: list[ConnectorPage]


class ConnectorDestinationRequest(ApiModel):
    page_id: str = Field(min_length=1, max_length=128)


class ConnectorSavedResponse(ApiModel):
    saved: bool


class NotionMarkdownRequest(ApiModel):
    markdown: str = Field(min_length=1, max_length=100_000)


class SlackChannel(ApiModel):
    id: str
    name: str
    is_private: bool


class SlackChannelsResponse(ApiModel):
    items: list[SlackChannel]


class SlackChannelChoice(ApiModel):
    channel_id: str = Field(min_length=1, max_length=128)


class SlackNotificationPreferencesRequest(ApiModel):
    enabled: bool = False
    channel_id: str | None = Field(default=None, max_length=128)
    statuses: list[ReviewStatus] = Field(default_factory=list, max_length=5)


class SlackNotificationPreferencesResponse(SlackNotificationPreferencesRequest):
    pass


class SlackShareRequest(ApiModel):
    event_id: str = Field(min_length=1, max_length=180)
    case_id: str = Field(min_length=1, max_length=100)
    case_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)
    status: ReviewStatus
    from_status: ReviewStatus | None = None
    snapshot_id: str = Field(min_length=1, max_length=80)


class SlackNotificationResult(ApiModel):
    sent: bool
    duplicate: bool
    skipped_reason: str | None = None


# --------------------------------------------------------------------------- estado / fuentes


class ProviderStatus(ApiModel):
    name: str
    mode: GenerationMode
    external: bool
    local_only: bool
    available: bool
    reason: str | None = None
    model: str | None = None
    sign_in: Literal["oauth", "cli"] | None = Field(
        default=None, description="Cómo iniciar sesión en este proveedor (solo local): OAuth propio o CLI oficial"
    )
    account: str | None = Field(default=None, description="Cuenta de la sesión reconocida (solo local)")


class IntegrityReport(ApiModel):
    manifest_verified: bool
    files_checked: int
    predictions_hash_verified: bool | None = None
    predictions_sha256: str | None = None
    errors: list[str] = Field(default_factory=list)
    checked_at: datetime


class HealthResponse(ApiModel):
    status: str  # ok | degradado
    api_version: str
    snapshot_id: str
    data_mode: DataMode
    provisional: bool
    contains_fixtures: bool
    classifier: str | None = None
    rules_version: str
    cutoff_utc: datetime
    offline: bool
    local_mode: bool
    persistence: str
    auth_mode: str
    counts: dict[str, int]
    integrity: IntegrityReport
    providers: list[ProviderStatus]
    server_time_utc: datetime
    notes: list[str] = Field(default_factory=list)
    snapshot_stale: bool = False
    snapshot_refresh_error: str | None = None
    snapshot_last_checked_at: datetime | None = None
    deploy_commit: str | None = None  # SHA desplegado; permite verificar qué versión atiende antes de publicar Hosting


class SnapshotInfoResponse(ApiModel):
    snapshot_id: str
    data_mode: DataMode
    manifest: dict[str, Any]
    quality_report: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] | None = Field(
        None, description="Métricas reales publicadas por `datos`; nulo si no hay ejecución"
    )
    integrity: IntegrityReport


class RulesResponse(ApiModel):
    rules_version: str
    formula: str
    weights: dict[str, int]
    bands: dict[str, str]
    rules: dict[str, str]
    changelog: list[dict[str, str]]
    version: int = 0
    history: list[RulesRevision] = Field(default_factory=list)


class RulesRevision(ApiModel):
    version: int
    rules_version: str
    weights: dict[str, int]
    reason: str
    author: str
    at: datetime


class RulesRequest(ApiModel):
    expected_version: int = Field(ge=0)
    weights: dict[str, StrictInt]
    reason: str = Field(min_length=3, max_length=1000)
    author: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def valid_weights(self) -> RulesRequest:
        if set(self.weights) != {"R", "I", "U", "N", "E"}:
            raise ValueError("Se requieren exactamente los pesos R, I, U, N y E.")
        if any(w < 0 or w > 100 for w in self.weights.values()) or sum(self.weights.values()) != 100:
            raise ValueError("Los pesos deben estar entre 0 y 100 y sumar 100.")
        if not self.author.strip() or len(self.reason.strip()) < 3:
            raise ValueError("Se requiere autor y motivo con contenido.")
        return self


class ErrorResponse(ApiModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


CaseView.model_rebuild()
TopicDetail.model_rebuild()
RulesResponse.model_rebuild()
