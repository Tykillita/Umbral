"""Etapa 'build': crudo -> validacion -> clasificacion -> duplicados -> snapshot con manifest."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from .classify.baseline import BaselineClassifier
from .cluster import build_clusters
from .config import (
    COUNTRIES,
    INDICATORS,
    MAX_WINDOW_DAYS,
    MIN_TVN,
    MIN_UNIQUE,
    TARGET_UNIQUE,
    YEARS,
)
from .fixtures import fixture_indicators, fixture_news
from .snapshot import export_snapshot
from .util import iso_z, now_utc, parse_dt
from .validate import merge_url_duplicates, normalize_record

TRANSFORMATIONS = [
    "html_unescape_titles",
    "normalize_whitespace_nfc",
    "canonicalize_url(https, sin www, sin tracking, sin fragmento)",
    "collapse_duplicates_by_canonical_url",
    "normalize_dates_utc_iso8601",
    "date_from_url_pattern(solo si no hay publicación; basis=url_pattern)",
    "validate_ids_urls_dates_fields -> invalid.jsonl",
    "classify_category_and_geo",
    "cluster_duplicates(title_exact, title_fuzzy, bm25+tiebreak)",
    "detect_recirculation(>14 d entre publicación y detección)",
]


def _latest_raw(data_dir: Path) -> Path:
    runs = sorted(p for p in (data_dir / "raw").glob("*") if (p / "fetch_meta.json").exists())
    if not runs:
        raise SystemExit("No hay crudo en data/raw/. Ejecuta `fetch` o `fixture-snapshot`.")
    return runs[-1]


def _load_raw(raw: Path) -> dict[str, Any]:
    meta = json.loads((raw / "fetch_meta.json").read_text(encoding="utf-8"))
    out: dict[str, Any] = {"meta": meta, "news": [], "indicators": None, "events": None}
    for name in ("tvn_records.json", "tvn_sitemap_records.json", "gdelt_records.json", "bing_news_records.json"):
        p = raw / name
        if p.exists():
            out["news"].extend(json.loads(p.read_text(encoding="utf-8")))
    p = raw / "worldbank_rows.json"
    if p.exists():
        out["indicators"] = json.loads(p.read_text(encoding="utf-8"))
    p = raw / "usgs_events.geojson"
    if p.exists():
        out["events"] = json.loads(p.read_text(encoding="utf-8"))
    return out


def run_build(
    data_dir: Path,
    *,
    raw_dir: Path | None,
    classifier: str = "baseline",
    extra_raw: list[Path] | None = None,
    use_fixtures: bool = False,
    fixtures_only: bool = False,
    laya_tiebreak: bool = True,
    set_current: bool = True,
    log=print,
) -> Path:
    queries: list[dict[str, Any]] = []
    news_raw: list[dict[str, Any]] = []
    indicators: list[dict[str, Any]] | None = None
    events: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = []
    extracted_by_source: dict[str, str | None] = {}

    if fixtures_only:
        cutoff = now_utc()
        window_start = cutoff - timedelta(days=30)
        use_fixtures = True
    else:
        raws = [raw_dir or _latest_raw(data_dir), *(extra_raw or [])]
        loaded = [_load_raw(r) for r in raws]
        primary = loaded[0]["meta"]
        cutoff = parse_dt(primary["cutoffUtc"])
        assert cutoff is not None
        window_start = min(parse_dt(x["meta"]["windowStartUtc"]) for x in loaded)  # type: ignore[type-var]
        window_start = max(window_start, cutoff - timedelta(days=MAX_WINDOW_DAYS))
        for x in loaded:
            news_raw += x["news"]
            queries += x["meta"]["queries"]
            errors += x["meta"].get("errors", [])
            indicators = indicators or x["indicators"]
            events = events or x["events"]
            for q in x["meta"]["queries"]:
                extracted_by_source.setdefault(q["source"], q.get("extractedAt") or x["meta"]["cutoffUtc"])
        log(f"[build] crudo: {len(news_raw)} registros de noticias; ventana {iso_z(window_start)} .. {iso_z(cutoff)}")

    extracted_default = iso_z(cutoff) or ""
    if use_fixtures:
        news_raw = [*news_raw, *fixture_news(cutoff)]
        extracted_by_source["fixture"] = extracted_default
    if indicators is None:
        if fixtures_only:
            indicators = fixture_indicators(extracted_default)
        else:
            indicators = []
            log("[build] ADVERTENCIA: no hay indicadores en el crudo")

    # --- validacion ---
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for raw in news_raw:
        is_fx = (raw.get("origin") or {}).get("source") == "fixture"
        art, rej = normalize_record(raw, window_start=window_start, cutoff=cutoff, extracted_default=extracted_default, is_fixture=is_fx)
        if art:
            valid.append(art)
        else:
            invalid.append(rej)  # type: ignore[arg-type]
    valid, dup_dropped = merge_url_duplicates(valid)
    # rechazos de identico contenido (mismo rejectId) se colapsan
    invalid = list({r["rejectId"]: r for r in invalid}.values())
    log(f"[build] validos {len(valid)} (duplicados de URL colapsados: {dup_dropped}); invalidos {len(invalid)}")

    # --- clasificacion ---
    tiebreak = None
    classifier_info: dict[str, Any]
    if classifier == "laya":
        from .classify.laya_clf import LayaClassifier  # requiere extra 'laya'

        log("[build] cargando Laya multilingüe desde el checkpoint oficial/cache local")
        clf = LayaClassifier(log=log)
        log(f"[build] Laya cargado en {clf.load_seconds} s; clasificación de {len(valid)} titulares")
        predictions = clf.predict(valid)
        classifier_info = clf.info()
        if laya_tiebreak:
            tiebreak = clf.same_event
    else:
        clf_b = BaselineClassifier()
        predictions = clf_b.predict(valid)
        classifier_info = {
            "classifier": "baseline", "modelId": clf_b.model_id, "modelVersion": clf_b.model_version,
            "runAt": iso_z(now_utc()), "device": "cpu",
            "note": "Baseline léxico; NO es Laya. Laya no se ejecutó en esta corrida.",
        }
    cutoff_dt = cutoff
    clusters, cstats = build_clusters(valid, predictions, cutoff_dt, tiebreak=tiebreak)
    if classifier == "laya" and tiebreak is not None:
        classifier_info = clf.info()
        classifier_info["tiebreakCalls"] = cstats["tiebreak_calls"]
    log(f"[build] clusters {len(clusters)}; enlaces {({k: v for k, v in cstats.items()})}")

    # --- reporte de calidad ---
    n_tvn = sum(1 for a in valid if a["isTvn"])
    n_gdelt = sum(1 for a in valid if a["origin"]["source"] == "gdelt_doc")
    n_bing = sum(1 for a in valid if a["origin"]["source"] == "bing_news_rss")
    real_valid = [a for a in valid if a["dataOrigin"] == "real"]
    eff = sorted(a["effectiveDate"] for a in real_valid)
    ind_missing = sum(1 for r in indicators if r["value"] is None)
    expected = len(COUNTRIES) * len(INDICATORS) * len(YEARS)
    window_days = max(1, math.ceil((cutoff - window_start).total_seconds() / 86400))
    cat_counts = Counter(p["category"] for p in predictions)
    checks = [
        {"id": "ids_unique", "ok": len({a["articleId"] for a in valid}) == len(valid), "detail": "articleId únicos"},
        {"id": "urls_canonical_unique", "ok": len({a["canonicalUrl"] for a in valid}) == len(valid), "detail": "canonicalUrl únicas"},
        {"id": "predictions_cover_articles", "ok": len(predictions) == len(valid), "detail": f"{len(predictions)} predicciones / {len(valid)} artículos"},
        {"id": "indicator_grid_complete", "ok": len(indicators) == expected, "detail": f"{len(indicators)} filas (esperadas {expected})"},
        {"id": "target_200_unique", "ok": len(real_valid) >= TARGET_UNIQUE, "detail": f"{len(real_valid)} reales únicos (objetivo {TARGET_UNIQUE})"},
        {"id": "minimum_100_unique", "ok": len(real_valid) >= MIN_UNIQUE, "detail": f"mínimo operativo {MIN_UNIQUE}"},
        {"id": "minimum_20_tvn", "ok": sum(1 for a in real_valid if a["isTvn"]) >= MIN_TVN, "detail": f"{sum(1 for a in real_valid if a['isTvn'])} de TVN (mínimo {MIN_TVN})"},
    ]
    warnings: list[str] = []
    gdelt_failed = [e for e in errors if e.get("source") == "gdelt_doc"]
    if gdelt_failed:
        warnings.append(f"{len(gdelt_failed)} consultas GDELT fallaron (ver manifest.queries / fetch_meta.errors); cobertura posiblemente incompleta")
    if ind_missing:
        warnings.append(f"{ind_missing} de {len(indicators)} combinaciones de indicadores sin valor (se conservan como faltantes)")
    if classifier != "laya":
        warnings.append("Clasificación con baseline léxico, NO Laya")
    n_pub_null = sum(1 for a in valid if a["publishedAt"] is None)
    if n_pub_null:
        warnings.append(f"{n_pub_null} noticias sin fecha de publicación (GDELT solo informa detección)")

    quality = {
        "schemaVersion": "1.0.0",
        "generatedAt": iso_z(now_utc()),
        "news": {
            "fetched": len(news_raw), "valid": len(valid), "invalid": len(invalid),
            "invalidByCode": dict(Counter(c for r in invalid for c in r["reasonCodes"])),
            "uniqueCanonicalUrls": len({a["canonicalUrl"] for a in valid}),
            "duplicateUrlsCollapsed": dup_dropped,
            "tvnValid": n_tvn, "gdeltValid": n_gdelt, "bingNewsValid": n_bing,
            "fixtureValid": sum(1 for a in valid if a["dataOrigin"] == "fixture"),
            "nullPublishedAt": n_pub_null,
            "targetMet": len(real_valid) >= TARGET_UNIQUE, "minimumMet": len(real_valid) >= MIN_UNIQUE,
            "tvnMinimumMet": sum(1 for a in real_valid if a["isTvn"]) >= MIN_TVN,
            "tvnCoverage": {
                "validTvn": n_tvn, "source": "tvn_rss",
                "publishedFrom": min((a["publishedAt"] for a in real_valid if a["isTvn"] and a["publishedAt"]), default=None),
                "publishedTo": max((a["publishedAt"] for a in real_valid if a["isTvn"] and a["publishedAt"]), default=None),
                "note": "RSS oficiales de portada/nacionales/economía y sitemap Google News de TVN cuando se obtiene. La ventana efectiva está en publishedFrom/publishedTo; "
                        "no se presupone que el RSS cubra todos los días. GDELT puede aportar otras procedencias si sus consultas funcionan.",
            },
            "coverageWindow": {"start": eff[0] if eff else None, "end": eff[-1] if eff else None, "days": window_days},
            "widenedTo90Days": window_days > 31,
        },
        "indicators": {
            "expectedCombinations": expected, "rows": len(indicators),
            "pdfStatedCombinations": 1350,
            "discrepancyNote": "PDF §6B: 'Seis países ... Años: 2010–2024. Seis indicadores' y 'Cuadrícula de 1.350 combinaciones'. 6×6×15 = 540, no 1.350 (1.350 exigiría 15 países o 15 indicadores). Se exportan las 540 combinaciones que el propio PDF enumera; ver DECISIONES.",
            "withValue": len(indicators) - ind_missing, "missing": ind_missing,
            "missingByIndicator": dict(Counter(r["indicatorId"] for r in indicators if r["value"] is None)),
            "missingByCountry": dict(Counter(r["countryIso3"] for r in indicators if r["value"] is None)),
        },
        "classification": {
            "classifier": classifier_info["classifier"], "indeterminate": cat_counts.get("indeterminado", 0),
            "byCategory": dict(cat_counts),
            "byGeo": dict(Counter(p["geoRelevance"] for p in predictions)),
        },
        "clusters": {
            "count": len(clusters), "duplicatesMerged": len(valid) - len(clusters),
            "ambiguous": sum(1 for c in clusters if c["ambiguous"]),
            "recirculation": sum(1 for c in clusters if c["isRecirculation"]),
            "contradictionCandidates": sum(1 for c in clusters if c["hasContradictionCandidate"]),
            "linkMethods": {k: v for k, v in cstats.items()},
        },
        "checks": checks,
        "warnings": warnings,
    }

    reasons = ["no_official_frozen_package"]
    if use_fixtures:
        reasons.append("contains_fixtures")
    if not fixtures_only:
        if not checks[5]["ok"]:
            reasons.append("below_minimum_100")
        elif not checks[4]["ok"]:
            reasons.append("below_target_200")
        if not checks[6]["ok"]:
            reasons.append("below_minimum_20_tvn")
    if classifier != "laya":
        reasons.append("classifier_baseline_not_laya")
    if gdelt_failed:
        reasons.append("gdelt_query_failures")
    if ind_missing and any(r["sourceUrl"].startswith("fixture") for r in indicators):
        reasons.append("indicators_fixture")

    window = {
        "startUtc": iso_z(window_start), "endUtc": iso_z(cutoff), "days": window_days, "widenedTo90": window_days > 31,
        "note": "Decisión del usuario (D-01 resuelta): se ignora el intervalo [2024-01-01, 2025-10-01) del PDF §7; "
                "ventana = días previos a la extracción (30, ampliable a 90); corte = fecha de extracción. "
                "La cobertura efectiva de los feeds TVN está en quality_report.news.tvnCoverage; GDELT registra cada consulta y su error.",
    }
    out = export_snapshot(
        data_dir, cutoff=cutoff, window=window, queries=queries, articles=valid, indicators=indicators,
        predictions=predictions, clusters=clusters, invalid=invalid, quality=quality, classifier_info=classifier_info,
        events_geojson=events, contains_fixtures=use_fixtures, provisional_reasons=reasons,
        sources_extracted=extracted_by_source, transformations=TRANSFORMATIONS, set_current=set_current and not fixtures_only,
    )
    log(f"[build] snapshot {out.name} escrito en {out}")
    return out
