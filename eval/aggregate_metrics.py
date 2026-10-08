"""Agrega los resultados REALES mas recientes de eval/results/ en eval/results/latest.json (lo lee el backend).

Solo copia numeros ya calculados por ejecuciones reales (cada seccion conserva comando, fecha y entorno).
Una seccion sin ejecucion queda como {"status": "pendiente"}: nunca se rellena con cifras.
Las consultas reservadas NO se copian: solo agregados (sin texto de preguntas) si se indica --reserved-results.

Uso: uv run --project pipeline python eval/aggregate_metrics.py [--reserved-results %USERPROFILE%/umbral-held-out/results.json]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

RES = Path(__file__).parent / "results"


def newest(pattern: str) -> Path | None:
    files = sorted(RES.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def load(p: Path | None):
    return json.loads(p.read_text(encoding="utf-8")) if p else None


def bench_summary(rep: dict) -> dict:
    s = dict(rep["summary"])
    if "retrievalPrecisionAt5" in s:
        s["retrievalPrecisionAt5"] = {k: v for k, v in s["retrievalPrecisionAt5"].items() if k != "perQuery"}
    elif "precisionAt5" in s:
        s["retrievalPrecisionAt5"] = {k: v for k, v in s.pop("precisionAt5").items() if k != "perQuery"}
    if "citationCoverage" in s:
        s["responseCitationPresence"] = s.pop("citationCoverage")
    s["failureCount"] = len(s.pop("failures"))
    return {"status": "ejecutado", "command": rep["command"], "ranAt": rep["ranAt"], "environment": rep["environment"],
            "benchmarkFile": rep["benchmarkFile"], "benchmarkSha256": rep.get("benchmarkSha256"),
            "evaluatorSha256": rep.get("evaluatorSha256"), "labelMethods": rep.get("labelMethods", []),
            "humanReviewed": rep.get("humanReviewed", False), "caveats": rep.get("caveats", []), **s}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reserved-results", type=Path, default=None)
    ap.add_argument("--snapshot", type=Path, default=None)
    a = ap.parse_args()
    snapshots = Path(__file__).resolve().parents[1] / "data" / "snapshots"
    snap = a.snapshot or snapshots / (snapshots / "CURRENT").read_text(encoding="utf-8").strip()
    snapshot_id = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))["snapshotId"]
    out: dict = {"schemaVersion": "1.1.0", "snapshotId": snapshot_id,
                 "generatedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "sections": {}}

    cls = load(newest("classification-*.json"))
    if cls and cls.get("evaluationKind") == "human" and cls.get("labelsTotal", 0) > 0 and any(
            r["snapshotId"] == snapshot_id for r in cls.get("results", {}).values()):
        sec: dict = {"status": "ejecutado", "command": cls["command"], "ranAt": cls["ranAt"], "labelsTotal": cls["labelsTotal"],
                     "labelers": cls["labelers"], "labelMethod": cls["labelMethod"], "byClassifier": {}}
        for name, r in cls["results"].items():
            if r["snapshotId"] != snapshot_id:
                continue
            sec["byClassifier"][name] = {"snapshotId": r["snapshotId"], "classifier": r["classifier"], "modelVersion": r["modelVersion"]}
            for scope in ("all", "uniform"):
                if scope in r:
                    c = r[scope]["category"]
                    sec["byClassifier"][name][scope] = {
                        "n": c["n"], "macroF1": round(c["macroF1"], 4), "accuracy": round(c["accuracy"], 4),
                        "geoMacroF1": round(r[scope]["geo"]["macroF1"], 4) if r[scope]["geo"]["macroF1"] is not None else None,
                        "confidenceVsAccuracy": r[scope]["confidenceVsAccuracy"],
                        "probabilityQuality": r[scope].get("probabilityQuality"),
                        "supportByClass": {k: v["support"] for k, v in c["perClass"].items()},
                    }
        out["sections"]["classification"] = sec
    else:
        out["sections"]["classification"] = {"status": "pendiente", "reason": "Sin etiquetas humanas para el snapshot actual."}

    clu = load(newest("clustering-*.json"))
    out["sections"]["clustering"] = (
        {"status": "ejecutado", "command": clu["command"], "ranAt": clu["ranAt"], "pairsLabeled": clu["pairsLabeled"],
         "positives": clu["positives"], "labelers": clu["labelers"],
         "results": {k: {kk: vv for kk, vv in v.items() if kk != "byStratum"}
                     for k, v in clu["results"].items() if v["snapshotId"] == snapshot_id}}
        if clu and clu.get("evaluationKind") == "human" and clu.get("pairsLabeled", 0) > 0
        and any(r["snapshotId"] == snapshot_id for r in clu["results"].values())
        else {"status": "pendiente", "reason": "Sin pares etiquetados para el snapshot actual."}
    )
    dev = load(newest("benchmark-dev-*.json"))
    out["sections"]["benchmarkDev"] = (
        bench_summary(dev) if dev and dev["environment"].get("snapshotId") == snapshot_id
        else {"status": "pendiente", "reason": "No hay ejecución de desarrollo para el snapshot actual."}
    )
    if a.reserved_results and a.reserved_results.exists():
        rs = bench_summary(json.loads(a.reserved_results.read_text(encoding="utf-8")))
        if rs["environment"].get("snapshotId") != snapshot_id:
            raise SystemExit("Resultados reservados no corresponden al snapshot actual")
        rs["benchmarkFile"] = "reservado (fuera del repo)"
        out["sections"]["benchmarkReserved"] = rs
    else:
        out["sections"]["benchmarkReserved"] = {"status": "pendiente"}
    out["sections"]["humanSupport"] = {"status": "pendiente", "reason": "Revisión humana de afirmaciones pendiente."}
    out["sections"]["agendaPrecisionAt5"] = {"status": "pendiente", "reason": "Juicio editorial independiente pendiente."}
    claims = load(newest("claims-human-*.json"))
    if claims and claims.get("evaluationKind") == "human" and claims.get("snapshotId") == snapshot_id:
        out["sections"]["humanSupport"] = {"status": "ejecutado", **claims}
    agenda = load(newest("agenda-human-*.json"))
    if agenda and agenda.get("evaluationKind") == "human" and agenda.get("snapshotId") == snapshot_id:
        out["sections"]["agendaPrecisionAt5"] = {"status": "ejecutado", **agenda}
    path = RES / "latest.json"
    RES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {path}: " + ", ".join(f"{k}={v['status']}" for k, v in out["sections"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
