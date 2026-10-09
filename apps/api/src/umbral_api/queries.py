"""Consultas en español con evidencia: recuperación BM25+RapidFuzz, citas y abstención explícita."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import (
    CATEGORY_LABELS,
    AnswerStatus,
    Contradiction,
    DataMode,
    IndicatorPoint,
    QueryCitation,
    QueryContext,
    QueryHit,
    QueryIntent,
    QueryRequest,
    QueryResponse,
    RetrievalInfo,
    TopicSummary,
)
from .retrieval import Doc, SearchIndex, fold, tokenize
from .scoring import RULES_VERSION
from .security import looks_like_guilt_question, looks_like_profiling, split_instruction
from .seismology import SEISMIC_BOX_NOTE, SEISMIC_DAMAGE_NOTE, SeismicEvent
from .snapshot import Corpus
from .topics import COUNTRY_KEYWORDS, INDICATOR_KEYWORDS, MASKED_TITLE, TopicBase
from .util import PANAMA_TZ, fmt_date_pa, fmt_pa, fmt_value

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
_RE_ECON = re.compile(
    r"contexto economico|indicadores?|banco mundial|\bpib\b|inflacion|desempleo|poblacion|\binternet\b|exportacion|crecimiento economico"
    r"|\bhabitantes\b|cuanta gente|producto interno|desempleados|\bcreci\w*\b.{0,25}\beconomia\b|\beconomia\b.{0,25}\bcreci\w*\b"
)
# Sinónimos cuando la pregunta no nombra el indicador con las palabras del paquete (solo si no hubo coincidencia directa).
_ECON_SYNONYMS = (
    ("NY.GDP.MKTP.KD.ZG", re.compile(r"\bcreci\w*|\bcrece\w*|\beconomia\b|\bexpansion\b")),
    ("FP.CPI.TOTL.ZG", re.compile(r"\bprecios?\b|\bcarest\w+|\bsubida de precios\b")),
    ("SL.UEM.TOTL.ZS", re.compile(r"\bparo\b|\bsin empleo\b|\bempleo\b|\bdesempleados\b")),
    ("SP.POP.TOTL", re.compile(r"\bhabitantes\b|\bgente\b|\bpersonas viven\b")),
    ("IT.NET.USER.ZS", re.compile(r"\busuarios de internet\b|\bconectad\w+")),
    ("NE.EXP.GNFS.ZS", re.compile(r"\bvende al exterior\b|\bventas al exterior\b")),
)
# Un indicador nombrado solo como unidad de otro («% del PIB», «% de la población») no es lo que se pregunta.
_UNIT_ONLY = (
    ("NE.EXP.GNFS.ZS", "NY.GDP.MKTP.KD.ZG", re.compile(r"(porcentaje|%|proporcion|parte)\s+(del|de\s+la)\s+pib")),
    ("IT.NET.USER.ZS", "SP.POP.TOTL", re.compile(r"(porcentaje|%|proporcion|parte)\s+de\s+la\s+poblacion")),
)


def _drop_unit_only(f: str, inds: list[str]) -> list[str]:
    for asked, unit, rx in _UNIT_ONLY:
        if asked in inds and unit in inds and rx.search(f):
            inds = [i for i in inds if i != unit]
    return inds


def _requested_number_kind(question: str) -> str | None:
    f = fold(question)
    if re.search(r"\b(murieron|muert\w*|fallecid\w*|decesos?|muertes?)\b", f):
        return "muertes"
    if re.search(r"\b(herid\w*|lesionad\w*)\b", f):
        return "heridos"
    if re.search(r"\b(magnitud|magnitude|escala richter)\b", f):
        return "magnitud"
    if re.search(r"\b(porcentaje|por ciento|%|proporcion)\b", f):
        return "porcentaje"
    if re.search(r"\b(costo|cuesta|inversion|presupuesto|millones de dolares|balboas|dolares|usd)\b|\$", f):
        return "dinero"
    if re.search(r"\b(danos?|perdidas?|destruid\w*|viviendas afectadas|damage|losses)\b", f):
        return "danos"
    if re.search(r"\b(personas|habitantes|poblacion|victimas|damnificad\w*)\b", f):
        return "personas"
    return None


def _number_has_kind(title: str, kind: str) -> bool:
    f = fold(title)
    patterns = {
        "muertes": r"\b(muert\w*|fallecid\w*|falleci\w*|decesos?)\b",
        "heridos": r"\b(herid\w*|lesionad\w*)\b",
        "magnitud": r"\b(magnitud|magnitude|richter|mb|ml|mw)\b",
        "porcentaje": r"%|\bpor ciento\b|\bporcentaje\b",
        "dinero": r"\$|\b(dolares?|balboas?|usd|millones? de|millones? en)\b",
        "danos": r"\b(danos?|perdidas?|destruid\w*|viviendas afectadas|damage|losses)\b",
        "personas": r"\b(personas?|habitantes|poblacion|victimas?|damnificad\w*)\b",
    }
    if not re.search(r"\d", f):
        return False
    cue = re.compile(patterns[kind])
    return any(cue.search(f[max(0, match.start() - 32):match.end() + 72]) for match in re.finditer(r"\d[\d.,]*", f))


# Palabras de forma, tiempo y unidad que pueden seguir a una preposición sin ser una entidad («en total», «de enero», «en dólares»).
_FORM_WORDS = {
    "total", "promedio", "general", "particular", "resumen", "breve", "detalle", "cifras", "cifra", "numeros", "terminos",
    "dolares", "dolar", "porcentaje", "ciento", "porciento", "puntos", "anual", "anuales", "mensual", "ano", "anos",
    "mes", "meses", "decada", "decadas", "siglo", "pasado", "proximo", "ultimo", "ultimos", "ultima", "reciente",
    "recientes", "disponible", "disponibles", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "setiembre", "octubre", "noviembre", "diciembre", "hoy", "ahora", "actualidad", "serie", "historico",
    "historica", "comparacion", "tabla", "grafico", "lista", "orden", "adelante", "atras", "promedios",
}
_RE_PREP_WORD = re.compile(r"(?<![a-záéíóúñü])(?:de|del|en|para|sobre|entre|hacia|desde)\s+([a-záéíóúñü]+)", re.IGNORECASE)
_RE_CAPITALIZED = re.compile(r"[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñüÁÉÍÓÚÑ]+")
# Preguntas que piden confirmar una afirmación con un agregado: el dato se reporta, pero no se presenta como prueba.
_RE_CLAIM = re.compile(r"\bgarantiz\w+|\bprueb[ao]\w*|\bdemuestr\w+|\bconfirm\w+|permite\w*\s+afirmar|\basegura\w*|\bimplica\w*|\btodos\s+los\b|\btodas\s+las\b")
# ---- seguimiento de preguntas (solo con `followUp` y solo si la frase parece una continuación)
_RE_FOLLOW_START = re.compile(r"^(y|e|ademas|tambien|pero|entonces|ahora)\b")
_RE_DEICTIC = re.compile(
    r"\b(eso|esto|ese|esa|esos|esas|este|esta|anterior|mismo|misma|primero|primera|segundo|segunda|tercero|tercera|cuarto|cuarta"
    r"|quinto|quinta|fuentes?|origen|respalda)\b|de donde sale|quien lo dice|tema \d|numero \d"
)
_RE_SOURCE = re.compile(r"\bfuentes?\b|de donde sale|quien lo dice|\borigen\b|\brespalda\w*")
_ORDINALS = (
    (re.compile(r"\bprimer[oa]?\b"), 1), (re.compile(r"\bsegund[oa]\b"), 2), (re.compile(r"\btercer[oa]?\b"), 3),
    (re.compile(r"\bcuart[oa]\b"), 4), (re.compile(r"\bquint[oa]\b"), 5),
)
_RE_TOPIC_NUMBER = re.compile(r"\b(?:tema|numero|n|no)\s*(\d)\b|\bel\s+(\d)\b")
_RE_SINGLE_REF = re.compile(r"\b(ese|esa|eso|este|esta|esto|mismo|misma)\b")
_COUNTRY_ORDER = ("PAN", "CRI", "COL", "DOM", "MEX", "GTM")
_INDICATOR_PHRASE = {
    "NY.GDP.MKTP.KD.ZG": "el crecimiento del PIB", "FP.CPI.TOTL.ZG": "la inflación", "SL.UEM.TOTL.ZS": "el desempleo",
    "SP.POP.TOTL": "la población", "IT.NET.USER.ZS": "el uso de internet", "NE.EXP.GNFS.ZS": "las exportaciones",
}


@dataclass
class _Resolved:
    """Resultado de interpretar un seguimiento: una pregunta autónoma, una lista de fuentes, o una aclaración."""

    question: str | None = None
    topic_id: str | None = None
    intent: QueryIntent | None = None
    sources: list[str] | None = None
    clarify: str | None = None
    notes: list[str] = field(default_factory=list)


_RE_YEAR_RANGE = re.compile(r"\b(?:entre|de|desde)\s+((?:19|20)\d{2})\s+(?:y|a|hasta)\s+((?:19|20)\d{2})\b|\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b")
_RE_NUMERIC = re.compile(r"\bcuant[oa]s?\b|\bcifra\b|\bmonto\b|\bporcentaje\b|\bnumero de\b|\btotal de\b|\bcuanto cuesta\b")
_RE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_RE_SUMMARY = re.compile(r"\b(resumen|resum\w*|repaso|balance)\b")
_RE_RELATIVE_PERIOD = re.compile(r"\b(esta semana|ultim[oa]s?\s+7\s+d[ií]as?|ultim[oa]s?\s+30\s+d[ií]as?|este mes|ultim[oa]s?\s+mes)\b")
_RE_ARBITRARY_DAYS = re.compile(r"\bultim[oa]s?\s+(\d{1,3})\s+d[ií]as?\b")
_RE_DATE_ISO_RANGE = re.compile(r"\b(?:desde|del)\s+(\d{4}-\d{2}-\d{2})\s+(?:hasta|al|a)\s+(\d{4}-\d{2}-\d{2})\b")
_RE_DATE_DMY_RANGE = re.compile(r"\b(?:desde|del)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(?:hasta|al|a)\s+(\d{1,2}/\d{1,2}/\d{4})\b")
_RE_MARKER = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
_RE_SEISMIC = re.compile(r"\bsism\w*|\bterremot\w*|\btemblor\w*|\busgs\b|\bearthquakes?\b")
_RE_DAMAGE = re.compile(r"\bdan\w*|\bmur\w*|\bmuert\w*|\bfallecid\w*|\bherid\w*|\bperdid\w*|\bvictim\w*|\bafectad\w*|\bdestrui\w*|\bdamages?\b|\bdeaths?\b|\binjured\b")


def _number_markers(answer: str, citations: list[QueryCitation]) -> str:
    """Sustituye «[id de evidencia]» por «[n]», donde n es el orden de la fuente en `citations` (el mismo que muestra la interfaz)."""
    order: dict[str, int] = {}
    for c in citations:
        order.setdefault(c.evidence_id, len(order) + 1)
    if not order:
        return answer
    return _RE_MARKER.sub(lambda m: f"[{order[m.group(1)]}]" if m.group(1) in order else m.group(0), answer)


def _detect_intent(q: str) -> QueryIntent:
    f = fold(q)
    if _RE_SUMMARY.search(f):
        return QueryIntent.resumen_periodo
    if _RE_VERIF.search(f):
        return QueryIntent.verificaciones
    if _RE_AGENDA.search(f):
        return QueryIntent.agenda
    if _RE_SEISMIC.search(f) and ("usgs" in f or not _RE_DAMAGE.search(f)):
        return QueryIntent.eventos_sismicos
    if _RE_ECON.search(f):
        return QueryIntent.contexto_economico
    return QueryIntent.busqueda


_SUMMARY_CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "economia": ("economia", "economico", "pib", "inflacion", "desempleo"),
    "logistica_canal": ("canal", "logistica", "transito", "buques"),
    "turismo": ("turismo", "turistas", "visitantes"),
    "servicios_publicos": ("servicios publicos", "electricidad", "agua", "tarifas"),
    "eventos_naturales": ("eventos naturales", "sismos", "terremotos", "lluvias", "inundaciones"),
    "regulacion": ("regulacion", "ley", "reforma", "decreto", "norma"),
}


def _summary_period(question: str, cutoff: datetime) -> tuple[datetime, datetime, str] | None:
    f = fold(question)
    if re.search(r"\bhoy\b", f):
        return cutoff - timedelta(days=1), cutoff + timedelta(microseconds=1), "últimas 24 horas hasta el corte del snapshot"
    if re.search(r"\bayer\b", f):
        end = cutoff - timedelta(days=1)
        return end - timedelta(days=1), end + timedelta(microseconds=1), "las 24 horas anteriores al día del corte"
    match = _RE_DATE_ISO_RANGE.search(f)
    try:
        if match:
            first, last = (datetime.fromisoformat(value).replace(tzinfo=cutoff.tzinfo) for value in match.groups())
            if first <= last:
                return first, last + timedelta(days=1), f"del {first:%Y-%m-%d} al {last:%Y-%m-%d}"
        match = _RE_DATE_DMY_RANGE.search(f)
        if match:
            first, last = (datetime.strptime(value, "%d/%m/%Y").replace(tzinfo=cutoff.tzinfo) for value in match.groups())
            if first <= last:
                return first, last + timedelta(days=1), f"del {first:%d/%m/%Y} al {last:%d/%m/%Y}"
    except ValueError:
        return None

    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", f)
    try:
        if match:
            first = datetime.fromisoformat(match.group(1)).replace(tzinfo=cutoff.tzinfo)
            return first, first + timedelta(days=1), f"el {first:%Y-%m-%d}"
        match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", f)
        if match:
            first = datetime.strptime(match.group(1), "%d/%m/%Y").replace(tzinfo=cutoff.tzinfo)
            return first, first + timedelta(days=1), f"el {first:%d/%m/%Y}"
    except ValueError:
        return None

    months = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12,
    }
    for name, month in months.items():
        match = re.search(rf"\b{name}\s+(?:de\s+)?((?:19|20)\d{{2}})\b", f)
        if match:
            year = int(match.group(1))
            start = datetime(year, month, 1, tzinfo=cutoff.tzinfo)
            end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=cutoff.tzinfo)
            return start, end, f"{name} de {year}"

    years = [int(year) for year in _RE_YEAR.findall(f)]
    ranges = list(_RE_YEAR_RANGE.finditer(f))
    if ranges:
        match = ranges[0]
        start_year, end_year = (int(value) for value in match.groups() if value)
        if start_year <= end_year and end_year - start_year <= 20:
            return (
                datetime(start_year, 1, 1, tzinfo=cutoff.tzinfo),
                datetime(end_year + 1, 1, 1, tzinfo=cutoff.tzinfo),
                f"{start_year}–{end_year}",
            )
    if years:
        year = years[0]
        return datetime(year, 1, 1, tzinfo=cutoff.tzinfo), datetime(year + 1, 1, 1, tzinfo=cutoff.tzinfo), str(year)

    relative = _RE_RELATIVE_PERIOD.search(f)
    arbitrary = _RE_ARBITRARY_DAYS.search(f)
    days = min(int(arbitrary.group(1)), 365) if arbitrary else 7 if relative and ("semana" in relative.group(0) or "7" in relative.group(0)) else 30 if relative else None
    if days:
        return cutoff - timedelta(days=days), cutoff + timedelta(microseconds=1), f"últimos {days} días hasta el corte del snapshot"
    return None


class QueryEngine:
    def __init__(self, corpus: Corpus, bases: dict[str, TopicBase]):
        self.corpus = corpus
        self.bases = bases
        docs: list[Doc] = []
        for a in corpus.articles.values():
            docs.append(Doc(a.id, "articulo", f"{a.title} {a.outlet}", a.cluster_id, semantic_eligible=not a.suspicious_instructions))
        for p in corpus.indicators.values():
            docs.append(
                Doc(
                    p.id,
                    "indicador",
                    f"{INDICATOR_ES.get(p.indicator_id, p.indicator_name)} {p.country_name or ''} {p.country_iso3} {p.year} indicador oficial",
                )
            )
        self.index = SearchIndex(docs, neighbors=corpus.neighbors)
        self.article_ids = set(corpus.articles)

    # ------------------------------------------------------------------ API
    def answer(self, req: QueryRequest, agenda: list[TopicSummary] | Callable[[], list[TopicSummary]]) -> QueryResponse:
        t0 = time.perf_counter()
        original = req.question.strip()
        q = original
        warnings: list[str] = []
        q, injection_detected = split_instruction(q)
        if injection_detected:
            warnings.append("inyeccion_detectada: se rechazó el fragmento con instrucciones y no se envió a búsqueda.")
            if len(tokenize(q)) < 2:
                rejected = self._abstain(
                    req, QueryIntent.busqueda, t0,
                    "se rechazó una instrucción dirigida al sistema; no quedó una pregunta legítima con evidencia que consultar.",
                    warnings=warnings,
                )
                return self._finish(rejected, original, None, [], None)
            req = req.model_copy(update={"question": q, "follow_up": None})
        if looks_like_profiling(q):
            rejected = self._abstain(
                req, QueryIntent.busqueda, t0,
                "no se perfila ni se clasifica a personas como sospechosas, culpables o peligrosas.",
                warnings=warnings + ["perfilamiento_rechazado"],
            )
            return self._finish(rejected, original, None, warnings, None)
        guilt_question = looks_like_guilt_question(q)
        ctx = req.follow_up
        resolved: _Resolved | None = None
        if ctx is not None:
            if ctx.snapshot_id != self.corpus.snapshot_id:
                warnings.append("El contexto de la conversación pertenece a otro snapshot; se trató como una pregunta nueva.")
            else:
                resolved = self._resolve_followup(q, ctx)
        intent = _detect_intent(q)
        if resolved is not None:
            warnings.extend(resolved.notes)
            if resolved.clarify:
                resp = self._abstain(
                    req, ctx.intent if ctx else intent, t0,
                    resolved.clarify, missing=["Una referencia explícita: el tema, el país o el indicador."],
                )
                return self._finish(resp, original, None, warnings, ctx)
            if resolved.sources is not None:
                resp = self._sources(req, ctx, resolved, t0)  # type: ignore[arg-type]
                return self._finish(resp, original, None, warnings, ctx)
            req = req.model_copy(update={"question": resolved.question or original, "topic_id": resolved.topic_id or req.topic_id})
            q = req.question.strip()
            intent = resolved.intent or _detect_intent(q)
        scope = None
        if req.topic_id:
            scope = self.bases.get(req.topic_id)
            if scope is None:
                return self._abstain(req, intent, t0, "El tema indicado no existe en el snapshot servido.", warnings)

        if intent == QueryIntent.agenda:
            resp = self._agenda(req, agenda() if callable(agenda) else agenda, t0)
        elif intent == QueryIntent.verificaciones:
            resp = self._verificaciones(req, scope, t0)
        elif intent == QueryIntent.contexto_economico:
            resp = self._economico(req, scope, t0)
        elif intent == QueryIntent.eventos_sismicos:
            resp = self._sismos(req, t0)
        elif intent == QueryIntent.resumen_periodo:
            resp = self._resumen_periodo(req, t0)
        else:
            resp = self._busqueda(req, scope, t0)
        if guilt_question:
            notice = "Umbral no determina culpabilidad ni verdad; solo puede describir lo que atribuyen las fuentes citadas. "
            resp.answer = notice + resp.answer
            resp.warnings.append("La respuesta mantiene atribución a las fuentes y no concluye responsabilidad penal.")
        return self._finish(resp, original, q if q != original else None, warnings, ctx)

    # ------------------------------------------------------------------ seguimiento
    def _finish(self, resp: QueryResponse, original: str, resolved_question: str | None, warnings: list[str],
                ctx: QueryContext | None) -> QueryResponse:
        resp.warnings = warnings + resp.warnings
        resp.question = original
        resp.resolved_question = resolved_question
        resp.follow_up_context = self._context_for(resp, resolved_question or original)
        resp.follow_up_suggestions = self._suggest(resp)
        return resp

    def _context_for(self, resp: QueryResponse, executed_question: str) -> QueryContext | None:
        if resp.answer_status == AnswerStatus.abstencion:
            return None
        evidence_ids = list(dict.fromkeys(c.evidence_id for c in resp.citations))[:10]
        countries: list[str] = []
        indicators: list[str] = []
        for evidence_id in evidence_ids:
            point = self.corpus.indicators.get(evidence_id)
            if point is not None:
                countries.append(point.country_iso3)
                indicators.append(point.indicator_id)
        f = fold(executed_question)
        years = [int(y) for y in _RE_YEAR.findall(f)]
        for m in _RE_YEAR_RANGE.finditer(f):
            first, last = (int(g) for g in m.groups() if g)
            if first <= last and last - first <= 14:
                years = sorted({*years, *range(first, last + 1)})
        return QueryContext(
            snapshot_id=resp.snapshot_id, intent=resp.intent, topic_ids=resp.related_topic_ids[:5], evidence_ids=evidence_ids,
            countries=list(dict.fromkeys(countries))[:6], indicators=list(dict.fromkeys(indicators))[:6],
            years=sorted(set(years))[:15],
        )

    def _suggest(self, resp: QueryResponse) -> list[str]:
        """Preguntas de continuación completas y resolubles por las reglas de `_resolve_followup`."""
        ctx = resp.follow_up_context
        if ctx is None:
            return []
        out: list[str] = []
        if resp.intent == QueryIntent.contexto_economico and ctx.indicators:
            other_country = next((c for c in _COUNTRY_ORDER if c not in ctx.countries), None)
            if other_country:
                out.append(f"¿Y en {_COUNTRY_ES[other_country]}?")
            other_indicator = next((i for i in _INDICATOR_PHRASE if i not in ctx.indicators), None)
            if other_indicator:
                out.append(f"¿Y {_INDICATOR_PHRASE[other_indicator]}?")
        elif resp.intent == QueryIntent.agenda and ctx.topic_ids:
            out.append("¿Qué falta verificar del primero?")
            if len(ctx.topic_ids) >= 2:
                out.append("¿Cuáles son las fuentes del segundo?")
        elif resp.intent == QueryIntent.busqueda and len(ctx.topic_ids) == 1:
            out.append("¿Qué falta verificar de ese tema?")
        elif resp.intent == QueryIntent.eventos_sismicos:
            out.append("¿Cuáles son las fuentes?")
        if ctx.evidence_ids:
            out.append("¿Cuáles son las fuentes?")
        return list(dict.fromkeys(out))[:4]

    def _is_followup(self, f: str) -> bool:
        if _RE_FOLLOW_START.search(f):
            return True
        short = len(tokenize(f)) <= 5
        return short and bool(_RE_DEICTIC.search(f) or _RE_VERIF.search(f) or _RE_SOURCE.search(f))

    def _ordinal_topic(self, f: str, ctx: QueryContext) -> TopicBase | None:
        known = [t for t in ctx.topic_ids if t in self.bases]
        if not known:
            return None
        position: int | None = None
        for rx, n in _ORDINALS:
            if rx.search(f):
                position = n
                break
        if position is None:
            m = _RE_TOPIC_NUMBER.search(f)
            if m:
                position = int(next(g for g in m.groups() if g))
        if position is None:
            if len(known) == 1 and _RE_SINGLE_REF.search(f):
                return self.bases[known[0]]
            return None
        # La posición se cuenta sobre la lista original, para que «el segundo» sea el segundo que se mostró.
        if 1 <= position <= len(ctx.topic_ids) and ctx.topic_ids[position - 1] in self.bases:
            return self.bases[ctx.topic_ids[position - 1]]
        return None

    def _resolve_followup(self, q: str, ctx: QueryContext) -> _Resolved | None:
        f = fold(q).lstrip("¿¡ ")
        if not self._is_followup(f):
            return None  # frase autónoma: el contexto se ignora
        wants_sources = bool(_RE_SOURCE.search(f))
        wants_verif = bool(_RE_VERIF.search(f))
        topic = self._ordinal_topic(f, ctx)
        if topic is not None:
            if wants_sources:
                return _Resolved(sources=[a.id for a in topic.usable_articles[:5]], topic_id=topic.id)
            if wants_verif:
                return _Resolved(question=f"¿Qué falta verificar sobre {topic.display_title}?", topic_id=topic.id,
                                 intent=QueryIntent.verificaciones)
            return _Resolved(question=topic.display_title, topic_id=topic.id, intent=QueryIntent.busqueda)
        if wants_sources:
            ids = [e for e in ctx.evidence_ids if e in self.corpus.articles or e in self.corpus.indicators or e in self.corpus.events]
            if ids:
                return _Resolved(sources=ids)
            return _Resolved(clarify="no hay fuentes registradas en el contexto de la conversación.")
        if ctx.intent == QueryIntent.eventos_sismicos:
            years = _RE_YEAR.findall(f)
            if years:
                return _Resolved(question="Sismos USGS en " + " y ".join(years), intent=QueryIntent.eventos_sismicos)
        if ctx.intent == QueryIntent.contexto_economico or ctx.indicators:
            filled = self._fill_econ(f, ctx)
            if filled is not None:
                return filled
        if wants_verif:
            known = [t for t in ctx.topic_ids if t in self.bases]
            if len(known) == 1:
                return _Resolved(question=q, topic_id=known[0], intent=QueryIntent.verificaciones)
            if len(known) > 1:
                return _Resolved(clarify="la respuesta anterior mostró varios temas; indica cuál con su orden (por ejemplo, «el segundo»).")
        return _Resolved(clarify=(
            f"no pude resolver a qué se refiere «{q.strip()}» con el contexto de la conversación. "
            "Reformula la pregunta nombrando el tema, el país o el indicador."
        ))

    def _fill_econ(self, f: str, ctx: QueryContext) -> _Resolved | None:
        """Completa país, indicador y años que faltan en un seguimiento económico con los de la respuesta anterior."""
        countries = [c for c, kws in COUNTRY_KEYWORDS.items() if any(kw in f for kw in kws)]
        indicators = [k for k, kws in INDICATOR_KEYWORDS.items() if any(kw.strip() in f for kw in kws)]
        if not indicators:
            indicators = [k for k, rx in _ECON_SYNONYMS if rx.search(f)][:1]
        years = [int(y) for y in _RE_YEAR.findall(f)]
        if not (countries or indicators or years):
            return None  # no aporta ningún dato nuevo: no hay nada que completar
        use_countries = countries or [c for c in ctx.countries if c in _COUNTRY_ES] or ["PAN"]
        use_indicators = indicators or [i for i in ctx.indicators if i in INDICATOR_LABEL_ES]
        if not use_indicators:
            return None
        use_years = years or ctx.years
        question = " y ".join(INDICATOR_LABEL_ES[i] for i in use_indicators)
        question += " de " + " y ".join(_COUNTRY_ES[c] for c in use_countries)
        if use_years:
            question += " en " + " y ".join(str(y) for y in use_years[:6])
        notes = []
        if not countries and ctx.countries:
            notes.append(f"Se mantuvo el país de la respuesta anterior ({', '.join(_COUNTRY_ES.get(c, c) for c in use_countries)}).")
        return _Resolved(question=question, intent=QueryIntent.contexto_economico, notes=notes)

    def _sources(self, req: QueryRequest, ctx: QueryContext, resolved: _Resolved, t0: float) -> QueryResponse:
        lines: list[str] = []
        cites: list[QueryCitation] = []
        for evidence_id in resolved.sources or []:
            article = self.corpus.articles.get(evidence_id)
            point = self.corpus.indicators.get(evidence_id)
            if article is not None and not article.suspicious_instructions:
                when = (
                    f"publicado {fmt_date_pa(article.published_at)}"
                    if article.published_at
                    else f"fecha de publicación desconocida; detectado {fmt_date_pa(article.detected_at)}"
                )
                lines.append(f"- {article.outlet} ({when}): «{article.title}» [{article.id}]")
                cites.append(QueryCitation(evidence_id=article.id, field="title", passage=article.title, title=article.title, url=article.url))
            elif point is not None and not point.is_missing:
                lines.append(f"- Banco Mundial: {_ind_text(point)} [{point.id}]")
                cites.extend(_ind_cites(point))
            elif event := self.corpus.events.get(evidence_id):
                lines.append(f"- USGS: M {fmt_value(event.magnitude)} · {event.place} · {fmt_pa(event.time)} [{event.id}]")
                cites.extend(_event_cites(event))
        if not cites:
            return self._abstain(req, ctx.intent, t0, "no hay fuentes utilizables registradas para esa respuesta.")
        topics = [resolved.topic_id] if resolved.topic_id else ctx.topic_ids
        return self._base_resp(
            req, ctx.intent, t0, answer_status=AnswerStatus.respondida, citations=cites, related_topic_ids=list(topics),
            answer=("Fuentes de la respuesta anterior:\n" if ctx.intent == QueryIntent.eventos_sismicos
                    else "Fuentes de la respuesta anterior (basado únicamente en titular/metadatos):\n") + "\n".join(lines),
        )

    # ------------------------------------------------------------------ helpers
    def _base_resp(self, req: QueryRequest, intent: QueryIntent, t0: float, **kw) -> QueryResponse:  # noqa: ANN003
        return QueryResponse(
            query_id="q_" + uuid.uuid4().hex[:12],
            question=req.question,
            intent=intent,
            answer_status=kw.pop("answer_status"),
            answer=_number_markers(kw.pop("answer"), kw.get("citations") or []),
            snapshot_id=self.corpus.snapshot_id,
            rules_version=RULES_VERSION,
            data_mode=self.corpus.data_mode,
            retrieval=RetrievalInfo(
                method=kw.pop("method", "usgs-catalog" if intent == QueryIntent.eventos_sismicos else "bm25+rapidfuzz"),
                corpus_size=len(self.index.docs),
                took_ms=round((time.perf_counter() - t0) * 1000, 2),
                matched_terms=kw.pop("matched_terms", []),
                coverage=kw.pop("coverage", 0.0),
                semantic_model=self.corpus.semantic_model if kw.get("semantic_expansion", False) else None,
                semantic_expansion=kw.pop("semantic_expansion", False),
                rrf_k=kw.pop("rrf_k", None),
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
                retrieval_origin=("lexical+semantic_neighbor" if h.matched else "semantic_neighbor") if h.semantic_similarity is not None else "lexical",
                semantic_similarity=h.semantic_similarity, semantic_anchor_id=h.semantic_anchor_id,
                rrf_score=h.rrf_score, literal_coverage=round(h.coverage, 4),
            )
        p = self.corpus.indicators[d.doc_id]
        return QueryHit(
            evidence_id=p.id, kind="indicador", title=f"{p.indicator_name} · {p.country_iso3} · {p.year}", url=p.source_url,
            outlet="Banco Mundial", snippet=_ind_text(p), bm25=round(h.bm25, 4), fuzzy=round(h.fuzzy, 4),
            relevance=h.relevance, retrieval_origin="lexical",
            literal_coverage=round(h.coverage, 4), rrf_score=h.rrf_score,
        )

    def _unknown_entities(self, question: str, scope: TopicBase | None) -> list[str]:
        """Entidades que la pregunta introduce y el paquete no puede vincular (p. ej. «Marte»).

        Solo cuentan las palabras que funcionan como entidad: las que siguen a una preposición («de Marte», «en Narnia») y las
        que van con mayúscula inicial a mitad de frase («el FMI»). Los verbos, adjetivos y adverbios corrientes («creció»,
        «alta», «según») ya no provocan una abstención.
        """
        known: set[str] = set(_GENERIC_ECON)
        for kws in list(INDICATOR_KEYWORDS.values()) + list(COUNTRY_KEYWORDS.values()):
            for kw in kws:
                known.update(tokenize(kw))
        for iso, name in _COUNTRY_ES.items():
            known.update(tokenize(name))
            known.add(fold(iso))
        for txt in list(INDICATOR_ES.values()) + list(INDICATOR_LABEL_ES.values()):
            known.update(tokenize(txt))
        for word in _FORM_WORDS:
            known.update(tokenize(word))
        if scope is not None:
            known.update(tokenize(scope.search_text))
        candidates: list[str] = [m.group(1) for m in _RE_PREP_WORD.finditer(question)]
        for m in _RE_CAPITALIZED.finditer(question):
            before = question[: m.start()].rstrip("\u00bf\u00a1 \t\n")
            if not before or before[-1] in ".?!:\n":
                continue  # inicio de frase: la mayúscula no indica una entidad
            candidates.append(m.group(0))
        out: list[str] = []
        for raw in candidates:
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
            rep = b.representative
            mark = "" if rep.suspicious_instructions else f" [{rep.id}]"
            lines.append(
                f"{i}. **{t.title}**{mark}\n"
                f"Puntaje **{t.score:.2f}** ({t.band.value}) · evidencia {t.evidence_status_label.lower()}"
                f"{' · requiere investigación (prioridad alta con evidencia insuficiente)' if t.needs_investigation else ''}."
            )
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
            supported = next((hit for hit in hits if hit.supported and hit.doc.cluster_id in self.bases), None)
            if supported:
                base = self.bases[supported.doc.cluster_id or ""]
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
            method="bm25+rapidfuzz+semantic-rrf" if any(hit.semantic_similarity is not None for hit in hits_models) else "bm25+rapidfuzz",
            semantic_expansion=any(hit.semantic_similarity is not None for hit in hits_models),
            rrf_k=60 if any(hit.semantic_similarity is not None for hit in hits_models) else None,
        )

    def _sismos(self, req: QueryRequest, t0: float) -> QueryResponse:
        """Consulta exclusiva del catálogo íntegro USGS; el texto de ubicación no acredita territorio ni daños."""
        question = fold(req.question)
        if _RE_DAMAGE.search(question):
            return self._abstain(req, QueryIntent.eventos_sismicos, t0, SEISMIC_DAMAGE_NOTE,
                                 missing=["Un reporte oficial de SINAPROC o la autoridad competente sobre las afectaciones solicitadas."])
        events = list(self.corpus.events.values())
        if not events:
            return self._abstain(req, QueryIntent.eventos_sismicos, t0,
                                 "el snapshot no dispone de un catálogo USGS íntegro utilizable.", missing=["Catálogo USGS verificado del periodo solicitado."])
        years = sorted({int(year) for year in _RE_YEAR.findall(question)})
        available_years = sorted({event.time.astimezone(PANAMA_TZ).year for event in events})
        absent = [year for year in years if year not in available_years]
        if absent:
            return self._abstain(req, QueryIntent.eventos_sismicos, t0,
                    f"el paquete USGS no contiene eventos de {', '.join(map(str, absent))}; sus años disponibles son {', '.join(map(str, available_years))}.",
                    missing=["Catálogo USGS verificado del año solicitado."], warnings=[SEISMIC_BOX_NOTE, SEISMIC_DAMAGE_NOTE])
        selected = [event for event in events if not years or event.time.astimezone(PANAMA_TZ).year in years]
        local_cutoff = self.corpus.cutoff.astimezone(PANAMA_TZ)
        start = None
        end = local_cutoff
        if re.search(r"\bhoy\b|\btoday\b", question):
            start = local_cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
        elif re.search(r"\bayer\b|\byesterday\b", question):
            end = local_cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
            start = end - timedelta(days=1)
        elif "esta semana" in question:
            start = (local_cutoff - timedelta(days=local_cutoff.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif "este mes" in question:
            start = local_cutoff.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start:
            selected = [event for event in selected if start <= event.time < end]
        # Solo se aplica un nombre geográfico explícito que exista en los metadatos del catálogo.
        places = " ".join(fold(event.place) for event in selected)
        geographic = []
        for match in _RE_PREP_WORD.finditer(req.question):
            word = fold(match.group(1))
            if word in _FORM_WORDS or word in {"usgs", "sismo", "sismos", "temblor", "terremoto", "magnitud", "mayor", "caja", "region"}:
                continue
            if word not in places and word not in {"panama", "regional"}:
                return self._abstain(req, QueryIntent.eventos_sismicos, t0,
                                     "la ubicación solicitada no aparece en el catálogo regional del snapshot.")
            if word in places:
                geographic.append(word)
        if "panama" in question:
            geographic = ["panama"]
        if geographic:
            selected = [event for event in selected if all(word in fold(event.place) for word in geographic)]
        if not selected:
            return self._abstain(req, QueryIntent.eventos_sismicos, t0,
                                 "no hay eventos USGS para la fecha y ubicación solicitadas en el snapshot servido.",
                                 warnings=[SEISMIC_BOX_NOTE, SEISMIC_DAMAGE_NOTE], missing=["Catálogo USGS del periodo y ubicación solicitados."])
        ranked = sorted(selected, key=lambda event: (-event.magnitude, event.time, event.id))[:req.limit]
        lines = []
        citations = []
        hits = []
        for index, event in enumerate(ranked, 1):
            depth = f" · profundidad {fmt_value(event.depth)} km" if event.depth is not None else " · profundidad desconocida"
            lines.append(f"{index}. **M {fmt_value(event.magnitude)}** · {event.place} · {fmt_pa(event.time)}{depth} [{event.id}]")
            citations.extend(_event_cites(event))
            hits.append(QueryHit(evidence_id=event.id, kind="evento_sismico", title=f"USGS: M {fmt_value(event.magnitude)} · {event.place}",
                        url=event.url, outlet="USGS", published_at=event.time, snippet=lines[-1], bm25=0, fuzzy=0, relevance=1,
                        retrieval_origin="usgs_catalog", literal_coverage=0))
        period = ", ".join(map(str, years or available_years))
        location_note = " con ese nombre en el campo de ubicación" if geographic else " en la caja regional"
        answer = (f"Sismos registrados en el paquete USGS ({period}): {len(selected)}{location_note}. Ordenados por magnitud.\n"
                  + "\n".join(lines) + f"\n\n{SEISMIC_BOX_NOTE} {SEISMIC_DAMAGE_NOTE}")
        return self._base_resp(req, QueryIntent.eventos_sismicos, t0, answer_status=AnswerStatus.respondida,
                              answer=answer, citations=citations, hits=hits, method="usgs-catalog",
                              warnings=[SEISMIC_BOX_NOTE, SEISMIC_DAMAGE_NOTE],
                              missing=["Daños o afectaciones requieren un reporte oficial de SINAPROC o la autoridad competente."])

    def _resumen_periodo(self, req: QueryRequest, t0: float) -> QueryResponse:
        period = _summary_period(req.question, self.corpus.cutoff)
        if period is None:
            return self._abstain(
                req, QueryIntent.resumen_periodo, t0,
                "indica un periodo de 7 días, 30 días o un rango/año explícito; los periodos se calculan respecto al corte del snapshot.",
                missing=["Un periodo consultado y titulares con fechas dentro del corte del snapshot."],
            )
        start, end, period_label = period
        end = min(end, self.corpus.cutoff + timedelta(microseconds=1))
        question = fold(req.question)
        categories = [
            category for category, terms in _SUMMARY_CATEGORY_TERMS.items()
            if any(term in question for term in terms)
        ]
        groups: list[tuple[TopicBase, list]] = []
        for base in self.bases.values():
            if categories and base.category.value not in categories:
                continue
            matched = []
            for article in base.articles:
                if article.suspicious_instructions:
                    continue
                published = article.published_at or article.detected_at
                if published is not None and start <= published < end:
                    matched.append(article)
            if matched:
                groups.append((base, matched))
        if not groups:
            return self._abstain(
                req, QueryIntent.resumen_periodo, t0,
                f"no hay titulares utilizables con fecha dentro del periodo {period_label}"
                + (f" para {', '.join(CATEGORY_LABELS[c].lower() for c in categories)}" if categories else "")
                + ".",
                missing=["Titulares y fechas verificables dentro del periodo elegido."],
            )

        groups.sort(key=lambda pair: (max(a.published_at or a.detected_at for a in pair[1]), len(pair[1]), pair[0].id), reverse=True)
        chosen = groups[: max(1, min(req.limit, 5))]
        citation_by_id: dict[str, QueryCitation] = {}
        lines = []
        related: list[str] = []
        total_articles = sum(len(articles) for _, articles in groups)
        for index, (base, articles) in enumerate(chosen, 1):
            article = max(articles, key=lambda item: item.published_at or item.detected_at)
            when = article.published_at or article.detected_at
            date_basis = "publicación" if article.published_at else "detección"
            lines.append(f"{index}. **{base.display_title}** · {len(articles)} titular(es) fechado(s) en el periodo; último registro por {date_basis}: {fmt_date_pa(when)} [{article.id}]")
            citation_by_id[article.id] = QueryCitation(
                evidence_id=article.id, field="title", passage=article.title, title=article.title, url=article.url,
            )
            related.append(base.id)
        category_label = ", ".join(CATEGORY_LABELS[c] for c in categories) if categories else "todas las categorías"
        answer = (
            f"**Resumen de {category_label} · {period_label}** (snapshot {self.corpus.snapshot_id}, "
            f"corte {fmt_date_pa(self.corpus.cutoff)}).\n\n"
            f"El corpus registra {total_articles} titular(es) fechado(s) en {len(groups)} grupo(s) temático(s) durante el periodo. "
            "Es un recuento del snapshot disponible, basado únicamente en titulares y metadatos; no equivale a una revisión exhaustiva de todos los hechos.\n\n"
            + "\n".join(lines)
        )
        return self._base_resp(
            req, QueryIntent.resumen_periodo, t0, answer_status=AnswerStatus.respondida, answer=answer,
            citations=list(citation_by_id.values()), related_topic_ids=related,
            missing=["El snapshot no incluye el texto completo de los artículos ni una cobertura necesariamente exhaustiva."],
            matched_terms=tokenize(req.question), coverage=1.0,
        )

    def _economico(self, req: QueryRequest, scope: TopicBase | None, t0: float) -> QueryResponse:
        f = fold(req.question)
        inds = [k for k, kws in INDICATOR_KEYWORDS.items() if any(kw.strip() in f for kw in kws)]
        countries = [c for c, kws in COUNTRY_KEYWORDS.items() if any(kw in f for kw in kws)] or ["PAN"]
        years = [int(y) for y in _RE_YEAR.findall(f)]
        for m in _RE_YEAR_RANGE.finditer(f):
            first, last = (int(g) for g in m.groups() if g)
            if first <= last and last - first <= 14:
                years = sorted({*years, *range(first, last + 1)})
        asked_today = bool(re.search(r"\bhoy\b|\bactual(es|mente)?\b|\beste ano\b|\bahora\b", f))
        unknown = self._unknown_entities(req.question, scope)
        if unknown:
            return self._abstain(
                req, QueryIntent.contexto_economico, t0,
                f"no puedo vincular «{', '.join(unknown)}» con ningún país o indicador oficial del paquete "
                "(Panamá, Costa Rica, Colombia, República Dominicana, México, Guatemala).",
                missing=[f"Un indicador oficial pertinente para: {', '.join(unknown)}."],
            )
        if not inds:
            inds = [k for k, rx in _ECON_SYNONYMS if rx.search(f)][:1]
        inds = _drop_unit_only(f, inds)
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
        notes: list[str] = []
        if not any(kw in f for kws in COUNTRY_KEYWORDS.values() for kw in kws) and not (scope is not None and scope.indicators):
            notes.append("No indicaste un país: se muestra Panamá. Nombra otro país del paquete para compararlo.")
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
                            lines.append(f"- {label}, {y}: {fmt_value(row.value)} {row.unit or ''} (dato anual de referencia, no una medición de hoy). [{row.id}]")
                            cites.extend(_ind_cites(row))
                else:
                    valid = [p for p in rows if not p.is_missing and p.year <= self.corpus.cutoff.year]
                    if not valid:
                        missing.append(f"{label}: sin valores disponibles en el paquete.")
                        continue
                    row = valid[-1]
                    found += 1
                    selected_ids.add(row.id)
                    lines.append(f"- {label}, último año con dato {row.year}: {fmt_value(row.value)} {row.unit or ''} (dato anual de referencia, no una medición de hoy). [{row.id}]")
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
        if _RE_CLAIM.search(f):
            extra += (
                " La consulta pide confirmar una afirmación: el indicador del paquete es un agregado anual y ni la respalda ni la "
                "refuta; solo se reporta el dato citado."
            )
            missing.append("Evidencia que sustente la afirmación planteada (un agregado anual no basta).")
        ans = (
            "Contexto oficial (Banco Mundial, snapshot " + self.corpus.snapshot_id + "):\n" + "\n".join(lines) + extra
        )
        status = AnswerStatus.respondida if not missing else AnswerStatus.parcial
        ranked_hits, _, _ = self.index.search(req.question, limit=req.limit, restrict=selected_ids)
        return self._base_resp(
            req, QueryIntent.contexto_economico, t0, answer_status=status, answer=ans, citations=cites,
            missing=missing, related_topic_ids=[scope.id] if scope else [], warnings=notes,
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
        best = max(hits, key=lambda hit: hit.coverage) if any(hit.semantic_similarity is not None for hit in hits) else hits[0]
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
        usable = [h for h in arts if not self.corpus.articles[h.doc.doc_id].suspicious_instructions and h.supported]
        warnings: list[str] = []
        semantic_expansion = any(hit.semantic_similarity is not None for hit in hits)
        if semantic_expansion:
            warnings.append("Los vecinos semánticos son paráfrasis o versiones multilingües candidatas; su similitud no demuestra respaldo literal ni corroboración independiente.")
        for h in arts:
            if self.corpus.articles[h.doc.doc_id].suspicious_instructions:
                warnings.append(
                    f"La fuente {h.doc.doc_id} contiene instrucciones dirigidas a un agente: se trató como contenido no confiable y no se usó."
                )
        ind_hits = [h for h in hits if h.doc.kind == "indicador" and h.coverage >= 0.5]
        requested_kind = _requested_number_kind(req.question)
        if requested_kind:
            usable = [
                h for h in usable
                if _number_has_kind(self.corpus.articles[h.doc.doc_id].title, requested_kind)
            ]
            if requested_kind in {"muertes", "heridos", "personas", "magnitud", "danos"}:
                ind_hits = []
            elif requested_kind == "porcentaje":
                ind_hits = [h for h in ind_hits if "%" in (self.corpus.indicators[h.doc.doc_id].unit or "")]
            elif requested_kind == "dinero":
                ind_hits = [h for h in ind_hits if re.search(r"\$|dolar|balboa|usd", fold(self.corpus.indicators[h.doc.doc_id].unit or ""))]
        if re.search(r"\b(hoy|esta manana|esta tarde|esta noche)\b", fold(req.question)):
            cutoff = self.corpus.cutoff
            start = cutoff - timedelta(hours=48)
            usable = [
                h for h in usable
                if (article_time := (self.corpus.articles[h.doc.doc_id].published_at or self.corpus.articles[h.doc.doc_id].detected_at))
                is not None and start <= article_time <= cutoff
            ]
            ind_hits = []
            warnings.append("La referencia a «hoy» se interpreta como las 48 horas anteriores al corte del snapshot.")
        if (requested_kind or re.search(r"\b(hoy|esta manana|esta tarde|esta noche)\b", fold(req.question))) and not usable and not ind_hits:
            kind_text = {
                "muertes": "personas fallecidas",
                "heridos": "personas heridas",
                "personas": "personas o población",
                "magnitud": "magnitud sísmica",
                "danos": "daños o pérdidas",
                "porcentaje": "porcentaje",
                "dinero": "dinero o costo",
            }.get(requested_kind or "", "fecha solicitada")
            return self._abstain(
                req, QueryIntent.busqueda, t0,
                f"las coincidencias no contienen una cifra del tipo solicitado ({kind_text})"
                + (" dentro de las 48 horas anteriores al corte del snapshot." if re.search(r"\b(hoy|esta manana|esta tarde|esta noche)\b", fold(req.question)) else "."),
                hits=hit_models, coverage=coverage, matched=best.matched, warnings=warnings,
                missing=[f"Una fuente fechada que respalde una cifra de {kind_text}."],
            )
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
        for h in usable:
            a = self.corpus.articles[h.doc.doc_id]
            if a.cluster_id and a.cluster_id not in used_clusters:
                used_clusters.append(a.cluster_id)
        for cid in used_clusters[:req.limit]:
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
            lines.append(f"- Banco Mundial: {_ind_text(p)} [{p.id}]")
            cites.extend(_ind_cites(p))
        contradictions = list({candidate.id: candidate for candidate in contradictions}.values())
        if contradictions:
            status = AnswerStatus.contradiccion
            lines.append("Versiones incompatibles (no se elige una; revisión pendiente):")
            for c in contradictions:
                lines.append(f"  · {c.description}")
                for v in c.versions:
                    when = f"publicado {fmt_date_pa(v.published_at)}" if v.published_at else f"detectado {fmt_date_pa(v.detected_at)}; publicación desconocida"
                    lines.append(f"    - {v.outlet} ({when}): «{v.statement}» [{v.evidence_id}]")
                    if not any(cite.evidence_id == v.evidence_id for cite in cites):
                        cites.append(QueryCitation(evidence_id=v.evidence_id, field="title", passage=v.statement, title=v.statement, url=v.url))
        uncovered = sorted(set(qtoks) - set(best.matched))
        if status == AnswerStatus.parcial and uncovered:
            lines.append(f"Cubierto: {', '.join(best.matched)}. Sin respaldo en las fuentes recuperadas: {', '.join(uncovered)}.")
            missing.append(f"Evidencia que mencione: {', '.join(uncovered)}.")
        ans = (
            "Lo que reporta el corpus (basado únicamente en titular/metadatos; no se leyó el artículo completo):\n"
            + "\n".join(lines)
        )
        return self._base_resp(
            req, QueryIntent.busqueda, t0, answer_status=status, answer=ans, citations=cites, hits=hit_models,
            contradictions=contradictions, missing=list(dict.fromkeys(missing)), related_topic_ids=related,
            warnings=warnings, coverage=coverage, matched_terms=best.matched,
            method="bm25+rapidfuzz+semantic-rrf" if semantic_expansion else "bm25+rapidfuzz",
            semantic_expansion=semantic_expansion, rrf_k=60 if semantic_expansion else None,
        )


def _ind_text(p: IndicatorPoint) -> str:
    if p.is_missing:
        return f"{p.indicator_name}, {p.country_iso3} {p.year}: valor ausente en la fuente."
    return f"{p.indicator_name}, {p.country_iso3} {p.year}: {fmt_value(p.value)} {p.unit or ''} (dato anual de referencia, no de hoy)."


def _ind_cites(p: IndicatorPoint) -> list[QueryCitation]:
    return [
        QueryCitation(evidence_id=p.id, field="value", passage=fmt_value(p.value), title=_ind_text(p), url=p.source_url),
        QueryCitation(evidence_id=p.id, field="year", passage=str(p.year), title=_ind_text(p), url=p.source_url),
    ]


def _event_cites(event: SeismicEvent) -> list[QueryCitation]:
    title = f"USGS {event.id}: M {fmt_value(event.magnitude)} · {event.place}"
    return [QueryCitation(evidence_id=event.id, field=key, passage=value, title=title, url=event.url)
            for key, value in event.citation_fields().items() if key in {"magnitude", "timePanama", "place", "depth"} and value]


__all__ = ["QueryEngine", "tokenize", "DataMode"]
