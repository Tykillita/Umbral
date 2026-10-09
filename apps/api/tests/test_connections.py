"""OAuth real de biblioteca: JWT RSA/JWKS y HTTP con transporte controlado, sin cuentas reales."""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from umbral_api.connections import DIRECT, ISSUER, RESOURCE, TOKEN, ChatGPTConnections, ConnectionStart
from umbral_api.errors import ServiceUnavailable, Unauthorized, Unprocessable


@pytest.fixture
def connection(tmp_path, monkeypatch):
    import umbral_api.connections as module
    from umbral_api.config import Settings

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path / "workspace")
    conn = ChatGPTConnections(Settings(chatgpt_credentials_file=tmp_path / "private" / "chatgpt.dat"))
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = "test-key"
    calls = []
    behavior = {"subject": "user-1", "scope": DIRECT, "invalid": None, "refresh_error": None, "nonce": None}

    def respond(request):
        calls.append(request)
        if request.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"revocation_endpoint": ISSUER + "/revoke"})
        if request.url.path == "/revoke":
            return httpx.Response(200)
        if str(request.url) == RESOURCE + "/models":
            return httpx.Response(200, json={"models": [{"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
                {"slug": "account-only", "display_name": "Modelo de cuenta", "visibility": "list"}]})
        assert str(request.url) == TOKEN
        form = parse_qs(request.content.decode())
        if form["grant_type"] == ["refresh_token"]:
            if behavior["refresh_error"]:
                return httpx.Response(400 if behavior["refresh_error"] == "invalid_grant" else 503,
                    json={"error": behavior["refresh_error"]})
            assert form["client_id"] == ["oaiapp_test"] and "scope" not in form
            assert form["resource"] == [RESOURCE]
            return httpx.Response(200, json={"access_token": "rotated-synthetic", "refresh_token": "replacement-synthetic",
                "token_type": "Bearer", "scope": DIRECT, "expires_in": 3600})
        state = next(iter(conn.pending.values()), None)
        # callback consumed pending before token exchange; nonce captured by start helper below.
        nonce = behavior["nonce"] or (state or {}).get("nonce", "invalid")
        claims = {"iss": ISSUER, "aud": form["client_id"][0], "sub": behavior["subject"],
            "iat": int(time.time()), "exp": int(time.time()) + 3600, "nonce": nonce, "email": "same@example.test"}
        if behavior["invalid"]:
            claims[behavior["invalid"]] = "wrong" if behavior["invalid"] != "exp" else 1
        encoded = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
        if behavior["invalid"] == "signature":
            encoded = jwt.encode(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256", headers={"kid": "test-key"})
        return httpx.Response(200, json={"access_token": "access-synthetic", "refresh_token": "refresh-synthetic", "id_token": encoded,
            "token_type": "Bearer", "scope": behavior["scope"], "expires_in": 3600})

    monkeypatch.setattr(conn, "_http", lambda: httpx.Client(transport=httpx.MockTransport(respond)))
    return conn, calls, behavior


def start(conn, behavior, profile=None):
    response = conn.start(ConnectionStart(label="Personal", profile_id=profile), "http://127.0.0.1:8000/api/v1/auth/callback")
    params = parse_qs(urlparse(response.authorization_url).query)
    behavior["nonce"] = params["nonce"][0]
    return params


def login(conn, behavior, profile=None):
    params = start(conn, behavior, profile)
    return conn.callback(state=params["state"][0], code="synthetic-code", client_id="oaiapp_test")


def test_pkce_state_nonce_host_token_exchange_identity_and_encryption(connection):
    conn, calls, behavior = connection
    params = start(conn, behavior)
    pending = conn.pending[params["state"][0]]
    expected = base64.urlsafe_b64encode(hashlib.sha256(pending["verifier"].encode()).digest()).decode().rstrip("=")
    assert params["code_challenge"] == [expected]
    assert params["client_id"] == ["dynamic_agent_client"] and params["agent_name_hint"] == ["Umbral"]
    assert DIRECT in params["scope"][0] and params["code_challenge_method"] == ["S256"]
    with pytest.raises(Unauthorized):
        conn.callback(state="wrong", code="code", client_id="oaiapp_test")
    assert not calls
    status = conn.callback(state=params["state"][0], code="synthetic", client_id="oaiapp_test")
    assert status.profiles[0].plan_usage_enabled and status.profiles[0].active
    assert "access-synthetic" not in status.model_dump_json() and "refresh-synthetic" not in status.model_dump_json()
    request = calls[0]
    form = parse_qs(request.content.decode())
    assert form["code_verifier"] == [pending["verifier"]] and form["redirect_uri"] == params["redirect_uri"]
    assert form["client_id"] == ["oaiapp_test"] and "client_secret" not in form
    raw = conn.store.path.read_bytes()
    import os

    if os.name == "nt":
        assert raw.startswith(b"UMBRAL-DPAPI") and b"access-synthetic" not in raw
    else:
        assert conn.store.path.stat().st_mode & 0o077 == 0
    second = start(conn, behavior, status.active_profile_id)
    assert second["ext_agent_host_id"] == params["ext_agent_host_id"]
    assert second["client_id"] == ["oaiapp_test"] and "agent_name_hint" not in second
    assert "id_token_hint" in second
    with pytest.raises(Unauthorized):
        conn.callback(state=params["state"][0], code="reused", client_id="oaiapp_test")


@pytest.mark.parametrize("invalid", ["iss", "aud", "exp", "nonce", "signature"])
def test_id_token_security_rejects_wrong_claims_without_persisting(connection, invalid):
    conn, _, behavior = connection
    behavior["invalid"] = invalid
    with pytest.raises(Unauthorized):
        login(conn, behavior)
    assert conn.status().profiles == []


def test_returning_account_identity_and_client_cannot_be_replaced(connection):
    conn, calls, behavior = connection
    original = login(conn, behavior)
    params = start(conn, behavior, original.active_profile_id)
    count = len(calls)
    with pytest.raises(Unauthorized):
        conn.callback(state=params["state"][0], code="c", client_id="different-client")
    assert len(calls) == count
    behavior["subject"] = "another-account"
    with pytest.raises(Unauthorized):
        login(conn, behavior, original.active_profile_id)
    assert conn.status() == original


def test_distinct_account_profiles_catalog_filter_and_selected_model(connection):
    conn, calls, behavior = connection
    first = login(conn, behavior)
    conn.choose_model("account-only")
    with pytest.raises(Unprocessable):
        conn.choose_model("hidden")
    behavior["subject"] = "user-2"
    second = login(conn, behavior)
    assert len(second.profiles) == 2 and second.profiles[0].email == second.profiles[1].email
    assert second.active_profile_id != first.active_profile_id
    assert conn.models().selected_model is None
    assert calls[-1].headers["authorization"] == "Bearer access-synthetic"
    conn.select(first.active_profile_id)
    assert conn.models().selected_model == "account-only"


def test_refresh_rotates_and_persists_credential_set(connection):
    conn, _, behavior = connection
    login(conn, behavior)
    saved = conn.store.read()
    saved["profiles"][saved["active"]]["expires_at"] = 1
    conn.store.write(saved)
    credentials = conn.credentials()
    assert credentials["access_token"] == "rotated-synthetic" and credentials["refresh_token"] == "replacement-synthetic"
    again = conn.store.read()["profiles"][saved["active"]]
    assert again["expires_at"] > time.time() and again["refresh_token"] == "replacement-synthetic"


@pytest.mark.parametrize("error", ["invalid_grant", "temporary_failure"])
def test_terminal_refresh_clears_tokens_but_transient_preserves_them(connection, error):
    conn, _, behavior = connection
    login(conn, behavior)
    saved = conn.store.read()
    saved["profiles"][saved["active"]]["expires_at"] = 1
    conn.store.write(saved)
    behavior["refresh_error"] = error
    with pytest.raises(Unauthorized if error == "invalid_grant" else ServiceUnavailable):
        conn.credentials()
    profile = conn.store.read()["profiles"][saved["active"]]
    assert ("access_token" not in profile) if error == "invalid_grant" else profile["access_token"] == "access-synthetic"


def test_declined_permission_never_allows_inference_and_signout_revokes(connection):
    conn, calls, behavior = connection
    behavior["scope"] = "openid email"
    status = login(conn, behavior)
    assert status.profiles[0].connected and not status.profiles[0].plan_usage_enabled
    with pytest.raises(Unauthorized):
        conn.models()
    result = conn.disconnect(status.active_profile_id)
    assert result.remote_revocation_confirmed
    assert calls[-1].url.path == "/revoke"
    assert not conn.status().profiles[0].connected


def test_connection_routes_reject_remote_clients_origin_and_web(make_app, tmp_path, monkeypatch):
    import umbral_api.connections as module

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path / "workspace")
    client = make_app(auth_mode="local", chatgpt_credentials_file=tmp_path / "private" / "conn.dat")
    assert client.get("/api/v1/connections/chatgpt").status_code == 200
    assert client.post("/api/v1/connections/chatgpt/start", json={}, headers={"Origin": "https://attacker.test"}).status_code == 403
    assert client.get("/api/v1/connections/chatgpt", headers={"Host": "attacker.test"}).status_code == 403


def test_desktop_oauth_callback_works_without_renderer_token(make_app, tmp_path, monkeypatch):
    import umbral_api.connections as module

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path / "workspace")
    client = make_app(auth_mode="local", desktop_token="ephemeral-desktop-token",
                      chatgpt_credentials_file=tmp_path / "private" / "chatgpt.dat")
    connection = client.svc.providers["chatgpt"].connection
    monkeypatch.setattr(connection, "callback", lambda **_: connection.status())

    response = client.get("/api/v1/auth/callback", params={
        "state": "valid-test-state", "code": "synthetic-code", "client_id": "test-client",
    })

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "ChatGPT conectado" in response.text
    assert "se actualizará automáticamente" in response.text
    assert client.get("/api/v1/health").status_code == 403
    assert client.get("/api/v1/auth/callback", params={"state": "valid-test-state", "code": "x"},
                      headers={"Origin": "https://auth.openai.com"}).status_code == 403


