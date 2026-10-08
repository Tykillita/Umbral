"""Smoke test de Laya (requiere `uv sync --extra laya` y pesos en cache HF). Excluido por defecto: `pytest -m laya`."""

import pytest

pytestmark = pytest.mark.laya


def test_laya_classifies_obvious_headlines():
    pytest.importorskip("laya")
    from umbral_pipeline.classify.laya_clf import LayaClassifier

    clf = LayaClassifier(log=lambda *_: None)
    arts = [
        {"articleId": "a1", "title": "Sismo de magnitud 5,1 sacude el sur de Panamá"},
        {"articleId": "a2", "title": "Hoteles de Panamá reportan alza en la ocupación por el feriado"},
    ]
    preds = clf.predict(arts)
    assert preds[0]["category"] == "eventos_naturales"
    assert preds[1]["category"] == "turismo"
    assert all(p["classifier"] == "laya" and p["modelVersion"] != "" for p in preds)
    assert abs(sum(preds[0]["probabilities"].values()) - 1) < 0.02
