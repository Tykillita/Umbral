"""Recuperación: BM25 (rank-bm25) + RapidFuzz sobre el corpus (titulares/metadatos e indicadores)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rank_bm25 import BM25Plus
from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

STOPWORDS = {
    "a", "al", "algo", "algun", "alguna", "algunas", "algunos", "ante", "como", "con", "cual", "cuales", "cuando",
    "de", "del", "desde", "donde", "dos", "el", "ella", "ellos", "en", "entre", "era", "es", "esa", "ese", "eso",
    "esta", "estan", "este", "esto", "fue", "ha", "han", "hay", "hasta", "la", "las", "le", "les", "lo", "los",
    "mas", "me", "muy", "no", "nos", "o", "para", "pero", "por", "porque", "que", "quien", "quienes", "se", "ser",
    "si", "sin", "sobre", "son", "su", "sus", "te", "un", "una", "uno", "unos", "unas", "y", "ya",
    # palabras de consulta que no son contenido
    "dime", "dame", "noticia", "noticias", "informacion", "sabe", "saber", "sabes", "pasa", "paso", "ocurrio",
    "ocurre", "reporta", "reporto", "reportan", "hubo", "existe", "existen", "tema", "temas", "cuanto", "cuantos",
    "cuanta", "cuantas", "favor", "puedes", "podrias", "quiero", "necesito", "hoy", "ultimo", "ultima",
    "ultimos", "ultimas", "reciente", "recientes", "cuenta",
}


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def stem(tok: str) -> str:
    """Stemming ligero en español (plurales y sufijos frecuentes)."""
    if len(tok) <= 4 or tok.isdigit():
        return tok
    for suf, rep in (("ciones", "cion"), ("siones", "sion"), ("idades", "idad"), ("ces", "z"), ("es", ""), ("s", "")):
        if tok.endswith(suf) and len(tok) - len(suf) + len(rep) >= 4:
            return tok[: len(tok) - len(suf)] + rep
    return tok


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def tokenize(text: str, *, drop_stop: bool = True) -> list[str]:
    toks = _TOKEN_RE.findall(fold(text))
    if drop_stop:
        toks = [t for t in toks if t not in STOPWORDS and len(t) > 1]
    return [stem(t) for t in toks]


@dataclass
class Doc:
    doc_id: str
    kind: str  # articulo | indicador
    text: str
    cluster_id: str | None = None
    semantic_eligible: bool = True


@dataclass
class Hit:
    doc: Doc
    bm25: float
    fuzzy: float
    relevance: float
    matched: list[str]
    coverage: float
    semantic_similarity: float | None = None
    semantic_anchor_id: str | None = None
    rrf_score: float | None = None

    @property
    def supported(self) -> bool:
        """Coincidencia literal suficiente o vecino de un ancla literal suficiente; son pruebas distintas."""
        return self.coverage >= 0.5 or (self.semantic_similarity is not None and self.semantic_anchor_id is not None)


class SearchIndex:
    def __init__(self, docs: list[Doc], *, neighbors: dict[str, list[tuple[str, float]]] | None = None):
        self.docs = docs
        self.tokens = [tokenize(d.text) for d in docs]
        self.vocab = sorted({t for toks in self.tokens for t in toks})
        self._bm25 = BM25Plus(self.tokens) if any(self.tokens) else None
        self._folded = [fold(d.text) for d in docs]
        self.neighbors = neighbors or {}
        self._positions = {d.doc_id: i for i, d in enumerate(docs)}

    def expand_query(self, text: str) -> tuple[list[str], list[str]]:
        """Tokens de consulta; los ausentes del vocabulario se corrigen con RapidFuzz si hay un vecino cercano."""
        toks = tokenize(text)
        out: list[str] = []
        unmatched: list[str] = []
        vocab_set = set(self.vocab)
        for t in toks:
            if t in vocab_set or t.isdigit():
                out.append(t)
                continue
            candidates = [word for word in self.vocab if word[:1] == t[:1] and abs(len(word) - len(t)) <= 1]
            best = process.extractOne(t, candidates, scorer=fuzz.ratio, score_cutoff=84) if candidates else None
            if best and Levenshtein.distance(t, best[0]) > 1:
                best = None
            if best:
                out.append(best[0])
            else:
                out.append(t)
                unmatched.append(t)
        return out, unmatched

    def search(self, text: str, *, limit: int = 5, restrict: set[str] | None = None) -> tuple[list[Hit], list[str], list[str]]:
        q, unmatched = self.expand_query(text)
        if not q or self._bm25 is None:
            return [], q, unmatched
        scores = self._bm25.get_scores(q)
        qfold = fold(text)
        qset = set(q)
        hits: list[Hit] = []
        top = max(scores) if len(scores) else 0.0
        for i, d in enumerate(self.docs):
            if restrict is not None and d.doc_id not in restrict:
                continue
            matched = sorted(qset & set(self.tokens[i]))
            if not matched:
                continue
            bm = float(scores[i])
            fz = fuzz.token_set_ratio(qfold, self._folded[i]) / 100.0
            bm_n = bm / top if top > 0 else 0.0
            cov = len(matched) / len(qset) if qset else 0.0
            hits.append(Hit(d, bm, fz, round(0.65 * bm_n + 0.35 * fz, 4), matched, cov))
        hits.sort(key=lambda h: (-h.relevance, h.doc.doc_id))
        hits = self._semantic_fuse(hits[:max(limit, 8)], qset, restrict) if self.neighbors else hits
        return hits[:limit], q, unmatched

    def _semantic_fuse(self, hits: list[Hit], qset: set[str], restrict: set[str] | None) -> list[Hit]:
        """RRF k=60 de la lista léxica y los vecinos de hasta tres anclas con cobertura literal >= 0,5."""
        if not hits:
            return hits
        articles = [hit for hit in hits if hit.doc.kind == "articulo" and hit.doc.semantic_eligible]
        best_coverage = max((hit.coverage for hit in articles), default=0)
        anchors = [hit for hit in articles if hit.coverage >= max(0.5, best_coverage - 1e-9)][:3]
        semantic: dict[str, tuple[float, str]] = {}
        for anchor in anchors:
            for nid, similarity in self.neighbors.get(anchor.doc.doc_id, []):
                if nid not in self._positions or (restrict is not None and nid not in restrict):
                    continue
                if similarity > semantic.get(nid, (0.0, ""))[0]:
                    semantic[nid] = (similarity, anchor.doc.doc_id)
        if not semantic:
            return hits
        by_id = {h.doc.doc_id: h for h in hits}
        scores = {h.doc.doc_id: 1 / (60 + rank) for rank, h in enumerate(hits, 1)}
        for rank, nid in enumerate(sorted(semantic, key=lambda key: (-semantic[key][0], key)), 1):
            scores[nid] = scores.get(nid, 0.0) + 1 / (60 + rank)
            similarity, anchor_id = semantic[nid]
            hit = by_id.get(nid)
            if hit is None:
                pos = self._positions[nid]
                matched = sorted(qset & set(self.tokens[pos]))
                hit = Hit(self.docs[pos], 0.0, 0.0, similarity, matched, len(matched) / len(qset) if qset else 0.0)
                by_id[nid] = hit
            hit.semantic_similarity, hit.semantic_anchor_id = similarity, anchor_id
        for nid, hit in by_id.items():
            hit.rrf_score = scores[nid]
        return sorted(by_id.values(), key=lambda hit: (-scores[hit.doc.doc_id], hit.doc.doc_id))
