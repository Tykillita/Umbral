"""Cortes diarios y reclasificación desde metadatos, sin requerir archivos crudos.

Nunca se activa un corte corrupto ni se usa baseline como sustitución de Laya.
La caché exige titular, checkpoint y reglas idénticos. Las citas de casos se
archivan en la API; la retención permite conservar sus snapshots referenciados.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .build import TRANSFORMATIONS, _load_raw
from .classify import input_hash
from .classify.calibration import load_profile, profile_path, resolve_model_version
from .classify.geo import METHOD as GEO_METHOD
from .classify.geo import geo_content_v2
from .classify.laya_clf import CATEGORY_QUESTION, PAIR_QUESTION, PINNED_REVISION, LayaClassifier
from .cluster import build_clusters
from .fetch import run_fetch
from .snapshot import activate_snapshot, export_snapshot, verify_snapshot
from .util import iso_z, now_utc, parse_dt, read_jsonl, sha256_hex
from .validate import merge_url_duplicates, normalize_record


def rules_hash() -> str:
    # A frozen executable has no Python source files; include all lexical data.
    from .classify import geo

    model_dir = Path(os.environ["UMBRAL_LAYA_MODEL_DIR"]) if os.environ.get("UMBRAL_LAYA_MODEL_DIR") else None
    model_version = resolve_model_version(model_dir, PINNED_REVISION)
    profile = load_profile(model_version, model_dir)
    active_profile = profile_path(model_dir)
    payload = {"category": CATEGORY_QUESTION, "pair": PAIR_QUESTION,
               "threshold": profile.threshold if profile else LayaClassifier.threshold,
               "calibrationProfileId": profile.profile_id if profile else None,
               "calibrationProfileSha256": sha256_hex(active_profile.read_text(encoding="utf-8"))
               if profile and active_profile else None,
               "geoMethod": GEO_METHOD, "geoTerms": [geo.PANAMA_TERMS, geo.REGION_TERMS, geo.FOREIGN_TERMS],
               "geoPatterns": [geo.PANAMA_RX.pattern, geo.BALBOA_RX.pattern, geo.CJK_PANAMA_RX.pattern]}
    return sha256_hex(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def load_verified(snapshot_dir: Path, *, no_fixtures: bool = True) -> dict[str, Any]:
    ok, problems = verify_snapshot(snapshot_dir)
    if not ok:
        raise ValueError("Snapshot inválido: " + "; ".join(problems))
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    if no_fixtures and manifest["containsFixtures"]:
        raise ValueError("No se acepta un snapshot con fixtures en producción.")
    return {"manifest": manifest, **{key: list(read_jsonl(snapshot_dir / f"{key}.jsonl"))
            for key in ("articles", "indicators", "predictions", "clusters", "invalid")},
            "quality": json.loads((snapshot_dir / "quality_report.json").read_text(encoding="utf-8")),
            "events": json.loads((snapshot_dir / "events.geojson").read_text(encoding="utf-8"))
            if (snapshot_dir / "events.geojson").exists() else None}


def classify_cached(articles: list[dict], previous: dict[str, Any], *, force: bool = False,
                    classifier_factory=LayaClassifier, progress=None, log=print):
    fingerprint = rules_hash()
    info = previous["manifest"]["classifier"]
    model_dir = Path(os.environ["UMBRAL_LAYA_MODEL_DIR"]) if os.environ.get("UMBRAL_LAYA_MODEL_DIR") else None
    model_version = resolve_model_version(model_dir, PINNED_REVISION)
    compatible = (not force and info.get("classifier") == "laya"
                  and info.get("modelVersion") == model_version and info.get("rulesHash") == fingerprint)
    cache = {p["articleId"]: p for p in previous["predictions"]} if compatible else {}
    cached, pending = {}, []
    for article in articles:
        pred = cache.get(article["articleId"])
        if pred and pred["inputHash"] == input_hash(article) and pred["modelVersion"] == model_version:
            # Geography depends on metadata as well as the headline, so always recompute it.
            pred = copy.deepcopy(pred)
            pred["geoRelevance"], pred["geoEvidence"] = geo_content_v2(article)
            cached[article["articleId"]] = pred
        else:
            pending.append(article)
    clf = classifier_factory(log=log)
    count = len(cached)
    if progress:
        progress("classification", count, len(articles))
    predicted = clf.predict(pending, progress=(lambda done, _: progress("classification", count + done,
                                                                        len(articles))) if progress else None)
    combined = {**cached, **{p["articleId"]: p for p in predicted}}
    predictions = [combined[a["articleId"]] for a in articles]
    classifier_info = {**clf.info(), "rulesHash": fingerprint, "cachedPredictions": count,
                       "newPredictions": len(pending)}
    return predictions, classifier_info, clf


def build_normalized(data_dir: Path, previous: dict[str, Any], *, articles: list[dict],
                     cutoff: datetime, window_start: datetime, indicators: list[dict] | None = None,
                     queries: list[dict] | None = None, errors: list[dict] | None = None,
                     events=None, invalid: list[dict] | None = None, force: bool = False,
                     set_current: bool = True, classifier_factory=LayaClassifier, progress=None, log=print) -> Path:
    if not articles:
        raise ValueError("La actualización no contiene noticias válidas; se conserva el corte anterior.")
    if any(a["dataOrigin"] != "real" for a in articles):
        raise ValueError("No se publican datos fixture.")
    indicators = indicators if indicators is not None else previous["indicators"]
    if any(r.get("dataOrigin") != "real" for r in indicators):
        raise ValueError("No se publican indicadores fixture.")
    predictions, info, clf = classify_cached(articles, previous, force=force,
        classifier_factory=classifier_factory, progress=progress, log=log)
    if progress:
        progress("clustering", 0, len(articles))
    clusters, stats = build_clusters(articles, predictions, cutoff, tiebreak=clf.same_event)
    info.update(clf.info())
    info["tiebreakCalls"] = stats["tiebreak_calls"]
    quality = copy.deepcopy(previous["quality"])
    news = quality["news"]
    real_tvn = sum(a["isTvn"] for a in articles)
    dates = sorted(a["effectiveDate"] for a in articles)
    window_days = max(1, math.ceil((cutoff - window_start).total_seconds() / 86400))
    news.update(fetched=len(articles), valid=len(articles), uniqueCanonicalUrls=len(articles), tvnValid=real_tvn,
                gdeltValid=sum(a["origin"]["source"] == "gdelt_doc" for a in articles), fixtureValid=0,
                invalid=len(invalid or []), invalidByCode=dict(Counter(c for r in invalid or [] for c in r["reasonCodes"])),
                nullPublishedAt=sum(a["publishedAt"] is None for a in articles), targetMet=len(articles) >= 200,
                minimumMet=len(articles) >= 100, tvnMinimumMet=real_tvn >= 20,
                coverageWindow={"start": dates[0], "end": dates[-1], "days": window_days},
                widenedTo90Days=window_days > 31)
    tvn_dates = [a["publishedAt"] for a in articles if a["isTvn"] and a["publishedAt"]]
    news["tvnCoverage"] = {"validTvn": real_tvn, "source": "tvn_rss+tvn_news_sitemap+gdelt_doc",
                           "publishedFrom": min(tvn_dates, default=None), "publishedTo": max(tvn_dates, default=None),
                           "note": "Cobertura observada, sin presuponer días cubiertos por los feeds."}
    missing = [r for r in indicators if r["value"] is None]
    quality["indicators"].update(rows=len(indicators), withValue=len(indicators) - len(missing), missing=len(missing),
                                 missingByIndicator=dict(Counter(r["indicatorId"] for r in missing)),
                                 missingByCountry=dict(Counter(r["countryIso3"] for r in missing)))
    quality["generatedAt"] = iso_z(now_utc())
    quality["classification"] = {"classifier": "laya", "byCategory": dict(Counter(p["category"] for p in predictions)),
                                 "indeterminate": sum(p["category"] == "indeterminado" for p in predictions),
                                 "byGeo": dict(Counter(p["geoRelevance"] for p in predictions))}
    quality["clusters"] = {"count": len(clusters), "duplicatesMerged": len(articles) - len(clusters),
                           "ambiguous": sum(c["ambiguous"] for c in clusters),
                           "recirculation": sum(c["isRecirculation"] for c in clusters), "linkMethods": stats,
                           "contradictionCandidates": sum(c["hasContradictionCandidate"] for c in clusters)}
    quality["checks"] = [{"id": "predictions_cover_articles", "ok": len(predictions) == len(articles),
                           "detail": f"{len(predictions)} predicciones / {len(articles)} artículos"},
                          {"id": "indicator_grid_complete", "ok": len(indicators) == 540, "detail": "540 combinaciones"},
                          {"id": "minimum_100_unique", "ok": len(articles) >= 100, "detail": "Mínimo operativo"},
                          {"id": "minimum_20_tvn", "ok": real_tvn >= 20, "detail": "Cobertura TVN"}]
    quality["warnings"] = ([f"{len(errors)} consultas de fuentes fallaron; se conserva cobertura previa disponible."]
                           if errors else [])
    quality["refresh"] = {"previousSnapshotId": previous["manifest"]["snapshotId"], "errors": errors or [],
                           "cachedPredictions": info["cachedPredictions"], "newPredictions": info["newPredictions"]}
    reasons = ["no_official_frozen_package"]
    if len(articles) < 100:
        reasons.append("below_minimum_100")
    if real_tvn < 20:
        reasons.append("below_minimum_20_tvn")
    if errors:
        reasons.append("source_query_failures")
    out = export_snapshot(data_dir, cutoff=cutoff,
        window={"startUtc": iso_z(window_start), "endUtc": iso_z(cutoff),
                "days": window_days, "widenedTo90": window_days > 31,
                "note": "Corte diario: 30 días, ingesta incremental con solapamiento de 48 horas."},
        queries=queries if queries is not None else previous["manifest"]["queries"], articles=articles,
        indicators=indicators, predictions=predictions, clusters=clusters, invalid=invalid or [], quality=quality,
        classifier_info=info, events_geojson=events if events is not None else previous["events"],
        contains_fixtures=False, provisional_reasons=reasons,
        sources_extracted={s["id"]: s.get("extractedAt") for s in previous["manifest"]["sources"]},
        transformations=[*TRANSFORMATIONS, "incremental_normalized_merge", "prediction_cache_hash_revision_rules"],
        set_current=False)
    ok, problems = verify_snapshot(out)
    if not ok:
        raise ValueError("Corte candidato rechazado: " + "; ".join(problems))
    if set_current:
        activate_snapshot(out)
    if progress:
        progress("complete", len(articles), len(articles))
    return out


def run_reclassify(data_dir: Path, snapshot_dir: Path, *, set_current: bool = False,
                   classifier_factory=LayaClassifier, progress=None, log=print) -> Path:
    previous = load_verified(snapshot_dir)
    manifest = previous["manifest"]
    return build_normalized(data_dir, previous, articles=previous["articles"], cutoff=parse_dt(manifest["cutoffUtc"]),
                            window_start=parse_dt(manifest["window"]["startUtc"]), force=True,
                            set_current=set_current, classifier_factory=classifier_factory, progress=progress, log=log)


def run_daily(data_dir: Path, *, previous_dir: Path | None = None, raw_dir: Path | None = None,
              set_current: bool = True, classifier_factory=LayaClassifier, progress=None, log=print) -> Path:
    previous_dir = previous_dir or data_dir / "snapshots" / (data_dir / "snapshots" / "CURRENT").read_text().strip()
    previous = load_verified(previous_dir)
    prev_cutoff = parse_dt(previous["manifest"]["cutoffUtc"])
    now = now_utc()
    fetch_days = min(30, max(2, math.ceil((now - prev_cutoff).total_seconds() / 86400) + 2))
    raw_dir = raw_dir or run_fetch(data_dir, window_days=fetch_days,
                                  sources=("tvn", "tvn-sitemap", "gdelt", "worldbank", "usgs"), log=log)
    raw = _load_raw(raw_dir)
    news_queries = [q for q in raw["meta"]["queries"] if q.get("source") in {"tvn_rss", "tvn_news_sitemap", "gdelt_doc"}]
    if not news_queries or not raw["news"]:
        raise ValueError("Ninguna fuente de noticias entregó una ingesta válida; se conserva el corte anterior.")
    cutoff = parse_dt(raw["meta"]["cutoffUtc"])
    if cutoff is None or cutoff < prev_cutoff:
        raise ValueError("El corte de ingesta es anterior al snapshot disponible.")
    start = cutoff - timedelta(days=30)
    fresh, invalid = [], []
    for record in raw["news"]:
        art, rejected = normalize_record(record, window_start=start, cutoff=cutoff, extracted_default=iso_z(cutoff))
        if art:
            fresh.append(art)
        elif rejected:
            invalid.append(rejected)
    if not fresh:
        raise ValueError("La ingesta no entregó noticias válidas en la ventana; se conserva el corte anterior.")
    # Failed/missing sources never remove previously observed records still in the window.
    old = [a for a in previous["articles"] if start <= parse_dt(a["effectiveDate"]) <= cutoff + timedelta(days=1)]
    articles, _ = merge_url_duplicates([*fresh, *old])
    indicators = raw["indicators"]
    if indicators is not None:
        previous_ind = {r["indicatorRowId"]: r for r in previous["indicators"]}
        indicators = [previous_ind.get(r["indicatorRowId"], r) if r["value"] is None else r for r in indicators]
    return build_normalized(data_dir, previous, articles=articles, indicators=indicators,
                            cutoff=cutoff, window_start=start, queries=raw["meta"]["queries"],
                            errors=raw["meta"].get("errors", []), events=raw["events"], invalid=invalid,
                            set_current=set_current, classifier_factory=classifier_factory, progress=progress, log=log)


def retain_snapshots(snapshots_root: Path, *, keep: int = 7, referenced: set[str] | None = None) -> list[str]:
    if keep < 1:
        raise ValueError("La retención debe conservar al menos un corte.")
    root = snapshots_root.resolve()
    current = (root / "CURRENT").read_text().strip() if (root / "CURRENT").exists() else None
    valid = []
    for path in root.iterdir():
        if path.is_dir() and not path.is_symlink() and re.fullmatch(r"\d{8}-[a-f0-9]{8}", path.name):
            try:
                manifest = load_verified(path)["manifest"]
                valid.append((manifest["cutoffUtc"], path))
            except (ValueError, KeyError, OSError):
                continue
    ordered = sorted(valid, key=lambda item: (item[0], item[1].name), reverse=True)
    preserve = {p.name for _, p in ordered[:keep]} | (referenced or set()) | {current}
    removed = []
    for _, path in valid:
        if path.name not in preserve and path.resolve().parent == root:
            shutil.rmtree(path)
            removed.append(path.name)
    return removed
