"""Identidad de cuota tras un edge explícito; cabeceras de visitantes no confiables."""

from __future__ import annotations

import pytest
from fastapi import Request

from umbral_api.auth import Authenticator
from umbral_api.config import Settings

from .test_public import API, context, public_app


def request(headers=(), *, client=("10.0.0.4", 8080)):
    return Request({"type": "http", "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
                    "client": client})


def test_public_socket_identity_ignores_spoofed_headers_by_default():
    auth = Authenticator("public")
    assert auth.user_for(request([("CF-Connecting-IP", "203.0.113.1"),
                                  ("X-Forwarded-For", "198.51.100.5")])) == "ip:10.0.0.4"


def test_local_session_ignores_cf_and_forwarded_spoof():
    auth = Authenticator("local")
    assert auth.user_for(request([("CF-Connecting-IP", "203.0.113.1"),
                                  ("X-Forwarded-For", "198.51.100.5")], client=("127.0.0.1", 8080))) == "local"


@pytest.mark.parametrize(("header", "identity"), [
    ("203.0.113.8", "ip:203.0.113.8"),
    (" 2001:0db8:0000::1 ", "ip:2001:db8::1"),
    ("::ffff:203.0.113.8", "ip:203.0.113.8"),
])
def test_cf_single_valid_ip_is_canonical_only_when_enabled(header, identity):
    auth = Authenticator("public", trust_cloudflare_ip=True)
    assert auth.user_for(request([("CF-Connecting-IP", header), ("X-Forwarded-For", "198.51.100.5")])) == identity


@pytest.mark.parametrize("header", [None, "", "unknown", "203.0.113.1, 203.0.113.2", "203.0.113.1:8080",
                                    "[2001:db8::1]", "fe80::1%ethernet", "999.1.2.3", "010.0.0.1"])
def test_cf_missing_or_invalid_falls_back_to_socket_without_xff(header):
    headers = [("X-Forwarded-For", "198.51.100.5")]
    if header is not None:
        headers.append(("CF-Connecting-IP", header))
    assert Authenticator("public", trust_cloudflare_ip=True).user_for(request(headers)) == "ip:10.0.0.4"


def test_duplicate_cf_headers_fall_back_to_socket():
    auth = Authenticator("public", trust_cloudflare_ip=True)
    assert auth.user_for(request([("CF-Connecting-IP", "203.0.113.1"),
                                  ("CF-Connecting-IP", "203.0.113.2")])) == "ip:10.0.0.4"


@pytest.mark.parametrize(("mode", "local_mode", "persistence"), [
    ("local", True, "memory"), ("dev-header", True, "memory"),
    ("firebase", False, "firestore"), ("public", True, "none"),
])
def test_cf_trust_rejects_other_modes_and_local_execution(mode, local_mode, persistence):
    with pytest.raises(RuntimeError, match="UMBRAL_TRUST_CLOUDFLARE_IP"):
        Settings(auth_mode=mode, local_mode=local_mode, persistence=persistence,
                 firestore_project="test-project", trust_cloudflare_ip=True).validate()


def test_settings_env_can_enable_cf_only_explicitly(monkeypatch):
    monkeypatch.setattr("umbral_api.config.load_dotenv_files", lambda: None)
    monkeypatch.setenv("UMBRAL_AUTH_MODE", "public")
    monkeypatch.setenv("UMBRAL_LOCAL_MODE", "0")
    monkeypatch.setenv("UMBRAL_PERSISTENCE", "none")
    monkeypatch.delenv("UMBRAL_TRUST_CLOUDFLARE_IP", raising=False)
    assert Settings.from_env().trust_cloudflare_ip is False
    monkeypatch.setenv("UMBRAL_TRUST_CLOUDFLARE_IP", "1")
    settings = Settings.from_env()
    settings.validate()
    assert settings.trust_cloudflare_ip is True


def test_cf_client_ips_have_independent_rate_limits_behind_one_socket(fixture_dir):
    client, svc = public_app(fixture_dir, trust_cloudflare_ip=True, queries_per_minute=1)
    payload = {"context": context(svc), "question": "inflación en Panamá"}
    assert client.post(API + "/public/queries", json=payload, headers={"CF-Connecting-IP": "203.0.113.1"}).status_code == 200
    assert client.post(API + "/public/queries", json=payload, headers={"CF-Connecting-IP": "203.0.113.2"}).status_code == 200
    assert client.post(API + "/public/queries", json=payload, headers={"CF-Connecting-IP": "203.0.113.1",
                                                                       "X-Forwarded-For": "198.51.100.5"}).status_code == 429


def test_without_cf_trust_or_valid_cf_same_proxy_keeps_shared_limit(fixture_dir):
    client, svc = public_app(fixture_dir, trust_cloudflare_ip=False, queries_per_minute=1)
    payload = {"context": context(svc), "question": "inflación en Panamá"}
    assert client.post(API + "/public/queries", json=payload, headers={"CF-Connecting-IP": "203.0.113.1"}).status_code == 200
    assert client.post(API + "/public/queries", json=payload, headers={"CF-Connecting-IP": "203.0.113.2"}).status_code == 429
    client, svc = public_app(fixture_dir, trust_cloudflare_ip=True, queries_per_minute=1)
    payload["context"] = context(svc)
    assert client.post(API + "/public/queries", json=payload).status_code == 200
    assert client.post(API + "/public/queries", json=payload, headers={"CF-Connecting-IP": "invalid",
                                                                       "X-Forwarded-For": "198.51.100.5"}).status_code == 429
