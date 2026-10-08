"""Validacion y normalizacion de noticias (PDF etapa 1 / T01).

Entrada: registros crudos de fetch (dicts). Salida: (articulos validos, rechazados).
Los registros invalidos NO bloquean la carga: se separan con motivo en invalid.jsonl.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any

from .config import TVN_DOMAIN
from .util import (
    canonicalize_url,
    date_from_url,
    domain_of,
    iso_z,
    normalize_text,
    parse_dt,
    sha256_hex,
)

LANG_MAP = {
    "spanish": "es", "english": "en", "portuguese": "pt", "french": "fr", "italian": "it", "german": "de",
    "catalan": "ca", "galician": "gl", "basque": "eu", "chinese": "zh", "russian": "ru", "arabic": "ar",
    "japanese": "ja", "korean": "ko", "dutch": "nl", "es": "es", "en": "en", "pt": "pt", "fr": "fr",
}

# Firmas de agencias (titular o ruta). Una agencia replicada = una procedencia.
AGENCIES = {
    "efe": r"\bEFE\b",
    "afp": r"\bAFP\b",
    "ap": r"\bAP\b|Associated Press",
    "reuters": r"\bReuters\b",
    "europa_press": r"Europa Press",
    "ansa": r"\bANSA\b",
    "xinhua": r"\bXinhua\b",
    "prensa_latina": r"Prensa Latina",
    "dpa": r"\bDPA\b",
    "bloomberg": r"\bBloomberg\b",
}
_AGENCY_DOMAINS = {
    "efe.com": "efe", "efeagro.com": "efe", "afp.com": "afp", "apnews.com": "ap", "reuters.com": "reuters",
    "europapress.es": "europa_press", "ansa.it": "ansa", "xinhuanet.com": "xinhua", "prensa-latina.cu": "prensa_latina",
    "dpa.com": "dpa", "bloomberg.com": "bloomberg", "bloomberglinea.com": "bloomberg",
}


def detect_agency(title: str, url: str, domain: str) -> str | None:
    """Agencia declarada en el titular (sufijo '- EFE', '(AFP)', '| Reuters') o dominio propio de la agencia."""
    if domain in _AGENCY_DOMAINS:
        return _AGENCY_DOMAINS[domain]
    tail = title[-40:]
    head = title[:25]
    for key, rx in AGENCIES.items():
        # solo si aparece como firma (tras separador o entre parentesis), no como palabra suelta en medio
        if re.search(rf"(?:[-–—|:(\[]\s*)(?:{rx})\s*[)\]]?\s*$", tail) or re.search(rf"^\s*[(\[]?(?:{rx})[)\]]?\s*[-–—:|]", head):
            return key
    return None


def provenance_for(title: str, url: str, domain: str) -> dict[str, Any]:
    ag = detect_agency(title, url, domain)
    if ag:
        return {"key": f"agency:{ag}", "kind": "agency", "agency": ag, "known": True}
    if domain:
        return {"key": f"outlet:{domain}", "kind": "outlet", "agency": None, "known": True}
    return {"key": "unknown:unknown", "kind": "unknown", "agency": None, "known": False}


def outlet_name(domain: str) -> str:
    if domain == TVN_DOMAIN:
        return "TVN Panamá"
    return domain


def _reject(raw: dict[str, Any], codes: list[str], reasons: list[str], *, source: str, at: str) -> dict[str, Any]:
    clipped = {k: (v[:2000] if isinstance(v, str) else v) for k, v in raw.items()}
    key = sha256_hex(f"{source}|{raw.get('url')}|{raw.get('title')}|{raw.get('publishedRaw')}|{raw.get('detectedRaw')}|{','.join(codes)}")[:16]
    return {
        "rejectId": f"rej_{key}", "source": source, "reasons": reasons, "reasonCodes": codes,
        "raw": clipped, "rejectedAt": at,
    }


def normalize_record(
    raw: dict[str, Any],
    *,
    window_start: datetime,
    cutoff: datetime,
    extracted_default: str,
    is_fixture: bool = False,
    future_tolerance: timedelta = timedelta(days=1),
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Valida un registro. Devuelve (articulo, None) o (None, rechazo)."""
    source = (raw.get("origin") or {}).get("source", "fixture" if is_fixture else "unknown")
    codes: list[str] = []
    reasons: list[str] = []
    now_iso = iso_z(cutoff) or extracted_default

    title_in = raw.get("title")
    url_in = raw.get("url")
    if (title_in in (None, "")) and (url_in in (None, "")) and not raw.get("publishedRaw") and not raw.get("detectedRaw"):
        return None, _reject(raw, ["empty_row"], ["fila vacía"], source=source, at=now_iso)

    title = normalize_text(html.unescape(str(title_in))) if title_in not in (None, "") else ""
    if len(title) < 8:
        codes.append("missing_title")
        reasons.append("titular ausente o demasiado corto")

    canon = None
    if url_in in (None, ""):
        codes.append("missing_url")
        reasons.append("URL ausente")
    else:
        canon = canonicalize_url(str(url_in))
        if canon is None:
            codes.append("invalid_url")
            reasons.append(f"URL inválida: {str(url_in)[:80]!r}")

    published = None
    pub_basis = "unknown"
    pub_raw = raw.get("publishedRaw")
    if pub_raw not in (None, ""):
        published = parse_dt(pub_raw)
        if published is None:
            codes.append("invalid_date")
            reasons.append(f"fecha de publicación no interpretable: {str(pub_raw)[:40]!r}")
        else:
            pub_basis = "news_sitemap_publication" if source == "tvn_news_sitemap" else "rss_pubdate"
    detected = None
    det_raw = raw.get("detectedRaw")
    if det_raw not in (None, ""):
        detected = parse_dt(det_raw)
        if detected is None:
            codes.append("invalid_date")
            reasons.append(f"fecha de detección no interpretable: {str(det_raw)[:40]!r}")

    if "invalid_date" not in codes:
        if published is None and canon:
            pdt = date_from_url(canon, not_after=cutoff + future_tolerance)
            if pdt is not None:
                published, pub_basis = pdt, "url_pattern"
        if published is None and detected is None:
            codes.append("null_date")
            reasons.append("sin ninguna fecha utilizable (publicación ni detección)")
        else:
            for label, dt in (("publicación", published), ("detección", detected)):
                if dt is not None and dt > cutoff + future_tolerance:
                    codes.append("invalid_date")
                    reasons.append(f"fecha de {label} en el futuro ({iso_z(dt)})")
            # ventana: se mide por detección/observación (GDELT) o publicación RSS; no por la fecha inferida de URL
            observed = detected or (published if pub_basis in {"rss_pubdate", "news_sitemap_publication"} else None)
            if observed is None:
                observed = published
            if observed is not None and "invalid_date" not in codes and observed < window_start:
                codes.append("date_out_of_window")
                reasons.append(f"fuera de la ventana ({iso_z(observed)} < {iso_z(window_start)})")

    if codes:
        return None, _reject(raw, sorted(set(codes), key=codes.index), reasons, source=source, at=now_iso)

    assert canon is not None
    domain = domain_of(canon) or ""
    prefix = "fx_" if is_fixture or source == "fixture" else "art_"
    extracted = raw.get("extractedAt") or extracted_default
    effective = iso_z(detected) or iso_z(published) or extracted
    lang_raw = (raw.get("language") or "").strip().lower()
    language = LANG_MAP.get(lang_raw) or (lang_raw if re.fullmatch(r"[a-z]{2}", lang_raw) else None)
    is_tvn = domain == TVN_DOMAIN

    article = {
        "articleId": prefix + sha256_hex(canon)[:16],
        "title": title,
        "url": str(url_in).strip(),
        "canonicalUrl": canon,
        "domain": domain,
        "outlet": outlet_name(domain),
        "isTvn": is_tvn,
        "language": language,
        "sourceCountry": raw.get("sourceCountry") or None,
        "publishedAt": iso_z(published),
        "publishedAtBasis": pub_basis if published else "unknown",
        "detectedAt": iso_z(detected),
        "extractedAt": extracted,
        "effectiveDate": effective,
        "topicHint": raw.get("topicHint"),
        "origin": raw.get("origin") or {"source": source, "query": None, "endpoint": ""},
        "textScope": "headline_metadata",
        "provenance": provenance_for(title, canon, domain),
        "dataOrigin": "fixture" if prefix == "fx_" else "real",
        "provisional": True,
        "sourceRank": int(raw.get("sourceRank") or 0),
        "urlVariantsSeen": 1,
    }
    return article, None


