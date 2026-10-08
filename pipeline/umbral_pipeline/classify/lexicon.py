"""Lexico del baseline (palabras clave y reglas tematicas). Textos plegados (minusculas, sin tildes).

Cada entrada es un prefijo de palabra (se busca con \\b al inicio), o una frase. Peso 1 por coincidencia distinta.
Los terminos se eligieron a partir de las seis categorias del reto, no de las etiquetas de evaluacion.
"""

from __future__ import annotations

CATEGORY_TERMS: dict[str, list[str]] = {
    "economia": [
        "econom", "inflacion", "pib", "producto interno", "empleo", "desempleo", "salario", "inversion", "inversionista",
        "exportacion", "importacion", "deuda", "fiscal", "presupuesto", "banco", "bancari", "credito", "prestamo", "tasa de interes",
        "mercado", "bolsa", "precio", "canasta basica", "costo de la vida", "impuesto", "tributari", "recaudacion", "dgi",
        "mef", "ministerio de economia", "crecimiento", "recesion", "comercio", "empresa", "empresari", "industria",
        "gdp", "inflation", "unemployment", "investment", "exports", "imports", "debt", "budget", "bank", "trade", "economy", "economic",
        "pension", "jubilacion", "css", "fmi", "banco mundial", "calificadora", "fitch", "moody", "s&p", "remesas", "minera", "cobre",
    ],
    "logistica_canal": [
        "canal de panama", "panama canal", "canal", "acp", "autoridad del canal", "esclusa", "neopanamax", "calado",
        "buque", "barco", "naviera", "naviero", "transito", "puerto", "portuari", "contenedor", "carga", "logistic",
        "cadena de suministro", "zona libre", "colon", "balboa", "cristobal", "aeropuerto de tocumen", "tocumen", "ferrocarril",
        "transporte de carga", "aduana", "maritim", "flete", "shipping", "port ", "ports", "vessel", "cargo", "logistics",
        "supply chain", "locks", "draft", "tanquero", "gnl", "oleoducto", "hub", "copa airlines", "carretera", "camion", "camionero",
    ],
    "turismo": [
        "turism", "turista", "visitante", "hotel", "hotelero", "hospedaje", "ocupacion hotelera", "vacaciones", "playa",
        "bocas del toro", "san blas", "guna yala", "boquete", "pedasi", "crucero", "aerolinea", "vuelo", "aeropuerto",
        "destino", "feria turistica", "atracadero", "gastronomia", "festival", "carnaval", "semana santa", "tourism", "tourist",
        "hotel", "resort", "cruise", "airline", "flights", "visitors", "pty", "atp", "autoridad de turismo",
    ],
    "servicios_publicos": [
        "agua potable", "idaan", "acueducto", "potabilizadora", "electricidad", "energia", "apagon", "corte de luz", "etesa",
        "distribuidora", "naturgy", "ensa", "tarifa", "subsidio", "hospital", "salud", "caja de seguro social", "css", "minsa",
        "clinica", "medicamento", "vacuna", "escuela", "educacion", "meduca", "docente", "maestro", "colegio", "universidad",
        "transporte publico", "metro", "metrobus", "bus", "recoleccion de basura", "aseo", "cinta costera", "vertedero", "cerro patacon",
        "telefon", "internet", "carretera", "via", "puente", "alcantarillado", "saneamiento", "seguridad ciudadana", "policia",
        "bomberos", "sinaproc", "mides", "bono", "pais", "water supply", "electricity", "blackout", "hospital", "school", "public transport",
    ],
    "eventos_naturales": [
        "sismo", "terremoto", "temblor", "replica", "tsunami", "volcan", "inundacion", "inundad", "desbordamiento", "lluvia",
        "aguacero", "tormenta", "huracan", "tormenta tropical", "ciclon", "sequia", "el nino", "la nina", "fenomeno", "deslizamiento",
        "derrumbe", "alud", "incendio forestal", "ola de calor", "oleaje", "marejada", "alerta de", "sinaproc", "imhpa", "hidrometeorologic",
        "earthquake", "quake", "flood", "hurricane", "storm", "drought", "landslide", "heavy rain", "tropical", "usgs", "magnitud",
        "damnificad", "evacuad", "cambio climatico", "crecida", "nivel del rio", "lago gatun", "fenomeno de el nino",
    ],
    "regulacion": [
        "ley", "proyecto de ley", "decreto", "resolucion", "reglament", "normativa", "regulacion", "regulator", "asamblea nacional",
        "diputado", "legisla", "constitucion", "constituyente", "reforma", "gaceta oficial", "sancion", "veto", "multa", "licencia",
        "concesion", "licitacion", "contralor", "procuradur", "fiscalia", "corte suprema", "tribunal", "fallo", "demanda", "amparo",
        "inconstitucional", "asep", "sbp", "superintendencia", "superbancos", "acodeco", "autoridad de", "sancionado", "acuerdo",
        "tratado", "law", "bill", "regulation", "decree", "ruling", "court", "legislat", "ministerio publico", "contratacion publica",
        "caso pandora", "caso odebrecht", "sentencia", "audiencia", "imputacion", "aprehension", "detencion provisional",
    ],
}

# Geografia (relevancia)
PANAMA_TERMS = [
    "panama", "panameno", "panamena", "panamenos", "ciudad de panama", "canal de panama", "bocas del toro", "chiriqui", "veraguas",
    "cocle", "herrera", "los santos", "darien", "colon", "guna yala", "embera", "ngabe", "san miguelito", "la chorrera", "david ",
    "tocumen", "asamblea nacional", "contraloria", "procuraduria", "mef", "minsa", "meduca", "mides", "idaan", "etesa", "ensa",
    "sinaproc", "acp", "css", "dgi", "tvn", "mulino", "pty",
]
REGIONAL_TERMS = [
    "costa rica", "colombia", "republica dominicana", "mexico", "guatemala", "centroamerica", "latinoamerica", "america latina",
    "caribe", "el salvador", "honduras", "nicaragua", "belice", "region", "regional", "sica", "cepal", "bid ", "latam", "istmo",
    "sudamerica", "venezuela", "ecuador", "peru", "cuba", "puerto rico", "jamaica", "haiti",
]
FOREIGN_TERMS = [
    "estados unidos", "eeuu", "ee. uu", "trump", "biden", "china", "rusia", "ucrania", "israel", "gaza", "iran", "europa", "espana",
    "francia", "alemania", "reino unido", "japon", "india", "argentina", "brasil", "chile", "canada", "australia", "onu", "otan",
    "oriente medio", "corea", "taiwan", "turquia", "italia", "portugal", "africa", "asia",
]
