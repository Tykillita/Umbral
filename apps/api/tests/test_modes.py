"""Stub de Gemini por entorno y guardas de configuración/persistencia."""

from __future__ import annotations

import pytest

from umbral_api.providers import StubGeminiProvider, build_providers
from umbral_api.storage import build_repository

from .conftest import find_topic

API = "/api/v1"


@pytest.mark.parametrize(("stub", "mode", "reason"), [
    ("ok", "modelo", None), ("quota", "plantilla", "cuota_agotada"), ("down", "plantilla", "proveedor_no_disponible"),
    ("no_key", "plantilla", "sin_credenciales"),
])
def test_gemini_stub_env_simulates_provider(make_app, stub, mode, reason):
    c = make_app(gemini_stub=stub)
    d = c.post(f"{API}/topics/{find_topic(c, 'calado')}/drafts", json={}).json()["draft"]
    assert d["generationMode"] == mode and d["fallbackReason"] == reason
    if mode == "modelo":
        assert d["model"] == "gemini-stub"
    h = c.get(f"{API}/health").json()
    assert any("STUB" in n for n in h["notes"])


def test_stub_model_draft_then_quota_gives_recovered(make_app):
    c = make_app(gemini_stub="ok")
    tid = find_topic(c, "calado")
    first = c.post(f"{API}/topics/{tid}/drafts", json={}).json()["draft"]
    c.svc.providers["gemini"].behavior = "quota"
    second = c.post(f"{API}/topics/{tid}/drafts", json={}).json()["draft"]
    assert second["generationMode"] == "recuperado" and second["recoveredFromDraftId"] == first["draftId"]


def test_stub_is_blocked_offline_like_a_real_external_provider(make_app):
    c = make_app(gemini_stub="ok", offline=True)
    d = c.post(f"{API}/topics/{find_topic(c, 'calado')}/drafts", json={}).json()["draft"]
    assert d["fallbackReason"] == "modo_sin_conexion" and c.svc.providers["gemini"].calls == 0


def test_stub_forbidden_with_firebase_auth(fixture_dir):
    from .conftest import make_settings

    with pytest.raises(RuntimeError):
        build_providers(make_settings(fixture_dir, gemini_stub="ok", auth_mode="firebase"))
    assert isinstance(build_providers(make_settings(fixture_dir, gemini_stub="ok"))["gemini"], StubGeminiProvider)


def test_firestore_configuration_failure_never_creates_sqlite(tmp_path, monkeypatch):
    import umbral_api.storage as storage

    def unavailable(*args):
        raise RuntimeError("credenciales ausentes")

    monkeypatch.setattr(storage, "FirestoreRepository", unavailable)
    with pytest.raises(RuntimeError, match="Firestore no disponible"):
        build_repository("firestore", tmp_path / "x.sqlite", "site-umbral")
    assert not (tmp_path / "x.sqlite").exists()


@pytest.mark.parametrize("options", [
    {"local_mode": False}, {"auth_mode": "firebase"},
    {"auth_mode": "firebase", "local_mode": False, "persistence": "sqlite"},
    {"auth_mode": "firebase", "local_mode": False, "persistence": "firestore"},
])
def test_web_requires_firebase_firestore_and_project(fixture_dir, options):
    from .conftest import make_settings

    with pytest.raises(RuntimeError):
        make_settings(fixture_dir, **options).validate()


def test_complete_web_config_is_accepted_without_using_credentials(fixture_dir):
    from .conftest import make_settings

    make_settings(fixture_dir, local_mode=False, auth_mode="firebase", persistence="firestore", firestore_project="site-umbral").validate()


class _FakeModels:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.models_called = []
        self.closed = False

    def generate_content(self, *, model, contents, config):
        self.models_called.append(model)
        b = self.behaviors.pop(0)
        if isinstance(b, Exception):
            raise b
        return b


def _patch_genai(monkeypatch, behaviors):
    import google.genai as genai

    holder = _FakeModels(behaviors)

    class _Client:
        def __init__(self, **kw):
            self.models = holder

        def close(self):
            holder.closed = True

    monkeypatch.setattr(genai, "Client", _Client)
    return holder


def _gemini(fixture_dir):
    from dataclasses import replace

    from umbral_api.providers import GeminiProvider

    from .conftest import make_settings

    return GeminiProvider(replace(make_settings(fixture_dir), gemini_api_key="test-key-no-real", gemini_model="gemini-x", gemini_fallback_model="gemini-fallback"))


def test_real_gemini_adapter_maps_429_to_quota(fixture_dir, monkeypatch):
    from google.genai import errors

    from umbral_api.providers import ProviderError

    holder = _patch_genai(monkeypatch, [errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}})])
    with pytest.raises(ProviderError) as e:
        _gemini(fixture_dir).generate("sys", "usr")
    assert e.value.reason.value == "cuota_agotada" and holder.closed


def test_real_gemini_adapter_maps_5xx_and_network_to_unavailable(fixture_dir, monkeypatch):
    from google.genai import errors

    from umbral_api.providers import ProviderError

    err = errors.ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "x"}})
    holder = _patch_genai(monkeypatch, [err, err])
    with pytest.raises(ProviderError) as e:
        _gemini(fixture_dir).generate("s", "u")
    assert e.value.reason.value == "proveedor_no_disponible"
    assert holder.models_called == ["gemini-x", "gemini-fallback"]  # probó el respaldo gratuito antes de rendirse
    _patch_genai(monkeypatch, [ConnectionError("sin red"), ConnectionError("sin red")])
    with pytest.raises(ProviderError) as e2:
        _gemini(fixture_dir).generate("s", "u")
    assert e2.value.reason.value == "proveedor_no_disponible"


def test_real_gemini_adapter_invalid_key_maps_to_no_credentials(fixture_dir, monkeypatch):
    from google.genai import errors

    from umbral_api.providers import ProviderError

    holder = _patch_genai(monkeypatch, [errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid."}})])
    with pytest.raises(ProviderError) as e:
        _gemini(fixture_dir).generate("s", "u")
    assert e.value.reason.value == "sin_credenciales" and holder.models_called == ["gemini-x"]


def test_real_gemini_adapter_unknown_model_uses_free_tier_fallback_model(fixture_dir, monkeypatch):
    from google.genai import errors

    from umbral_api.providers import stub_output_from_prompt

    user = '<evidencia>{"evidence":[{"evidence_id":"art_1","fields":{"title":"T","outlet":"O"}}]}</evidencia>'

    class _Resp:
        parsed = stub_output_from_prompt(user)
        text = ""

    holder = _patch_genai(monkeypatch, [errors.ClientError(404, {"error": {"status": "NOT_FOUND", "message": "model"}}), _Resp()])
    res = _gemini(fixture_dir).generate("s", user)
    assert holder.models_called == ["gemini-x", "gemini-fallback"] and res.model == "gemini-fallback"


def test_real_gemini_without_key_and_offline_never_calls_sdk(fixture_dir, monkeypatch):
    from dataclasses import replace

    from umbral_api.providers import GeminiProvider, ProviderError

    from .conftest import make_settings

    holder = _patch_genai(monkeypatch, [])
    with pytest.raises(ProviderError) as e:
        GeminiProvider(make_settings(fixture_dir)).generate("s", "u")
    assert e.value.reason.value == "sin_credenciales"
    with pytest.raises(ProviderError) as e2:
        GeminiProvider(replace(make_settings(fixture_dir), gemini_api_key="k", offline=True)).generate("s", "u")
    assert e2.value.reason.value == "modo_sin_conexion" and holder.models_called == []
