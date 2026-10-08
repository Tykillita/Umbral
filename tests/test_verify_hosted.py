import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_hosted.py"
_SPEC = importlib.util.spec_from_file_location("verify_hosted", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
verify_model_identity = _MODULE.verify_model_identity


@pytest.fixture
def calibrated_snapshot_info():
    return {
        "snapshotId": "20261007-e704e952",
        "manifest": {
            "snapshotId": "20261007-e704e952",
            "classifier": {
                "modelVersion": "laya-ft-ccb4ea2758e5e524",
                "calibrated": True,
                "calibrationProfileId": "laya-cal-c593b2461ec6daf2",
                "calibrationProfileSha256": "9fdc8b9920c1df12ad4a341125810b5db051757c60bc6bd164b1773dfb15db99",
            },
        },
    }


def test_hosted_verifier_accepts_the_exact_calibrated_model(calibrated_snapshot_info):
    result = verify_model_identity(
        calibrated_snapshot_info,
        "laya-ft-ccb4ea2758e5e524",
        "laya-cal-c593b2461ec6daf2",
        "9fdc8b9920c1df12ad4a341125810b5db051757c60bc6bd164b1773dfb15db99",
    )

    assert result["calibrated"] is True
    assert result["calibrationProfileId"] == "laya-cal-c593b2461ec6daf2"


@pytest.mark.parametrize("field,value", [
    ("modelVersion", "laya-base"),
    ("calibrated", False),
    ("calibrationProfileId", "laya-cal-stale"),
    ("calibrationProfileSha256", "0" * 64),
])
def test_hosted_verifier_rejects_a_different_model_or_profile(calibrated_snapshot_info, field, value):
    calibrated_snapshot_info["manifest"]["classifier"][field] = value

    with pytest.raises(ValueError, match="identidad calibrada"):
        verify_model_identity(
            calibrated_snapshot_info,
            "laya-ft-ccb4ea2758e5e524",
            "laya-cal-c593b2461ec6daf2",
            "9fdc8b9920c1df12ad4a341125810b5db051757c60bc6bd164b1773dfb15db99",
        )


def test_hosted_verifier_rejects_mismatched_snapshot_manifest(calibrated_snapshot_info):
    calibrated_snapshot_info["manifest"]["snapshotId"] = "20261007-cfa338b6"

    with pytest.raises(ValueError, match="identidad calibrada"):
        verify_model_identity(
            calibrated_snapshot_info,
            "laya-ft-ccb4ea2758e5e524",
            "laya-cal-c593b2461ec6daf2",
            "9fdc8b9920c1df12ad4a341125810b5db051757c60bc6bd164b1773dfb15db99",
        )
