"""Recuperación: BM25 (rank-bm25) + RapidFuzz sobre el corpus (titulares/metadatos e indicadores)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rank_bm25 import BM25Plus
from rapidfuzz import fuzz, process

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


@dataclass
class Hit:
    doc: Doc
    bm25: float
    fuzzy: float
    relevance: float
    matched: list[str]
    coverage: float


class SearchIndex:
    def __init__(self, docs: list[Doc]):
        self.docs = docs
        self.tokens = [tokenize(d.text) for d in docs]
        self.vocab = sorted({t for toks in self.tokens for t in toks})
        self._bm25 = BM25Plus(self.tokens) if any(self.tokens) else None
        self._folded = [fold(d.text) for d in docs]

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
            best = process.extractOne(t, self.vocab, scorer=fuzz.ratio, score_cutoff=84) if self.vocab else None
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
        return hits[:limit], q, unmatched
