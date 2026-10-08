import math

from umbral_pipeline.evalkit.metrics import (
    accuracy,
    latency_summary,
    macro_f1,
    pairwise_precision_recall,
    percentile,
    precision_at_k,
    prf_per_class,
)


def test_macro_f1_hand_computed():
    y_true = ["a", "a", "b", "b", "c"]
    y_pred = ["a", "b", "b", "b", "a"]
    per = prf_per_class(y_true, y_pred)
    # a: tp1 fp1 fn1 -> P=.5 R=.5 F1=.5 ; b: tp2 fp1 fn0 -> P=2/3 R=1 F1=.8 ; c: tp0 -> 0
    assert math.isclose(per["a"]["f1"], 0.5)
    assert math.isclose(per["b"]["f1"], 0.8)
    assert per["c"]["f1"] == 0.0
    assert math.isclose(macro_f1(y_true, y_pred), (0.5 + 0.8 + 0.0) / 3)
    assert math.isclose(accuracy(y_true, y_pred), 3 / 5)


def test_macro_f1_ignores_classes_without_support_when_asked():
    y_true, y_pred = ["a", "a"], ["a", "z"]
    assert math.isclose(macro_f1(y_true, y_pred, only_supported=True), prf_per_class(y_true, y_pred)["a"]["f1"])
    assert macro_f1(y_true, y_pred, only_supported=False) < macro_f1(y_true, y_pred, only_supported=True)


def test_pairwise_pr():
    gold = [["a", "b", "c"], ["d"]]
    pred = [["a", "b"], ["c", "d"]]
    r = pairwise_precision_recall(pred, gold)
    # pred pairs: ab, cd ; gold pairs: ab, ac, bc ; tp=1
    assert r["tp"] == 1 and r["predictedPairs"] == 2 and r["goldPairs"] == 3
    assert math.isclose(r["precision"], 0.5) and math.isclose(r["recall"], 1 / 3)


def test_precision_at_k_and_percentiles():
    assert precision_at_k(["x", "a", "y", "b", "c", "d"], {"a", "b", "c"}, 5) == 3 / 5
    assert math.isclose(percentile([1, 2, 3, 4], 50), 2.5)
    s = latency_summary([1.0, 2.0, 3.0, 4.0, 100.0])
    assert s["median"] == 3.0 and s["p95"] > 50 and s["n"] == 5
