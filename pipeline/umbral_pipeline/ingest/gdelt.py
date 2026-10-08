"""GDELT DOC 2.0 (ArtList). 'seendate' = deteccion, no publicacion. Max 250 por consulta, 1 consulta / 5 s."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx

from ..config import GDELT_ENDPOINT, GDELT_QUERIES
from ..util import iso_z, now_utc
from .http import Throttle, get_with_retry, make_client


def gdelt_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def parse_artlist(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for rank, a in enumerate(payload.get("articles", []) or []):
        out.append(
            {
                "title": a.get("title"),
                "url": a.get("url"),
                "publishedRaw": None,  # GDELT no entrega publicacion
                "detectedRaw": a.get("seendate"),
                "language": a.get("language"),
                "domain": a.get("domain"),
                "sourceCountry": a.get("sourcecountry"),
                "sourceRank": rank,
            }
        )
    return out


def fetch_gdelt(
    start: datetime,
    end: datetime,
    *,
    queries: dict[str, str] | None = None,
    window_days: int = 10,
    client: httpx.Client | None = None,
    log=print,
    max_failures: int = 2,
    retries: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Devuelve (registros, log de consultas, errores). Parte [start,end) en ventanas de `window_days`."""
    queries = queries or GDELT_QUERIES
    own = client is None
    client = client or make_client(30.0)
    throttle = Throttle(15.0)
    records: list[dict[str, Any]] = []
    qlog: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    failures = 0
    extracted = iso_z(now_utc())
    try:
        for topic, qtext in queries.items():
            cur = start
            step = timedelta(days=(end - start).days + 1) if topic == "tvn" else timedelta(days=window_days)
            while cur < end:
                nxt = min(cur + step, end)
                params = {
                    "query": qtext,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": 250,
                    "sort": "datedesc",
                    "startdatetime": gdelt_ts(cur),
                    "enddatetime": gdelt_ts(nxt),
                }
                entry = {
                    "source": "gdelt_doc", "endpoint": GDELT_ENDPOINT, "query": qtext, "topic": topic,
                    "from": iso_z(cur), "to": iso_z(nxt), "returned": 0,
                }
                try:
                    resp = get_with_retry(
                        client, GDELT_ENDPOINT, params, throttle=throttle, retries=retries, backoff=15.0, log=log
                    )
                    try:
                        payload = json.loads(resp.text)
                    except json.JSONDecodeError:
                        # GDELT responde texto plano ante consultas invalidas; se registra, no se inventa nada
                        raise ValueError(f"respuesta no JSON: {resp.text[:120]!r}") from None
                    recs = parse_artlist(payload)
                    for r in recs:
                        r["topicHint"] = topic
                        r["origin"] = {"source": "gdelt_doc", "query": qtext, "endpoint": GDELT_ENDPOINT}
                        r["extractedAt"] = extracted
                    records.extend(recs)
                    entry["returned"] = len(recs)
                    entry["truncated250"] = len(recs) >= 250
                    log(f"  [gdelt] {topic} {cur:%Y-%m-%d}..{nxt:%Y-%m-%d}: {len(recs)}")
                    failures = 0
                except Exception as exc:  # noqa: BLE001 - se registra y se continua
                    failures += 1
                    entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
                    errors.append(entry)
                    log(f"  [gdelt] FALLO {topic} {cur:%Y-%m-%d}: {entry['error']}")
                    if failures >= max_failures:
                        qlog.append(entry)
                        log("  [gdelt] demasiados fallos seguidos; se aborta GDELT (queda como riesgo)")
                        return records, qlog, errors
                qlog.append(entry)
                cur = nxt
    finally:
        if own:
            client.close()
    return records, qlog, errors
