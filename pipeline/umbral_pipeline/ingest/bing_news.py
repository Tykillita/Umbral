"""Búsqueda secundaria de titulares mediante Bing News RSS; no descarga cuerpos."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from ..config import BING_NEWS_ENDPOINT, BING_NEWS_MARKET, BING_NEWS_QUERIES
from ..util import iso_z, now_utc
from .http import Throttle, get_with_retry, make_client


def original_article_url(link: str | None) -> str | None:
    """Extrae el enlace editorial del redirect RSS de Bing sin visitar el artículo."""
    if not link:
        return None
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    if parts.hostname.lower() in {"bing.com", "www.bing.com"} and parts.path.rstrip("/") == "/news/apiclick.aspx":
        try:
            target = parse_qs(parts.query).get("url", [None])[0]
            target_parts = urlsplit(target or "")
        except ValueError:
            return None
        if target_parts.scheme.lower() not in {"http", "https"} or not target_parts.hostname:
            return None
        return target
    return link.strip()


def parse_rss(xml_text: str, *, query: str, topic: str, endpoint: str = BING_NEWS_ENDPOINT,
              extracted_at: str | None = None) -> list[dict[str, Any]]:
    """Lee título, fecha y enlace al medio original de un RSS de Bing News."""
    root = ET.fromstring(xml_text)
    extracted_at = extracted_at or iso_z(now_utc())
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(root.iter("item")):
        title = item.findtext("title")
        link = original_article_url(item.findtext("link"))
        if not title or not link:
            continue
        title = re.sub(r"\s+", " ", title).strip()
        source = item.find("source")
        publisher = (source.text or "").strip() if source is not None else ""
        if publisher:
            for separator in (" - ", " – ", " — "):
                suffix = separator + publisher
                if title.endswith(suffix):
                    title = title[:-len(suffix)].rstrip()
                    break
        rows.append({
            "title": title,
            "url": link,
            "publishedRaw": item.findtext("pubDate"),
            "language": None,
            "sourceRank": rank,
            "topicHint": topic,
            "origin": {"source": "bing_news_rss", "query": query, "endpoint": endpoint,
                       "publisher": publisher or None},
            "extractedAt": extracted_at,
        })
    return rows


def fetch_bing_news(client: httpx.Client | None = None, log=print, *,
                    queries: dict[str, str] | None = None,
                    market: str = BING_NEWS_MARKET) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Devuelve registros, consultas y errores; una consulta fallida no cancela las demás."""
    own = client is None
    client = client or make_client(20.0)
    throttle = Throttle(5.0)
    queries = queries or BING_NEWS_QUERIES
    extracted = iso_z(now_utc())
    records: list[dict[str, Any]] = []
    qlog: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        for topic, query in queries.items():
            entry: dict[str, Any] = {
                "source": "bing_news_rss", "endpoint": BING_NEWS_ENDPOINT, "query": query,
                "topic": topic, "from": None, "to": extracted, "returned": 0, "extractedAt": extracted,
            }
            try:
                response = get_with_retry(
                    client, BING_NEWS_ENDPOINT, {"q": query, "format": "rss", "mkt": market},
                    throttle=throttle, retries=1, backoff=5.0, log=log,
                )
                rows = parse_rss(response.text, query=query, topic=topic, extracted_at=extracted)
                records.extend(rows)
                entry["returned"] = len(rows)
                log(f"  [bing-news] {topic}: {len(rows)} titulares")
            except Exception as exc:  # noqa: BLE001 - una consulta caída no cancela las otras
                entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
                errors.append(entry.copy())
                log(f"  [bing-news] FALLO {topic}: {entry['error']}")
            qlog.append(entry)
    finally:
        if own:
            client.close()
    return records, qlog, errors
