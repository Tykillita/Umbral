"""Utilidades deterministas: hashing, URLs canonicas, fechas UTC, JSONL."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src", "ocid", "cmpid",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id", "outputtype",
    "amp", "_ga", "wt.mc_id", "s_cid", "taid", "xtor",
}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(text: str | None) -> str:
    """NFC + espacios colapsados. No cambia mayusculas (el hash de entrada de Laya depende de esto)."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fold_text(text: str) -> str:
    """Minusculas sin tildes (para comparar/lexico)."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def canonicalize_url(url: str) -> str | None:
    """URL canonica: https, host en minusculas sin www., sin fragmento, sin tracking, sin '/' final.

    Devuelve None si no es una URL http(s) valida con host.
    """
    if not url:
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = (parts.hostname or "").lower()
    if not host or "." not in host:
        return None
    if host.startswith("www."):
        host = host[4:]
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    query.sort()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit(("https", host + port, path, urlencode(query), ""))


def domain_of(url: str) -> str | None:
    c = canonicalize_url(url)
    if not c:
        return None
    return urlsplit(c).hostname


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def parse_dt(value: Any) -> datetime | None:
    """Parsea fechas razonables a UTC aware. Devuelve None si no es valida (no inventa)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    s = str(value).strip()
    if not s or s.lower() in {"null", "none", "nan", "n/a", "-", "0000-00-00"}:
        return None
    # GDELT: 20260930T123000Z
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", s)
    if m:
        try:
            return datetime(*map(int, m.groups()), tzinfo=UTC)
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    try:  # RFC 822 (RSS)
        dt = parsedate_to_datetime(s)
        if dt is None:
            return None
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        return None


_URL_DATE_RE = [
    re.compile(r"/(20\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])(?:/|$)"),
    re.compile(r"(?<!\d)(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"),
]


def date_from_url(url: str, not_after: datetime | None = None) -> datetime | None:
    """Fecha en un patron del path de la URL (heuristica; el origen se marca 'url_pattern')."""
    path = urlsplit(url).path
    for rx in _URL_DATE_RE:
        m = rx.search(path)
        if m:
            try:
                dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
            except ValueError:
                continue
            if not_after is not None and dt > not_after:
                continue
            return dt
    return None


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=False, separators=(",", ":")) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: Path, obj: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
