"""Modo público: aislamiento real, cuotas y revisión sin escrituras compartidas."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.models import FallbackReason
from umbral_api.providers import ProviderError
from umbral_api.services import Services

from .conftest import FakeProvider, make_settings

API = "/api/v1"


class Counter:
    def __init__(self):
        self.used = 0
        self.lock = threading.Lock()

    def reserve(self, limit):
        with self.lock:
            if self.used >= limit:
                return False, self.used
            self.used += 1
            return True, self.used


def public_app(fixture_dir, *, behavior=None, counter=True, **kwargs):
    settings = make_settings(fixture_dir, auth_mode="public", persistence="none", local_mode=False, **kwargs)
    providers = {"gemini": FakeProvider(settings, behavior)} if behavior else None
    services = Services(settings, providers=providers)
    if behavior and counter:
        services.public_gemini_counter = Counter()
    app = create_app(settings, services=services)
    client = TestClient(app)
    return client, services


def context(svc):
    return {"snapshotId": svc.corpus.snapshot_id}


def topic(svc, needle="calado"):
    return next(base.id for base in svc.bases.values() if needle in base.display_title.lower())


def test_public_configuration_health_and_read_contracts(fixture_dir):
    c, svc = public_app(fixture_dir)
    health = c.get(API + "/health")
    assert health.status_code == 200
    assert health.json()["authMode"] == "public" and health.json()["persistence"] == "none"
    assert c.get(API + "/rules").status_code == c.get(API + "/snapshot").status_code == 200
    assert c.post(API + "/public/agenda", json={"context": context(svc)}).status_code == 200


@pytest.mark.parametrize(("method", "path"), [
    ("put", "/rules"), ("put", "/topics/evt/impact"), ("post", "/topics/evt/drafts"),
    ("put", "/cases/case-evt/draft"), ("patch", "/cases/case-evt/review"),
    ("post", "/workspace/import"), ("get", "/workspace/export"),
    ("get", "/connections/chatgpt"), ("post", "/connections/chatgpt/start"),
])
def test_public_private_routes_reject_before_parsing(fixture_dir, method, path):
    c, svc = public_app(fixture_dir)
    assert getattr(c, method)(API + path).status_code == 403
    assert svc.repo.list_cases("local") == []


def test_public_context_never_leaks_between_requests_or_rebuilds_indexes(fixture_dir, monkeypatch):
    c, svc = public_app(fixture_dir)
    original_state = svc._state
    import umbral_api.services as services_module

    def forbidden_rebuild(*args):
        raise AssertionError("No se reconstruyen índices por visitante")

    monkeypatch.setattr(services_module, "build_snapshot_state", forbidden_rebuild)
    tid = topic(svc)
    ctx = context(svc) | {"weights": {"R": 100, "I": 0, "U": 0, "N": 0, "E": 0}, "rulesVersion": "scoring-local-v2",
                          "topicOverrides": [{"topicId": tid, "status": "descartado", "evidenceConfirmed": True}]}
    changed = c.post(API + f"/public/topics/{tid}", json={"context": ctx}).json()
    plain = c.post(API + f"/public/topics/{tid}", json={"context": context(svc)}).json()
    assert changed["summary"]["reviewStatus"] == "descartado"
    assert plain["summary"]["reviewStatus"] == "nuevo"
    assert changed["rulesVersion"] == "scoring-local-v2" and plain["rulesVersion"] == "scoring-v1"
    assert changed["score"]["components"][0]["weight"] == 100
    assert plain["score"]["components"][0]["weight"] == 30
    assert changed["case"]["persisted"] is False
    assert svc._state is original_state and not svc.repo._cases and not svc.repo._rules


def test_public_snapshot_mismatch_is_actionable_conflict(fixture_dir):
    c, svc = public_app(fixture_dir)
    response = c.post(API + "/public/agenda", json={"context": {"snapshotId": "older"}})
    assert response.status_code == 409
    assert response.json()["details"]["currentSnapshotId"] == svc.corpus.snapshot_id


def test_public_queries_ip_limits_and_headers_cannot_change_identity(fixture_dir):
    c, svc = public_app(fixture_dir, queries_per_minute=2)
    for index in range(2):
        assert c.post(API + "/public/queries", json={"context": context(svc), "question": "inflación en Panamá"},
                      headers={"X-Umbral-User": str(index), "X-Forwarded-For": str(index)}).status_code == 200
    response = c.post(API + "/public/queries", json={"context": context(svc), "question": "inflación en Panamá"})
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0


def test_public_gemini_requires_global_counter_and_returns_template(fixture_dir):
    c, svc = public_app(fixture_dir, behavior="ok", counter=False)
    response = c.post(API + "/public/drafts", json={"context": context(svc), "topicId": topic(svc)}).json()
    assert response["draft"]["fallbackReason"] == "contador_no_disponible"
    assert response["draft"]["generationMode"] == "plantilla" and svc.providers["gemini"].calls == 0
    assert "case" not in response and response["evidence"]["topicId"] == topic(svc)
    assert not svc.repo._cases


def test_public_quota_counts_validation_retry_and_fails_closed(fixture_dir):
    c, svc = public_app(fixture_dir, behavior="bad_citation", gemini_global_calls_per_day=1)
    result = c.post(API + "/public/drafts", json={"context": context(svc), "topicId": topic(svc)}).json()
    assert svc.public_gemini_counter.used == svc.providers["gemini"].calls == 1
    assert result["draft"]["fallbackReason"] == "limite_global" and result["draft"]["generationMode"] == "plantilla"


def test_public_model_cache_reuses_calls_across_visitors_and_draft_limit_still_applies(fixture_dir):
    c, svc = public_app(fixture_dir, behavior="ok")
    payload = {"context": context(svc), "topicId": topic(svc)}
    first = c.post(API + "/public/drafts", json=payload).json()
    second = c.post(API + "/public/drafts", json=payload).json()
    assert first["draft"]["generationMode"] == "modelo"
    assert first["draft"]["draftId"] != second["draft"]["draftId"]
    assert second["draft"]["recoveredFromDraftId"] == first["draft"]["draftId"]
    assert second["draft"]["generationMode"] == "recuperado" and second["draft"]["usage"] is None
    assert svc.providers["gemini"].calls == svc.public_gemini_counter.used == 1
    assert c.post(API + "/public/drafts", json=payload).status_code == 429
    another = TestClient(c.app, client=("203.0.113.9", 1234))
    assert another.post(API + "/public/drafts", json=payload).status_code == 200
    assert svc.providers["gemini"].calls == 1 and not svc.repo._cases


def test_public_global_reservation_is_concurrent_and_preserved_by_request_views(fixture_dir):
    _, svc = public_app(fixture_dir, behavior="ok")

    def reserve(_):
        try:
            svc.request_view()._reserve_gemini_call("different-ip")
            return True
        except ProviderError as exc:
            assert exc.reason == FallbackReason.limite_global
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        allowed = list(pool.map(reserve, range(40)))
    assert sum(allowed) == svc.public_gemini_counter.used == 20


def test_public_counter_failure_never_calls_provider(fixture_dir):
    c, svc = public_app(fixture_dir, behavior="ok")

    class BrokenCounter:
        def reserve(self, limit):
            raise ConnectionError("credential content must not escape")

    svc.public_gemini_counter = BrokenCounter()
    response = c.post(API + "/public/drafts", json={"context": context(svc), "topicId": topic(svc)})
    assert response.json()["draft"]["fallbackReason"] == "contador_no_disponible"
    assert "credential content" not in response.text and svc.providers["gemini"].calls == 0


def test_public_review_returns_candidate_and_revalidates_untrusted_draft(fixture_dir):
    c, svc = public_app(fixture_dir)
    tid = topic(svc)
    detail = c.post(API + f"/public/topics/{tid}", json={"context": context(svc)}).json()
    response = c.post(API + "/public/validate", json={"context": context(svc), "topicId": tid,
                      "case": detail["case"], "review": {"expectedVersion": 0, "status": "en_revision", "reviewer": "A"}})
    assert response.status_code == 200, response.text
    candidate = response.json()["case"]
    assert candidate["version"] == 1 and len(candidate["history"]) == 1 and candidate["persisted"] is False
    draft = c.post(API + "/public/drafts", json={"context": context(svc), "topicId": tid, "provider": "plantilla"}).json()["draft"]
    draft["package"]["claims"][0]["citations"][0]["evidenceId"] = "inexistente"
    draft["validation"]["ok"] = True
    candidate["drafts"] = [draft]
    response = c.post(API + "/public/validate", json={"context": context(svc), "topicId": tid,
                      "case": candidate, "review": {"expectedVersion": 1, "status": "aprobado_como_borrador", "reviewer": "A",
                                                      "evidenceConfirmed": True, "comment": "Revisadas las fuentes"}})
    assert response.status_code == 422 and "validación" in response.json()["message"]
    assert not svc.repo._cases


def test_desktop_nonce_required_before_all_api_operations(fixture_dir):
    settings = replace(make_settings(fixture_dir), auth_mode="local", desktop_token="ephemeral-test-token")
    client = TestClient(create_app(settings))
    assert client.get(API + "/health").status_code == 403
    assert client.get(API + "/health", headers={"X-Umbral-Desktop-Token": settings.desktop_token}).status_code == 200
    assert client.get(API + "/health", headers={"X-Umbral-Desktop-Token": settings.desktop_token,
                                                "Origin": "https://foreign.example"}).status_code == 403


def test_public_real_gemini_adapter_reserves_every_model_and_validation_retry(fixture_dir, monkeypatch):
    from types import SimpleNamespace

    import google.genai as genai
    from google.genai import errors

    from umbral_api.providers import stub_output_from_prompt

    calls = []

    class Models:
        def generate_content(self, *, model, contents, config):
            calls.append(model)
            if len(calls) == 1:
                raise errors.ClientError(404, {"error": {"status": "NOT_FOUND", "message": "model"}})
            behavior = "bad_citation" if len(calls) == 2 else "ok"
            return SimpleNamespace(parsed=stub_output_from_prompt(contents, behavior))

    class Client:
        def __init__(self, **kwargs):
            self.models = Models()

        def close(self):
            pass

    monkeypatch.setattr(genai, "Client", Client)
    c, svc = public_app(fixture_dir, gemini_api_key="fake-test-key", gemini_model="test-primary", gemini_fallback_model="test-fallback")
    svc.public_gemini_counter = Counter()
    result = c.post(API + "/public/drafts", json={"context": context(svc), "topicId": topic(svc)}).json()
    assert result["draft"]["generationMode"] == "modelo", result
    assert calls == ["test-primary", "test-fallback", "test-primary"]
    assert svc.public_gemini_counter.used == 3


@pytest.mark.parametrize("kwargs", [{"local_mode": True}, {"persistence": "memory"}, {"gemini_stub": "ok"},
                                     {"gemini_global_calls_per_day": 21}])
def test_public_mode_rejects_shared_persistence_and_unsafe_budget(fixture_dir, kwargs):
    with pytest.raises(RuntimeError):
        make_settings(fixture_dir, **({"auth_mode": "public", "persistence": "none", "local_mode": False} | kwargs)).validate()


def test_public_queries_resolve_follow_ups_with_the_structured_context(fixture_dir):
    c, svc = public_app(fixture_dir, queries_per_minute=10)
    first = c.post(API + "/public/queries", json={"context": context(svc), "question": "desempleo de Panamá en 2023"}).json()
    ctx = first["followUpContext"]
    assert ctx["countries"] == ["PAN"] and ctx["years"] == [2023]
    second = c.post(API + "/public/queries", json={"context": context(svc), "question": "¿Y en Colombia?", "followUp": ctx}).json()
    assert second["resolvedQuestion"] == "Desempleo de Colombia en 2023"
    assert second["followUpContext"]["countries"] == ["COL"]
