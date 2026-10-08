"""Baseline lexico documentado (PDF 8: comparar contra baseline simple). NO es Laya.

Puntaje por categoria = numero de terminos distintos del lexico presentes en el titular (texto plegado).
Probabilidad = (score + alpha) / (suma + alpha*K) con alpha=0.25 (suavizado; NO esta calibrada).
`indeterminado` si no hay coincidencias o si el margen entre las dos mejores categorias es 0 (empate).
"""

from __future__ import annotations

import re
from datetime import datetime

from ..config import CATEGORIES, INDETERMINATE
from ..util import fold_text, iso_z, now_utc, sha256_hex
from . import input_hash, input_text_for
from .geo import METHOD as GEO_METHOD
from .geo import geo_content_v2
from .lexicon import CATEGORY_TERMS

BASELINE_ID = "baseline-lexical-v1"
ALPHA = 0.25


_CAT_RX = {c: [re.compile(rf"(?<![a-z0-9]){re.escape(t.strip())}") for t in sorted(set(ts), key=len, reverse=True)] for c, ts in CATEGORY_TERMS.items()}


def category_scores(folded: str) -> dict[str, int]:
    scores = {}
    for c in CATEGORIES:
        hits = {rx.pattern for rx in _CAT_RX[c] if rx.search(folded)}
        scores[c] = len(hits)
    return scores


def geo_relevance(article: dict) -> tuple[str, list[str]]:
    """Relevancia geográfica por CONTENIDO (regla lexical-content-v2, ver classify/geo.py)."""
    return geo_content_v2(article)


class BaselineClassifier:
    name = "baseline"
    model_id = BASELINE_ID
    model_version = "1.0.0"
    threshold = 0.0

    def predict(self, articles: list[dict], *, predicted_at: datetime | None = None) -> list[dict]:
        ts = iso_z(predicted_at or now_utc())
        out = []
        k = len(CATEGORIES)
        for a in articles:
            folded = fold_text(input_text_for(a))
            scores = category_scores(folded)
            total = sum(scores.values())
            probs = {c: (scores[c] + ALPHA) / (total + ALPHA * k) for c in CATEGORIES}
            ranked = sorted(CATEGORIES, key=lambda c: (-scores[c], c))
            best = ranked[0]
            margin = scores[best] - scores[ranked[1]]
            category = best if total > 0 and margin > 0 else INDETERMINATE
            geo, geo_ev = geo_relevance(a)
            ih = input_hash(a)
            out.append(
                {
                    "predictionId": "pred_" + sha256_hex(a["articleId"] + ih + self.model_id)[:16],
                    "articleId": a["articleId"],
                    "inputHash": ih,
                    "task": "category",
                    "category": category,
                    "probability": round(probs[best], 6),
                    "probabilities": {c: round(p, 6) for c, p in probs.items()},
                    "threshold": self.threshold,
                    "geoRelevance": geo,
                    "geoEvidence": geo_ev,
                    "geoMethod": GEO_METHOD,
                    "classifier": "baseline",
                    "modelId": self.model_id,
                    "modelVersion": self.model_version,
                    "predictedAt": ts,
                    "calibrated": False,
                    "provisional": True,
                }
            )
        return out
