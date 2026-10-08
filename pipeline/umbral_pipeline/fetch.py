"""Etapa 'fetch': descarga las fuentes y guarda lo CRUDO en data/raw/<runId>/ (no se redistribuye)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from .config import DEFAULT_WINDOW_DAYS
from .ingest.gdelt import fetch_gdelt
from .ingest.tvn import fetch_tvn
from .ingest.tvn_sitemap import fetch_news_sitemap
from .ingest.usgs import fetch_usgs
from .ingest.worldbank import fetch_worldbank
from .util import iso_z, now_utc, write_json


def run_fetch(
    data_dir: Path,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    sources: tuple[str, ...] = ("tvn", "gdelt", "worldbank", "usgs"),
    gdelt_window_days: int = 10,
    tvn_feeds: tuple[str, ...] = (
        "https://www.tvn-2.com/rss/", "https://www.tvn-2.com/rss/nacionales/",
        "https://www.tvn-2.com/rss/economia/",
    ),
    run_id: str | None = None,
    log=print,
) -> Path:
    cutoff = now_utc()
    run_id = run_id or cutoff.strftime("%Y%m%dT%H%M%SZ")
    raw_dir = data_dir / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {
        "runId": run_id, "cutoffUtc": iso_z(cutoff), "windowDays": window_days,
        "windowStartUtc": iso_z(cutoff - timedelta(days=window_days)), "sources": list(sources),
        "queries": [], "errors": [],
    }
    # Save the run before network access and after each source: an interrupted
    # extraction must leave a usable audit trail rather than orphaned records.
    write_json(raw_dir / "fetch_meta.json", meta)

    if "tvn" in sources:
        log("[fetch] TVN RSS")
        all_tvn: list[dict] = []
        for index, feed_url in enumerate(tvn_feeds):
            try:
                recs, q, xml_text = fetch_tvn(log=log, feed_url=feed_url)
                xml_name = "tvn_rss.xml" if index == 0 else f"tvn_rss_{index}.xml"
                (raw_dir / xml_name).write_text(xml_text, encoding="utf-8")
                all_tvn.extend(recs)
                meta["queries"].append(q)
                log(f"[fetch] TVN {q['endpoint']}: {len(recs)} items")
            except Exception as exc:  # noqa: BLE001
                meta["errors"].append({"source": "tvn_rss", "endpoint": feed_url,
                                       "error": f"{type(exc).__name__}: {exc}"[:300]})
                log(f"[fetch] TVN FALLO {feed_url}: {exc}")
            write_json(raw_dir / "tvn_records.json", all_tvn)
            write_json(raw_dir / "fetch_meta.json", meta)

    write_json(raw_dir / "fetch_meta.json", meta)

    if "tvn-sitemap" in sources:
        try:
            rows, query, xml_text = fetch_news_sitemap(log=log)
            (raw_dir / "tvn_news_sitemap.xml").write_text(xml_text, encoding="utf-8")
            write_json(raw_dir / "tvn_sitemap_records.json", rows)
            meta["queries"].append(query)
            log(f"[fetch] TVN Google News sitemap: {len(rows)} titulares con publicación")
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append({"source": "tvn_news_sitemap", "error": f"{type(exc).__name__}: {exc}"[:300]})
            log(f"[fetch] TVN sitemap FALLO: {exc}")
        write_json(raw_dir / "fetch_meta.json", meta)

    # Independent official indicators should finish before the rate-limited
    # news search, so GDELT cannot stall the whole corpus preparation.
    if "worldbank" in sources:
        log("[fetch] Banco Mundial (36 consultas)")
        rows, qlog, errs = fetch_worldbank(log=log)
        write_json(raw_dir / "worldbank_rows.json", rows)
        meta["queries"].extend(qlog)
        meta["errors"].extend({"source": "world_bank", **e} for e in errs)
        log(f"[fetch] WB: {len(rows)} filas, {sum(1 for r in rows if r['value'] is None)} faltantes")
        write_json(raw_dir / "fetch_meta.json", meta)

    if "gdelt" in sources:
        log(f"[fetch] GDELT DOC 2.0, ventana {window_days} d en tramos de {gdelt_window_days} d")
        recs, qlog, errs = fetch_gdelt(
            cutoff - timedelta(days=window_days), cutoff, window_days=gdelt_window_days, log=log
        )
        write_json(raw_dir / "gdelt_records.json", recs)
        meta["queries"].extend(qlog)
        meta["errors"].extend({"source": "gdelt_doc", **e} for e in errs)
        log(f"[fetch] GDELT: {len(recs)} registros, {len(errs)} consultas con error")
        write_json(raw_dir / "fetch_meta.json", meta)

    if "usgs" in sources:
        log("[fetch] USGS")
        try:
            gj, q = fetch_usgs(log=log)
            (raw_dir / "usgs_events.geojson").write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
            meta["queries"].append(q)
            log(f"[fetch] USGS: {q['returned']} eventos")
        except Exception as exc:  # noqa: BLE001
            meta["errors"].append({"source": "usgs", "error": f"{type(exc).__name__}: {exc}"[:300]})
            log(f"[fetch] USGS FALLO: {exc}")

    meta["finishedUtc"] = iso_z(now_utc())
    write_json(raw_dir / "fetch_meta.json", meta)
    log(f"[fetch] listo: {raw_dir}")
    return raw_dir
