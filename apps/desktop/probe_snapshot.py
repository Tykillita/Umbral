"""Corte pequeño de metadatos reales para probar CPU/jobs sin repetir todo el corpus.

Sólo se escribe bajo .qa; no forma parte del instalador ni acredita cobertura.
"""

from __future__ import annotations

import copy
import argparse
from pathlib import Path

from umbral_pipeline.cluster import build_clusters
from umbral_pipeline.refresh import load_verified
from umbral_pipeline.snapshot import export_snapshot
from umbral_pipeline.util import parse_dt

ROOT = Path(__file__).resolve().parents[2]


def prepare_probe(data_dir: Path) -> Path:
    source = ROOT / "data/snapshots" / (ROOT / "data/snapshots/CURRENT").read_text().strip()
    state = load_verified(source)
    preds = state["predictions"]
    chosen = []
    for category in ("logistica_canal", "turismo"):
        match = next(p for p in preds if p["category"] == category)
        chosen.append(match["articleId"])
    articles = [copy.deepcopy(a) for a in state["articles"] if a["articleId"] in chosen]
    predictions = [p for p in preds if p["articleId"] in chosen]
    manifest = state["manifest"]
    cutoff = parse_dt(manifest["cutoffUtc"])
    clusters, _ = build_clusters(articles, predictions, cutoff)
    quality = {"schemaVersion": "1.0.0", "generatedAt": manifest["createdAt"],
               "news": {"fetched": len(articles), "valid": len(articles), "invalid": 0,
                        "fixtureValid": 0, "tvnValid": sum(a["isTvn"] for a in articles),
                        "targetMet": False, "minimumMet": False},
               "indicators": state["quality"]["indicators"], "classification": {"classifier": "laya"},
               "clusters": {"count": len(clusters)}, "checks": [],
               "warnings": ["Corte reducido de dos titulares reales usado sólo para smoke de escritorio."]}
    return export_snapshot(data_dir, cutoff=cutoff, window=manifest["window"], queries=manifest["queries"],
                           articles=articles, indicators=state["indicators"], predictions=predictions, clusters=clusters,
                           invalid=[], quality=quality, classifier_info=manifest["classifier"], events_geojson=None,
                           contains_fixtures=False, provisional_reasons=["desktop_smoke_reduced_real_corpus"],
                           sources_extracted={s["id"]: s.get("extractedAt") for s in manifest["sources"]},
                           transformations=manifest["transformations"], set_current=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / ".qa/state/Umbral")
    args = parser.parse_args()
    print(prepare_probe(args.data_dir))
