"""Metricas de evaluacion (puras, sin dependencias). Solo calculan; los numeros reportados salen de ejecuciones reales."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from itertools import combinations


def confusion(y_true: Sequence[str], y_pred: Sequence[str]) -> dict[str, dict[str, int]]:
    m: dict[str, Counter] = defaultdict(Counter)
    for t, p in zip(y_true, y_pred, strict=True):
        m[t][p] += 1
    return {t: dict(c) for t, c in m.items()}


def prf_per_class(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] | None = None) -> dict[str, dict[str, float | int]]:
    labels = list(labels or sorted(set(y_true) | set(y_pred)))
    out = {}
    for c in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[c] = {"precision": prec, "recall": rec, "f1": f1, "support": tp + fn, "tp": tp, "fp": fp, "fn": fn}
    return out


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str] | None = None, *, only_supported: bool = True) -> float:
    """Macro-F1. Con only_supported=True promedia solo clases con soporte > 0 en las etiquetas humanas."""
    per = prf_per_class(y_true, y_pred, labels)
    vals = [v["f1"] for v in per.values() if (v["support"] > 0 or not only_supported)]
    return sum(vals) / len(vals) if vals else 0.0


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    return sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p) / len(y_true) if y_true else 0.0


def pairs_from_clusters(clusters: Iterable[Iterable[str]]) -> set[frozenset[str]]:
    out: set[frozenset[str]] = set()
    for c in clusters:
        for a, b in combinations(sorted(set(c)), 2):
            out.add(frozenset((a, b)))
    return out


def pairwise_precision_recall(
    predicted_clusters: Iterable[Iterable[str]], gold_clusters: Iterable[Iterable[str]], universe: set[str] | None = None
) -> dict[str, float | int]:
    """Precision/recall a nivel de PARES de articulos. Si `universe`, solo cuentan pares dentro del universo etiquetado."""
    pred = pairs_from_clusters(predicted_clusters)
    gold = pairs_from_clusters(gold_clusters)
    if universe is not None:
        pred = {p for p in pred if p <= universe}
        gold = {p for p in gold if p <= universe}
    tp = len(pred & gold)
    prec = tp / len(pred) if pred else 1.0 if not gold else 0.0
    rec = tp / len(gold) if gold else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": prec, "recall": rec, "f1": f1, "tp": tp, "predictedPairs": len(pred), "goldPairs": len(gold)}


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int = 5) -> float:
    if k <= 0:
        return 0.0
    top = list(ranked)[:k]
    return sum(1 for r in top if r in relevant) / k


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil por interpolacion lineal (q en 0..100)."""
    if not values:
        return math.nan
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def latency_summary(values: Sequence[float]) -> dict[str, float | int]:
    return {"n": len(values), "median": percentile(values, 50), "p95": percentile(values, 95),
            "max": max(values) if values else math.nan}


def ratio(num: int, den: int) -> dict[str, float | int | None]:
    return {"numerator": num, "denominator": den, "value": (num / den) if den else None}


def probability_quality(y_true: Sequence[str], predictions: Sequence[dict], labels: Sequence[str], bins: int = 10) -> dict:
    """Uncalibrated confidence: multiclass Brier and top-label ECE, no fitting.

    Evaluates only supplied labels; caller must preserve human/synthetic provenance.
    Uses the probability of the actual predicted category, including indeterminate.
    """
    if not y_true:
        return {"n": 0, "brier": None, "ece": None, "bins": [], "calibrated": False}
    if len(y_true) != len(predictions) or bins < 1:
        raise ValueError("Longitudes diferentes o cantidad de bins inválida")
    groups: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    brier_values = []
    for gold, prediction in zip(y_true, predictions, strict=True):
        if gold not in labels or prediction["category"] not in labels:
            raise ValueError("Categoría desconocida en evaluación de probabilidades")
        probabilities = {label: float(prediction["probabilities"].get(label, 0)) for label in labels}
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in probabilities.values()):
            raise ValueError("Probabilidad inválida")
        if not math.isclose(sum(probabilities.values()), 1, abs_tol=.002):
            raise ValueError("Las probabilidades no suman 1")
        confidence = probabilities[prediction["category"]]
        correct = prediction["category"] == gold
        groups[min(bins - 1, int(confidence * bins))].append((confidence, correct))
        brier_values.append(sum((probabilities[label] - int(gold == label)) ** 2 for label in labels))
    rows = []
    ece = 0.0
    for index, values in enumerate(groups):
        if not values:
            continue
        confidence = sum(v[0] for v in values) / len(values)
        observed = sum(v[1] for v in values) / len(values)
        ece += len(values) / len(y_true) * abs(confidence - observed)
        rows.append({"bin": index, "n": len(values), "meanConfidence": confidence, "accuracy": observed})
    return {"n": len(y_true), "brier": sum(brier_values) / len(brier_values), "ece": ece,
            "bins": rows, "calibrated": False,
            "note": "Diagnóstico crudo; no ajuste/calibración de probabilidades ni exactitud humana sin etiquetas."}