def test_offline_does_not_call_transport(connection):
    from dataclasses import replace

    conn, calls, behavior = connection
    login(conn, behavior)
    conn.settings = replace(conn.settings, offline=True)
    previous = len(calls)
    with pytest.raises(ServiceUnavailable):
        conn.models()
    assert len(calls) == previous


def test_separate_managers_serialize_refresh_and_share_rotating_token(connection, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    conn, calls, behavior = connection
    login(conn, behavior)
    saved = conn.store.read()
    saved["profiles"][saved["active"]]["expires_at"] = 1
    conn.store.write(saved)
    other = ChatGPTConnections(conn.settings)
    monkeypatch.setattr(other, "_http", conn._http)
    before = len(calls)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda manager: manager.credentials()["access_token"], [conn, other]))
    assert results == ["rotated-synthetic", "rotated-synthetic"]
    assert len(calls) - before == 1


def test_personal_provider_uses_selected_profile_after_restart(connection, monkeypatch):
    from umbral_api.providers import ChatGPTProvider, stub_output_from_prompt

    from .test_provider_contracts import PROMPT, sse

    conn, _, behavior = connection
    status = login(conn, behavior)
    conn.choose_model("account-only")
    provider = ChatGPTProvider(conn.settings)
    assert provider.status().available
    assert provider.status().model == "account-only"
    captured = []

    def response(request):
        captured.append(request)
        assert request.headers["authorization"] == "Bearer access-synthetic"
        return httpx.Response(200, text=sse({"type": "response.output_text.delta", "delta": stub_output_from_prompt(PROMPT).model_dump_json()},
            {"type": "response.completed"}))

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: httpx.Client(transport=httpx.MockTransport(response)).stream(*args, **kwargs))
    result = provider.generate("sistema", PROMPT)
    assert result.model == "account-only"
    assert json.loads(captured[0].content)["model"] == "account-only"
    assert status.active_profile_id == provider.connection.status().active_profile_id
