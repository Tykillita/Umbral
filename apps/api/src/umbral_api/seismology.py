"""Lectura y citas del catálogo USGS publicado en el snapshot; no es evidencia de daños."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from .security import looks_like_instruction
from .util import fmt_pa, fmt_value

SEISMIC_BOX_NOTE = "El catálogo cubre una caja regional; no equivale al territorio de Panamá ni demuestra que cada sismo se sintió en el país."
SEISMIC_DAMAGE_NOTE = "USGS registra eventos sísmicos: magnitud y profundidad no prueban daños, víctimas ni pérdidas; eso requiere un reporte oficial de afectaciones."


@dataclass(frozen=True)
class SeismicEvent:
    id: str
    magnitude: float
    time: datetime
    place: str
    url: str
    depth: float | None
    latitude: float
    longitude: float

    def citation_fields(self) -> dict[str, str]:
        return {"magnitude": fmt_value(self.magnitude), "time": self.time.isoformat(),
                "timePanama": fmt_pa(self.time), "place": self.place, "url": self.url, "outlet": "USGS",
                "depth": fmt_value(self.depth) if self.depth is not None else "",
                "latitude": fmt_value(self.latitude), "longitude": fmt_value(self.longitude)}


def load_seismic_events(path: Path, manifest: dict) -> tuple[dict[str, SeismicEvent], dict, str | None]:
    fp = path / "events.geojson"
    if not fp.exists():
        return {}, {}, None
    try:
        expected = (manifest.get("files", {}).get("events.geojson") or {}).get("sha256")
        if not expected or hashlib.sha256(fp.read_bytes()).hexdigest() != expected:
            raise ValueError("SHA-256 de events.geojson no coincide o falta")
        data = json.loads(fp.read_text(encoding="utf-8"))
        if data.get("type") != "FeatureCollection":
            raise ValueError("se esperaba FeatureCollection")
        events = {}
        for row in data["features"]:
            props = row["properties"]
            eid = row["id"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", eid) or eid in events:
                raise ValueError("ID de evento inválido o duplicado")
            raw_time = props.get("time")
            when = (datetime.fromtimestamp(raw_time / 1000, UTC) if isinstance(raw_time, (int, float))
                    else datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")))
            if when.tzinfo is None:
                raise ValueError("fecha de evento sin zona horaria")
            magnitude = float(props.get("magnitude", props.get("mag")))
            if row.get("type") != "Feature" or row["geometry"].get("type") != "Point":
                raise ValueError("geometría de evento inválida")
            coordinates = row["geometry"]["coordinates"]
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
            depth = float(coordinates[2]) if len(coordinates) > 2 and coordinates[2] is not None else None
            if (not all(math.isfinite(v) for v in (magnitude, latitude, longitude))
                    or not -90 <= latitude <= 90 or not -180 <= longitude <= 180
                    or (depth is not None and not math.isfinite(depth))):
                raise ValueError("magnitud o coordenadas inválidas")
            url = str(props["url"])
            parsed = urlparse(url)
            if (parsed.scheme != "https" or parsed.hostname != "earthquake.usgs.gov" or parsed.username or parsed.password
                    or parsed.path.rstrip("/") != f"/earthquakes/eventpage/{eid}"):
                raise ValueError("URL de evento fuera de USGS o de su ID")
            place = str(props.get("place") or "ubicación sin nombre")
            if looks_like_instruction(place):
                raise ValueError("instrucciones en la ubicación del evento")
            events[eid] = SeismicEvent(eid, magnitude, when.astimezone(UTC), place, url, depth, latitude, longitude)
        return events, data.get("metadata") or {}, None
    except (OSError, ValueError, TypeError, KeyError, OverflowError, IndexError, AttributeError) as exc:
        detail = "archivo ilegible" if isinstance(exc, OSError) else str(exc)
        return {}, {}, f"Catálogo USGS rechazado; no se usarán sus eventos ({detail})."
