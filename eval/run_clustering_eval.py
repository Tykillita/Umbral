"""Precision/recall de agrupacion sobre pares etiquetados «mismo evento» (eval/labels/pairs_labels.jsonl).

Un par se predice «mismo evento» si ambos articulos caen en el mismo cluster del snapshot.
Uso: uv run --project pipeline python eval/run_clustering_eval.py --labels eval/labels/pairs_labels.jsonl \
        --snapshot sin_desempate=data/snapshots/<id1> --snapshot con_laya=data/snapshots/<id2> --out eval/results/clustering-<fecha>.json
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from label_provenance import evaluation_kind, verified_manifest
from umbral_pipeline.util import read_jsonl, sha256_file


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=Path("eval/labels/pairs_labels.jsonl"))
    ap.add_argument("--snapshot", action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    labels = [r for r in read_jsonl(a.labels) if r.get("sameEvent") is not None]
    if any(type(r["sameEvent"]) is not bool for r in labels):
        raise ValueError("sameEvent requiere true/false JSON, no una cadena")
    report = {"command": " ".join(sys.argv), "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "python": platform.python_version(), "pairsLabeled": len(labels),
              "positives": sum(1 for r in labels if r["sameEvent"]),
              "labelers": sorted({r.get("labeler", "") for r in labels}), "results": {},
              "labelMethod": sorted({r.get("labelMethod", "") for r in labels}),
              "evaluationKind": evaluation_kind(labels), "labelsSha256": sha256_file(a.labels),
              "evaluatorSha256": sha256_file(Path(__file__))}
    for spec in a.snapshot:
        name, _, path = spec.partition("=")
        snap = Path(path)
        m = verified_manifest(snap)
        if any(r.get("snapshotId") and r["snapshotId"] != m["snapshotId"]
               and r.get("articlesSha256") != m["files"]["articles.jsonl"]["sha256"] for r in labels):
            raise ValueError("Los pares humanos pertenecen a otro snapshot")
        cl_of: dict[str, str] = {}
        for c in read_jsonl(snap / "clusters.jsonl"):
            for x in c["memberArticleIds"]:
                cl_of[x] = c["clusterId"]
        tp = fp = fn = tn = skipped = 0
        by_stratum: dict[str, list[int]] = {}
        for r in labels:
            if r["a"] not in cl_of or r["b"] not in cl_of:
                skipped += 1
                continue
            pred = cl_of[r["a"]] == cl_of[r["b"]]
            gold = bool(r["sameEvent"])
            s = by_stratum.setdefault(r["stratum"], [0, 0, 0, 0])
            if pred and gold:
                tp += 1; s[0] += 1
            elif pred and not gold:
                fp += 1; s[1] += 1
            elif not pred and gold:
                fn += 1; s[2] += 1
            else:
                tn += 1; s[3] += 1
        report["results"][name] = {
            "snapshotId": m["snapshotId"], "classifier": m["classifier"]["classifier"], "skippedPairsNotInSnapshot": skipped,
            "manifestSha256": m["manifestSha256"],
            **prf(tp, fp, fn), "tn": tn,
            "byStratum": {k: prf(v[0], v[1], v[2]) | {"tn": v[3]} for k, v in by_stratum.items()},
            "linkMethods": json.loads((snap / "quality_report.json").read_text(encoding="utf-8"))["clusters"].get("linkMethods"),
            "caveat": "Pares CANDIDATOS (BM25+RapidFuzz) etiquetados por revisor único; recall sobre pares candidatos, no sobre el universo.",
        }
        r0 = report["results"][name]
        print(f"{name:14s} P={r0['precision']} R={r0['recall']} F1={r0['f1']} tp={tp} fp={fp} fn={fn} tn={tn}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
