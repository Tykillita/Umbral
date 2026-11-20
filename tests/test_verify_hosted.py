import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_hosted.py"
_SPEC = importlib.util.spec_from_file_location("verify_hosted", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
verify_model_identity = _MODULE.verify_model_identity


def test_hosted_verifier_waits_for_the_candidate_descriptor(monkeypatch):
    web_url = "https://site.example"
    api_url = "https://api.example"
    descriptor_url = web_url + "/data/current.json"
    descriptors = iter([
        {"schemaVersion": 1, "snapshotId": "previous"},
        {"schemaVersion": 1, "snapshotId": "candidate"},
    ])
    calls = 0

    def fake_request(url, *args, **kwargs):
        assert url in {web_url + "/", web_url + "/app"}
        return 200, {}, b"Umbral"

    def fake_json_response(url, *args, **kwargs):
        nonlocal calls
        if url == web_url + "/public-config.json":
            return 200, {}, {"schemaVersion": 1, "apiUrl": api_url}
        if url == descriptor_url:
            calls += 1
            return 200, {}, next(descriptors)
        if url == api_url + "/api/v1/health":
            return 200, {"access-control-allow-origin": web_url}, {
                "snapshotId": "candidate",
                "authMode": "public",
                "containsFixtures": False,
                "classifier": "laya",
                "integrity": {"manifestVerified": True, "predictionsHashVerified": True},
                "counts": {},
            }
        if url == api_url + "/api/v1/public/agenda":
            return 200, {}, {"snapshotId": "candidate", "items": [{"id": "topic"}]}
        if url == api_url + "/api/v1/public/topics/topic":
            return 200, {}, {"articles": [{}]}
        if url == api_url + "/api/v1/public/queries":
            return 200, {}, {"snapshotId": "candidate", "answer": "respuesta"}
        if url == api_url + "/api/v1/public/drafts":
            return 200, {}, {"draft": {"generationMode": "plantilla", "validation": {"ok": True}}}
        if url == api_url + "/api/v1/rules":
            return 403, {}, {}
        raise AssertionError(f"Ruta inesperada: {url}")

    monkeypatch.setattr(_MODULE, "request", fake_request)
    monkeypatch.setattr(_MODULE, "json_response", fake_json_response)
    monkeypatch.setattr(_MODULE.time, "sleep", lambda _: None)

    result = _MODULE.verify(web_url, api_url, "candidate", wait_seconds=10)

    assert calls == 2
    assert result["snapshotId"] == "candidate"


def test_request_disables_caching(monkeypatch):
    headers = {}

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b"{}"

    def fake_urlopen(request, timeout):
        headers.update({key.lower(): value for key, value in request.header_items()})
        assert timeout == 15
        return Response()

    monkeypatch.setattr(_MODULE, "urlopen", fake_urlopen)

    _MODULE.request("https://site.example/data/current.json")

    assert headers["cache-control"] == "no-cache"
    assert headers["pragma"] == "no-cache"


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
