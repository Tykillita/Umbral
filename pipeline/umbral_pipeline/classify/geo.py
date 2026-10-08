"""Relevancia geográfica basada en el CONTENIDO del titular (regla léxica auditable `lexical-content-v2`).

Regla (fijada antes de medir; ver eval/README.md):
  1. panama      : el titular nombra Panamá/panameño, el Canal de Panamá, una provincia/ciudad/lugar panameño de la lista
                   acotada, la moneda «B/.» o un nombre propio panameño de la lista (p. ej. Mulino).
  2. regional    : (si no hay señal 1) el titular nombra un país de la lista del PDF (Costa Rica, Colombia, República
                   Dominicana, México, Guatemala) o Centroamérica/Latinoamérica/Caribe (incluye El Salvador, Honduras,
                   Nicaragua, Belice por ser Centroamérica).
  3. none        : (si no hay 1 ni 2) el titular nombra un lugar o actor extranjero de la lista (EE. UU., Trump, China,
                   Rusia, Europa, Venezuela, Argentina...): sin relación con Panamá ni la región.
  4. panama      : (si no hay 1-3) la fuente es panameña (TVN, dominio .pa o país del medio = Panama según GDELT) y el
                   titular no nombra nada extranjero: se asume tema local. Es la única regla que mira la fuente y solo
                   actúa cuando el contenido no nombra nada extranjero.
  5. indeterminate: sin señal de contenido ni fuente panameña.
La relevancia NO depende del medio salvo en la regla 4. Evidencia: `geoEvidence` lista los términos/la regla.
"""

from __future__ import annotations

import re

from ..util import fold_text

METHOD = "lexical-content-v2"

# 1) panameño (términos plegados: minúsculas sin tildes). `panam(?!eric)` cubre panama/panameño/panamenos/panamena.
PANAMA_RX = re.compile(r"(?<![a-z0-9])panam(?!eric)[a-z]*")
PANAMA_TERMS = [
    "canal de panama", "ciudad de panama", "bocas del toro", "chiriqui", "veraguas", "cocle", "los santos", "darien",
    "guna yala", "embera", "ngabe", "ngobe", "san miguelito", "la chorrera", "arraijan", "boquete", "portobelo", "pedasi",
    "tocumen", "puerto armuelles", "puerto pilon", "zona libre de colon", "provincia de colon", "cerro patacon",
    "cinta costera", "metro de panama", "mulino", "asamblea nacional de panama", "contraloria general", "tribunal electoral de panama",
    "sinaproc", "idaan", "etesa", "caja de seguro social", "meduca", "miviot", "acodeco",
    "autoridad del canal", "autoridad de turismo", "superintendencia de bancos de panama",
]
# Siglas/instituciones que otros países también usan (MOP, MEF, CSS, DGI, Minsa de Perú, Mides de Uruguay, ACP...) NO cuentan
# por sí solas: solo actúa la regla 4 (fuente panameña) cuando no hay nada extranjero.
CJK_PANAMA_RX = re.compile(r"巴拿马|巴拿馬|파나마|パナマ")  # Panamá en chino/coreano/japonés (el resto del texto se normaliza a ASCII)
BALBOA_RX = re.compile(r"\bB\s*/\s*\.")  # «B/.» o «B /.» (tokenizado por GDELT): moneda panameña en el texto original

