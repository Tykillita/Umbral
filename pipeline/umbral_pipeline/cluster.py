"""Agrupacion de duplicados / evento (PDF etapa 2; T02, T03, CU-03).

1) URL canonica: ya colapsada en validate (merge_url_duplicates).
2) Titular normalizado identico -> enlace `title_exact`.
3) Similitud de titulares (RapidFuzz token_sort_ratio) >= STRONG -> `title_fuzzy`.
4) Zona gris [GRAY, STRONG): candidatos seleccionados por BM25 (rank-bm25) y RapidFuzz; si hay desempatador
   (Laya) se consulta; si no, NO se une (conservador) y se marca `ambiguous` en el cluster con los candidatos.
Una agencia replicada (mismo texto, distintos medios) cuenta como una sola procedencia independiente.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz

from .config import INDETERMINATE
from .util import fold_text, iso_z, parse_dt, sha256_hex

STRONG = 88.0
GRAY = 72.0
REPLICA = 95.0  # titulares casi identicos entre medios distintos => misma procedencia
MAX_DAYS_BETWEEN = 10
RECIRC_DAYS = 14
MIN_TOKENS = 4
CONTAIN_MIN_TOKENS = 5  # un titular contenido en otro cuenta como copia solo si tiene >= 5 palabras
BM25_TOPK = 8

_STOP = set(
    "el la los las un una unos unas de del al y e o u a en por para con sin sobre entre que se su sus lo es son fue ser "
    "ha han hay como mas pero si no ya tras ante desde hasta the of and in to for on at by with from is are was".split()
)
_SUFFIX_RX = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,25}$")


def norm_title(title: str) -> str:
    t = fold_text(title)
    t = _SUFFIX_RX.sub("", t)
    t = re.sub(r"[^a-z0-9% ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(title: str) -> list[str]:
    return [w for w in norm_title(title).split() if w not in _STOP and len(w) > 1]


_YEAR_RX = re.compile(r"^(?:19|20)\d{2}$")


def numbers_in(title: str) -> set[str]:
    """Cifras del titular (sin anos): '4,5' y '4.5' se igualan; los anos 19xx/20xx se excluyen."""
    out = set()
    for n in re.findall(r"\d+(?:[.,]\d+)?", title):
        if _YEAR_RX.match(n):
            continue
        out.add(n.replace(",", "."))
    return out


def masked_tokens(title: str) -> set[str]:
    return {w for w in tokens(title) if not re.fullmatch(r"\d+(?:[.,]\d+)?", w) or _YEAR_RX.match(w)}


def numbers_conflict(na: set[str], nb: set[str]) -> bool:
    """Cifras en conflicto: ambas tienen cifras y ninguna contiene a la otra.

    {33, 49} frente a {33} NO es conflicto (el segundo titular simplemente omite una cifra); {4.5} frente a {2.8} sí lo es.
    """
    return bool(na) and bool(nb) and not (na <= nb or nb <= na)


def contradiction_pairs(articles: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Candidatos a contradiccion ENTRE clusters: mismo tema (>=4 tokens comunes sin cifras) pero cifras distintas.

    Es una heuristica de CANDIDATOS para revision humana (T05); no afirma que haya contradiccion.
    """
    cand = [a for a in articles if numbers_in(a["title"])]
    peers: dict[str, set[str]] = defaultdict(set)
    for n, a in enumerate(cand):
        ta, na = masked_tokens(a["title"]), numbers_in(a["title"])
        for b in cand[n + 1 :]:
            if _days_apart(a, b) > 14:
                continue
            nb = numbers_in(b["title"])
            if not numbers_conflict(na, nb):
                continue
            tb = masked_tokens(b["title"])
            if len(ta & tb) >= 4 and len(ta & tb) / len(ta | tb) >= 0.35:
                peers[a["articleId"]].add(b["articleId"])
                peers[b["articleId"]].add(a["articleId"])
    return peers


class UF:
    def __init__(self, items: list[str]) -> None:
        self.p = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _days_apart(a: dict[str, Any], b: dict[str, Any]) -> float:
    da = parse_dt(a["effectiveDate"])
    db = parse_dt(b["effectiveDate"])
    if da is None or db is None:
        return 0.0
    return abs((da - db).total_seconds()) / 86400


