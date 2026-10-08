"""Macro-F1 de clasificacion (y de relevancia geografica) contra etiquetas manuales, para uno o varios snapshots.

Uso:
  uv run --project pipeline python eval/run_classification.py \
      --labels eval/labels/cls_labels.jsonl --snapshot baseline=data/snapshots/<id_baseline> --snapshot laya=data/snapshots/<id_laya> \
      --out eval/results/classification-<fecha>.json

Las etiquetas viven en eval/labels/cls_labels.jsonl (articleId, label, geo, stratum, labeler, labelMethod).
Solo se evaluan articulos presentes en el snapshot (articleId = hash de URL canonica, estable entre snapshots).
Se reporta macro-F1 sobre (a) todo el conjunto etiquetado y (b) el estrato `uniform`, con n, soporte por clase y matriz de confusion.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from label_provenance import evaluation_kind, verified_manifest
from umbral_pipeline.config import CATEGORIES, INDETERMINATE
from umbral_pipeline.evalkit.metrics import (
    accuracy,
    confusion,
    macro_f1,
    prf_per_class,
    probability_quality,
)
from umbral_pipeline.util import read_jsonl, sha256_file

LABELS = [*CATEGORIES, INDETERMINATE]
GEO = ["panama", "regional", "none", "indeterminate"]


def evaluate(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict:
    per = prf_per_class(y_true, y_pred, labels)
    return {
        "n": len(y_true),
        "macroF1": macro_f1(y_true, y_pred, labels) if y_true else None,
        "macroF1AllLabels": macro_f1(y_true, y_pred, labels, only_supported=False) if y_true else None,
        "accuracy": accuracy(y_true, y_pred) if y_true else None,
        "perClass": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in per.items()},
        "confusion": confusion(y_true, y_pred),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=Path("eval/labels/cls_labels.jsonl"))
    ap.add_argument("--snapshot", action="append", required=True, help="nombre=ruta (p. ej. laya=data/snapshots/ID)")
    ap.add_argument("--split", choices=("train", "validation", "calibration", "test", "difficult"),
                    help="Evalúa solo una partición, útil para mantener intacto el conjunto de prueba")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    source_labels = [r for r in read_jsonl(a.labels) if r.get("label")]
    labels = {r["articleId"]: r for r in source_labels}
    if len(labels) != len(source_labels):
        raise ValueError("El archivo de etiquetas contiene articleId duplicados")
    if a.split:
        labels = {article_id: row for article_id, row in labels.items() if row.get("split") == a.split}
        if not labels:
            raise ValueError(f"No hay etiquetas para split={a.split}")
    if any(r["label"] not in LABELS or (r.get("geo") and r["geo"] not in GEO) for r in labels.values()):
        raise ValueError("Etiqueta de categoría/geografía inválida")
    report: dict = {
        "command": " ".join(sys.argv), "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": platform.python_version(), "labelsFile": str(a.labels), "labelsTotal": len(labels),
        "split": a.split,
        "labelMethod": sorted({r.get("labelMethod", "") for r in labels.values()}),
        "labelers": sorted({r.get("labeler", "") for r in labels.values()}),
        "results": {},
        "evaluationKind": evaluation_kind(list(labels.values())),
        "labelsSha256": sha256_file(a.labels), "evaluatorSha256": sha256_file(Path(__file__)),
    }
    for spec in a.snapshot:
        name, _, path = spec.partition("=")
        snap = Path(path)
        manifest = verified_manifest(snap)
        preds = {p["articleId"]: p for p in read_jsonl(snap / "predictions.jsonl")}
        ids = [i for i in labels if i in preds]
        res: dict = {"snapshotId": manifest["snapshotId"], "classifier": manifest["classifier"]["classifier"],
                     "modelVersion": manifest["classifier"].get("modelVersion"), "labeledInSnapshot": len(ids),
                     "manifestSha256": manifest["manifestSha256"]}
        for i in ids:
            if (labels[i].get("snapshotId") and labels[i]["snapshotId"] != manifest["snapshotId"]
                    and labels[i].get("articlesSha256") != manifest["files"]["articles.jsonl"]["sha256"]):
                raise ValueError("La etiqueta pertenece a otro corpus/snapshot")
            if labels[i].get("inputHash") and labels[i]["inputHash"] != preds[i]["inputHash"]:
                raise ValueError("La etiqueta corresponde a un titular distinto (inputHash)")
        for scope, sel in (("all", ids), ("uniform", [i for i in ids if labels[i].get("stratum") == "uniform"])):
            if not sel:
                continue
            res[scope] = {
                "category": evaluate([labels[i]["label"] for i in sel], [preds[i]["category"] for i in sel], LABELS),
                "geo": evaluate([labels[i]["geo"] for i in sel if labels[i].get("geo")],
                                [preds[i]["geoRelevance"] for i in sel if labels[i].get("geo")], GEO),
            }
            # calibracion cruda: confianza media vs exactitud (sin ajustar)
            correct = [preds[i]["category"] == labels[i]["label"] for i in sel]
            conf = [preds[i]["probability"] for i in sel]
            res[scope]["confidenceVsAccuracy"] = {
                "meanConfidence": round(sum(conf) / len(conf), 4), "accuracy": round(sum(correct) / len(correct), 4),
                "note": "Probabilidades sin calibrar; si meanConfidence >> accuracy el modelo está sobreconfiado.",
            }
            res[scope]["probabilityQuality"] = probability_quality(
                [labels[i]["label"] for i in sel], [preds[i] for i in sel], LABELS)
            if all(preds[i].get("calibratedProbabilities") for i in sel):
                calibrated = [dict(preds[i], probabilities=preds[i]["calibratedProbabilities"]) for i in sel]
                res[scope]["calibratedProbabilityQuality"] = probability_quality(
                    [labels[i]["label"] for i in sel], calibrated, LABELS, calibrated=True)
        report["results"][name] = res
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, res in report["results"].items():
        for scope in ("all", "uniform"):
            if scope in res:
                c = res[scope]["category"]
                print(f"{name} {scope} n={c['n']} macroF1={c['macroF1']} accuracy={c['accuracy']} "
                      f"geo macroF1={res[scope]['geo']['macroF1']}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