def merge_url_duplicates(articles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Colapsa por URL canonica. Prefiere la fuente con publishedAt rss > url_pattern > desconocido; conserva el topicHint combinado."""
    rank = {"rss_pubdate": 0, "news_sitemap_publication": 0, "url_pattern": 1, "unknown": 2}
    best: dict[str, dict[str, Any]] = {}
    dropped = 0
    for a in articles:
        cur = best.get(a["canonicalUrl"])
        if cur is None:
            best[a["canonicalUrl"]] = a
            continue
        dropped += 1
        keep, other = (a, cur) if rank[a["publishedAtBasis"]] < rank[cur["publishedAtBasis"]] else (cur, a)
        keep["urlVariantsSeen"] = cur["urlVariantsSeen"] + a["urlVariantsSeen"]
        if not keep.get("detectedAt") and other.get("detectedAt"):
            keep["detectedAt"] = other["detectedAt"]
        if not keep.get("language") and other.get("language"):
            keep["language"] = other["language"]
        if not keep.get("sourceCountry") and other.get("sourceCountry"):
            keep["sourceCountry"] = other["sourceCountry"]
        if keep.get("topicHint") and other.get("topicHint") and other["topicHint"] not in keep["topicHint"].split("|"):
            keep["topicHint"] = keep["topicHint"] + "|" + other["topicHint"]
        elif not keep.get("topicHint"):
            keep["topicHint"] = other.get("topicHint")
        best[a["canonicalUrl"]] = keep
    out = sorted(best.values(), key=lambda x: (x["effectiveDate"], x["articleId"]))
    return out, dropped
