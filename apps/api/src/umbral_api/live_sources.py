"""Lectura temporal de feeds públicos: alertas recientes y búsqueda de titulares.

Solo se conservan metadatos y enlaces. Ningún texto externo se ejecuta como instrucción.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
TVN_URL = "https://www.tvn-2.com/rss/"
BING_URL = "https://www.bing.com/news/search"
IMHPA_URL = "https://www.imhpa.gob.pa/es/avisos"
SINAPROC_URL = "https://www.sinaproc.gob.pa/"
USER_AGENT = "Umbral/0.4 (+https://github.com/Tykillita/Umbral; public headline metadata)"
EMERGENCY_TERMS = re.compile(r"sismo|terremot|temblor|alerta|emergencia|inund|desliz|evacu|incendio|tsunami|viento|lluvia|tormenta|rescate", re.I)
CURRENT_TERMS = re.compile(
    r"\b(?:hoy|ayer|ahora|actual|actuales|reciente|recientes|últim[oa]s?|en vivo|"
    r"esta semana|este mes|noticias? del día|acaba de (?:temblar|ocurrir|pasar)|"
    r"tembló|tiembla|está temblando|sismo de hoy|terremoto de hoy|alerta vigente)\b",
    re.I,
)
SEARCH_STOPWORDS = {
    "para", "desde", "sobre", "entre", "donde", "cuando", "como", "porque", "cual", "cuales",
    "noticia", "noticias", "actual", "actuales", "reciente", "recientes", "ultima", "ultimas",
    "ultimo", "ultimos", "hoy", "ayer", "ahora", "panama", "buscar", "busca", "hay", "que",
}


@dataclass(frozen=True)
class LiveItem:
    id: str
    kind: str
    title: str
    source: str
    url: str
    published_at: datetime | None
    occurred_at: datetime | None = None
    magnitude: float | None = None
    place: str | None = None
    status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "source": self.source,
            "url": self.url, "publishedAt": self.published_at, "occurredAt": self.occurred_at,
            "magnitude": self.magnitude, "place": self.place, "status": self.status,
        }


@dataclass(frozen=True)
class LiveResult:
    items: tuple[LiveItem, ...]
    checked_at: datetime
    warnings: tuple[str, ...] = ()


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", " ".join(self._text)).strip()
            if text:
                self.links.append((text, self._href))
            self._href = None
            self._text = []


def _date(value: str | None) -> datetime | None:
    if not value:
        return None


def _date_in_title(value: str) -> datetime | None:
    match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{1,2})\s*(am|pm)\b", value, re.I)
    if not match:
        return None
    try:
        date = datetime.strptime(f"{match[1]} {match[2]} {match[3].upper()}", "%d/%m/%Y %I:%M %p")
        return date.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(UTC)
    except ValueError:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _id(source: str, url: str) -> str:
    return f"live_{hashlib.sha256((source + '|' + url).encode()).hexdigest()[:16]}"


def _safe_url(value: str | None, *, allowed: set[str] | None = None) -> str | None:
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        if allowed and parts.hostname.lower() not in allowed:
            return None
        if parts.hostname.lower() == "www.bing.com" and parts.path.rstrip("/") == "/news/apiclick.aspx":
            target = parse_qs(parts.query).get("url", [None])[0]
            return _safe_url(target)
        return value.strip()
    except ValueError:
        return None


def _rss_items(xml_text: str, source: str, kind: str = "noticia") -> list[LiveItem]:
    root = ET.fromstring(xml_text)
    items: list[LiveItem] = []
    for entry in root.iter("item"):
        title = re.sub(r"\s+", " ", entry.findtext("title") or "").strip()
        url = _safe_url(entry.findtext("link"))
        if not title or not url:
            continue
        publisher = entry.find("source")
        publisher_name = (publisher.text or "").strip() if publisher is not None else ""
        if publisher_name:
            for separator in (" - ", " – ", " — "):
                if title.endswith(separator + publisher_name):
                    title = title[: -len(separator + publisher_name)].strip()
                    break
        pubdate = _date(entry.findtext("pubDate"))
        items.append(LiveItem(_id(source, url), kind, title[:500], publisher_name or source, url, pubdate))
    return items


def is_current_question(question: str) -> bool:
    return bool(CURRENT_TERMS.search(question))


def _search_terms(question: str) -> set[str]:
    plain = "".join(char for char in unicodedata.normalize("NFD", question.casefold()) if unicodedata.category(char) != "Mn")
    return {term for term in re.findall(r"[\w.]+", plain) if len(term) > 3 and term not in SEARCH_STOPWORDS}


def _matches_query(item: LiveItem, terms: set[str]) -> bool:
    if not terms:
        return True
    plain = "".join(char for char in unicodedata.normalize("NFD", item.title.casefold()) if unicodedata.category(char) != "Mn")
    title_terms = set(re.findall(r"[\w.]+", plain))
    return any(term in plain or any(word.startswith(term[:5]) for word in title_terms) for term in terms)


def _diverse(items: list[LiveItem], *, limit: int, per_source: int) -> tuple[LiveItem, ...]:
    groups: dict[str, list[LiveItem]] = {}
    for item in items:
        groups.setdefault(item.source, []).append(item)
    preferred = ("USGS", "TVN", "IMHPA", "SINAPROC")
    sources = sorted(groups, key=lambda source: (preferred.index(source) if source in preferred else len(preferred), source))
    selected: list[LiveItem] = []
    for index in range(per_source):
        for source in sources:
            group = groups[source]
            if index < len(group):
                selected.append(group[index])
                if len(selected) == limit:
                    return tuple(selected)
    return tuple(selected)


class LiveSources:
    """Cliente con cachés breves por fuente; cada solicitud usa fuentes fijas y URLs allowlisted."""

    def __init__(self, *, offline: bool = False, client_factory=httpx.Client) -> None:
        self.offline = offline
        self._client_factory = client_factory
        self._lock = threading.Lock()
        self._alert_cache: tuple[float, LiveResult] | None = None
        self._search_cache: dict[str, tuple[float, LiveResult]] = {}

    def _client(self, timeout: float = 8) -> httpx.Client:
        return self._client_factory(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=False)

    @staticmethod
    def _response_url(response: httpx.Response, allowed: set[str]) -> None:
        host = (urlsplit(str(response.request.url)).hostname or "").lower()
        if host not in allowed:
            raise ValueError("El origen no está permitido.")
        if response.is_redirect:
            raise ValueError("No se siguen redirecciones de fuentes externas.")
        response.raise_for_status()

    def alerts(self, *, force: bool = False) -> LiveResult:
        now = time.monotonic()
        if self.offline:
            return LiveResult((), datetime.now(UTC), ("Búsqueda en vivo desactivada en modo sin conexión.",))
        with self._lock:
            if self._alert_cache and not force and now - self._alert_cache[0] < 60:
                return self._alert_cache[1]
            checked = datetime.now(UTC)
            items: list[LiveItem] = []
            warnings: list[str] = []
            try:
                with self._client() as client:
                    response = client.get(USGS_URL, params={
                        "format": "geojson", "starttime": (checked - timedelta(days=3)).isoformat(),
                        "endtime": checked.isoformat(), "minlatitude": 5, "maxlatitude": 12,
                        "minlongitude": -86, "maxlongitude": -76, "minmagnitude": 3,
                        "orderby": "time", "limit": 100,
                    })
                    self._response_url(response, {"earthquake.usgs.gov"})
                    for feature in response.json().get("features", []):
                        props = feature.get("properties") or {}
                        url = _safe_url(props.get("url"), allowed={"earthquake.usgs.gov"})
                        if not url:
                            continue
                        event_time = datetime.fromtimestamp(props["time"] / 1000, UTC) if props.get("time") else None
                        items.append(LiveItem(
                            _id("USGS", url), "sismo", str(props.get("title") or "Evento sísmico")[:500], "USGS", url,
                            datetime.fromtimestamp(props["updated"] / 1000, UTC) if props.get("updated") else event_time,
                            event_time, props.get("mag"), props.get("place"), props.get("alert") or props.get("status"),
                        ))
            except Exception:
                warnings.append("USGS no respondió; se conservan los avisos de otras fuentes disponibles.")
            for source, url, allowed in (
                ("IMHPA", IMHPA_URL, {"www.imhpa.gob.pa"}),
                ("SINAPROC", SINAPROC_URL, {"www.sinaproc.gob.pa"}),
            ):
                try:
                    with self._client() as client:
                        response = client.get(url)
                        self._response_url(response, allowed)
                        parser = _Links()
                        parser.feed(response.text[:2_000_000])
                        host = next(iter(allowed))
                        official_items: list[LiveItem] = []
                        for title, href in parser.links:
                            if not EMERGENCY_TERMS.search(title):
                                continue
                            if href.startswith("/"):
                                href = f"https://{host}{href}"
                            safe = _safe_url(href, allowed=allowed)
                            if safe:
                                published = _date_in_title(title)
                                if published and checked - published > timedelta(days=7):
                                    continue
                                official_items.append(LiveItem(
                                    _id(source, safe), "aviso", title[:500], source, safe, published, status="publicado",
                                ))
                        items.extend(official_items[:5])
                except Exception:
                    warnings.append(f"No se pudo consultar {source}; los demás resultados siguen disponibles.")
            try:
                with self._client() as client:
                    response = client.get(TVN_URL)
                    self._response_url(response, {"www.tvn-2.com"})
                    items.extend(
                        item for item in _rss_items(response.text[:2_000_000], "TVN")
                        if EMERGENCY_TERMS.search(item.title)
                        and (item.published_at is None or checked - item.published_at <= timedelta(days=7))
                    )
            except Exception:
                warnings.append("TVN no respondió; los avisos oficiales disponibles siguen visibles.")
            unique = {item.id: item for item in items}
            sorted_items = sorted(unique.values(), key=lambda item: item.occurred_at or item.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)
            selected_items = _diverse(sorted_items, limit=30, per_source=10)
            result = LiveResult(selected_items, checked, tuple(warnings))
            self._alert_cache = (now, result)
            return result

    def search(self, question: str, *, mode: str = "auto", force: bool = False) -> LiveResult:
        query = re.sub(r"\s+", " ", question).strip()[:500]
        key = query.casefold()
        now = time.monotonic()
        if self.offline:
            return LiveResult((), datetime.now(UTC), ("Búsqueda en vivo desactivada en modo sin conexión.",))
        with self._lock:
            cached = self._search_cache.get(key)
            if cached and not force and now - cached[0] < 300:
                return cached[1]
        checked = datetime.now(UTC)
        items: list[LiveItem] = []
        warnings: list[str] = []
        terms = _search_terms(query)
        try:
            with self._client(timeout=10) as client:
                response = client.get(TVN_URL)
                self._response_url(response, {"www.tvn-2.com"})
                items.extend(item for item in _rss_items(response.text[:2_000_000], "TVN") if _matches_query(item, terms))
        except Exception:
            warnings.append("No se pudo consultar el feed reciente de TVN.")
        try:
            with self._client(timeout=10) as client:
                response = client.get(BING_URL, params={"q": f"{query} Panamá", "format": "rss", "mkt": "es-PA"})
                self._response_url(response, {"www.bing.com"})
                items.extend(_rss_items(response.text[:2_000_000], "Bing News"))
        except Exception:
            warnings.append("La búsqueda web secundaria no respondió.")
        if re.search(r"sism|terremot|tembl", query, re.I):
            seismic = self.alerts()
            items.extend(item for item in seismic.items if item.kind == "sismo")
            warnings.extend(seismic.warnings)
        elif re.search(r"emergencia|alerta|tsunami|inund|desliz|evacu|incendio|tormenta", query, re.I):
            notices = self.alerts()
            items.extend(item for item in notices.items if item.kind == "aviso" and _matches_query(item, terms))
        unique = {item.id: item for item in items}
        ranked = sorted(unique.values(), key=lambda item: item.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        result = LiveResult(_diverse(ranked, limit=10, per_source=3), checked, tuple(warnings))
        with self._lock:
            self._search_cache[key] = (now, result)
            while len(self._search_cache) > 128:
                self._search_cache.pop(next(iter(self._search_cache)))
        return result
