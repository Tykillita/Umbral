"""Exportación de la ficha a Markdown listo para pegar en Notion."""

from __future__ import annotations

from .models import CATEGORY_LABELS, GEO_LABELS, TopicDetail
from .util import fmt_pa, now_utc


def _cell(s: str | None) -> str:
    return (s or "—").replace("|", "\\|").replace("\n", " ")


def export_markdown(detail: TopicDetail) -> str:
    s = detail.summary
    case = detail.case
    out: list[str] = []
    out.append(f"# Ficha: {s.title}")
    out.append("")
    out.append(f"- **ID del tema:** `{s.id}`  ·  **ID del caso:** `{case.case_id}`")
    out.append(f"- **Snapshot:** `{detail.snapshot_id}` ({detail.data_mode.value})  ·  **Reglas:** `{detail.rules_version}`")
    out.append(f"- **Categoría:** {CATEGORY_LABELS[s.category.value]}  ·  **Relevancia geográfica:** {GEO_LABELS[s.geo_relevance.value]}")
    out.append(f"- **Puntaje de atención:** {s.score:.2f} / 100 ({s.band.value})  ·  **Estado de evidencia:** {s.evidence_status_label}")
    out.append(f"- **Estado de revisión:** {case.status_label}  ·  **Responsable:** {case.reviewer or '—'}  ·  **Versión del caso:** {case.version}")
    out.append(f"- **Exportado:** {fmt_pa(now_utc())}")
    if detail.data_mode.value == "fixture":
        out.append("")
        out.append("> ⚠️ Datos de **fixture** (sintéticos): solo para demostración del contrato.")
    out.append("")
    out.append("> Basado únicamente en titular/metadatos. El puntaje ordena la atención; no es una probabilidad de verdad ni habilita publicación.")
    if s.needs_investigation:
        out.append("> 🔎 Prioridad alta con evidencia insuficiente: requiere investigación; no habilita publicación.")
    out.append("")
    out.append("## Qué se reporta")
    out.append(detail.what_is_reported)
    out.append("")
    out.append("## Quién lo reporta y procedencia")
    out.append("| Medio | Procedencia | Rol | Fuentes |")
    out.append("|---|---|---|---|")
    for r in detail.reporters:
        out.append(f"| {_cell(r.outlet)} | {_cell(r.origin)}{'' if r.origin_known else ' (desconocida)'} | {r.role} | {', '.join(f'`{i}`' for i in r.evidence_ids)} |")
    out.append("")
    out.append("## Noticias agrupadas")
    out.append("| ID | Titular | Medio | Publicación original | Detección | Extracción | URL |")
    out.append("|---|---|---|---|---|---|---|")
    for a in detail.articles:
        flag = " ⚠ contiene instrucciones (contenido no confiable)" if a.suspicious_instructions else ""
        out.append(
            f"| `{a.id}` | {_cell(a.title)}{flag} | {_cell(a.outlet)} | {fmt_pa(a.published_at, unknown='desconocida')} | "
            f"{fmt_pa(a.detected_at, unknown='—')} | {fmt_pa(a.extracted_at, unknown='—')} | {a.url} |"
        )
    out.append("")
    out.append("## Puntaje desglosado")
    out.append(f"`{detail.score.formula}` — {detail.rules_version}")
    out.append("")
    out.append("| Componente | Peso | Valor | Puntos | Regla / justificación | Límites |")
    out.append("|---|---|---|---|---|---|")
    for sc in detail.score.components:
        out.append(
            f"| {sc.key} · {sc.label} | {sc.weight} | {sc.value:g} | {sc.points:g} | {_cell(sc.rule + ' ' + sc.justification)} | {_cell('; '.join(sc.limits))} |"
        )
    out.append(f"\n**Total: {detail.score.total:.2f} ({detail.score.band.value})**. Desempate: urgencia, luego ID.")
    out.append("")
    out.append("## Estado de evidencia")
    out.append(f"**{detail.evidence.status_label}** — {detail.evidence.rationale}")
    if detail.evidence.reviewer_confirmed is not None:
        out.append(f"Confirmación del revisor: {'confirma suficiencia' if detail.evidence.reviewer_confirmed else 'no confirma suficiencia'} ({detail.evidence.reviewer_confirmed_by or '—'}).")
    for g in detail.evidence.gaps:
        out.append(f"- {g.message}")
    out.append("")
    out.append("## Contexto oficial")
    out.append(detail.official_context.relation_rationale)
    if detail.official_context.indicators:
        out.append("")
        out.append("| País | Indicador | Año | Valor | Unidad | Fuente |")
        out.append("|---|---|---|---|---|---|")
        for ip in detail.official_context.indicators:
            val = "ausente (nulo)" if ip.is_missing else f"{ip.value:g}"
            out.append(f"| {ip.country_iso3} | {_cell(ip.indicator_name)} | {ip.year} | {val} | {_cell(ip.unit)} | {ip.source_url or '—'} |")
    for lim in detail.official_context.limitations:
        out.append(f"- _{lim}_")
    out.append("")
    if detail.contradictions:
        out.append("## Contradicciones (revisión pendiente)")
        for ct in detail.contradictions:
            out.append(f"- {ct.description}")
            for v in ct.versions:
                out.append(f"  - {v.outlet}: «{v.statement}» (`{v.evidence_id}`, {v.scope})")
            out.append(f"  - Pendiente: {ct.pending_verification}")
        out.append("")
    out.append("## Afirmaciones respaldadas")
    for cl in detail.supported_claims:
        cites = ", ".join(f"`{x.evidence_id}`·{x.field}" + (f" — «{x.passage}»" if x.passage else "") for x in cl.citations)
        out.append(f"- **[{cl.type.value}]** {cl.text} ({cites})")
    out.append("")
    out.append("## Verificaciones pendientes")
    for p in detail.pending_verifications:
        out.append(f"- [ ] {p}")
    out.append("")
    out.append("## Acción recomendada")
    out.append(detail.recommended_action)
    out.append("")
    out.append("## Impacto")
    imp = detail.impact
    out.append(f"**{imp.level.value}** ({'asignación editorial' if imp.origin == 'editorial' else 'propuesta automática, requiere confirmación'}): {imp.justification}")
    if imp.reason:
        out.append(f"Motivo del cambio: {imp.reason} (autor: {imp.author or '—'}, versión {imp.version}).")
    out.append("")
    d = case.current_draft
    out.append("## Borrador")
    if d is None:
        out.append("_Aún no se ha generado un borrador._")
    else:
        out.append(f"**{d.generation_label}** · proveedor `{d.provider}`{f' · modelo `{d.model}`' if d.model else ''} · borrador #{d.number}")
        if d.fallback_reason:
            out.append(f"Motivo de respaldo: {d.fallback_reason.value}{f' — {d.fallback_detail}' if d.fallback_detail else ''}.")
        pk = d.package
        out.append("")
        out.append(f"### {pk.proposed_title}")
        if pk.headline_only_notice:
            out.append(f"> {pk.headline_only_notice}")
        out.append("")
        out.append(f"**Enfoque de interés público.** {pk.public_interest_angle}")
        out.append("")
        out.append("**Brief**")
        out.append(pk.brief)
        out.append("")
        out.append("**Preguntas de investigación**")
        for i, q in enumerate(pk.research_questions, 1):
            out.append(f"{i}. {q}")
        out.append("")
        out.append("**Verificaciones pendientes**")
        for pv in pk.pending_verifications:
            out.append(f"- [ ] {pv}")
        out.append("")
        out.append(f"**Guion (≈{d.validation.script_seconds_estimate:.0f} s)**")
        out.append(pk.script)
        out.append("")
        out.append("**Copy digital**")
        out.append(pk.social_copy)
        out.append("")
        out.append("**Afirmaciones y citas**")
        out.append("| ID | Tipo | Afirmación | Citas (ID · campo · pasaje) |")
        out.append("|---|---|---|---|")
        for cl in pk.claims:
            cites = "; ".join(f"`{x.evidence_id}`·{x.field}" + (f" — «{_cell(x.passage)}»" if x.passage else "") for x in cl.citations) or "—"
            out.append(f"| {cl.id} | {cl.type.value} | {_cell(cl.text)} | {cites} |")
        out.append("")
        out.append(f"_Validación: {'correcta' if d.validation.ok else 'con errores'}; cobertura de citas {d.validation.citation_coverage:.0%}. {d.validation.note}_")
    out.append("")
    out.append("## Historial de revisión")
    if not case.history:
        out.append("_Sin eventos._")
    for e in case.history:
        tr = f" {e.from_status.value if e.from_status else '—'} → {e.to_status.value}" if e.to_status else ""
        out.append(f"- v{e.version} · {fmt_pa(e.at)} · {e.kind}{tr} · {e.actor}{f' — {e.comment}' if e.comment else ''}"
            + (f" · reglas `{e.rules_version}`" if e.rules_version else ""))
    out.append("")
    return "\n".join(out)
