"""Muestra de PARES de titulares para etiquetar «¿mismo evento?» (ciego: no muestra decisiones del sistema).

Candidatos: vecinos BM25 (top-8) de cada articulo; se estratifican por similitud RapidFuzz (token_sort_ratio):
  alta >=88 | gris 72-88 | baja 55-72 | negativos aleatorios (<40, sin relacion).
Sesgo declarado: es una muestra de pares CANDIDATOS (no de todos los pares), por lo que el recall medido es el recall
sobre pares candidatos etiquetados, no sobre el universo completo.

Uso: uv run --project pipeline python eval/sample_pairs.py --snapshot data/snapshots/<id> --per-stratum 30
Salida: eval/labels/pairs_sample.jsonl  (pairId, a, b, titleA, titleB, stratum, sameEvent=null)
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz
from umbral_pipeline.cluster import norm_title, tokens
from umbral_pipeline.util import read_jsonl, sha256_hex


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--per-stratum", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--out", type=Path, default=Path("eval/labels/pairs_sample.jsonl"))
    a = ap.parse_args()
    if a.out.exists():
        raise SystemExit("La muestra existe y se conserva; usa --out con una ruta nueva explícita")

    arts = [x for x in read_jsonl(a.snapshot / "articles.jsonl") if x["dataOrigin"] == "real"]
    ids = [x["articleId"] for x in arts]
    toks = [tokens(x["title"]) or ["_"] for x in arts]
    normed = [norm_title(x["title"]) for x in arts]
    bm25 = BM25Okapi(toks)
    seen: set[tuple[int, int]] = set()
    strata: dict[str, list[tuple[int, int, float]]] = {"alta": [], "gris": [], "baja": [], "negativo": []}
    for i, t in enumerate(toks):
        if len(t) < 4:
            continue
        scores = bm25.get_scores(t)
        for j in sorted(range(len(arts)), key=lambda n: -scores[n])[:9]:
            if j == i or (min(i, j), max(i, j)) in seen:
                continue
            seen.add((min(i, j), max(i, j)))
            s = fuzz.token_sort_ratio(normed[i], normed[j])
            key = "alta" if s >= 88 else "gris" if s >= 72 else "baja" if s >= 55 else None
            if key:
                strata[key].append((i, j, s))
    rng = random.Random(a.seed)
    n = len(arts)
    attempts = 0
    # Sparse/small corpora may contain fewer than 400 possible negative pairs.
    # Bound attempts to prevent an endless loop after exhausting the pool.
    while len(strata["negativo"]) < 400 and n > 2 and attempts < max(4000, n * 50):
        attempts += 1
        i, j = rng.sample(range(n), 2)
        if (min(i, j), max(i, j)) in seen:
            continue
        s = fuzz.token_sort_ratio(normed[i], normed[j])
        if s < 40:
            strata["negativo"].append((i, j, s))
            seen.add((min(i, j), max(i, j)))
    snapshot_id = json.loads((a.snapshot / "manifest.json").read_text(encoding="utf-8"))["snapshotId"]
    rows = []
    for name, pairs in strata.items():
        rng.shuffle(pairs)
        for i, j, s in pairs[: a.per_stratum]:
            x, y = sorted((ids[i], ids[j]))
            rows.append({"pairId": "pair_" + sha256_hex(x + y)[:12], "snapshotId": snapshot_id, "a": x, "b": y,
                         "titleA": arts[ids.index(x)]["title"], "titleB": arts[ids.index(y)]["title"],
                         "stratum": name, "sameEvent": None, "labeler": None, "labelMethod": "human_pending"})
        print(f"estrato {name}: {len(pairs)} candidatos, {min(a.per_stratum, len(pairs))} muestreados")
    rng.shuffle(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} pares -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
