"""Reglas de renovación y caché; dobles de inferencia explícitos, sin red/modelo."""

import json
from pathlib import Path

import pytest

from umbral_pipeline.classify import input_hash
from umbral_pipeline.classify.laya_clf import PINNED_REVISION
from umbral_pipeline.refresh import classify_cached, retain_snapshots, rules_hash, run_daily, run_reclassify
from umbral_pipeline.snapshot import activate_snapshot

ROOT = Path(__file__).resolve().parents[2]


class SpyClassifier:
    """Prueba la reutilización; NO representa una inferencia de Laya real."""
    seen = []

    def __init__(self, log=None):
        pass

    def predict(self, articles, progress=None):
        self.seen.extend(a["articleId"] for a in articles)
        return [{"articleId": a["articleId"], "inputHash": input_hash(a), "modelVersion": PINNED_REVISION,
                 "classifier": "laya"} for a in articles]

    def info(self):
        return {"classifier": "laya", "modelVersion": PINNED_REVISION}


def previous_for(article):
    return {"manifest": {"classifier": {"classifier": "laya", "modelVersion": PINNED_REVISION,
                                          "rulesHash": rules_hash()}},
            "predictions": [{"articleId": article["articleId"], "inputHash": input_hash(article),
                              "modelVersion": PINNED_REVISION, "classifier": "laya"}]}


@pytest.mark.parametrize("change", ["title", "revision", "rules", "force"])
def test_cache_requires_same_input_revision_rules(change):
    article = {"articleId": "art_a", "title": "Canal de Panamá inicia nuevas obras", "domain": "tvn-2.com", "isTvn": True}
    previous = previous_for(article)
    if change == "title":
        article["title"] = "Canal de Panamá termina las obras"
    if change == "revision":
        previous["manifest"]["classifier"]["modelVersion"] = "old"
    if change == "rules":
        previous["manifest"]["classifier"]["rulesHash"] = "old"
    SpyClassifier.seen = []
    _, info, _ = classify_cached([article], previous, force=change == "force", classifier_factory=SpyClassifier)
    assert SpyClassifier.seen == ["art_a"]
    assert info["cachedPredictions"] == 0


def test_cache_reuses_inference_but_recomputes_geo_from_metadata():
    article = {"articleId": "art_a", "title": "Servicio de agua vuelve a funcionar", "domain": "tvn-2.com", "isTvn": True}
    previous = previous_for(article)
    SpyClassifier.seen = []
    predictions, info, _ = classify_cached([article], previous, classifier_factory=SpyClassifier)
    assert SpyClassifier.seen == []
    assert info["cachedPredictions"] == 1
    assert predictions[0]["geoRelevance"] == "panama"
    assert "geoRelevance" not in previous["predictions"][0]


def actual_snapshot():
    return ROOT / "data/snapshots" / (ROOT / "data/snapshots/CURRENT").read_text().strip()


def test_daily_all_news_sources_fail_does_not_advance_cutoff(tmp_path):
    raw = tmp_path / "raw/test"
    raw.mkdir(parents=True)
    (raw / "fetch_meta.json").write_text(json.dumps({"cutoffUtc": "2026-10-08T10:00:00Z", "queries": [],
                                                     "errors": [{"source": "tvn_rss", "error": "offline"}]}))
    with pytest.raises(ValueError, match="Ninguna fuente"):
        run_daily(tmp_path, previous_dir=actual_snapshot(), raw_dir=raw, classifier_factory=SpyClassifier)
    assert not (tmp_path / "snapshots/CURRENT").exists()


def test_activation_rejects_corruption_and_preserves_pointer(tmp_path):
    import shutil

    source = actual_snapshot()
    target = tmp_path / source.name
    shutil.copytree(source, target)
    (tmp_path / "CURRENT").write_text("original\n")
    (target / "articles.jsonl").write_bytes(b'{}\n')
    with pytest.raises((ValueError, KeyError)):
        activate_snapshot(target)
    assert (tmp_path / "CURRENT").read_text() == "original\n"


def test_reclassification_does_not_require_raw(tmp_path, monkeypatch):
    import umbral_pipeline.refresh as module

    captured = {}

    def capture(*args, **kwargs):
        captured.update(kwargs)
        return Path("candidate")

    monkeypatch.setattr(module, "build_normalized", capture)
    result = run_reclassify(tmp_path, actual_snapshot())
    assert result == Path("candidate")
    assert captured["force"] is True
    assert captured["set_current"] is False
    assert captured["articles"] and all(a["dataOrigin"] == "real" for a in captured["articles"])
    assert not (tmp_path / "raw").exists()


def test_retention_keeps_seven_and_referenced_at_same_cutoff(tmp_path, monkeypatch):
    import umbral_pipeline.refresh as module

    names = [f"20261007-{i:08x}" for i in range(11)]
    for name in names:
        (tmp_path / name).mkdir()
        (tmp_path / name / "sentinel").write_text("keep")
    (tmp_path / "CURRENT").write_text(names[0])
    monkeypatch.setattr(module, "load_verified", lambda path: {"manifest": {"cutoffUtc": "2026-10-07T12:00:00Z"}})
    removed = retain_snapshots(tmp_path, keep=7, referenced={names[1]})
    assert set(removed) == {names[2], names[3]}
    assert {p.name for p in tmp_path.iterdir() if p.is_dir()} == set(names) - set(removed)
