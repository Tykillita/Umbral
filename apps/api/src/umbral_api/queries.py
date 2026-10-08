"""Consultas en español con evidencia: recuperación BM25+RapidFuzz, citas y abstención explícita."""

from __future__ import annotations

import re
import time
import uuid

from .models import (
    AnswerStatus,
    Contradiction,
    DataMode,
    IndicatorPoint,
    QueryCitation,
    QueryHit,
    QueryIntent,
    QueryRequest,
    QueryResponse,
    RetrievalInfo,
    TopicSummary,
)
from .retrieval import Doc, SearchIndex, fold, tokenize
from .scoring import RULES_VERSION
from .security import looks_like_instruction
from .snapshot import Corpus
from .topics import COUNTRY_KEYWORDS, INDICATOR_KEYWORDS, MASKED_TITLE, TopicBase
from .util import fmt_date_pa

INDICATOR_ES = {
    "NY.GDP.MKTP.KD.ZG": "crecimiento del PIB producto interno bruto crecimiento económico",
    "FP.CPI.TOTL.ZG": "inflación precios al consumidor costo de vida",
    "SL.UEM.TOTL.ZS": "desempleo tasa de desempleo mercado laboral",
    "SP.POP.TOTL": "población habitantes demografía",
    "IT.NET.USER.ZS": "uso de internet usuarios de internet conectividad",
    "NE.EXP.GNFS.ZS": "exportaciones de bienes y servicios comercio exterior porcentaje del PIB",
}
INDICATOR_LABEL_ES = {
    "NY.GDP.MKTP.KD.ZG": "Crecimiento del PIB",
    "FP.CPI.TOTL.ZG": "Inflación (precios al consumidor)",
    "SL.UEM.TOTL.ZS": "Desempleo",
    "SP.POP.TOTL": "Población total",
    "IT.NET.USER.ZS": "Uso de internet",
    "NE.EXP.GNFS.ZS": "Exportaciones de bienes y servicios",
}
_COUNTRY_ES = {"PAN": "Panamá", "CRI": "Costa Rica", "COL": "Colombia", "DOM": "República Dominicana", "MEX": "México", "GTM": "Guatemala"}

_GENERIC_ECON = {
    "econom", "economico", "contexto", "indicador", "indicadores", "banco", "mundial", "oficial", "oficiales", "dato",
    "datos", "valor", "valores", "ano", "anos", "serie", "ultimo", "ultima", "actual", "actuales", "cifra", "cifras",
    "nivel", "tasa", "porcentaje", "anual", "pais", "paises", "comparado", "compara", "comparar", "evolucion",
    "tendencia", "periodo", "unidad", "fuente", "tema", "dame", "dime", "muestra", "pib", "inflacion", "desempleo",
    "poblacion", "internet", "exportacion", "exportaciones", "crecimiento", "cuant", "cual", "como",
}
_RE_AGENDA = re.compile(r"\b(cinco|5|principales)\b.*\btemas?\b|\bque temas?\b|\bagenda\b|merecen revision|\bpriorid\w*|\bprioriz\w*")
_RE_VERIF = re.compile(r"falta(n)?\s+(por\s+)?verificar|verificaciones?|pendientes?\s+de\s+verif|que falta|vacios|por comprobar|falta comprobar")
_RE_ECON = re.compile(r"contexto economico|indicadores?|banco mundial|\bpib\b|inflacion|desempleo|poblacion|\binternet\b|exportacion|crecimiento economico")
_RE_NUMERIC = re.compile(r"\bcuant[oa]s?\b|\bcifra\b|\bmonto\b|\bporcentaje\b|\bnumero de\b|\btotal de\b|\bcuanto cuesta\b")
_RE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def _detect_intent(q: str) -> QueryIntent:
    f = fold(q)
    if _RE_VERIF.search(f):
        return QueryIntent.verificaciones
    if _RE_AGENDA.search(f):
        return QueryIntent.agenda
    if _RE_ECON.search(f):
        return QueryIntent.contexto_economico
    return QueryIntent.busqueda


