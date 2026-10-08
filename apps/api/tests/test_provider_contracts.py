"""Contratos de transporte reales con red reemplazada; nunca usan cuentas personales."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from umbral_api.auth import Authenticator
from umbral_api.config import Settings
from umbral_api.models import FallbackReason
from umbral_api.providers import (
    ChatGPTProvider,
    ClaudeCliProvider,
    GeminiProvider,
    ProviderError,
    completed_response_text,
    stub_output_from_prompt,
)

PROMPT = '<evidencia>{"evidence":[{"evidence_id":"art_1","fields":{"title":"Titular de prueba","outlet":"Medio"}}]}</evidencia>'


def sse(*events):
    return "".join("data: " + json.dumps(e) + "\n\n" for e in events)


@pytest.mark.parametrize("terminal", ["response.failed", "response.incomplete", None])
def test_chatgpt_never_accepts_partial_text(terminal):
    events = [{"type": "response.output_text.delta", "delta": '{"proposed_title":"parcial"}'}]
    if terminal:
        events.append({"type": terminal})
    with pytest.raises(ProviderError):
        completed_response_text(sse(*events).splitlines())


def test_chatgpt_usage_limit_after_deltas_is_quota():
    events = sse({"type": "response.output_text.delta", "delta": "texto parcial"}, {
        "type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}},
    })
    with pytest.raises(ProviderError) as error:
        completed_response_text(events.splitlines())
    assert error.value.reason == FallbackReason.cuota_agotada


def test_chatgpt_oauth_transport_uses_required_stream_contract(tmp_path, monkeypatch):
    import umbral_api.providers as providers

    token_path = tmp_path / "oauth.json"
    token_path.write_text(json.dumps({"access_token": "synthetic-test-token", "scope": "chatgpt.tokens.use.direct", "expires_at": 9999999999}))
    monkeypatch.setattr(providers, "repo_root", lambda: tmp_path / "workspace")
    output = stub_output_from_prompt(PROMPT)
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse(
            {"type": "response.output_text.delta", "delta": output.model_dump_json()},
            {"type": "response.completed"},
        ))

    original_stream = httpx.stream
    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: httpx.Client(transport=httpx.MockTransport(respond)).stream(*a, **kw))
    result = ChatGPTProvider(Settings(chatgpt_token_file=token_path, chatgpt_model="account-model")).generate("sistema", PROMPT)
    assert result.output == output
    body = captured[0]
    assert body["store"] is False and body["stream"] is True
    assert body["input"] == [{"role": "user", "content": PROMPT}]
    assert body["model"] == "account-model"
    assert original_stream is not httpx.stream


@pytest.mark.parametrize("saved", [[], {"access_token": "token"}, {"access_token": "token", "scope": "chatgpt.tokens.use.direct", "expires_at": 1}])
def test_chatgpt_rejects_missing_permission_or_expired_tokens(tmp_path, monkeypatch, saved):
    import umbral_api.providers as providers

    monkeypatch.setattr(providers, "repo_root", lambda: tmp_path / "workspace")
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(saved))
    assert not ChatGPTProvider(Settings(chatgpt_token_file=path, chatgpt_model="model")).status().available


def test_chatgpt_rejects_token_file_inside_workspace(tmp_path, monkeypatch):
    import umbral_api.providers as providers

    monkeypatch.setattr(providers, "repo_root", lambda: tmp_path)
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"access_token": "synthetic", "scope": "chatgpt.tokens.use.direct"}))
    assert not ChatGPTProvider(Settings(chatgpt_token_file=path)).status().available


def test_claude_uses_schema_and_disables_tools_without_invoking_cli(monkeypatch):
    import umbral_api.providers as providers

    output = stub_output_from_prompt(PROMPT)
    captured = []
    monkeypatch.setattr(ClaudeCliProvider, "_bin", lambda self: "claude-test")

    def run(cmd, **kw):
        captured.append((cmd, kw))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"structured_output": output.model_dump()}))

    monkeypatch.setattr(providers.subprocess, "run", run)
    result = ClaudeCliProvider(Settings()).generate("sistema", PROMPT)
    assert result.output == output
    cmd, kwargs = captured[0]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--disallowedTools") + 1] == "mcp__*"
    assert "--json-schema" in cmd and "--no-session-persistence" in cmd
    assert "--strict-mcp-config" in cmd and kwargs.get("shell", False) is False
    assert PROMPT in kwargs["input"]


@pytest.mark.parametrize("provider", [ChatGPTProvider, ClaudeCliProvider])
def test_direct_personal_provider_call_is_blocked_in_web(provider):
    with pytest.raises(ProviderError) as error:
        provider(Settings(local_mode=False)).generate("s", "u")
    assert error.value.reason == FallbackReason.solo_localhost


def test_actual_gemini_sdk_serializes_schema_and_parses_output_without_network(monkeypatch):
    from google import genai

    output = stub_output_from_prompt(PROMPT)
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": output.model_dump_json()}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 200, "totalTokenCount": 300}})

    original_client = genai.Client

    def isolated_client(**kwargs):
        options = kwargs["http_options"]
        options.client_args = {"transport": httpx.MockTransport(respond)}
        return original_client(**kwargs)

    monkeypatch.setattr(genai, "Client", isolated_client)
    result = GeminiProvider(Settings(gemini_api_key="synthetic-no-real-key", gemini_fallback_model=None)).generate("sistema", PROMPT)
    assert result.output == output
    assert result.usage.prompt_tokens == 100 and result.usage.output_tokens == 200 and result.usage.total_tokens == 300
    assert result.usage.cost_usd is None and result.usage.latency_ms >= 0
    wire = captured[0]["generationConfig"]
    assert wire["responseMimeType"] == "application/json"
    schema = wire["responseSchema"]
    assert "$defs" not in schema
    assert schema["properties"]["claims"]["items"]["properties"]["type"]["enum"] == ["hecho", "declaracion", "inferencia", "hipotesis"]


@pytest.mark.parametrize("limit, expected_calls, mode", [(1, 1, "plantilla"), (2, 2, "modelo")])
def test_actual_gemini_fallback_reserves_budget_for_each_http_call(make_app, monkeypatch, limit, expected_calls, mode):
    from google import genai

    from .conftest import find_topic

    captured = []

    def respond(request):
        captured.append(request)
        if len(captured) == 1:
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND", "message": "model unavailable"}})
        body = json.loads(request.content)
        prompt = body["contents"][0]["parts"][0]["text"]
        output = stub_output_from_prompt(prompt)
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": output.model_dump_json()}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 123, "candidatesTokenCount": 456, "totalTokenCount": 579}})

    original_client = genai.Client

    def isolated_client(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(respond)}
        return original_client(**kwargs)

    monkeypatch.setattr(genai, "Client", isolated_client)
    client = make_app(gemini_api_key="synthetic", gemini_model="primary", gemini_fallback_model="backup", gemini_calls_per_user_day=limit)
    topic = find_topic(client, "calado")
    response = client.post(f"/api/v1/topics/{topic}/drafts", json={"provider": "gemini"}).json()
    assert len(captured) == expected_calls
    assert response["draft"]["generationMode"] == mode
    if mode == "plantilla":
        assert response["draft"]["fallbackReason"] == "limite_por_usuario"
    else:
        assert response["draft"]["usage"]["totalTokens"] == 579
        assert response["draft"]["model"] == "backup"
    second = client.post(f"/api/v1/topics/{topic}/drafts", json={"provider": "gemini"}).json()
    assert len(captured) == expected_calls
    assert second["draft"]["fallbackReason"] == "limite_por_usuario"


def test_gemini_invalid_schema_does_not_retry_another_model(fixture_dir, monkeypatch):
    from google.genai import errors

    from .test_modes import _gemini, _patch_genai

    holder = _patch_genai(monkeypatch, [errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "schema invalid"}})])
    with pytest.raises(ProviderError) as error:
        _gemini(fixture_dir).generate("s", "u")
    assert error.value.reason == FallbackReason.validacion_fallida
    assert holder.models_called == ["gemini-x"]


def test_firebase_verifies_app_and_revocation_without_real_credentials(monkeypatch):
    from starlette.requests import Request

    auth = Authenticator("firebase", "site-umbral")
    fake_app = object()
    auth._firebase_app = fake_app
    calls = []

    def verify(token, **kw):
        calls.append((token, kw))
        return {"uid": "anon-user", "iat": 1, "exp": 9999999999}

    monkeypatch.setattr(auth, "_init_firebase", lambda: SimpleNamespace(verify_id_token=verify))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer synthetic-token")]})
    assert auth.user_for(request) == "anon-user"
    assert calls == [("synthetic-token", {"app": fake_app, "check_revoked": True})]


@pytest.mark.parametrize("dates", [{"iat": 1, "exp": 2}, {"iat": 9999999999, "exp": 99999999999},
    {}, {"iat": True, "exp": 9999999999}, {"iat": 1, "exp": float("inf")}])
def test_firebase_rejects_expired_or_invalid_temporal_claims_even_when_sdk_accepts(monkeypatch, dates):
    from starlette.requests import Request

    from umbral_api.errors import Unauthorized

    auth = Authenticator("firebase", "demo-umbral-audit")
    monkeypatch.setattr(auth, "_init_firebase", lambda: SimpleNamespace(verify_id_token=lambda *args, **kwargs: {"uid": "anon-user", **dates}))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer synthetic-token")]})
    with pytest.raises(Unauthorized):
        auth.user_for(request)
