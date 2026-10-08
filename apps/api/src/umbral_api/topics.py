"""Construcción de temas (clusters) con evidencia, contexto oficial, contradicciones y vacíos."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .models import (
    CATEGORY_LABELS,
    EVIDENCE_LABELS,
    Category,
    Citation,
    Claim,
    ClaimType,
    Contradiction,
    ContradictionVersion,
    EvidenceArticle,
    EvidenceAssessment,
    EvidenceStatus,
    Gap,
    GeoRelevance,
    ImpactAssignment,
    ImpactLevel,
    IndicatorPoint,
    OfficialContext,
    Reporter,
)
from .retrieval import fold, stem
from .snapshot import Corpus

MASKED_TITLE = "[texto con instrucciones omitido]"
HEADLINE_NOTICE = "Basado únicamente en titular/metadatos: no se leyó el artículo completo ni se le atribuyen detalles adicionales."

_GEO_RANK = {
    GeoRelevance.panama: 3,
    GeoRelevance.regional: 2,
    GeoRelevance.none: 1,
    GeoRelevance.indeterminate: 0,
}

INDICATOR_KEYWORDS: dict[str, list[str]] = {
    "NY.GDP.MKTP.KD.ZG": ["pib", "producto interno", "crecimiento economico", "crecimiento del pib", "economia crece"],
    "FP.CPI.TOTL.ZG": ["inflacion", "precios al consumidor", "costo de vida", "canasta basica", "indice de precios"],
    "SL.UEM.TOTL.ZS": ["desempleo", "desocupacion", "tasa de empleo", "mercado laboral", "despidos"],
    "SP.POP.TOTL": ["poblacion", "censo", "habitantes", "demografic"],
    "IT.NET.USER.ZS": ["internet", "conectividad", "banda ancha", "brecha digital"],
    "NE.EXP.GNFS.ZS": ["exportacion", "exportaciones", "exporta ", "comercio exterior", "balanza comercial"],
}
COUNTRY_KEYWORDS = {
    "PAN": ["panama", "panameno", "panamena"],
    "CRI": ["costa rica", "costarricense"],
    "COL": ["colombia", "colombian"],
    "DOM": ["republica dominicana", "dominicana", "dominicano"],
    "MEX": ["mexico", "mexican"],
    "GTM": ["guatemala", "guatemalteco"],
}

_NUM_NOUN = re.compile(r"(\d[\d.,]*)\s*(%|[a-záéíóúñ]+)", re.IGNORECASE)


@dataclass
class TopicBase:
    id: str
    cluster: dict
    articles: list[EvidenceArticle]
    representative: EvidenceArticle
    category: Category
    geo: GeoRelevance
    geo_evidence_ids: list[str]
    indicators: list[IndicatorPoint]
    relation_rationale: str
    relation_limits: list[str]
    first_published: datetime | None
    last_published: datetime | None
    publish_date_issue: str | None
    is_recirculation: bool
    recirculation_reason: str | None
    independent: int
    has_outlet_original: bool
    provenance_known: bool
    contradictions: list[Contradiction]
    suspicious_ids: list[str]
    gaps: list[Gap]
    system_status: EvidenceStatus  # estado SIN fuente primaria confirmada (ver status_for)
    status_rationale: str
    proposed_impact: ImpactAssignment
    claims: list[Claim]
    pending: list[str]
    search_text: str
    primary_ids: list[str] = field(default_factory=list)
    date_known: bool = True
    sponsored_ids: list[str] = field(default_factory=list)
    sponsored_only: bool = False

    def status_for(self, primary_confirmed: bool) -> tuple[EvidenceStatus, str]:
        return _status(self.independent, primary_confirmed, bool(self.contradictions), self.date_known, self.sponsored_only)

    @property
    def display_title(self) -> str:
        """Titular seguro para mostrar/redactar: nunca reproduce el texto de una fuente con instrucciones."""
        return MASKED_TITLE if self.representative.suspicious_instructions else self.representative.title

    @property
    def usable_articles(self) -> list[EvidenceArticle]:
        return [a for a in self.articles if not a.suspicious_instructions]


def _num(s: str) -> float | None:
    s = s.strip(".,")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[-1]) == 3):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def detect_contradictions(
    topic_id: str, arts: list[EvidenceArticle], flagged: bool, candidate_ids: list[str] | None = None
) -> list[Contradiction]:
    """Cifras distintas sobre la misma magnitud en titulares del mismo evento (candidato; requiere revisión humana)."""
    by_noun: dict[str, dict[float, list[EvidenceArticle]]] = {}
    for a in arts:
        if a.suspicious_instructions:
            continue
        seen_here: set[tuple[str, float]] = set()
        for m in _NUM_NOUN.finditer(a.title):
            val = _num(m.group(1))
            noun = fold(m.group(2))
            if val is None or noun in {"de", "en", "del", "la", "el", "y", "a"}:
                continue
            if re.fullmatch(r"(19|20)\d\d", m.group(1)) and noun not in {"%"}:
                continue  # años
            noun = stem(noun)
            if (noun, val) in seen_here:
                continue
            seen_here.add((noun, val))
            by_noun.setdefault(noun, {}).setdefault(val, []).append(a)
    out: list[Contradiction] = []
    for noun, values in sorted(by_noun.items()):
        if len(values) < 2:
            continue
        versions = []
        for _val, group in sorted(values.items()):
            for a in group:
                versions.append(
                    ContradictionVersion(
                        evidence_id=a.id,
                        statement=a.title,
                        scope="titular/metadatos",
                        outlet=a.outlet,
                        published_at=a.published_at,
                    )
                )
        shown = ", ".join(f"{v:g}" for v in sorted(values))
        out.append(
            Contradiction(
                id=f"{topic_id}:cifra:{noun}",
                description=f"Los titulares del mismo evento dan cifras distintas para «{noun}»: {shown}. No se elige una versión.",
                versions=versions,
                pending_verification=(
                    f"Contrastar con una fuente primaria u oficial la cifra de «{noun}» y determinar si las versiones "
                    "describen momentos distintos del mismo evento."
                ),
            )
        )
    if not out and flagged:
        versions = [
            ContradictionVersion(
                evidence_id=a.id, statement=a.title, scope="titular/metadatos", outlet=a.outlet, published_at=a.published_at
            )
            for a in arts
            if not a.suspicious_instructions and (not candidate_ids or a.id in candidate_ids)
        ]
        out.append(
            Contradiction(
                id=f"{topic_id}:candidato",
                description="El pipeline marcó un candidato a contradicción (cifras distintas sobre la misma entidad). "
                "Se muestran las versiones sin elegir una.",
                versions=versions,
                pending_verification="Revisar manualmente las versiones y verificar con fuente primaria.",
            )
        )
    return out


def link_indicators(corpus: Corpus, arts: list[EvidenceArticle], geo: GeoRelevance) -> tuple[list[IndicatorPoint], str, list[str]]:
    """Relaciona el tema con series oficiales solo si el titular las nombra (no se fuerza)."""
    text = " ".join(fold(a.title) for a in arts if not a.suspicious_instructions) + " "
    inds = [k for k, kws in INDICATOR_KEYWORDS.items() if any(kw in text for kw in kws)]
    if not inds:
        return [], "Sin relación sustentada con indicadores oficiales disponibles (no se fuerza).", [
            "No existe un indicador oficial del paquete (Banco Mundial) que el titular nombre."
        ]
    countries = [c for c, kws in COUNTRY_KEYWORDS.items() if any(kw in text for kw in kws)]
    if not countries:
        if geo == GeoRelevance.panama:
            countries = ["PAN"]
        else:
            return [], "El titular nombra un indicador pero no un país del paquete; no se fuerza la relación.", [
                "País del indicador no identificable desde el titular."
            ]
    if "PAN" in countries and len(countries) > 1:
        countries = ["PAN"] + [c for c in countries if c != "PAN"]
    cutoff_year = corpus.cutoff.year
    points: list[IndicatorPoint] = []
    for iso in countries:
        for ind in inds:
            series = sorted(
                (p for p in corpus.indicators.values() if p.country_iso3 == iso and p.indicator_id == ind and p.year <= cutoff_year),
                key=lambda p: p.year,
            )
            valid = [p for p in series if not p.is_missing]
            if valid:
                latest_valid = valid[-1]
                later_missing = [p for p in series if p.is_missing and p.year > latest_valid.year]
                points.append(latest_valid)
                if later_missing:
                    points.append(later_missing[-1])
            elif series:
                points.append(series[-1])
    if not points:
        return [], "No hay filas del indicador para el país identificado.", ["Sin datos oficiales para esa combinación."]
    limits = [
        "Los indicadores del Banco Mundial son anuales históricos: se muestra el año de referencia, no una medición de hoy.",
        "La relación es temática (el titular nombra el indicador); no demuestra causalidad.",
    ]
    if any(p.is_missing for p in points):
        limits.append("Hay años posteriores con valor ausente; se conservan como nulos, sin rellenar.")
    names = ", ".join(sorted({p.indicator_name for p in points}))
    return points, f"El titular nombra: {names}. Se muestran valores oficiales con año y unidad.", limits


def _status(
    independent: int,
    primary: bool,
    contradictions: bool,
    date_known: bool,
    sponsored_only: bool = False,
) -> tuple[EvidenceStatus, str]:
    """`primary` = fuente primaria pertinente CONFIRMADA por un revisor (no basta una serie vinculada por palabra clave)."""
    if sponsored_only:
        return EvidenceStatus.insuficiente, "Posible contenido patrocinado: no cuenta como procedencia independiente."
    if independent < 2 and not primary:
        return EvidenceStatus.insuficiente, (
            "Menos de dos procedencias independientes y sin fuente primaria pertinente confirmada."
        )
    if independent >= 2 and (primary or independent >= 3) and not contradictions and date_known:
        return EvidenceStatus.suficiente, (
            "Al menos dos procedencias independientes con fuente primaria confirmada, o ≥3 procedencias independientes, "
            "sin contradicciones pendientes y con fecha de publicación original conocida."
        )
    return EvidenceStatus.parcial, "Hay algo de respaldo, pero persisten vacíos (ver lista) antes de considerarla suficiente."


def build_topic(corpus: Corpus, cluster: dict) -> TopicBase | None:
    arts = [corpus.articles[i] for i in cluster.get("memberArticleIds", []) if i in corpus.articles]
    if not arts:
        return None
    cutoff = corpus.cutoff

    def pub_key(a: EvidenceArticle):  # noqa: ANN202
        return (a.published_at is None, a.published_at or cutoff, a.id)

    arts.sort(key=pub_key)
    rep = corpus.articles.get(cluster.get("representativeArticleId", ""), arts[0])
    if rep.suspicious_instructions:
        rep = next((a for a in arts if not a.suspicious_instructions), rep)
    # Una fecha posterior al corte se ignora (límite visible)
    valid_pubs = [a.published_at for a in arts if a.published_at and a.published_at <= cutoff]
    issue = None
    if any(a.published_at and a.published_at > cutoff for a in arts):
        issue = "Existen fechas de publicación posteriores al corte; se ignoran."
    original = None
    if cluster.get("originalPublishedAt"):
        from .snapshot import parse_dt

        original = parse_dt(cluster["originalPublishedAt"])
        if original and original > cutoff:
            original = None
    first = min(valid_pubs) if valid_pubs else original
    if original and valid_pubs:
        first = min(original, min(valid_pubs))
    last = max(valid_pubs) if valid_pubs else None

    cat_raw = cluster.get("category") or rep.category.value
    category = Category(cat_raw) if cat_raw in {c.value for c in Category} else Category.indeterminado
    geo = max((a.geo_relevance for a in arts), key=lambda g: _GEO_RANK[g])
    geo_ids = [a.id for a in arts if a.geo_relevance == geo][:3]

    usable = [a for a in arts if not a.suspicious_instructions]
    sponsored_ids = [a.id for a in usable if a.sponsored_content]
    sponsored_only = bool(usable) and len(sponsored_ids) == len(usable)
    # El contenido patrocinado no es una procedencia independiente (si todo es patrocinado cuenta como una sola).
    keys = {a.origin_key for a in usable if not a.sponsored_content} or {a.origin_key for a in usable}
    # Una agencia replicada = una procedencia; los orígenes desconocidos se identifican por dominio.
    independent = len(keys)
    if sponsored_only:
        independent = min(independent, 1)
    snap_indep = cluster.get("independentProvenanceCount")
    if isinstance(snap_indep, int) and not any(a.suspicious_instructions for a in arts):
        independent = min(independent, snap_indep) if snap_indep > 0 else independent
    has_outlet_original = any(a.origin_key.startswith("outlet:") for a in usable)
    provenance_known = all(a.origin_known for a in usable) if usable else False

    ind_points, rationale, rel_limits = link_indicators(corpus, arts, geo)
    primary_ids = [p.id for p in ind_points if not p.is_missing]  # contexto oficial vinculado por tema (NO fuente primaria)
    official_context = bool(primary_ids)

    contradictions = detect_contradictions(
        cluster["clusterId"], arts, bool(cluster.get("hasContradictionCandidate")), cluster.get("contradictionCandidateIds")
    )
    suspicious_ids = [a.id for a in arts if a.suspicious_instructions]

    is_recirc = bool(cluster.get("isRecirculation"))
    date_known = first is not None
    status, why = _status(independent, False, bool(contradictions), date_known, sponsored_only)

    gaps: list[Gap] = [
        Gap(code="solo_titular_metadatos", message="Solo se dispone de titular y metadatos; no se leyó el artículo completo.")
    ]
    if independent < 2:
        gaps.append(Gap(code="una_sola_procedencia", message="Una sola procedencia: la repetición no es corroboración independiente."))
    if len(usable) > independent:
        gaps.append(
            Gap(
                code="replicas_contadas_una_vez",
                message=f"{len(usable)} notas con {independent} procedencia(s) independiente(s): las réplicas de agencia cuentan una vez.",
            )
        )
    gaps.append(
        Gap(
            code="sin_fuente_primaria",
            message="No hay fuente primaria pertinente confirmada" + (
                "; la serie oficial vinculada por tema es solo contexto y no respalda este hecho." if official_context else "."
            ),
        )
    )
    if sponsored_ids:
        gaps.append(
            Gap(
                code="contenido_patrocinado",
                message="Posible contenido patrocinado (URL de publirreportaje/patrocinado): no cuenta como procedencia independiente; E máximo 0,33.",
            )
        )
    if first is None:
        gaps.append(Gap(code="fecha_publicacion_desconocida", message="Se desconoce la fecha de publicación original (solo hay fecha de detección)."))
    if not provenance_known:
        gaps.append(Gap(code="procedencia_desconocida", message="Alguna procedencia es desconocida; se identifica pero no se acredita."))
    if contradictions:
        gaps.append(Gap(code="contradiccion_pendiente", message="Hay versiones incompatibles; revisión pendiente, no se elige una."))
    if is_recirc:
        gaps.append(Gap(code="recirculacion", message=f"Noticia antigua recirculada: {cluster.get('recirculationReason') or 'fecha original anterior'}."))
    if suspicious_ids:
        gaps.append(Gap(code="fuente_con_instrucciones", message="Una fuente contiene instrucciones dirigidas a un agente; se trató como dato no confiable y se excluyó."))
    if category == Category.indeterminado:
        gaps.append(Gap(code="clasificacion_indeterminada", message="La categoría quedó indeterminada; se conserva sin forzarla."))
    if category == Category.economia and not official_context:
        gaps.append(Gap(code="sin_contexto_oficial", message="Tema económico sin serie oficial vinculada; no se infiere una cifra."))

    # impacto propuesto (heurística con evidencia; requiere confirmación editorial)
    factors: list[str] = []
    pts = 0
    if geo == GeoRelevance.panama:
        pts += 1
        factors.append("relación directa con Panamá")
    if independent >= 2:
        pts += 1
        factors.append(f"{independent} procedencias independientes")
    category_note = ""
    if category in (Category.eventos_naturales, Category.servicios_publicos, Category.logistica_canal):
        # La categoría viene de un clasificador sin calibrar: solo cuenta como «alcance público amplio» si hay
        # corroboración (≥2 procedencias independientes); ni la etiqueta ni una serie vinculada por palabra clave bastan.
        if independent >= 2 and not sponsored_only:
            pts += 1
            factors.append(f"alcance público amplio ({CATEGORY_LABELS[category.value]}, con evidencia que lo corrobora)")
        else:
            category_note = (
                f" La categoría «{CATEGORY_LABELS[category.value]}» (clasificador sin calibrar) no suma por sí sola: "
                "falta corroboración independiente."
            )
    level = ImpactLevel.alto if pts >= 3 else ImpactLevel.medio if pts == 2 else ImpactLevel.bajo
    justification = (
        f"Propuesta automática ({pts} de 3 factores): " + ("; ".join(factors) if factors else "sin factores de alcance identificados")
        + "." + category_note + " Requiere confirmación editorial."
    )
    proposed = ImpactAssignment(
        level=level,
        justification=justification,
        evidence_ids=[rep.id],
        origin="propuesta_automatica",
        version=0,
    )

    claims = _supported_claims(usable, ind_points)

    pending: list[str] = []
    for g in gaps:
        pending.append(_PENDING.get(g.code, g.message))
    for c in contradictions:
        pending.append(c.pending_verification)
    pending = list(dict.fromkeys(p for p in pending if p))

    search_text = " ".join(a.title for a in usable) + " " + CATEGORY_LABELS[category.value]
    return TopicBase(
        id=cluster["clusterId"],
        cluster=cluster,
        articles=arts,
        representative=rep,
        category=category,
        geo=geo,
        geo_evidence_ids=geo_ids,
        indicators=ind_points,
        relation_rationale=rationale,
        relation_limits=rel_limits,
        first_published=first,
        last_published=last,
        publish_date_issue=issue,
        is_recirculation=is_recirc,
        recirculation_reason=cluster.get("recirculationReason"),
        independent=independent,
        has_outlet_original=has_outlet_original,
        provenance_known=provenance_known,
        contradictions=contradictions,
        suspicious_ids=suspicious_ids,
        gaps=gaps,
        system_status=status,
        status_rationale=why,
        proposed_impact=proposed,
        claims=claims,
        pending=pending,
        search_text=search_text,
        primary_ids=primary_ids,
        date_known=date_known,
        sponsored_ids=sponsored_ids,
        sponsored_only=sponsored_only,
    )


_PENDING = {
    "solo_titular_metadatos": "Leer el artículo completo en la fuente original antes de redactar; hoy solo hay titular/metadatos.",
    "una_sola_procedencia": "Buscar una segunda procedencia independiente que corrobore el hecho.",
    "sin_fuente_primaria": "Localizar la fuente primaria u oficial (comunicado, entidad, base de datos oficial).",
    "fecha_publicacion_desconocida": "Confirmar la fecha de publicación original (solo se conoce la fecha de detección).",
    "procedencia_desconocida": "Identificar la procedencia (agencia o medio de origen) de las notas.",
    "recirculacion": "Verificar la fecha original: puede ser una noticia antigua recirculada, no un evento nuevo.",
    "fuente_con_instrucciones": "Revisar manualmente la fuente que contiene instrucciones; no se utilizó como evidencia.",
    "clasificacion_indeterminada": "Confirmar manualmente la categoría temática.",
    "sin_contexto_oficial": "Buscar una serie oficial pertinente si el tema es económico.",
}


def _supported_claims(arts: list[EvidenceArticle], inds: list[IndicatorPoint]) -> list[Claim]:
    """Afirmaciones respaldadas sin LLM: lo que cada procedencia reporta (declaración) y valores oficiales (hecho)."""
    claims: list[Claim] = []
    seen: set[str] = set()
    n = 0
    for a in arts:
        if a.origin_key in seen:
            continue
        seen.add(a.origin_key)
        n += 1
        claims.append(
            Claim(
                id=f"c{n}",
                type=ClaimType.declaracion,
                text=f"{a.outlet} reporta en su titular: «{a.title}»",
                citations=[Citation(evidence_id=a.id, field="title", passage=a.title),
                    Citation(evidence_id=a.id, field="outlet", passage=a.outlet)],
            )
        )
    for p in inds:
        if p.is_missing or p.value is None:
            continue
        n += 1
        claims.append(
            Claim(
                id=f"c{n}",
                type=ClaimType.hecho,
                text=(
                    f"Según el Banco Mundial, {p.indicator_name} de {p.country_name or p.country_iso3} en {p.year} fue "
                    f"{p.value:g} ({p.unit or 'sin unidad'}); dato anual de referencia, no una medición de hoy."
                ),
                citations=[
                    Citation(evidence_id=p.id, field="value", passage=f"{p.value:g}"),
                    Citation(evidence_id=p.id, field="year", passage=str(p.year)),
                ],
            )
        )
    return claims


def build_reporters(top: TopicBase) -> list[Reporter]:
    first_by_key: dict[str, str] = {}
    out: dict[str, Reporter] = {}
    for a in top.articles:
        first = first_by_key.setdefault(a.origin_key, a.id)
        role = "original" if first == a.id else "replica"
        key = (a.outlet, role)
        k = f"{key[0]}|{key[1]}|{a.origin_key}"
        if k not in out:
            out[k] = Reporter(outlet=a.outlet, origin=a.origin, origin_known=a.origin_known, role=role, evidence_ids=[])
        out[k].evidence_ids.append(a.id)
    return list(out.values())


def assess_evidence(
    top: TopicBase, reviewer_confirmed: bool | None, confirmed_by: str | None, primary_confirmed: bool = False
) -> EvidenceAssessment:
    status, why = top.status_for(primary_confirmed)
    return EvidenceAssessment(
        status=status,
        status_label=EVIDENCE_LABELS[status.value],
        independent_provenances=top.independent,
        primary_source_linked=primary_confirmed,
        official_context_linked=bool(top.primary_ids),
        possible_sponsored=bool(top.sponsored_ids),
        headline_only=True,
        gaps=[g for g in top.gaps if not (primary_confirmed and g.code == "sin_fuente_primaria")],
        rationale=why,
        reviewer_confirmed=reviewer_confirmed,
        reviewer_confirmed_by=confirmed_by,
    )


def official_context(top: TopicBase) -> OfficialContext:
    return OfficialContext(
        indicators=top.indicators, relation_rationale=top.relation_rationale, limitations=top.relation_limits
    )
