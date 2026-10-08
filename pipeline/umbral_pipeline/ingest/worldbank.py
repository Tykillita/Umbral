"""Banco Mundial Indicators API v2: una consulta por indicador x pais; cuadricula completa con faltantes."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import COUNTRIES, INDICATORS, WB_ENDPOINT, WB_LICENSE, YEARS
from ..util import iso_z, now_utc
from .http import get_with_retry, make_client


def build_grid(raw_by_key: dict[tuple[str, str], dict[str, Any]], extracted_at: str) -> list[dict[str, Any]]:
    """Construye las 540 combinaciones (6x6x15; el PDF dice 1.350, aritmetica inconsistente) pais x indicador x ano a partir de respuestas crudas.

    raw_by_key[(iso3, indicator)] = {"url", "lastupdated", "name", "values": {year:int -> value|None}}
    Lo que no llega se conserva como faltante (value=None, status='missing'); nunca se rellena.
    """
    rows = []
    for iso3, cname in COUNTRIES.items():
        for ind_id, (ind_name, unit) in INDICATORS.items():
            info = raw_by_key.get(
                (iso3, ind_id), {"url": None, "lastupdated": None, "values": {}, "name": None}
            )
            for year in YEARS:
                val = info["values"].get(year)
                rows.append(
                    {
                        "indicatorRowId": f"ind_{iso3}_{ind_id}_{year}",
                        "countryIso3": iso3,
                        "countryName": cname,
                        "indicatorId": ind_id,
                        "indicatorName": info.get("name") or ind_name,
                        "year": year,
                        "value": val,
                        "unit": unit,
                        "status": "ok" if val is not None else "missing",
                        "sourceUrl": info["url"] or f"{WB_ENDPOINT}/country/{iso3}/indicator/{ind_id}",
                        "sourceLastUpdated": info.get("lastupdated"),
                        "extractedAt": extracted_at,
                        "license": WB_LICENSE,
                        "dataOrigin": "real",
                    }
                )
    return rows


def parse_wb_response(payload: Any) -> dict[str, Any]:
    """Extrae {year: value|None}, lastupdated y nombre de la respuesta JSON del WB."""
    values: dict[int, float | None] = {}
    lastupdated = None
    name = None
    if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], list):
        lastupdated = (payload[0] or {}).get("lastupdated")
        for item in payload[1]:
            try:
                year = int(item["date"])
            except (KeyError, ValueError, TypeError):
                continue
            v = item.get("value")
            values[year] = float(v) if isinstance(v, (int, float)) else None
            name = name or (item.get("indicator") or {}).get("value")
    return {"values": values, "lastupdated": lastupdated, "name": name}


def fetch_worldbank(
    client: httpx.Client | None = None, log=print
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    own = client is None
    client = client or make_client(60.0)
    extracted = iso_z(now_utc())
    raw: dict[tuple[str, str], dict[str, Any]] = {}
    qlog: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        for iso3 in COUNTRIES:
            for ind_id in INDICATORS:
                url = f"{WB_ENDPOINT}/country/{iso3}/indicator/{ind_id}"
                params = {"format": "json", "date": f"{YEARS[0]}:{YEARS[-1]}", "per_page": 100}
                full = str(httpx.URL(url, params=params))
                entry = {
                    "source": "world_bank", "endpoint": url, "query": f"{iso3}/{ind_id}",
                    "from": str(YEARS[0]), "to": str(YEARS[-1]), "returned": 0,
                }
                try:
                    resp = get_with_retry(client, url, params, retries=3, backoff=4.0, log=log)
                    parsed = parse_wb_response(resp.json())
                    parsed["url"] = full
                    raw[(iso3, ind_id)] = parsed
                    entry["returned"] = len(parsed["values"])
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
                    errors.append(entry)
                    log(f"  [wb] FALLO {iso3}/{ind_id}: {entry['error']}")
                qlog.append(entry)
                log(f"  [wb] {len(qlog)}/{len(COUNTRIES) * len(INDICATORS)} {iso3}/{ind_id}: {entry['returned']} años")
    finally:
        if own:
            client.close()
    return build_grid(raw, extracted), qlog, errors