# tiebreak(a, b) -> (same_event: bool, score: float) | None si no hay desempatador
Tiebreak = Callable[[dict[str, Any], dict[str, Any]], tuple[bool, float] | None]


def build_clusters(
    articles: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    cutoff: datetime,
    tiebreak: Tiebreak | None = None,
    *,
    provisional: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_id = {a["articleId"]: a for a in articles}
    pred_by = {p["articleId"]: p for p in predictions}
    ids = [a["articleId"] for a in articles]
    uf = UF(ids)
    links: list[dict[str, Any]] = []
    gray_pairs: dict[tuple[str, str], float] = {}
    stats = {"title_exact": 0, "title_fuzzy": 0, "bm25_laya": 0, "gray_unresolved": 0, "tiebreak_calls": 0}

    normed = {i: norm_title(by_id[i]["title"]) for i in ids}
    toks = {i: tokens(by_id[i]["title"]) for i in ids}

    # (2) titular exacto
    by_norm: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        if len(toks[i]) >= MIN_TOKENS:
            by_norm[normed[i]].append(i)
    for group in by_norm.values():
        for other in group[1:]:
            uf.union(group[0], other)
            links.append({"a": group[0], "b": other, "method": "title_exact", "score": 100.0})
            stats["title_exact"] += 1

    # (3)/(4) candidatos por BM25 + RapidFuzz
    corpus = [toks[i] if toks[i] else ["_"] for i in ids]
    bm25 = BM25Okapi(corpus)
    seen: set[tuple[str, str]] = set()
    for i in ids:
        if len(toks[i]) < MIN_TOKENS:
            continue
        scores = bm25.get_scores(toks[i])
        order = sorted(range(len(ids)), key=lambda n: -scores[n])[: BM25_TOPK + 1]
        for n in order:
            j = ids[n]
            if j == i or len(toks[j]) < MIN_TOKENS:
                continue
            pair = (min(i, j), max(i, j))
            if pair in seen:
                continue
            seen.add(pair)
            a, b = by_id[i], by_id[j]
            if uf.find(i) == uf.find(j):
                continue
            sim = fuzz.token_sort_ratio(normed[i], normed[j])
            if sim < GRAY:
                continue
            if _days_apart(a, b) > MAX_DAYS_BETWEEN and sim < 97:
                continue
            jac = len(set(toks[i]) & set(toks[j])) / len(set(toks[i]) | set(toks[j]))
            if sim >= STRONG and jac >= 0.5:
                uf.union(i, j)
                links.append({"a": pair[0], "b": pair[1], "method": "title_fuzzy", "score": round(sim, 2)})
                stats["title_fuzzy"] += 1
            elif jac >= 0.4:
                gray_pairs[pair] = sim

    # (4) zona gris con desempate
    ambiguous_candidates: dict[str, set[str]] = defaultdict(set)
    for (i, j), _sim in sorted(gray_pairs.items()):
        if uf.find(i) == uf.find(j):
            continue
        res = tiebreak(by_id[i], by_id[j]) if tiebreak else None
        if res is None:
            stats["gray_unresolved"] += 1
            ambiguous_candidates[i].add(j)
            ambiguous_candidates[j].add(i)
            continue
        stats["tiebreak_calls"] += 1
        same, score = res
        if same:
            uf.union(i, j)
            links.append({"a": i, "b": j, "method": "bm25_laya", "score": round(score, 4)})
            stats["bm25_laya"] += 1
        else:
            ambiguous_candidates[i].add(j)
            ambiguous_candidates[j].add(i)

    # agrupar
    groups: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        groups[uf.find(i)].append(i)

    cutoff_dt = cutoff
    peers = contradiction_pairs(articles)
    clusters = []
    for members in groups.values():
        members.sort(key=lambda m: (by_id[m]["effectiveDate"], m))
        arts = [by_id[m] for m in members]
        mset = set(members)
        cluster_links = [lk for lk in links if lk["a"] in mset and lk["b"] in mset]
        pubs = [parse_dt(a["publishedAt"]) for a in arts if a["publishedAt"]]
        pubs = [p for p in pubs if p]
        rep = None
        for a in arts:
            if a["publishedAt"]:
                if rep is None or a["publishedAt"] < rep["publishedAt"]:
                    rep = a
        if rep is None:
            rep = sorted(arts, key=lambda a: a["articleId"])[0]

        prov_keys = sorted({a["provenance"]["key"] for a in arts})
        independent = independent_provenance(arts, normed)
        # categoria: voto ponderado por probabilidad
        votes: dict[str, float] = defaultdict(float)
        for a in arts:
            p = pred_by.get(a["articleId"])
            if p and p["category"] != INDETERMINATE:
                votes[p["category"]] += p["probability"]
        category = max(votes, key=lambda c: (votes[c], c)) if votes else INDETERMINATE

        # recirculacion: publicacion original mucho mas antigua que la deteccion/extraccion
        reason = None
        for a in arts:
            pub = parse_dt(a["publishedAt"])
            obs = parse_dt(a["detectedAt"]) or parse_dt(a["extractedAt"]) or cutoff_dt
            if pub and (obs - pub) > timedelta(days=RECIRC_DAYS):
                reason = (
                    f"detectedAt/extractedAt {iso_z(obs)[:10]} vs publishedAt {iso_z(pub)[:10]} "
                    f"({(obs - pub).days} d; base {a['publishedAtBasis']})"
                )
                break
        nums = [numbers_in(a["title"]) for a in arts]
        contradiction = len(arts) > 1 and any(numbers_conflict(x, y) for i, x in enumerate(nums) for y in nums[i + 1 :])
        peer_ids = sorted({p for m in members for p in peers.get(m, ()) if p not in mset})
        contradiction = bool(contradiction or peer_ids)

        clusters.append(
            {
                "clusterId": "evt_" + sha256_hex("|".join(sorted(members)))[:16],
                "memberArticleIds": members,
                "representativeArticleId": rep["articleId"],
                "size": len(members),
                "category": category,
                "provenanceKeys": prov_keys,
                "independentProvenanceCount": independent,
                "outletCount": len({a["domain"] for a in arts}),
                "links": cluster_links,
                "ambiguous": any(m in ambiguous_candidates for m in members),
                "ambiguousCandidateIds": sorted({c for m in members for c in ambiguous_candidates.get(m, ()) if c not in mset}),
                "firstPublishedAt": iso_z(min(pubs)) if pubs else None,
                "lastPublishedAt": iso_z(max(pubs)) if pubs else None,
                "originalPublishedAt": iso_z(min(pubs)) if pubs else None,
                "isRecirculation": reason is not None,
                "recirculationReason": reason,
                "hasContradictionCandidate": bool(contradiction),
                "contradictionCandidateIds": peer_ids,
                "dataOrigin": "fixture" if all(a["dataOrigin"] == "fixture" for a in arts) else "real",
                "provisional": provisional,
            }
        )
    clusters.sort(key=lambda c: (c["memberArticleIds"][0] if c["memberArticleIds"] else "", c["clusterId"]))
    return clusters, stats


def independent_provenance(arts: list[dict[str, Any]], normed: dict[str, str]) -> int:
    """Procedencias independientes: misma clave de procedencia => 1; titulares casi identicos entre medios
    distintos (copias de agencia/replicas) => 1. Nunca cuenta mas que la cantidad de claves distintas."""
    if not arts:
        return 0
    uf = UF([a["articleId"] for a in arts])
    first_by_key: dict[str, str] = {}
    for a in arts:
        k = a["provenance"]["key"]
        if k in first_by_key and not k.startswith("unknown:"):
            uf.union(first_by_key[k], a["articleId"])
        else:
            first_by_key.setdefault(k, a["articleId"])
    for n, a in enumerate(arts):
        for b in arts[n + 1 :]:
            ta, tb = normed.get(a["articleId"], ""), normed.get(b["articleId"], "")
            if fuzz.token_sort_ratio(ta, tb) >= REPLICA:
                uf.union(a["articleId"], b["articleId"])
            elif fuzz.token_set_ratio(ta, tb) >= 100 and min(len(ta.split()), len(tb.split())) >= CONTAIN_MIN_TOKENS:
                # un titular contenido íntegro en el otro (prefijo/sufijo añadido por el medio): copia, no corroboración
                uf.union(a["articleId"], b["articleId"])
    return len({uf.find(a["articleId"]) for a in arts})
