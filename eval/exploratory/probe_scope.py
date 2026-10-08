"""Sondeo EXPLORATORIO del control de alcance de Laya (no es una evaluación con etiquetas humanas).

Lista: eval/exploratory/scope_probe.jsonl = 36 titulares ajenos al alcance (sucesos, deportes, farándula, política
internacional, curiosidades) y 30 titulares dentro del alcance (5 por categoría), todos escritos por el agente `datos`
como ejemplos genéricos, NO tomados del corpus real, y sin ajustar umbrales sobre el corpus real.
Compara variantes de preguntas/criterios; guarda probabilidades crudas. Selección con regla fijada de antemano:
la variante con mayor (recall fuera de alcance + retención dentro de alcance)/2; empate -> la más simple.

Uso: pipeline/.venv/Scripts/python.exe eval/exploratory/probe_scope.py --out eval/results/scope-probe-<fecha>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from umbral_pipeline.classify import laya_clf as L
from umbral_pipeline.config import CATEGORIES
from umbral_pipeline.util import read_jsonl

ROOT = Path(__file__).resolve().parents[2]

SCOPE_Q = L.SCOPE_QUESTION


def decide(variant: str, cat: dict, scope: dict | None, thr: float = 0.5, margin: float = 0.0, gate: float = 0.5) -> str:
    probs = {k: float(v) for k, v in cat.items()}
    best = max(probs, key=lambda k: probs[k])
    ranked = sorted(probs.values(), reverse=True)
    if best == "otro" or probs[best] < thr:
        return "indeterminado"
    if margin and (ranked[0] - ranked[1]) < margin:
        return "indeterminado"
    if scope is not None and float(scope.get("B", 0.0)) >= gate:
        return "indeterminado"
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    items = list(read_jsonl(ROOT / "eval/exploratory/scope_probe.jsonl"))
    clf = L.LayaClassifier(log=lambda *_: None)
    variants = {
        "v0_actual": {"q": L.CATEGORY_QUESTION_V0, "scope": False},
        "v1_criterios": {"q": L.CATEGORY_QUESTION_V1, "scope": False},
        "v1b_criterios_ampliados": {"q": L.CATEGORY_QUESTION_V1B, "scope": False},
        "v2_v1+puerta": {"q": L.CATEGORY_QUESTION_V1, "scope": True},
    }
    rows = []
    for it in items:
        row = {"id": it["id"], "title": it["title"], "expected": it["expected"], "raw": {}}
        for name, v in variants.items():
            qs = {"category": v["q"]["category"]}
            if v["scope"]:
                qs["scope"] = SCOPE_Q["scope"]
            ans = clf._answer(it["title"], qs)
            row["raw"][name] = {"category": ans["category"]["probabilities"],
                                "scope": ans["scope"]["probabilities"] if v["scope"] else None}
        rows.append(row)
    summary = {}
    for name, v in variants.items():
        for margin, gate in ((0.0, 0.5), (0.2, 0.5), (0.0, 0.8), (0.0, 0.95)):
            key = f"{name}|margen={margin}|puerta>={gate}"
            os_ok = os_n = in_keep = in_n = in_exact = 0
            fp = []
            for r in rows:
                pred = decide(name, r["raw"][name]["category"], r["raw"][name]["scope"], margin=margin, gate=gate)
                if r["expected"] == "out_of_scope":
                    os_n += 1
                    if pred == "indeterminado":
                        os_ok += 1
                    else:
                        fp.append({"title": r["title"], "pred": pred})
                else:
                    in_n += 1
                    if pred != "indeterminado":
                        in_keep += 1
                    if pred == r["expected"]:
                        in_exact += 1
            rec, ret = os_ok / os_n, in_keep / in_n
            summary[key] = {"outOfScopeRecall": {"num": os_ok, "den": os_n, "value": round(rec, 3)},
                            "inScopeRetained": {"num": in_keep, "den": in_n, "value": round(ret, 3)},
                            "inScopeExactCategory": {"num": in_exact, "den": in_n, "value": round(in_exact / in_n, 3)},
                            "score": round((rec + ret) / 2, 3), "outOfScopeMissed": fp}
    report = {"command": " ".join(sys.argv), "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "status": "exploratorio (lista propia pequeña, un solo autor; no es macro-F1 ni etiquetas humanas)",
              "model": clf.info(), "summary": summary, "rows": rows}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in summary.items():
        print(f"{k:52s} fuera:{v['outOfScopeRecall']['num']}/{v['outOfScopeRecall']['den']} "
              f"dentro-retenidos:{v['inScopeRetained']['num']}/{v['inScopeRetained']['den']} "
              f"categoría-exacta:{v['inScopeExactCategory']['num']}/{v['inScopeExactCategory']['den']} score={v['score']}")
    _ = CATEGORIES
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
