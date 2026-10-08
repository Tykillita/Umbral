"""Utilidades pequeñas compartidas."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

PANAMA_TZ = timezone(timedelta(hours=-5), "America/Panama")  # Panamá no tiene horario de verano


def now_utc() -> datetime:
    return datetime.now(UTC)


def fmt_pa(dt: datetime | None, *, unknown: str = "fecha desconocida") -> str:
    if dt is None:
        return unknown
    return dt.astimezone(PANAMA_TZ).strftime("%Y-%m-%d %H:%M") + " (hora de Panamá)"


def fmt_value(value: float | None) -> str:
    """Valor de un indicador para mostrar y citar. `:g` pierde cifras en cantidades grandes (4,515,577 -> «4.51558e+06»)."""
    if value is None:
        return "sin dato"
    if abs(value) >= 100_000:
        return f"{value:,.0f}"
    return f"{value:g}"


def fmt_date_pa(dt: datetime | None, *, unknown: str = "fecha desconocida") -> str:
    if dt is None:
        return unknown
    return dt.astimezone(PANAMA_TZ).strftime("%Y-%m-%d")


def word_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ%]+(?:[.,'’-][0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)*", text))


def strip_markers(text: str) -> str:
    return re.sub(r"\s*\[c\d+\]", "", text)


def marker_ids(text: str) -> list[str]:
    return re.findall(r"\[(c\d+)\]", text)
