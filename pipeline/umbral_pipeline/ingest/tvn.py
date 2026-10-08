"""TVN Panama RSS. Solo metadatos (titular, URL, fecha); la descripcion NO se persiste."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..config import TVN_RSS_URL
from ..util import iso_z, now_utc
from .http import get_with_retry, make_client


def parse_rss(xml_text: str) -> list[dict[str, Any]]:
    """Parsea el XML; no valida (la validacion es otra etapa)."""
    root = ET.fromstring(xml_text)
    items = []
    for rank, item in enumerate(root.iter("item")):

        def text(tag: str, item=item) -> str | None:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text and el.text.strip() else None

        items.append(
            {
                "title": text("title"),
                "url": text("link") or text("guid"),
                "publishedRaw": text("pubDate"),
                "modifiedRaw": text("{http://purl.org/dc/terms/}modified"),
                "language": "es",
                "sourceRank": rank,
            }
        )
    return items


def fetch_tvn(
    client: httpx.Client | None = None, log=print, *, feed_url: str = TVN_RSS_URL
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Devuelve (registros, entrada de consulta para el manifest, XML crudo)."""
    own = client is None
    client = client or make_client()
    try:
        resp = get_with_retry(client, feed_url, log=log)
        # Section feed aliases use an HTML meta refresh, which HTTP redirect
        # handling does not follow. Accept only same-site public RSS targets.
        if "<rss" not in resp.text:
            match = re.search(r"https://www\.tvn-2\.com/rss/[A-Za-z0-9_/-]+/?", resp.text)
            if match is None:
                raise ValueError("El endpoint TVN no devolvió RSS ni un redirect RSS del mismo sitio")
            feed_url = match.group(0)
            resp = get_with_retry(client, feed_url, log=log)
    finally:
        if own:
            client.close()
    xml_text = resp.text
    recs = parse_rss(xml_text)
    extracted = iso_z(now_utc())
    for r in recs:
        r["origin"] = {"source": "tvn_rss", "query": None, "endpoint": feed_url}
        r["extractedAt"] = extracted
        r["topicHint"] = None
    q = {
        "source": "tvn_rss", "endpoint": feed_url, "query": None,
        "from": None, "to": None, "returned": len(recs),
    }
    return recs, q, xml_text