class QueryEngine:
    def __init__(self, corpus: Corpus, bases: dict[str, TopicBase]):
        self.corpus = corpus
        self.bases = bases
        docs: list[Doc] = []
        for a in corpus.articles.values():
            docs.append(Doc(a.id, "articulo", f"{a.title} {a.outlet}", a.cluster_id))
        for p in corpus.indicators.values():
            docs.append(
                Doc(
                    p.id,
                    "indicador",
                    f"{INDICATOR_ES.get(p.indicator_id, p.indicator_name)} {p.country_name or ''} {p.country_iso3} {p.year} indicador oficial",
                )
            )
        self.index = SearchIndex(docs)
        self.article_ids = set(corpus.articles)

    # ------------------------------------------------------------------ API
    def answer(self, req: QueryRequest, agenda: list[TopicSummary]) -> QueryResponse:
        t0 = time.perf_counter()
        q = req.question.strip()
        warnings: list[str] = []
        if looks_like_instruction(q):
            warnings.append(
                "La consulta contiene texto con forma de instrucción; se trata solo como texto de búsqueda y no cambia el comportamiento del sistema."
            )
        intent = _detect_intent(q)
        scope = None
        if req.topic_id:
            scope = self.bases.get(req.topic_id)
            if scope is None:
                return self._abstain(req, intent, t0, "El tema indicado no existe en el snapshot servido.", warnings)

        if intent == QueryIntent.agenda:
            resp = self._agenda(req, agenda, t0)
        elif intent == QueryIntent.verificaciones:
            resp = self._verificaciones(req, scope, t0)
        elif intent == QueryIntent.contexto_economico:
            resp = self._economico(req, scope, t0)
        else:
            resp = self._busqueda(req, scope, t0)
        resp.warnings = warnings + resp.warnings
        return resp

    # ------------------------------------------------------------------ helpers
    def _base_resp(self, req: QueryRequest, intent: QueryIntent, t0: float, **kw) -> QueryResponse:  # noqa: ANN003
        return QueryResponse(
            query_id="q_" + uuid.uuid4().hex[:12],
            question=req.question,
            intent=intent,
            answer_status=kw.pop("answer_status"),
            answer=kw.pop("answer"),
            snapshot_id=self.corpus.snapshot_id,
            rules_version=RULES_VERSION,
            data_mode=self.corpus.data_mode,
            retrieval=RetrievalInfo(
                corpus_size=len(self.index.docs),
                took_ms=round((time.perf_counter() - t0) * 1000, 2),
                matched_terms=kw.pop("matched_terms", []),
                coverage=kw.pop("coverage", 0.0),
            ),
            **kw,
        )

    def _abstain(self, req: QueryRequest, intent: QueryIntent, t0: float, reason: str, warnings: list[str] | None = None,
                 missing: list[str] | None = None, hits: list[QueryHit] | None = None, coverage: float = 0.0,
                 matched: list[str] | None = None) -> QueryResponse:
        return self._base_resp(
            req,
            intent,
            t0,
            answer_status=AnswerStatus.abstencion,
            answer=(
                "No puedo responder con la evidencia del corpus: " + reason +
                " No se inventan cifras, declaraciones ni fuentes."
            ),
            abstention_reason=reason,
            missing=missing or ["Una fuente en el corpus que respalde la consulta."],
            hits=hits or [],
            warnings=warnings or [],
            coverage=coverage,
            matched_terms=matched or [],
        )

    def _hit_model(self, h, art_only: bool = True) -> QueryHit:  # noqa: ANN001
        d = h.doc
        if d.kind == "articulo":
            a = self.corpus.articles[d.doc_id]
            shown = MASKED_TITLE if a.suspicious_instructions else a.title  # nunca se reproduce texto con instrucciones
            return QueryHit(
                evidence_id=a.id, kind="articulo", title=shown, url=a.url, outlet=a.outlet, published_at=a.published_at,
                snippet=shown, bm25=round(h.bm25, 4), fuzzy=round(h.fuzzy, 4), relevance=h.relevance,
                cluster_id=a.cluster_id, suspicious_instructions=a.suspicious_instructions,
            )
        p = self.corpus.indicators[d.doc_id]
        return QueryHit(
            evidence_id=p.id, kind="indicador", title=f"{p.indicator_name} · {p.country_iso3} · {p.year}", url=p.source_url,
            outlet="Banco Mundial", snippet=_ind_text(p), bm25=round(h.bm25, 4), fuzzy=round(h.fuzzy, 4),
            relevance=h.relevance,
        )

    def _unknown_entities(self, question: str, scope: TopicBase | None) -> list[str]:
        """Términos de la pregunta que no son indicador, país, año ni palabra genérica (p. ej. «Marte»)."""
        known: set[str] = set(_GENERIC_ECON)
        for kws in list(INDICATOR_KEYWORDS.values()) + list(COUNTRY_KEYWORDS.values()):
            for kw in kws:
                known.update(tokenize(kw))
        for iso, name in _COUNTRY_ES.items():
            known.update(tokenize(name))
            known.add(fold(iso))
        for txt in list(INDICATOR_ES.values()) + list(INDICATOR_LABEL_ES.values()):
            known.update(tokenize(txt))
        if scope is not None:
            known.update(tokenize(scope.search_text))
        out = []
        for raw in re.findall(r"[a-záéíóúñü]+", question.lower()):
            for t in tokenize(raw):
                if t not in known and not t.isdigit():
                    out.append(raw)
        return list(dict.fromkeys(out))

    # ------------------------------------------------------------------ intents
    def _agenda(self, req: QueryRequest, agenda: list[TopicSummary], t0: float) -> QueryResponse:
        top = agenda[: max(1, min(req.limit, 5))] if agenda else []
        if not top:
            return self._abstain(req, QueryIntent.agenda, t0, "no hay temas en el snapshot servido.")
        lines = []
        cites: list[QueryCitation] = []
        for i, t in enumerate(top, 1):
            b = self.bases[t.id]
            lines.append(
                f"{i}. **{t.title}**\n"
                f"Puntaje **{t.score:.2f}** ({t.band.value}) · evidencia {t.evidence_status_label.lower()}"
                f"{' · requiere investigación (prioridad alta con evidencia insuficiente)' if t.needs_investigation else ''}."
            )
            rep = b.representative
            if rep.suspicious_instructions:
                continue
            cites.append(QueryCitation(evidence_id=rep.id, field="title", passage=rep.title, title=rep.title, url=rep.url))
        ans = (
            f"**Temas que merecen revisión** según `{RULES_VERSION}` (snapshot {self.corpus.snapshot_id}).\n\n"
            "Basado únicamente en titular/metadatos: el puntaje ordena, no demuestra verdad ni habilita publicación.\n\n"
            + "\n".join(lines)
        )
        return self._base_resp(
            req, QueryIntent.agenda, t0, answer_status=AnswerStatus.respondida, answer=ans, citations=cites,
            related_topic_ids=[t.id for t in top],
            missing=[g for t in top for g in [f"{t.title}: ver verificaciones pendientes en la ficha."] if t.evidence_status.value != "suficiente"][:5],
        )

    def _verificaciones(self, req: QueryRequest, scope: TopicBase | None, t0: float) -> QueryResponse:
        base = scope
        hits_models: list[QueryHit] = []
        if base is None:
            hits, _, _ = self.index.search(req.question, limit=5, restrict=self.article_ids)
            hits_models = [self._hit_model(h) for h in hits]
            if hits and hits[0].coverage >= 0.5 and hits[0].doc.cluster_id in self.bases:
                base = self.bases[hits[0].doc.cluster_id or ""]
        if base is None:
            return self._abstain(
                req, QueryIntent.verificaciones, t0,
                "no identifico a qué tema se refiere la pregunta; indica un tema (topicId) o menciona su titular.",
                hits=hits_models,
            )
        pend = base.pending
        cites = [QueryCitation(evidence_id=a.id, field="title", passage=a.title, title=a.title, url=a.url) for a in base.usable_articles[:3]]
        ans = (
            f"Verificaciones pendientes para «{base.display_title}» "
            f"(evidencia {base.system_status.value}, basado únicamente en titular/metadatos):\n"
            + "\n".join(f"- {p}" for p in pend)
        )
        return self._base_resp(
            req, QueryIntent.verificaciones, t0, answer_status=AnswerStatus.respondida, answer=ans, citations=cites,
            missing=pend, related_topic_ids=[base.id], hits=hits_models, contradictions=base.contradictions,
        )

    def _economico(self, req: QueryRequest, scope: TopicBase | None, t0: float) -> QueryResponse:
        f = fold(req.question)
        inds = [k for k, kws in INDICATOR_KEYWORDS.items() if any(kw.strip() in f for kw in kws)]
        countries = [c for c, kws in COUNTRY_KEYWORDS.items() if any(kw in f for kw in kws)] or ["PAN"]
        years = [int(y) for y in _RE_YEAR.findall(f)]
        asked_today = bool(re.search(r"\bhoy\b|\bactual(es|mente)?\b|\beste ano\b|\bahora\b", f))
        unknown = self._unknown_entities(req.question, scope)
        if unknown:
            return self._abstain(
                req, QueryIntent.contexto_economico, t0,
                f"no puedo vincular «{', '.join(unknown)}» con ningún país o indicador oficial del paquete "
                "(Panamá, Costa Rica, Colombia, República Dominicana, México, Guatemala).",
                missing=[f"Un indicador oficial pertinente para: {', '.join(unknown)}."],
            )
        if not inds and scope is not None and scope.indicators:
            inds = sorted({p.indicator_id for p in scope.indicators})
            countries = sorted({p.country_iso3 for p in scope.indicators})
        if not inds:
            avail = ", ".join(INDICATOR_LABEL_ES.values())
            return self._abstain(
                req, QueryIntent.contexto_economico, t0,
                "no identifico qué indicador oficial pides.",
                missing=[f"Indica un indicador entre: {avail}."],
            )
        lines: list[str] = []
        cites: list[QueryCitation] = []
        missing: list[str] = []
        selected_ids: set[str] = set()
        found = 0
        for iso in countries:
            for ind in inds:
                rows = sorted(
                    (p for p in self.corpus.indicators.values() if p.country_iso3 == iso and p.indicator_id == ind),
                    key=lambda p: p.year,
                )
                label = f"{INDICATOR_LABEL_ES.get(ind, ind)} de {_COUNTRY_ES.get(iso, iso)}"
                if years:
                    for y in years:
                        row = next((p for p in rows if p.year == y), None)
                        if row is None:
                            missing.append(f"{label} {y}: el año no existe en la cuadrícula del paquete (2010–2024).")
                        elif row.is_missing:
                            missing.append(f"{label} {y}: valor ausente en la fuente (se conserva como nulo, no se rellena).")
                        else:
                            found += 1
                            selected_ids.add(row.id)
                            lines.append(f"- {label}, {y}: {row.value:g} {row.unit or ''} (dato anual de referencia, no una medición de hoy).")
                            cites.extend(_ind_cites(row))
                else:
                    valid = [p for p in rows if not p.is_missing and p.year <= self.corpus.cutoff.year]
                    if not valid:
                        missing.append(f"{label}: sin valores disponibles en el paquete.")
                        continue
                    row = valid[-1]
                    found += 1
                    selected_ids.add(row.id)
                    lines.append(f"- {label}, último año con dato {row.year}: {row.value:g} {row.unit or ''} (dato anual de referencia, no una medición de hoy).")
                    cites.extend(_ind_cites(row))
                    later = [p for p in rows if p.is_missing and p.year > row.year]
                    if later:
                        missing.append(f"{label}: {', '.join(str(p.year) for p in later)} sin valor en la fuente.")
        if found == 0:
            return self._abstain(
                req, QueryIntent.contexto_economico, t0,
                "el paquete oficial no contiene el valor solicitado.", missing=missing or None,
            )
        extra = " Se pidió un dato «de hoy»: el paquete solo tiene valores anuales históricos." if asked_today else ""
        ans = (
            "Contexto oficial (Banco Mundial, snapshot " + self.corpus.snapshot_id + "):\n" + "\n".join(lines) + extra
        )
        status = AnswerStatus.respondida if not missing else AnswerStatus.parcial
        ranked_hits, _, _ = self.index.search(req.question, limit=req.limit, restrict=selected_ids)
        return self._base_resp(
            req, QueryIntent.contexto_economico, t0, answer_status=status, answer=ans, citations=cites,
            missing=missing, related_topic_ids=[scope.id] if scope else [],
            hits=[self._hit_model(hit) for hit in ranked_hits],
            matched_terms=ranked_hits[0].matched if ranked_hits else [],
            coverage=round(ranked_hits[0].coverage, 3) if ranked_hits else 0.0,
        )

    def _busqueda(self, req: QueryRequest, scope: TopicBase | None, t0: float) -> QueryResponse:
        restrict = None
        if scope is not None:
            restrict = {a.id for a in scope.articles} | {p.id for p in scope.indicators}
        future_years = {year for year in _RE_YEAR.findall(req.question) if int(year) > self.corpus.cutoff.year}
        if future_years:
            future_ids = {a.id for a in self.corpus.articles.values()
                          if not a.suspicious_instructions and future_years <= set(_RE_YEAR.findall(a.title))}
            restrict = future_ids if restrict is None else restrict & future_ids
            if not restrict:
                return self._abstain(
                    req, QueryIntent.busqueda, t0,
                    "la consulta pide un año futuro que no aparece en ningún titular pertinente del corpus.",
                    missing=["Una fuente que mencione explícitamente el periodo futuro solicitado; no se predicen resultados."],
                )
        hits, qtoks, unmatched = self.index.search(req.question, limit=max(req.limit, 5), restrict=restrict)
        hit_models = [self._hit_model(h) for h in hits[: req.limit]]
        if not hits:
            return self._abstain(
                req, QueryIntent.busqueda, t0, "ningún documento del corpus coincide con los términos de la consulta.",
                missing=[f"Cobertura para: {', '.join(unmatched or qtoks) or req.question}."],
            )
        best = hits[0]
        coverage = round(best.coverage, 3)
        if coverage < 0.5:
            return self._abstain(
                req, QueryIntent.busqueda, t0,
                f"la mejor coincidencia cubre menos de la mitad de los términos de la consulta (términos sin respaldo: "
                f"{', '.join(sorted(set(qtoks) - set(best.matched))) or '—'}).",
                hits=hit_models, coverage=coverage, matched=best.matched,
                missing=[f"Evidencia que mencione: {', '.join(sorted(set(qtoks) - set(best.matched)))}."],
            )
        # ¿pide una cifra? solo se responde si algún titular relevante la contiene
        wants_number = bool(_RE_NUMERIC.search(fold(req.question)))
        arts = [h for h in hits if h.doc.kind == "articulo"]
        usable = [h for h in arts if not self.corpus.articles[h.doc.doc_id].suspicious_instructions and h.coverage >= 0.5]
        warnings: list[str] = []
        for h in arts:
            if self.corpus.articles[h.doc.doc_id].suspicious_instructions:
                warnings.append(
                    f"La fuente {h.doc.doc_id} contiene instrucciones dirigidas a un agente: se trató como contenido no confiable y no se usó."
                )
        ind_hits = [h for h in hits if h.doc.kind == "indicador" and h.coverage >= 0.5]
        if not usable and not ind_hits:
            return self._abstain(
                req, QueryIntent.busqueda, t0, "las únicas coincidencias son fuentes no confiables o de baja cobertura.",
                hits=hit_models, coverage=coverage, matched=best.matched, warnings=warnings,
            )
        if wants_number and not any(re.search(r"\d", self.corpus.articles[h.doc.doc_id].title) for h in usable) and not ind_hits:
            return self._abstain(
                req, QueryIntent.busqueda, t0,
                "los titulares relacionados no contienen la cifra solicitada y no hay serie oficial pertinente.",
                hits=hit_models, coverage=coverage, matched=best.matched, warnings=warnings,
                missing=["La cifra solicitada con su fuente primaria u oficial."],
            )

        # agrupar por cluster; tomar el cluster del mejor artículo utilizable
        lines: list[str] = []
        cites: list[QueryCitation] = []
        contradictions: list[Contradiction] = []
        related: list[str] = []
        status = AnswerStatus.respondida if coverage >= 0.75 else AnswerStatus.parcial
        missing: list[str] = []
        used_clusters: list[str] = []
        for h in usable[:3]:
            a = self.corpus.articles[h.doc.doc_id]
            if a.cluster_id and a.cluster_id not in used_clusters:
                used_clusters.append(a.cluster_id)
        for cid in used_clusters[:2]:
            base = self.bases.get(cid)
            if base is None:
                continue
            related.append(cid)
            seen_keys: set[str] = set()
            for a in base.usable_articles:
                if a.origin_key in seen_keys:
                    continue
                seen_keys.add(a.origin_key)
                if len(seen_keys) > 3:
                    break
                when = (
                    f"publicado {fmt_date_pa(a.published_at)}"
                    if a.published_at
                    else f"fecha de publicación desconocida; detectado {fmt_date_pa(a.detected_at)}"
                )
                lines.append(f"- {a.outlet} ({when}): «{a.title}» [{a.id}]")
                cites.append(QueryCitation(evidence_id=a.id, field="title", passage=a.title, title=a.title, url=a.url))
            note = (
                f"  ({len(base.usable_articles)} nota(s), {base.independent} procedencia(s) independiente(s); "
                f"evidencia {base.system_status.value})"
            )
            lines.append(note)
            if base.is_recirculation:
                lines.append(f"  Atención: posible noticia antigua recirculada ({base.recirculation_reason or 'fecha original anterior'}).")
            contradictions.extend(base.contradictions)
            missing.extend(base.pending[:3])
        for h in ind_hits[:2]:
            p = self.corpus.indicators[h.doc.doc_id]
            if p.is_missing:
                missing.append(f"{p.indicator_name} {p.country_iso3} {p.year}: valor ausente en la fuente.")
                continue
            lines.append(f"- Banco Mundial: {_ind_text(p)}")
            cites.extend(_ind_cites(p))
        if contradictions:
            status = AnswerStatus.contradiccion
            lines.append("Versiones incompatibles (no se elige una; revisión pendiente):")
            for c in contradictions:
                lines.append(f"  · {c.description}")
                for v in c.versions:
                    lines.append(f"    - {v.outlet}: «{v.statement}» [{v.evidence_id}]")
        ans = (
            "Lo que reporta el corpus (basado únicamente en titular/metadatos; no se leyó el artículo completo):\n"
            + "\n".join(lines)
        )
        return self._base_resp(
            req, QueryIntent.busqueda, t0, answer_status=status, answer=ans, citations=cites, hits=hit_models,
            contradictions=contradictions, missing=list(dict.fromkeys(missing)), related_topic_ids=related,
            warnings=warnings, coverage=coverage, matched_terms=best.matched,
        )


def _ind_text(p: IndicatorPoint) -> str:
    if p.is_missing:
        return f"{p.indicator_name}, {p.country_iso3} {p.year}: valor ausente en la fuente."
    return f"{p.indicator_name}, {p.country_iso3} {p.year}: {p.value:g} {p.unit or ''} (dato anual de referencia, no de hoy)."


def _ind_cites(p: IndicatorPoint) -> list[QueryCitation]:
    return [
        QueryCitation(evidence_id=p.id, field="value", passage=f"{p.value:g}", title=_ind_text(p), url=p.source_url),
        QueryCitation(evidence_id=p.id, field="year", passage=str(p.year), title=_ind_text(p), url=p.source_url),
    ]


__all__ = ["QueryEngine", "tokenize", "DataMode"]
