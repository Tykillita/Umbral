"""USGS sismos 2024 en la caja regional lat 5-12, lon -86..-76, magnitud >= 3 (PDF 6C). Opcional."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ..config import USGS_ENDPOINT
from ..util import iso_z, now_utc
from .http import get_with_retry, make_client


def _ms(v: int | None) -> str | None:
    return iso_z(datetime.fromtimestamp(v / 1000, UTC)) if v else None


def fetch_usgs(client: httpx.Client | None = None, log=print) -> tuple[dict[str, Any], dict[str, Any]]:
    own = client is None
    client = client or make_client(90.0)
    params = {
        "format": "geojson", "starttime": "2024-01-01", "endtime": "2024-12-31T23:59:59",
        "minlatitude": 5, "maxlatitude": 12, "minlongitude": -86, "maxlongitude": -76,
        "minmagnitude": 3, "orderby": "time-asc",
    }
    try:
        resp = get_with_retry(client, USGS_ENDPOINT, params, log=log)
    finally:
        if own:
            client.close()
    data = resp.json()
    feats = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        g = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        feats.append(
            {
                "type": "Feature",
                "id": f.get("id"),
                "properties": {
                    "id": f.get("id"), "magnitude": p.get("mag"), "time": _ms(p.get("time")),
                    "updated": _ms(p.get("updated")), "longitude": g[0], "latitude": g[1],
                    "depth": g[2] if len(g) > 2 else None, "place": p.get("place"),
                    "status": p.get("status"), "url": p.get("url"),
                },
                "geometry": f.get("geometry"),
            }
        )
    out = {
        "type": "FeatureCollection",
        "features": feats,
        "metadata": {"source": "USGS FDSN event", "query": params, "extractedAt": iso_z(now_utc()), "count": len(feats)},
    }
    q = {
        "source": "usgs", "endpoint": USGS_ENDPOINT, "query": params,
        "from": "2024-01-01", "to": "2024-12-31", "returned": len(feats),
    }
    return out, q
