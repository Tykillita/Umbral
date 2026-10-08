"""TVN's declared Google News sitemap: only headlines, URLs and publication dates."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..util import iso_z, now_utc
from .http import get_with_retry, make_client

TVN_NEWS_SITEMAP = "https://www.tvn-2.com/tvn_sitemap_google_news.xml"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9",
      "n": "http://www.google.com/schemas/sitemap-news/0.9"}


def parse_news_sitemap(xml_text: str) -> list[dict[str, Any]]:
    rows = []
    root = ET.fromstring(xml_text)
    for rank, element in enumerate(root.findall("s:url", NS)):
        news = element.find("n:news", NS)
        if news is None:
            continue
        rows.append({"title": news.findtext("n:title", namespaces=NS),
                     "url": element.findtext("s:loc", namespaces=NS),
                     "publishedRaw": news.findtext("n:publication_date", namespaces=NS),
                     "publishedAtBasis": "news_sitemap_publication",
                     "language": news.findtext("n:publication/n:language", namespaces=NS),
                     "sourceRank": rank})
    return rows


def fetch_news_sitemap(client: httpx.Client | None = None, log=print):
    own = client is None
    client = client or make_client(20.0)
    try:
        response = get_with_retry(client, TVN_NEWS_SITEMAP, retries=1, backoff=3, log=log)
    finally:
        if own:
            client.close()
    extracted = iso_z(now_utc())
    rows = parse_news_sitemap(response.text)
    for row in rows:
        row["origin"] = {"source": "tvn_news_sitemap", "query": None, "endpoint": TVN_NEWS_SITEMAP}
        row["extractedAt"] = extracted
    return rows, {"source": "tvn_news_sitemap", "endpoint": TVN_NEWS_SITEMAP,
                  "query": None, "from": None, "to": None, "returned": len(rows),
                  "extractedAt": extracted,
                  "discoveredFrom": "https://tvn-2.com/tvn_sitemap_index.xml (robots.txt Sitemap)"}, response.text