# 2) región (lista del PDF + Centroamérica)
REGION_TERMS = [
    "costa rica", "costarricense", "colombia", "colombiano", "republica dominicana", "dominicano", "dominicana", "mexico", "mexicano",
    "guatemala", "guatemalteco", "centroamerica", "centroamericano", "america central", "latinoamerica", "america latina",
    "latinoamericano", "caribe", "el salvador", "salvadoreno", "honduras", "hondureno", "nicaragua", "nicaraguense", "belice",
]
# 3) extranjero (no regional)
FOREIGN_TERMS = [
    "estados unidos", "eeuu", "ee uu", "united states", "u s", "trump", "biden", "harris", "rubio", "casa blanca", "washington",
    "nueva york", "new york", "florida", "texas", "california", "china", "beijing", "pekin", "xi jinping", "rusia", "russia", "putin", "ucrania",
    "ukraine", "zelenski", "israel", "gaza", "iran", "netanyahu", "hamas", "hezbola", "libano", "siria", "irak", "yemen", "oriente medio",
    "europa", "europe", "union europea", "espana", "madrid", "barcelona", "francia", "paris", "alemania", "berlin", "reino unido",
    "londres", "italia", "roma", "portugal", "grecia", "polonia", "suiza", "suecia", "noruega", "japon", "tokio", "india", "corea",
    "taiwan", "turquia", "australia", "sidney", "sydney", "canada", "argentina", "buenos aires", "brasil", "brazil", "lula", "chile",
    "santiago de chile", "peru", "lima", "ecuador", "quito", "venezuela", "maduro", "caracas", "cuba", "habana", "bolivia", "paraguay",
    "uruguay", "puerto rico", "haiti", "jamaica", "trinidad", "onu", "otan", "nato", "vaticano", "papa leon", "africa", "asia", "marruecos",
    "egipto", "sudafrica", "nigeria", "pakistan", "afganistan", "tailandia", "vietnam", "filipinas", "indonesia", "arabia saudita", "qatar",
    "emiratos",
    # gentilicios extranjeros (añadidos tras auditar el top 5: «Congreso español» salía como panameño por la regla 4)
    "espanol", "espanola", "espanoles", "estadounidense", "estadounidenses", "norteamericano", "norteamericana", "chino", "china",
    "ruso", "rusa", "frances", "francesa", "aleman", "alemana", "britanico", "britanica", "israeli", "iraní", "irani", "argentino",
    "argentina", "brasileno", "brasilena", "chileno", "chilena", "peruano", "peruana", "ecuatoriano", "ecuatoriana", "venezolano",
    "venezolana", "cubano", "cubana", "boliviano", "boliviana", "paraguayo", "paraguaya", "uruguayo", "uruguaya", "canadiense",
    "japones", "japonesa", "coreano", "coreana", "italiano", "italiana", "europeo", "europea", "ucraniano", "ucraniana", "palestino",
    "palestina", "congreso espanol", "senado", "congreso de los diputados", "mundial de futbol", "champions league", "premier league", "la liga", "nba", "nfl", "mlb",
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold_text(text)).strip()


def _compile(terms: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    return [(t, re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")) for t in sorted(set(terms), key=len, reverse=True)]


_PAN = _compile(PANAMA_TERMS)
_REG = _compile(REGION_TERMS)
_FOR = _compile(FOREIGN_TERMS)


def is_panamanian_source(article: dict) -> bool:
    dom = article.get("domain") or ""
    return bool(article.get("isTvn")) or dom.endswith(".pa") or (article.get("sourceCountry") or "").lower() == "panama"


def _hits(rxs: list[tuple[str, re.Pattern[str]]], norm: str) -> list[str]:
    return [t for t, rx in rxs if rx.search(norm)]


def geo_content_v2(article: dict) -> tuple[str, list[str]]:
    title = article["title"]
    norm = _norm(title)
    pan = _hits(_PAN, norm)
    m = PANAMA_RX.search(norm)
    if m:
        pan.insert(0, m.group(0))
    if BALBOA_RX.search(title):
        pan.append("B/.")
    if CJK_PANAMA_RX.search(title):
        pan.append("Panamá(CJK)")
    if pan:
        return "panama", ["contenido:" + t for t in pan[:4]]
    reg = _hits(_REG, norm)
    if reg:
        return "regional", ["contenido:" + t for t in reg[:4]]
    foreign = _hits(_FOR, norm)
    if foreign:
        return "none", ["extranjero:" + t for t in foreign[:4]]
    if is_panamanian_source(article):
        return "panama", ["fuente_panameña:sin_señal_extranjera"]
    return "indeterminate", []
