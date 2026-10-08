"""Genera las hojas de etiquetado humano (CSV + JSONL) con carga razonable para una persona, e importa los juicios.

  # crear muestras para un snapshot (NUNCA sobrescribe: falla si el archivo ya existe)
  pipeline/.venv/Scripts/python.exe eval/make_label_sheets.py make --snapshot data/snapshots/<id> \
        --claims eval/labels/claims_sample.<id>.jsonl

  # tras rellenar la columna juicio_humano de los CSV: convertir a los JSONL que leen run_classification.py / run_clustering_eval.py
  pipeline/.venv/Scripts/python.exe eval/make_label_sheets.py import --snapshot data/snapshots/<id> --labeler "Nombre"

Reglas: no inventa juicios (las columnas quedan vacías); las muestras no contienen las consultas reservadas (esas viven fuera del repo
y no son artículos); los archivos se nombran con el id del snapshot para no pisar etiquetas de otro snapshot.
Tamaños: <=150 artículos (estratificados por categoría predicha x fuente + 40 uniformes), <=64 pares, <=32 afirmaciones.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz
from umbral_pipeline.cluster import norm_title, tokens
from umbral_pipeline.config import CATEGORIES, INDETERMINATE
from umbral_pipeline.util import read_jsonl, sha256_hex

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "eval" / "labels"
SEED = 20261007
COLS = ["id", "texto", "predicción", "juicio_humano", "comentario"]
CAT_VALUES = [*CATEGORIES, INDETERMINATE]
PAIR_VALUES = {"si": True, "sí": True, "no": False}
CLAIM_VALUES = {"respaldada", "no_respaldada", "cita_incorrecta"}


def _excl_write(path: Path, writer) -> None:
    try:
        fh = path.open("x", encoding="utf-8-sig" if path.suffix == ".csv" else "utf-8", newline="" if path.suffix == ".csv" else "\n")
    except FileExistsError:
        raise SystemExit(f"{path} ya existe: no se sobrescribe (puede contener juicios humanos). Bórralo a mano si es intencional.") from None
    with fh:
        writer(fh)


def write_csv(path: Path, rows: list[list[str]]) -> None:
    def w(fh):
        cw = csv.writer(fh, lineterminator="\r\n")
        cw.writerow(COLS)
        cw.writerows(rows)

    _excl_write(path, w)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    _excl_write(path, lambda fh: [fh.write(json.dumps(r, ensure_ascii=False) + "\n") for r in rows])


# ---------------- artículos ----------------
def sample_articles(snap: Path, rng: random.Random, cap: int = 150) -> list[dict]:
    arts = {a["articleId"]: a for a in read_jsonl(snap / "articles.jsonl") if a["dataOrigin"] == "real"}
    preds = {p["articleId"]: p for p in read_jsonl(snap / "predictions.jsonl")}
    cluster_of = {}
    for c in read_jsonl(snap / "clusters.jsonl"):
        for m in c["memberArticleIds"]:
            cluster_of[m] = c["clusterId"]
    # un artículo por cluster (el representante en orden estable) para no pedir juzgar copias
    seen_clusters: set[str] = set()
    pool = []
    for aid in sorted(arts, key=lambda x: sha256_hex(x)):
        cl = cluster_of.get(aid, aid)
        if cl in seen_clusters:
            continue
        seen_clusters.add(cl)
        pool.append(aid)
    src = lambda aid: "TVN" if arts[aid]["isTvn"] else "GDELT"
    chosen: dict[str, str] = {}

    def take(cands: list[str], k: int, stratum: str) -> None:
        cands = [c for c in cands if c not in chosen]
        rng.shuffle(cands)
        for c in cands[:k]:
            chosen[c] = stratum

    for s in ("TVN", "GDELT"):
        take([a for a in pool if src(a) == s], 20, "uniforme")
    for cat in CAT_VALUES:
        quotas = {"TVN": 10, "GDELT": 10} if cat == INDETERMINATE else {"TVN": 6, "GDELT": 9}
        for s, k in quotas.items():
            take([a for a in pool if src(a) == s and preds[a]["category"] == cat], k, f"{cat}|{s}")
    ids = list(chosen)
    if len(ids) > cap:  # recorta primero lo estratificado de indeterminado GDELT/TVN
        drop = [i for i in ids if chosen[i].startswith(INDETERMINATE)][: len(ids) - cap]
        ids = [i for i in ids if i not in drop]
    rng.shuffle(ids)
    return [{"id": aid, "articleId": aid, "title": arts[aid]["title"], "domain": arts[aid]["domain"], "source": src(aid),
             "stratum": chosen[aid], "predictedCategory": preds[aid]["category"], "predictedGeo": preds[aid]["geoRelevance"],
             "label": None, "labeler": None, "labelMethod": "human_pending"} for aid in ids]


# ---------------- pares ----------------
def sample_pairs(snap: Path, rng: random.Random, cap: int = 64) -> list[dict]:
    arts = {a["articleId"]: a for a in read_jsonl(snap / "articles.jsonl") if a["dataOrigin"] == "real"}
    clusters = list(read_jsonl(snap / "clusters.jsonl"))
    cluster_of = {m: c["clusterId"] for c in clusters for m in c["memberArticleIds"]}
    rows: dict[frozenset, dict] = {}

    def add(a: str, b: str, stratum: str) -> bool:
        if a == b or frozenset((a, b)) in rows or len(rows) >= cap:
            return False
        x, y = sorted((a, b))
        rows[frozenset((a, b))] = {
            "id": "pair_" + sha256_hex(x + y)[:12], "a": x, "b": y, "stratum": stratum,
            "titleA": arts[x]["title"], "domainA": arts[x]["domain"], "titleB": arts[y]["title"], "domainB": arts[y]["domain"],
            "predictedSameCluster": cluster_of.get(x) == cluster_of.get(y),
            "sameEvent": None, "labeler": None, "labelMethod": "human_pending"}
        return True

    def cross_domain_pairs(c: dict) -> list[tuple[str, str]]:
        ms = c["memberArticleIds"]
        out = [(a, b) for i, a in enumerate(ms) for b in ms[i + 1:] if arts[a]["domain"] != arts[b]["domain"]]
        rng.shuffle(out)
        return out

    # A: clusters con >=2 procedencias independientes (hasta 24)
    n = 0
    for c in sorted((c for c in clusters if c["independentProvenanceCount"] >= 2), key=lambda c: -c["independentProvenanceCount"]):
        for a, b in cross_domain_pairs(c)[:4]:
            if n < 24 and add(a, b, "agrupado_procedencias_independientes"):
                n += 1
    # C: ambiguos (candidatos no unidos), hasta 16
    n = 0
    for c in clusters:
        for cand in c.get("ambiguousCandidateIds", []):
            if cand in arts and n < 16 and add(c["memberArticleIds"][0], cand, "ambiguo_no_unido"):
                n += 1
    # candidatos BM25 en zona gris/baja que el sistema NO unió (el recall se mide sobre candidatos)
    ids = list(arts)
    toks = [tokens(arts[i]["title"]) or ["_"] for i in ids]
    normed = [norm_title(arts[i]["title"]) for i in ids]
    bm25 = BM25Okapi(toks)
    gray, low = [], []
    idx_sample = list(range(len(ids)))
    rng.shuffle(idx_sample)
    for i in idx_sample[:400]:
        if len(toks[i]) < 4:
            continue
        sc = bm25.get_scores(toks[i])
        for j in sorted(range(len(ids)), key=lambda k: -sc[k])[:6]:
            if j == i or cluster_of.get(ids[i]) == cluster_of.get(ids[j]):
                continue
            s = fuzz.token_sort_ratio(normed[i], normed[j])
            (gray if 70 <= s < 90 else low if 50 <= s < 70 else []).append((ids[i], ids[j]))
    rng.shuffle(gray)
    rng.shuffle(low)
    for a, b in gray:
        if n < 16 and add(a, b, "candidato_bm25_no_unido"):
            n += 1
    # B: copias agrupadas con 1 procedencia (precisión de title_exact/fuzzy), hasta 16
    n = 0
    singles = [c for c in clusters if c["size"] >= 2 and c["independentProvenanceCount"] < 2]
    rng.shuffle(singles)
    for c in singles:
        for a, b in cross_domain_pairs(c)[:1]:
            if n < 16 and add(a, b, "agrupado_copia_una_procedencia"):
                n += 1
    # D: negativos de control (hasta 8)
    n = 0
    for a, b in low:
        if n < 8 and add(a, b, "control_negativo_similitud_baja"):
            n += 1
    out = list(rows.values())
    rng.shuffle(out)
    return out


# ---------------- afirmaciones ----------------
def sample_claims(path: Path, rng: random.Random, cap: int = 32) -> list[dict]:
    rows = list(read_jsonl(path))
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_topic[r["topicId"]].append(r)
    picked: list[dict] = []
    topics = list(by_topic)
    rng.shuffle(topics)
    depth = 0
    while len(picked) < cap and any(len(by_topic[t]) > depth for t in topics):
        for t in topics:
            if len(by_topic[t]) > depth and len(picked) < cap:
                picked.append(by_topic[t][depth])
        depth += 1
    for r in picked:
        r.setdefault("id", f"{r['topicId']}:{r['claimId']}")
    return picked


def cmd_make(a: argparse.Namespace) -> int:
    snap = a.snapshot
    sid = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))["snapshotId"]
    rng = random.Random(SEED)
    arts = sample_articles(snap, rng)
    pairs = sample_pairs(snap, rng)
    write_jsonl(LABELS / f"cls_sample.{sid}.jsonl", arts)
    write_csv(LABELS / f"clasificacion.{sid}.csv", [[r["id"], r["title"], r["predictedCategory"], "", ""] for r in arts])
    write_jsonl(LABELS / f"pairs_sample.{sid}.jsonl", pairs)
    write_csv(LABELS / f"pares.{sid}.csv", [[r["id"], f"A [{r['domainA']}]: {r['titleA']}  ||  B [{r['domainB']}]: {r['titleB']}",
                                              "mismo grupo" if r["predictedSameCluster"] else "grupos distintos", "", ""] for r in pairs])
    msg = [f"artículos {len(arts)} (TVN {sum(r['source'] == 'TVN' for r in arts)}, GDELT {sum(r['source'] == 'GDELT' for r in arts)})",
           f"pares {len(pairs)}"]
    if a.claims:
        claims = sample_claims(a.claims, rng)
        write_jsonl(LABELS / f"claims_review.{sid}.jsonl", claims)
        write_csv(LABELS / f"afirmaciones.{sid}.csv", [[r["id"], r["text"] + "  [cita: " + "; ".join(
            f"{c['evidenceId']}/{c.get('field')}" for c in r.get("citations", [])) + "]", "borrador de plantilla (" + r["type"] + ")", "", ""]
            for r in claims])
        msg.append(f"afirmaciones {len(claims)}")
    print("; ".join(msg), f"-> {LABELS}")
    return 0


def _read_csv(path: Path) -> dict[str, tuple[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return {r["id"]: (r["juicio_humano"].strip().lower(), r["comentario"].strip()) for r in csv.DictReader(fh)}


def cmd_import(a: argparse.Namespace) -> int:
    manifest = json.loads((a.snapshot / "manifest.json").read_text(encoding="utf-8"))
    sid = manifest["snapshotId"]
    provenance = {"snapshotId": sid, "articlesSha256": manifest["files"]["articles.jsonl"]["sha256"]}
    out_dir = LABELS
    done = {}
    # clasificación
    p = LABELS / f"clasificacion.{sid}.csv"
    if p.exists():
        j = _read_csv(p)
        rows, bad = [], []
        for r in read_jsonl(LABELS / f"cls_sample.{sid}.jsonl"):
            v, note = j.get(r["id"], ("", ""))
            if not v:
                continue
            if v not in CAT_VALUES:
                bad.append((r["id"], v))
                continue
            rows.append({**provenance, "articleId": r["articleId"], "label": v, "geo": None, "stratum": "uniform" if r["stratum"] == "uniforme" else r["stratum"],
                         "labeler": a.labeler, "labelMethod": "human", "notes": note})
        write_jsonl_over(out_dir / f"cls_labels.{sid}.jsonl", rows)
        done["clasificacion"] = (len(rows), bad)
    p = LABELS / f"pares.{sid}.csv"
    if p.exists():
        j = _read_csv(p)
        rows, bad = [], []
        for r in read_jsonl(LABELS / f"pairs_sample.{sid}.jsonl"):
            v, note = j.get(r["id"], ("", ""))
            if not v:
                continue
            if v not in PAIR_VALUES:
                bad.append((r["id"], v))
                continue
            rows.append({**provenance, "pairId": r["id"], "a": r["a"], "b": r["b"], "stratum": r["stratum"], "sameEvent": PAIR_VALUES[v],
                         "labeler": a.labeler, "labelMethod": "human", "notes": note})
        write_jsonl_over(out_dir / f"pairs_labels.{sid}.jsonl", rows)
        done["pares"] = (len(rows), bad)
    p = LABELS / f"afirmaciones.{sid}.csv"
    if p.exists():
        j = _read_csv(p)
        rows, bad = [], []
        for r in read_jsonl(LABELS / f"claims_review.{sid}.jsonl"):
            v, note = j.get(r["id"], ("", ""))
            if not v:
                continue
            if v not in CLAIM_VALUES:
                bad.append((r["id"], v))
                continue
            rows.append({**r, "supported": v == "respaldada", "citationCorrect": v == "respaldada",
                         "labeler": a.labeler, "labelMethod": "human", "notes": note, "judgment": v})
        write_jsonl_over(out_dir / f"claims_labels.{sid}.jsonl", rows)
        done["afirmaciones"] = (len(rows), bad)
    for k, (n, bad) in done.items():
        print(f"{k}: {n} juicios importados; valores no válidos ignorados: {bad}")
    return 0


def write_jsonl_over(path: Path, rows: list[dict]) -> None:
    """Los JSONL derivados SÍ se regeneran desde los CSV (la fuente de verdad humana)."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--snapshot", type=Path, required=True)
    m.add_argument("--claims", type=Path, default=None)
    i = sub.add_parser("import")
    i.add_argument("--snapshot", type=Path, required=True)
    i.add_argument("--labeler", required=True)
    a = ap.parse_args()
    return cmd_make(a) if a.cmd == "make" else cmd_import(a)


if __name__ == "__main__":
    sys.exit(main())
