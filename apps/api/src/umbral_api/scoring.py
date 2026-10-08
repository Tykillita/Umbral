"""Ranking `scoring-v1`: P = 30R + 25I + 20U + 15N + 10E (0-100), con aritmética exacta (Fraction).

Reglas, bandas y desempate según PLAN §3. Las fechas se evalúan contra el corte del snapshot (reproducible).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fractions import Fraction

from .models import (
    GeoRelevance,
    ImpactAssignment,
    ImpactLevel,
    ScoreBand,
    ScoreComponent,
    ScoreDetail,
)

RULES_VERSION = "scoring-v1"
WEIGHTS = {"R": 30, "I": 25, "U": 20, "N": 15, "E": 10}
LABELS = {"R": "Relevancia", "I": "Impacto potencial", "U": "Urgencia", "N": "Novedad", "E": "Evidencia disponible"}

RULE_TEXT = {
    "R": "Panamá: 1; relación regional: 0,5; sin relación o indeterminada: 0.",
    "I": "Asignación editorial: bajo 0,25; medio 0,5; alto 1. Requiere justificación con evidencia.",
    "U": "Publicación original dentro de 24 h del corte: 1; dentro de 7 días: 0,5; anterior o desconocida: 0.",
    "N": "Evento nuevo: 1; recirculación: 0. Los duplicados conservan la puntuación del evento.",
    "E": "Sin procedencia: 0; una: 0,33; dos independientes: 0,67; fuente primaria pertinente + cobertura original: 1.",
}
BANDS = {"bajo": "[0, 40)", "medio": "[40, 70)", "alto": "[70, 100]"}
CHANGELOG = [
    {
        "version": "scoring-v1",
        "date": "2026-10-07",
        "reason": "Reglas iniciales del PLAN §3. Los cambios de pesos o reglas crean una versión nueva con motivo; "
        "los cambios editoriales de impacto conservan motivo, autor y versión del caso.",
    }
]

_R = {GeoRelevance.panama: Fraction(1), GeoRelevance.regional: Fraction(1, 2)}
_I = {ImpactLevel.bajo: Fraction(1, 4), ImpactLevel.medio: Fraction(1, 2), ImpactLevel.alto: Fraction(1)}
_E_VALUES = {0: Fraction(0), 1: Fraction(33, 100), 2: Fraction(67, 100)}


def _prob(evidence: str) -> float | None:
    m = re.search(r"=\s*([0-9]*\.?[0-9]+)\s*$", evidence)
    return float(m.group(1)) if m else None


def relevance_explanation(geo: GeoRelevance, value: Fraction, basis: list[tuple[str, str, list[str]]]) -> str:
    rule = {
        GeoRelevance.panama: "Panamá: 1",
        GeoRelevance.regional: "relación regional: 0,5",
        GeoRelevance.none: "sin relación: 0",
        GeoRelevance.indeterminate: "indeterminada: 0",
    }[geo]
    txt = f"R = {float(value):g}. Regla aplicada: {rule} (clasificador de relevancia geográfica; máximo entre los artículos del evento)."
    if basis:
        pid, title, ev = basis[0]
        shown = title if len(title) <= 140 else title[:137] + "…"
        txt += f" Titular que la justifica [{pid}]: «{shown}»."
        if ev:
            txt += f" Evidencia (regla de contenido o clasificador): {', '.join(ev)}."
    else:
        txt += " Sin artículo que la respalde."
    return txt


def band_for(total: Fraction | float) -> ScoreBand:
    if total < 40:
        return ScoreBand.bajo
    if total < 70:
        return ScoreBand.medio
    return ScoreBand.alto


@dataclass
class ScoreInputs:
    geo: GeoRelevance
    geo_evidence_ids: list[str]
    impact: ImpactAssignment
    first_published: datetime | None
    publish_date_issue: str | None
    cutoff: datetime
    is_recirculation: bool
    recirculation_reason: str | None
    independent_provenances: int
    primary_source_linked: bool  # fuente primaria pertinente CONFIRMADA por un revisor
    primary_source_ids: list[str]
    has_outlet_original: bool
    provenance_known: bool
    article_ids: list[str]
    sponsored: bool = False  # posible contenido patrocinado: E máximo 0,33
    geo_basis: list[tuple[str, str, list[str]]] = field(default_factory=list)  # (id, titular, evidencia del clasificador)


def urgency_value(first_published: datetime | None, cutoff: datetime) -> tuple[Fraction, str, list[str]]:
    limits: list[str] = []
    if first_published is None:
        limits.append("Fecha de publicación original desconocida (solo fecha de detección): no se infiere urgencia.")
        return Fraction(0), "Fecha de publicación desconocida: 0.", limits
    age = cutoff - first_published
    if age < timedelta(0):
        limits.append("La fecha de publicación es posterior al corte del snapshot; se ignora.")
        return Fraction(0), "Fecha posterior al corte: 0.", limits
    hours = age.total_seconds() / 3600
    if age <= timedelta(hours=24):
        return Fraction(1), f"Publicado hace {hours:.1f} h respecto al corte (≤24 h): 1.", limits
    if age <= timedelta(days=7):
        return Fraction(1, 2), f"Publicado hace {age.days} d {int(hours % 24)} h respecto al corte (≤7 d): 0,5.", limits
    return Fraction(0), f"Publicado hace {age.days} d respecto al corte (>7 d): 0.", limits


def evidence_value(inp: ScoreInputs) -> tuple[Fraction, str, list[str]]:
    limits: list[str] = []
    n = inp.independent_provenances
    if n == 0:
        return Fraction(0), "Sin procedencia identificable: 0.", ["No hay procedencia independiente."]
    if inp.sponsored:
        limits.append("Posible contenido patrocinado: E limitado a 0,33 y no cuenta como procedencia independiente.")
        return _E_VALUES[1], "Posible contenido patrocinado: máximo 0,33.", limits
    if inp.primary_source_linked and inp.has_outlet_original:
        return Fraction(1), "Fuente primaria pertinente confirmada por un revisor + cobertura original: 1.", limits
    if not inp.provenance_known:
        limits.append("Procedencia desconocida: se identifica pero no se acredita como independiente.")
    if n >= 2:
        limits.append(
            "Sin fuente primaria pertinente confirmada (una serie oficial vinculada por tema es solo contexto): máximo 0,67."
        )
        return _E_VALUES[2], f"{n} procedencias independientes: 0,67.", limits
    limits.append("Una sola procedencia: la repetición no es corroboración.")
    return _E_VALUES[1], "Una procedencia: 0,33.", limits


def score_topic(inp: ScoreInputs, *, weights: dict[str, int] | None = None, rules_version: str = RULES_VERSION) -> ScoreDetail:
    weights = weights or WEIGHTS
    comps: list[ScoreComponent] = []
    total = Fraction(0)

    # R
    r = _R.get(inp.geo, Fraction(0))
    r_lim = []
    if inp.geo in (GeoRelevance.indeterminate, GeoRelevance.none):
        r_lim.append("Relevancia geográfica sin relación demostrada o indeterminada: 0, no se fuerza.")
    r_lim.append("Relevancia tomada del máximo entre los artículos del evento (clasificador, sin calibrar).")
    r_just = relevance_explanation(inp.geo, r, inp.geo_basis)
    if inp.geo in (GeoRelevance.panama, GeoRelevance.regional) and inp.geo_basis:
        weak = [p for p in (_prob(e) for _, _, ev in inp.geo_basis for e in ev) if p is not None and p < 0.7]
        if weak:
            r_lim.append(
                f"Evidencia débil (probabilidad {min(weak):.2f} < 0,70): puede ser un falso positivo; "
                "verifica el titular antes de confiar en este componente."
            )
    r_lim.append(
        "R no se edita en la API: si es incorrecta, corrige la clasificación en el pipeline (predictions) o descarta el caso con comentario."
    )
    comps.append(_comp("R", r, r_just, r_lim, inp.geo_evidence_ids))
    total += 30 * r

    # I
    i = _I[inp.impact.level]
    i_lim = []
    if inp.impact.origin != "editorial":
        i_lim.append("Impacto propuesto automáticamente (heurística con evidencia); requiere confirmación editorial.")
    comps.append(
        _comp("I", i, f"Impacto {inp.impact.level.value}: {inp.impact.justification}", i_lim, inp.impact.evidence_ids)
    )
    total += 25 * i

    # U
    u, u_just, u_lim = urgency_value(inp.first_published, inp.cutoff)
    if inp.publish_date_issue:
        u_lim.append(inp.publish_date_issue)
    comps.append(_comp("U", u, u_just, u_lim, inp.article_ids[:3]))
    total += 20 * u

    # N
    n = Fraction(0) if inp.is_recirculation else Fraction(1)
    n_lim = ["Los duplicados conservan la puntuación del evento: repetir no aumenta N."]
    n_just = "Evento nuevo: 1." if n == 1 else f"Recirculación: 0. {inp.recirculation_reason or ''}".strip()
    comps.append(_comp("N", n, n_just, n_lim, inp.article_ids[:3]))
    total += 15 * n

    # E
    e, e_just, e_lim = evidence_value(inp)
    ev_ids = inp.primary_source_ids + inp.article_ids[:3]
    comps.append(_comp("E", e, e_just, e_lim, ev_ids))
    total += 10 * e

    # Recalcula con una configuración versionada; los valores/reglas originales permanecen reproducibles.
    total = Fraction(0)
    for component in comps:
        component.weight = weights[component.key]
        points = Fraction(str(component.value)) * component.weight
        component.points = round(float(points), 2)
        total += points
    total_f = round(float(total), 2)
    return ScoreDetail(
        total=total_f,
        band=band_for(total),
        rules_version=rules_version,
        formula="P = " + " + ".join(f"{weights[k]}{k}" for k in WEIGHTS),
        components=comps,
        urgency_tiebreak=float(u),
        id_tiebreak="",
    )


def _comp(key: str, value: Fraction, just: str, limits: list[str], ids: list[str]) -> ScoreComponent:
    return ScoreComponent(
        key=key,
        label=LABELS[key],
        weight=WEIGHTS[key],
        value=float(value),
        points=round(float(WEIGHTS[key] * value), 2),
        rule=RULE_TEXT[key],
        justification=just,
        limits=limits,
        evidence_ids=list(dict.fromkeys(ids)),
    )


def sort_key(total: float, urgency: float, topic_id: str) -> tuple[float, float, str]:
    """Orden: puntaje desc, urgencia desc, ID asc."""
    return (-total, -urgency, topic_id)
