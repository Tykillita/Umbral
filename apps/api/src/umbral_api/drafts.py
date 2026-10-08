"""Borradores: paquete de evidencia, validación (citas/alcance/formato/límites) y plantilla con citas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import (
    CATEGORY_LABELS,
    Claim,
    ClaimType,
    EditorialPackage,
    ValidationIssue,
    ValidationReport,
)
from .retrieval import fold
from .security import leaks_secret
from .topics import HEADLINE_NOTICE, MASKED_TITLE, TopicBase
from .util import fmt_date_pa, marker_ids, strip_markers, word_count

BRIEF_MAX_WORDS = 250
COPY_MAX_WORDS = 80
SCRIPT_WPS = 2.5  # palabras por segundo (guion hablado en español)
SCRIPT_MIN_S, SCRIPT_MAX_S = 45.0, 60.0
SCRIPT_MIN_WORDS = int(SCRIPT_MIN_S * SCRIPT_WPS)  # 112
SCRIPT_MAX_WORDS = int(SCRIPT_MAX_S * SCRIPT_WPS)  # 150
HEADLINE_PREFIX = "Basado únicamente en titular/metadatos."

ARTICLE_FIELDS = ("title", "outlet", "publishedAt", "detectedAt", "url", "origin", "category")
INDICATOR_FIELDS = ("value", "unit", "year", "countryIso3", "indicatorName")


@dataclass
class EvidencePack:
    """Evidencia recuperada del corpus para un tema: lo único que puede citar un borrador."""

    items: dict[str, dict[str, str]] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    excluded: set[str] = field(default_factory=set)  # fuentes con instrucciones: no citables
    headline_only: bool = True


def build_pack(base: TopicBase) -> EvidencePack:
    pack = EvidencePack()
    for a in base.articles:
        if a.suspicious_instructions:
            pack.excluded.add(a.id)
            continue
        pack.items[a.id] = {
            "title": a.title,
            "outlet": a.outlet,
            "publishedAt": a.published_at.isoformat() if a.published_at else "",
            "detectedAt": a.detected_at.isoformat() if a.detected_at else "",
            "url": a.url,
            "origin": a.origin,
            "category": a.category.value,
        }
        pack.kinds[a.id] = "articulo"
    for p in base.indicators:
        if p.is_missing or p.value is None:
            continue
        pack.items[p.id] = {
            "value": f"{p.value:g}",
            "unit": p.unit or "",
            "year": str(p.year),
            "countryIso3": p.country_iso3,
            "indicatorName": p.indicator_name,
        }
        pack.kinds[p.id] = "indicador"
    return pack


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", fold(s)).strip()


def _numbers(text: str) -> set[float]:
    out: set[float] = set()
    for tok in re.findall(r"\d[\d.,]*\d|\d", text):
        cands = {tok.replace(",", "."), tok.replace(".", "").replace(",", "."), tok.replace(",", "")}
        for c in cands:
            try:
                out.add(float(c))
            except ValueError:
                pass
    return out


def validate_claims(claims: list[Claim], pack: EvidencePack) -> tuple[list[Claim], list[ValidationIssue]]:
    """Valida IDs de cita, campo, pasaje, alcance y cifras. Devuelve afirmaciones aceptadas y problemas."""
    issues: list[ValidationIssue] = []
    kept: list[Claim] = []
    seen_ids: set[str] = set()
    for c in claims:
        problems: list[ValidationIssue] = []

        def bad(code: str, msg: str, _c: Claim = c, _p: list[ValidationIssue] = problems) -> None:
            _p.append(ValidationIssue(code=code, severity="error", message=msg, claim_id=_c.id))

        if c.id in seen_ids:
            bad("id_duplicado", f"El ID de afirmación {c.id} está repetido.")
        seen_ids.add(c.id)
        if not c.text.strip():
            bad("afirmacion_vacia", "Afirmación sin texto.")
        if c.type in (ClaimType.hecho, ClaimType.declaracion, ClaimType.inferencia) and not c.citations:
            bad("sin_cita", f"La afirmación {c.id} ({c.type.value}) requiere al menos una cita.")
        cited_text: list[str] = []
        for ct in c.citations:
            if ct.evidence_id in pack.excluded:
                bad("fuente_no_confiable", f"{ct.evidence_id} contiene instrucciones y no es citable.")
                continue
            item = pack.items.get(ct.evidence_id)
            if item is None:
                bad("cita_inexistente", f"El ID de evidencia {ct.evidence_id} no existe en el alcance del tema.")
                continue
            if ct.field not in item:
                bad("campo_inexistente", f"El campo «{ct.field}» no existe en {ct.evidence_id}.")
                continue
            value = item[ct.field]
            if ct.passage is not None and ct.passage.strip():
                if _norm(ct.passage) not in _norm(value):
                    bad("pasaje_no_encontrado", f"El pasaje citado no aparece en {ct.evidence_id}.{ct.field}.")
                    continue
            cited_text.append(value)
            if ct.passage:
                cited_text.append(ct.passage)
        if c.type in (ClaimType.hecho, ClaimType.declaracion) and cited_text and not problems:
            allowed = _numbers(" ".join(cited_text))
            for tok in re.findall(r"\d[\d.,]*\d|\d", c.text):
                cand = _numbers(tok)
                if cand and not (cand & allowed):
                    bad("cifra_no_respaldada", f"La cifra «{tok}» de la afirmación {c.id} no aparece en lo citado.")
                    break
        if problems:
            issues.extend(problems)
        else:
            kept.append(c)
    return kept, issues


def validate_package(pkg: EditorialPackage, pack: EvidencePack, *, proposed_claims: int | None = None) -> tuple[EditorialPackage, ValidationReport]:
    """Valida formato, límites y citas. Las afirmaciones inválidas se rechazan (no se muestran)."""
    issues: list[ValidationIssue] = []
    claims, claim_issues = validate_claims(pkg.claims, pack)
    issues.extend(claim_issues)
    rejected = sorted({i.claim_id for i in claim_issues if i.claim_id})
    total_claims = proposed_claims if proposed_claims is not None else len(pkg.claims)
    valid_ids = {c.id for c in claims}

    def fix_markers(text: str, name: str) -> str:
        bad = [m for m in marker_ids(text) if m not in valid_ids]
        if bad:
            issues.append(
                ValidationIssue(code="marcador_invalido", severity="warning", message=f"{name}: marcadores a afirmaciones inexistentes o rechazadas ({', '.join(sorted(set(bad)))}); se retiraron.")
            )
            for m in set(bad):
                text = re.sub(rf"\s*\[{m}\]", "", text)
        return text

    brief = fix_markers(pkg.brief, "brief")
    script = fix_markers(pkg.script, "guion")
    copy = fix_markers(pkg.social_copy, "copy")

    if not claims:
        issues.append(ValidationIssue(code="sin_afirmaciones_validas", severity="error", message="Ninguna afirmación pasó la validación de citas."))

    # aviso obligatorio titular/metadatos
    headline_only = pack.headline_only
    notice = HEADLINE_NOTICE if headline_only else None
    if headline_only and fold(HEADLINE_PREFIX.rstrip(".")) not in fold(brief):
        brief = f"{HEADLINE_PREFIX} {brief}".strip()

    wc = {"brief": word_count(strip_markers(brief)), "script": word_count(strip_markers(script)), "socialCopy": word_count(strip_markers(copy))}
    if wc["brief"] > BRIEF_MAX_WORDS:
        issues.append(ValidationIssue(code="brief_excede_limite", severity="error", message=f"El brief tiene {wc['brief']} palabras (máximo {BRIEF_MAX_WORDS})."))
    if wc["socialCopy"] > COPY_MAX_WORDS:
        issues.append(ValidationIssue(code="copy_excede_limite", severity="error", message=f"El copy tiene {wc['socialCopy']} palabras (máximo {COPY_MAX_WORDS})."))
    secs = wc["script"] / SCRIPT_WPS
    if not (SCRIPT_MIN_S <= secs <= SCRIPT_MAX_S):
        issues.append(ValidationIssue(code="guion_fuera_de_rango", severity="error", message=f"El guion dura ≈{secs:.0f} s ({wc['script']} palabras); debe estar entre 45 y 60 s (≈{SCRIPT_MIN_WORDS}–{SCRIPT_MAX_WORDS} palabras)."))
    qs = [q.strip() for q in pkg.research_questions if q.strip()]
    if len(qs) != 3:
        issues.append(ValidationIssue(code="preguntas_invalidas", severity="error", message=f"Se requieren exactamente 3 preguntas de investigación (hay {len(qs)})."))
    if not [p for p in pkg.pending_verifications if p.strip()]:
        issues.append(ValidationIssue(code="sin_verificaciones", severity="error", message="Falta la lista de verificaciones pendientes."))
    if not pkg.proposed_title.strip() or len(pkg.proposed_title) > 160:
        issues.append(ValidationIssue(code="titulo_invalido", severity="error", message="El título propuesto está vacío o supera 160 caracteres."))
    if not pkg.public_interest_angle.strip():
        issues.append(ValidationIssue(code="sin_enfoque", severity="error", message="Falta el enfoque de interés público."))
    if not marker_ids(brief) and claims:
        issues.append(ValidationIssue(code="brief_sin_marcadores", severity="warning", message="El brief no referencia afirmaciones ([c1]…): las citas no son visibles en el texto."))
    for name, txt in (("brief", brief), ("guion", script), ("copy", copy), ("título", pkg.proposed_title)):
        if leaks_secret(txt):
            issues.append(ValidationIssue(code="posible_fuga_de_secreto", severity="error", message=f"El texto de {name} parece contener un secreto/credencial."))
    if claims and all(c.type == ClaimType.hipotesis for c in claims):
        issues.append(ValidationIssue(code="solo_hipotesis", severity="warning", message="Todas las afirmaciones son hipótesis; no hay hechos ni declaraciones respaldadas."))

    cited = [c for c in claims if c.citations]
    coverage = (len(cited) / total_claims) if total_claims else 0.0
    factual_types = (ClaimType.hecho, ClaimType.declaracion)
    factual_proposed = [c for c in pkg.claims if c.type in factual_types]
    factual_ok = [c for c in claims if c.type in factual_types and c.citations]
    factual_cov = round(len(factual_ok) / len(factual_proposed), 3) if factual_proposed else None
    ok = not [i for i in issues if i.severity == "error"]
    cleaned = pkg.model_copy(
        update={
            "brief": brief,
            "script": script,
            "social_copy": copy,
            "claims": claims,
            "research_questions": qs,
            "headline_only": headline_only,
            "headline_only_notice": notice,
        }
    )
    report = ValidationReport(
        ok=ok,
        issues=issues,
        rejected_claim_ids=rejected,
        word_counts=wc,
        script_seconds_estimate=round(secs, 1),
        citation_coverage=round(coverage, 3),
        factual_citation_coverage=factual_cov,
    )
    return cleaned, report


# --------------------------------------------------------------------------- plantilla


def _q(title: str) -> str:
    return f"«{title.strip()}»"


def build_template_package(base: TopicBase, *, score: float, band: str, status: str) -> EditorialPackage:
    """Paquete editorial determinista con citas (modo plantilla / sin conexión)."""
    claims = [c.model_copy(deep=True) for c in base.claims]
    # reenumerar de forma estable c1..cN
    for i, c in enumerate(claims, 1):
        c.id = f"c{i}"
    n = len(claims)
    decl = [c for c in claims if c.type == ClaimType.declaracion]
    facts = [c for c in claims if c.type == ClaimType.hecho]
    if base.independent >= 2 and len(decl) >= 2:
        n += 1
        claims.append(
            Claim(
                id=f"c{n}",
                type=ClaimType.inferencia,
                text=(
                    f"Dado que {len(decl)} procedencias independientes reportan el mismo evento, es razonable inferir "
                    "que el hecho fue observado más de una vez; esto no prueba su veracidad."
                ),
                citations=[c.citations[0] for c in decl[:2]],
            )
        )
    n += 1
    claims.append(
        Claim(
            id=f"c{n}",
            type=ClaimType.hipotesis,
            text=(
                f"Hipótesis a verificar: el tema podría tener interés público en {CATEGORY_LABELS[base.category.value].lower()} "
                "para Panamá; el corpus no lo confirma."
            ),
            citations=[],
        )
    )
    rep = base.usable_articles[0] if base.usable_articles else base.representative
    first_decl = decl[0] if decl else None
    outlet = rep.outlet if not rep.suspicious_instructions else "una fuente no confiable"
    title = rep.title if not rep.suspicious_instructions else MASKED_TITLE
    pending = list(base.pending)[:6] or ["Confirmar el hecho con la fuente primaria."]
    status_txt = {"insuficiente": "insuficiente", "parcial": "parcial", "suficiente": "suficiente para el borrador"}[status]
    first_marker = f" [{first_decl.id}]" if first_decl else ""

    parts = [
        f"{HEADLINE_PREFIX}",
        f"{outlet} reporta en su titular {_q(title)}{first_marker}.",
    ]
    for c in decl[1:3]:
        parts.append(f"También lo reporta {c.text.split(' reporta')[0]} [{c.id}].")
    for c in facts[:1]:
        parts.append(f"Contexto oficial: {c.text} [{c.id}]")
    if base.is_recirculation:
        parts.append(f"Atención: posible noticia antigua recirculada ({base.recirculation_reason or 'fecha original anterior'}).")
    if base.contradictions:
        parts.append("Hay versiones incompatibles entre fuentes; se muestran ambas y la revisión está pendiente, sin elegir una.")
    parts.append(
        f"Evidencia {status_txt}; puntaje de atención {score:.1f} ({band}), que ordena la revisión y no demuestra verdad."
    )
    parts.append("Falta verificar: " + "; ".join(pending[:3]) + ".")
    brief = " ".join(parts)
    while word_count(strip_markers(brief)) > 235 and len(parts) > 4:
        parts.pop(-3 if len(parts) > 5 else -2)
        brief = " ".join(parts)

    when = fmt_date_pa(base.first_published, unknown="fecha de publicación no confirmada")
    script_parts = [
        f"Tema en revisión editorial: {title.strip()}.",
        f"Según el titular de {outlet}{first_marker}, esto es lo que se reporta; la fecha original es {when}.",
    ]
    if facts:
        script_parts.append(f"Como contexto oficial: {facts[0].text} [{facts[0].id}]")
    script_parts += [
        f"Por ahora la evidencia es {status_txt}: solo contamos con titulares y metadatos, sin el texto completo.",
        f"Antes de cualquier uso editorial falta verificar lo siguiente: {pending[0].rstrip('.')}.",
        "Este guion es un borrador para revisión humana; no incluye entrevistas, imágenes ni declaraciones que no estén respaldadas.",
        "Se recomienda confirmar la fecha original y la fuente primaria antes de avanzar con cualquier pieza.",
        "La decisión editorial final corresponde a la persona responsable de la revisión.",
    ]
    script = " ".join(script_parts)
    # ajustar a 45-60 s
    fillers = [
        "Recuerda que el puntaje de atención solo ordena temas y no equivale a una verificación de los hechos.",
        "Si aparece una segunda fuente independiente, el estado de la evidencia puede cambiar.",
        "Cualquier cifra que se mencione debe citar su fuente, su año y su unidad.",
    ]
    fi = 0
    while word_count(strip_markers(script)) < SCRIPT_MIN_WORDS + 6 and fi < len(fillers):
        script += " " + fillers[fi]
        fi += 1
    while word_count(strip_markers(script)) > SCRIPT_MAX_WORDS - 4 and len(script_parts) > 5:
        script_parts.pop(-2)
        script = " ".join(script_parts)
    if word_count(strip_markers(script)) > SCRIPT_MAX_WORDS - 2:  # titular muy largo
        words = strip_markers(script).split()
        script = " ".join(words[: SCRIPT_MAX_WORDS - 6]) + "."

    copy_core = f"{title.strip()}"
    cwords = copy_core.split()
    if len(cwords) > 38:
        copy_core = " ".join(cwords[:38]) + "…"
    copy = (
        f"Borrador para revisión: {outlet} reporta {_q(copy_core)}{first_marker}. "
        f"Evidencia {status_txt}. Basado únicamente en titular/metadatos; pendiente de verificación."
    )

    angle = (
        f"Posible interés público en {CATEGORY_LABELS[base.category.value].lower()} para Panamá; el alcance real "
        "depende de verificar la fuente primaria y la fecha original."
    )
    qs = [
        "¿Qué fuente primaria u oficial confirma el hecho y qué dice exactamente?",
        "¿Cuál es la fecha original del hecho y cómo cambia la lectura si es una noticia recirculada?",
        (
            "¿Qué impacto concreto tiene para la audiencia en Panamá según datos oficiales y de qué año provienen?"
            if base.indicators
            else "¿Qué dato oficial pertinente existe para dimensionar el alcance y de qué período proviene?"
        ),
    ]
    limitations = [
        "Basado únicamente en titular/metadatos.",
        "Las citas verifican estructura, no sustento: requieren revisión humana.",
        "Borrador construido mediante plantilla; no sustituye la redacción editorial.",
    ]
    return EditorialPackage(
        proposed_title=f"Revisión: {title.strip()}"[:160],
        brief=brief,
        public_interest_angle=angle,
        research_questions=qs,
        pending_verifications=pending,
        script=script,
        social_copy=copy,
        claims=claims,
        headline_only=True,
        headline_only_notice=HEADLINE_NOTICE,
        limitations=limitations,
    )
