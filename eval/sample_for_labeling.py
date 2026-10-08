"""Genera la muestra para etiquetado manual de clasificacion (ciego: NO muestra predicciones).

Estratos:
  - uniform: muestra aleatoria simple (semilla fija) -> estima el desempeno global.
  - boost:   hasta K articulos por categoria predicha por Laya o por el baseline (para tener soporte en categorias raras).
Las metricas se reportan sobre `uniform` y sobre todo el conjunto (ver run_classification.py).

Uso: uv run --project pipeline python eval/sample_for_labeling.py --snapshot data/snapshots/<id> --n-uniform 120 --boost 8
Salida: eval/labels/cls_sample.jsonl  (articleId, title, domain, stratum; label vacio)
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from umbral_pipeline.util import read_jsonl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--extra-pred", type=Path, action="append", default=[], help="otros snapshots cuyas predicciones usar para el estrato boost")
    ap.add_argument("--n-uniform", type=int, default=120)
    ap.add_argument("--boost", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--out", type=Path, default=Path("eval/labels/cls_sample.jsonl"))
    a = ap.parse_args()
    if a.out.exists():
        raise SystemExit("La muestra existe y se conserva; usa --out con una ruta nueva explícita")

    arts = [x for x in read_jsonl(a.snapshot / "articles.jsonl") if x["dataOrigin"] == "real"]
    rng = random.Random(a.seed)
    uniform = rng.sample(arts, min(a.n_uniform, len(arts)))
    chosen = {x["articleId"]: "uniform" for x in uniform}
    by_id = {x["articleId"]: x for x in arts}
    preds: dict[str, list[str]] = {}
    for d in [a.snapshot, *a.extra_pred]:
        for p in read_jsonl(d / "predictions.jsonl"):
            preds.setdefault(p["category"], []).append(p["articleId"])
    for cat, ids in sorted(preds.items()):
        pool = sorted({i for i in ids if i in by_id and i not in chosen})
        rng.shuffle(pool)
        for i in pool[: a.boost]:
            chosen[i] = f"boost:{cat}"
    snapshot_id = json.loads((a.snapshot / "manifest.json").read_text(encoding="utf-8"))["snapshotId"]
    rows = []
    for aid, stratum in sorted(chosen.items()):
        art = by_id[aid]
        # A boost category is itself a prediction: keep it out of the reviewer
        # form, while retaining whether the row belongs to the uniform sample.
        rows.append({"articleId": aid, "snapshotId": snapshot_id, "title": art["title"],
                     "sourceUrl": art["canonicalUrl"], "domain": art["domain"],
                     "stratum": "boost" if stratum.startswith("boost:") else stratum,
                     "label": None, "geo": None, "labeler": None, "labelMethod": "human_pending"})
    rng.shuffle(rows)  # orden aleatorio: el etiquetador no infiere el estrato
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} articulos a etiquetar -> {a.out} (uniform={sum(1 for r in rows if r['stratum']=='uniform')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
