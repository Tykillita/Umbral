"""Constantes del reto (PDF TVN Media) y de la extraccion."""

from __future__ import annotations

SCHEMA_VERSION = "1.1.0"

CATEGORIES = [
    "economia",
    "logistica_canal",
    "turismo",
    "servicios_publicos",
    "eventos_naturales",
    "regulacion",
]
INDETERMINATE = "indeterminado"
CATEGORY_LABELS_ES = {
    "economia": "Economía",
    "logistica_canal": "Logística/Canal",
    "turismo": "Turismo",
    "servicios_publicos": "Servicios públicos",
    "eventos_naturales": "Eventos naturales",
    "regulacion": "Regulación",
    "indeterminado": "Indeterminado",
}

COUNTRIES = {
    "PAN": "Panama",
    "CRI": "Costa Rica",
    "COL": "Colombia",
    "DOM": "Dominican Republic",
    "MEX": "Mexico",
    "GTM": "Guatemala",
}
YEARS = list(range(2010, 2025))

# id -> (nombre original WB, unidad legible)
INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": ("GDP growth (annual %)", "% anual"),
    "FP.CPI.TOTL.ZG": ("Inflation, consumer prices (annual %)", "% anual"),
    "SL.UEM.TOTL.ZS": ("Unemployment, total (% of total labor force) (modeled ILO estimate)", "% de la fuerza laboral"),
    "SP.POP.TOTL": ("Population, total", "personas"),
    "IT.NET.USER.ZS": ("Individuals using the Internet (% of population)", "% de la población"),
    "NE.EXP.GNFS.ZS": ("Exports of goods and services (% of GDP)", "% del PIB"),
}
WB_LICENSE = "CC BY 4.0 (salvo excepciones de terceros indicadas en los metadatos de cada indicador)"
WB_TERMS_URL = "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets"

TVN_RSS_URL = "https://www.tvn-2.com/rss/"
TVN_DOMAIN = "tvn-2.com"
GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
BING_NEWS_ENDPOINT = "https://www.bing.com/news/search"
BING_NEWS_MARKET = "es-PA"
WB_ENDPOINT = "https://api.worldbank.org/v2"
USGS_ENDPOINT = "https://earthquake.usgs.gov/fdsnws/event/1/query"

USER_AGENT = "UmbralHackathon/0.1 (+https://github.com/; educational MVP; contact: repo owner)"

# Consultas GDELT DOC 2.0 (PDF 6A: Panama, logistica, turismo, economia, eventos naturales).
GDELT_QUERIES: dict[str, str] = {
    "tvn": "domain:tvn-2.com",
    "panama": "(Panamá OR Panama) sourcelang:spanish",
    "logistica": '("Canal de Panamá" OR "Panama Canal" OR logística OR puerto OR contenedores) (Panamá OR Panama)',
    "turismo": "(turismo OR turistas OR hoteles OR aeropuerto) (Panamá OR Panama) sourcelang:spanish",
    "economia": "(economía OR inflación OR empleo OR inversión OR exportaciones OR PIB) (Panamá OR Panama) sourcelang:spanish",
    "naturales": "(sismo OR terremoto OR inundación OR lluvias OR huracán OR sequía) (Panamá OR Panama) sourcelang:spanish",
}

# Bing News RSS queda como buscador web secundario cuando GDELT limita o falla.
# Solo se conservan titulares, enlaces al medio original y fechas publicadas.
BING_NEWS_QUERIES: dict[str, str] = {
    "panama": "Panamá",
    "logistica": "Canal de Panamá",
    "turismo": "turismo Panamá",
    "economia": "economía Panamá",
    "naturales": "sismo Panamá",
}

TARGET_UNIQUE = 200
MIN_UNIQUE = 100
MIN_TVN = 20
DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 90

# Condiciones de uso por fuente (se vuelcan a TERMS_OF_USE.md y manifest.sources).
SOURCE_TERMS = {
    "tvn_news_sitemap": {
        "name": "TVN Panamá – sitemap Google News público",
        "url": "https://www.tvn-2.com/tvn_sitemap_google_news.xml",
        "license": "Sin licencia abierta. Solo titular, URL y fecha de publicación declarada por el editor.",
        "terms": "Sitemap enlazado desde robots.txt/índice oficial. No se conservan imágenes ni cuerpos. news:publication_date es publicación; lastmod no se utiliza como publicación.",
    },
    "tvn_rss": {
        "name": "TVN Panamá – feed RSS público",
        "url": TVN_RSS_URL,
        "license": "Sin licencia abierta. Solo se conservan metadatos (titular, URL, fecha).",
        "terms": "El RSS observado contiene noticias, fechas y descripciones; eso no implica licencia abierta sobre artículos, videos o imágenes (PDF §12). No se redistribuyen descripciones/extractos ni cuerpos; reutilización de extractos requiere autorización explícita del patrocinador.",
    },
    "gdelt_doc": {
        "name": "GDELT DOC 2.0 API (ArtList)",
        "url": "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts",
        "license": "GDELT es de uso libre con atribución; la API no transfiere derechos sobre los artículos de los medios enlazados.",
        "terms": "Máx. 250 artículos por consulta; 1 consulta cada 5 s. 'seendate' es detección, no publicación. Se guardan titular, URL, dominio, idioma y país del medio.",
    },
    "bing_news_rss": {
        "name": "Bing News – búsqueda pública RSS",
        "url": "https://www.bing.com/news/",
        "license": "Sin licencia abierta. Solo se conservan titular, URL original del medio y fecha de publicación; aplican las condiciones de Bing y del editor enlazado.",
        "terms": "Feed de búsqueda RSS usado como fuente secundaria cuando GDELT limita consultas. No se conservan extractos, imágenes ni cuerpos; el enlace se resuelve al URL del editor antes de validar y publicar metadatos.",
    },
    "world_bank": {
        "name": "Banco Mundial – Indicators API v2",
        "url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation",
        "license": WB_LICENSE,
        "terms": "Atribución obligatoria («World Bank Open Data»); revisar excepciones de terceros por indicador. Los datos pueden revisarse; el período de referencia no coincide con el año de extracción.",
    },
    "usgs": {
        "name": "USGS – catálogo sísmico (FDSN event)",
        "url": "https://earthquake.usgs.gov/fdsnws/event/1",
        "license": "Dominio público del Gobierno de EE. UU. salvo elementos de terceros.",
        "terms": "Usar solo para hechos sísmicos; nunca como evidencia de inundación o pérdidas económicas. La caja regional no equivale al territorio de Panamá.",
    },
}
