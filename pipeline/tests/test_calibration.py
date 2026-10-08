from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from umbral_pipeline.classify.calibration import (
    CalibrationProfile,
    load_profile,
    resolve_model_version,
)
from umbral_pipeline.classify.laya_clf import LayaClassifier
from umbral_pipeline.util import sha256_file

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))
from fit_calibration import LABELS, choose_threshold, validate_partition_groups  # noqa: E402


def profile_data(model_version: str = "laya-ft-test") -> dict:
    return {
        "schemaVersion": "1.0.0",
        "profileId": "laya-cal-test",
        "modelVersion": model_version,
        "method": "temperature-scaling",
        "temperature": 2.0,
        "threshold": 0.4,
        "evaluationKind": "agent_review",
        "fit": {"calibrationExamples": 150, "validationExamples": 100, "testGate": {"passed": True}},
    }


def test_profile_applies_temperature_to_logits() -> None:
    profile = CalibrationProfile("id", "version", temperature=2.0, threshold=0.5)
    result = profile.apply_logits({"economia": 2.0, "otro": 0.0})
    assert result["economia"] == pytest.approx(math.exp(1) / (math.exp(1) + 1))
    assert sum(result.values()) == pytest.approx(1.0)


def test_profile_is_bound_to_model_version_and_support(tmp_path) -> None:
    path = tmp_path / "umbral-calibration.json"
    path.write_text(json.dumps(profile_data()), encoding="utf-8")
    loaded = load_profile("laya-ft-test", tmp_path, use_environment=False)
    assert loaded.profile_id == "laya-cal-test"
    assert loaded.sha256 == sha256_file(path)
    with pytest.raises(ValueError, match="no corresponde"):
        load_profile("other-model", tmp_path, use_environment=False)

    raw = profile_data()
    raw["fit"]["validationExamples"] = 99
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="soporte mínimo"):
        load_profile("laya-ft-test", tmp_path, use_environment=False)

    raw = profile_data()
    raw["fit"]["testGate"]["passed"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="prueba intacta"):
        load_profile("laya-ft-test", tmp_path, use_environment=False)


def test_model_metadata_detects_changed_weights(tmp_path) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights-a")
    metadata = {"modelVersion": "laya-ft-a", "weightsSha256": sha256_file(weights)}
    (tmp_path / "umbral-model.json").write_text(json.dumps(metadata), encoding="utf-8")
    assert resolve_model_version(tmp_path, "base") == "laya-ft-a"
    weights.write_bytes(b"weights-b")
    with pytest.raises(ValueError, match="no coinciden"):
        resolve_model_version(tmp_path, "base")


def test_partition_groups_use_source_and_reject_candidate_cross_split_merge() -> None:
    labels = {
        "calibration": {"a": {"eventGroup": "source-a"}},
        "validation": {"b": {"eventGroup": "source-b"}},
    }
    source_groups = {"a": "source-a", "b": "source-b"}
    validate_partition_groups(labels, source_groups, {"a": "candidate-a", "b": "candidate-b"})

    with pytest.raises(ValueError, match="clúster candidato cruza"):
        validate_partition_groups(labels, source_groups, {"a": "merged", "b": "merged"})

    overlapping_source_labels = {
        "calibration": {"a": {"eventGroup": "source-a"}},
        "validation": {"b": {"eventGroup": "source-a"}},
    }
    overlapping_source_groups = {"a": "source-a", "b": "source-a"}
    with pytest.raises(ValueError, match="snapshot base se comparte"):
        validate_partition_groups(overlapping_source_labels, overlapping_source_groups,
                                  {"a": "candidate-a", "b": "candidate-b"})


def test_threshold_keeps_both_scope_recalls_at_the_validation_baseline() -> None:
    in_scope = dict.fromkeys(LABELS, 0.0)
    in_scope.update(economia=0.8, indeterminado=0.2)
    out_of_scope = dict.fromkeys(LABELS, 0.0)
    out_of_scope.update(economia=0.55, indeterminado=0.45)

    threshold, metrics = choose_threshold(
        [(in_scope, "economia"), (out_of_scope, "indeterminado")],
        minimum_in_scope_recall=1.0,
        minimum_out_of_scope_recall=1.0,
    )

    assert threshold == pytest.approx(0.56)
    assert metrics["scopeGatePassed"] is True
    assert metrics["inScopeRecall"] == 1.0
    assert metrics["outOfScopeRecall"] == 1.0

    impossible = dict.fromkeys(LABELS, 0.0)
    impossible.update(economia=0.4, indeterminado=0.6)
    threshold, metrics = choose_threshold(
        [(impossible, "economia"), (out_of_scope, "indeterminado")],
        minimum_in_scope_recall=1.0,
        minimum_out_of_scope_recall=1.0,
    )
    assert 0.0 <= threshold <= 0.95
    assert metrics["scopeGatePassed"] is False


def test_laya_logits_are_captured_before_probability_rounding(monkeypatch) -> None:
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "_option_logits", lambda _logits, _items, _offset: np.array([[2.0, 0.0]]), raising=False)
    monkeypatch.setattr(module, "temp_bucket", lambda _kind, _count: "choice-2", raising=False)
    monkeypatch.setattr(module, "QTYPES", {"choice": "choice"}, raising=False)
    monkeypatch.setattr(module, "unpermute_probs", lambda values, _order: values, raising=False)
    monkeypatch.setattr(module, "np", np, raising=False)

    class FakeAgent:
        __module__ = __name__
        temperature_by_options = {}
        temperature = {"choice": 2.0}

        def _decode_answers(self, *_args, **_kwargs):
            return {"category": {"probabilities": {"economia": 0.731, "otro": 0.269}}}

    classifier = object.__new__(LayaClassifier)
    classifier.agent = FakeAgent()
    classifier.calibration_profile = CalibrationProfile("profile", "version", temperature=2.0, threshold=0.5)
    classifier._install_calibration_capture()

    answers = classifier.agent._decode_answers(
        np.zeros((1, 2)),
        np.zeros((1, 1)),
        [{"markers": ["A", "B"]}],
        ["category"],
        {"category": {"t": "choice", "crit": {"economia": "Economía", "otro": "Otro"}}},
        0,
    )

    logits = answers["category"]["calibration_logits"]
    assert logits["economia"] - logits["otro"] == pytest.approx(1.0)
    calibrated = answers["category"]["umbral_calibrated_probabilities"]
    assert calibrated["economia"] == pytest.approx(math.exp(0.5) / (math.exp(0.5) + 1))
    assert sum(calibrated.values()) == pytest.approx(1.0)
