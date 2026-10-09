"""OAuth de conectores: callbacks simulados, credenciales cifradas y aislamiento por UID."""

from __future__ import annotations

import base64
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.auth import Authenticator
from umbral_api.connectors import ConnectorManager, MemoryConnectorStore
from umbral_api.errors import Unauthorized
from umbral_api.services import Services

from .conftest import make_settings

API = "/api/v1"
TOKEN_NOT_FOR_RESPONSE = "oauth-secret-token-never-return"
ENCRYPTION_KEY = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")


def _response(payload, status=200):
    return SimpleNamespace(status_code=status, is_success=200 <= status < 300, json=lambda: payload)


def _client(make_app, *, configured=True):
    settings = {
        "auth_mode": "dev-header",
        "firestore_project": "connector-test-project",
        "connector_encryption_key": ENCRYPTION_KEY,
        "notion_oauth_client_id": "notion-client-test" if configured else None,
        "notion_oauth_client_secret": "notion-secret-test" if configured else None,
        "notion_oauth_redirect_uri": "https://api.example.test/api/v1/connectors/notion/callback" if configured else None,
        "slack_oauth_client_id": "slack-client-test" if configured else None,
        "slack_oauth_client_secret": "slack-secret-test" if configured else None,
        "slack_oauth_redirect_uri": "https://api.example.test/api/v1/connectors/slack/callback" if configured else None,
    }
    client = make_app(**settings)
    store = MemoryConnectorStore()
    manager = ConnectorManager(client.app.state.settings, store)
    client.app.state.connector_manager = manager
    return client, store, manager


def _state(client, provider: str) -> str:
    result = client.post(f"{API}/connectors/{provider}/start")
    assert result.status_code == 200
    query = parse_qs(urlparse(result.json()["authorizationUrl"]).query)
    return query["state"][0]


def _connect_notion(client, monkeypatch):
    monkeypatch.setattr("umbral_api.connectors.httpx.post", lambda *args, **kwargs: _response({
        "access_token": TOKEN_NOT_FOR_RESPONSE,
        "refresh_token": "notion-refresh-secret",
        "workspace_id": "workspace-notion-1",
        "workspace_name": "Redacción",
        "bot_id": "bot-1",
    }))
    state = _state(client, "notion")
    response = client.get(f"{API}/connectors/notion/callback", params={"state": state, "code": "oauth-code-test"})
    assert response.status_code == 200
    assert TOKEN_NOT_FOR_RESPONSE not in response.text
    assert "refresh-secret" not in response.text
    return response


def _connect_slack(client, monkeypatch):
    monkeypatch.setattr("umbral_api.connectors.httpx.post", lambda *args, **kwargs: _response({
        "ok": True,
        "access_token": TOKEN_NOT_FOR_RESPONSE,
        "refresh_token": "slack-refresh-secret",
        "expires_in": 43_200,
        "team": {"id": "team-1", "name": "Mesa editorial"},
        "bot_user_id": "bot-2",
        "scope": "chat:write,channels:read,groups:read",
    }))
    state = _state(client, "slack")
    response = client.get(f"{API}/connectors/slack/callback", params={"state": state, "code": "oauth-code-test"})
    assert response.status_code == 200
    assert TOKEN_NOT_FOR_RESPONSE not in response.text
    return response


def test_missing_oauth_configuration_is_unavailable_and_callback_state_is_single_use(make_app):
    client, _, _ = _client(make_app, configured=False)
    overview = client.get(f"{API}/connectors")
    assert overview.status_code == 200
    assert overview.json()["providers"]["notion"]["available"] is False
    assert overview.json()["providers"]["slack"]["available"] is False
    assert "token" not in overview.text.lower()
    assert client.post(f"{API}/connectors/notion/start").status_code == 503

    response = client.get(f"{API}/connectors/notion/callback", params={"state": "invalid-state", "code": "unused"})
    assert response.status_code == 400
    assert TOKEN_NOT_FOR_RESPONSE not in response.text
    assert "invalid-state" not in response.text


def test_public_connector_routes_use_firebase_uid_and_leave_editorial_routes_stateless(fixture_dir, monkeypatch):
    settings = make_settings(fixture_dir, auth_mode="public", persistence="none", local_mode=False, firestore_project="test-project")
    client = TestClient(create_app(settings, services=Services(settings)))
    client.app.state.connector_manager = ConnectorManager(settings, MemoryConnectorStore())
    original = Authenticator.user_for

    def fake_verify(self, request):
        if self.mode == "firebase":
            if request.headers.get("authorization") == "Bearer valid-anonymous-id-token":
                return "anonymous-uid"
            raise Unauthorized("Token de Firebase inválido o no verificable.")
        return original(self, request)

    monkeypatch.setattr(Authenticator, "user_for", fake_verify)
    assert client.get(f"{API}/connectors").status_code == 401
    authorized = client.get(f"{API}/connectors", headers={"Authorization": "Bearer valid-anonymous-id-token"})
    assert authorized.status_code == 200
    assert authorized.json()["providers"]["notion"]["connected"] is False
    assert client.post(f"{API}/cases/no-case/review", headers={"Authorization": "Bearer valid-anonymous-id-token"}).status_code == 403


def test_notion_oauth_credential_is_encrypted_scoped_and_used_for_destination_export(make_app, monkeypatch):
    client, store, _ = _client(make_app)
    exchange_calls = []
    monkeypatch.setattr("umbral_api.connectors.httpx.post", lambda url, **kwargs: exchange_calls.append((url, kwargs)) or _response({
        "access_token": TOKEN_NOT_FOR_RESPONSE,
        "refresh_token": "notion-refresh-secret",
        "workspace_id": "workspace-notion-1",
        "workspace_name": "Redacción",
        "bot_id": "bot-1",
    }))
    state = _state(client, "notion")
    response = client.get(f"{API}/connectors/notion/callback", params={"state": state, "code": "oauth-code-test"})
    assert response.status_code == 200
    assert TOKEN_NOT_FOR_RESPONSE not in response.text
    assert TOKEN_NOT_FOR_RESPONSE not in next(iter(store.credentials.values()))
    assert exchange_calls[0][0] == "https://api.notion.com/v1/oauth/token"
    assert exchange_calls[0][1]["json"]["redirect_uri"].endswith("/connectors/notion/callback")

    other = client.get(f"{API}/connectors", headers={"X-Umbral-User": "other-user"})
    own = client.get(f"{API}/connectors")
    assert other.json()["providers"]["notion"]["connected"] is False
    assert own.json()["providers"]["notion"]["connected"] is True
    assert own.json()["providers"]["notion"]["workspaceName"] == "Redacción"
    assert TOKEN_NOT_FOR_RESPONSE not in own.text

    calls = []

    def notion_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/search"):
            return _response({"results": [{"id": "page-1", "url": "https://www.notion.so/page-1", "properties": {"Nombre": {"title": [{"plain_text": "Agenda TVN"}]}}}], "has_more": False})
        return _response({"id": "created-page", "url": "https://www.notion.so/created-page"})

    monkeypatch.setattr("umbral_api.connectors.httpx.request", notion_request)
    pages = client.get(f"{API}/connectors/notion/pages")
    assert pages.json() == {"items": [{"id": "page-1", "title": "Agenda TVN", "url": "https://www.notion.so/page-1"}]}
    assert client.put(f"{API}/connectors/notion/destination", json={"pageId": "page-1"}).json() == {"saved": True}
    exported = client.post(f"{API}/connectors/notion/export", json={"markdown": "# Ficha: Caso\n\nEvidencia."})
    assert exported.status_code == 200
    assert exported.json() == {"pageId": "created-page", "url": "https://www.notion.so/created-page", "title": "Ficha: Caso"}
    assert calls[-1][2]["json"]["parent"] == {"page_id": "page-1"}
    assert calls[-1][2]["headers"]["Authorization"] == f"Bearer {TOKEN_NOT_FOR_RESPONSE}"
    assert TOKEN_NOT_FOR_RESPONSE not in exported.text
    assert "parent-page" not in exported.text


def test_notion_callback_rejection_expiry_and_refresh_rotate_server_side(make_app, monkeypatch):
    client, store, manager = _client(make_app)
    state = _state(client, "notion")
    denied = client.get(f"{API}/connectors/notion/callback", params={"state": state, "error": "access_denied"})
    assert denied.status_code == 400
    assert "No se completó" in denied.text
    assert state not in store.states

    store.save_oauth_state("expired", {"uid": "ana", "provider": "notion", "expires_at": int(time.time()) - 1})
    assert client.get(f"{API}/connectors/notion/callback", params={"state": "expired", "code": "code"}).status_code == 400

    manager._put_credential("ana", "notion", {"access_token": "old-access", "refresh_token": "old-refresh", "expires_at": int(time.time()) - 10, "workspace_name": "Redacción"})
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _response({"access_token": "new-access", "refresh_token": "new-refresh"})

    monkeypatch.setattr("umbral_api.connectors.httpx.post", post)
    monkeypatch.setattr("umbral_api.connectors.httpx.request", lambda method, url, **kwargs: _response({"results": [], "has_more": False}))
    assert client.get(f"{API}/connectors/notion/pages").status_code == 200
    assert calls[0][1]["json"] == {"grant_type": "refresh_token", "refresh_token": "old-refresh"}
    assert manager._get_credential("ana", "notion")["access_token"] == "new-access"


def test_slack_channel_selection_notifications_deduplicate_and_do_not_leak_token(make_app, monkeypatch):
    client, store, _ = _client(make_app)
    _connect_slack(client, monkeypatch)
    overview = client.get(f"{API}/connectors").json()
    assert overview["slackNotifications"] == {"enabled": False, "statuses": []}
    assert TOKEN_NOT_FOR_RESPONSE not in str(overview)

    monkeypatch.setattr("umbral_api.connectors.httpx.get", lambda url, **kwargs: _response({
        "ok": True,
        "channels": [
            {"id": "C-public", "name": "editorial", "is_private": False, "is_member": True},
            {"id": "G-private", "name": "investigación", "is_private": True, "is_member": True},
            {"id": "C-not-member", "name": "otro", "is_private": False, "is_member": False},
        ],
        "response_metadata": {"next_cursor": ""},
    }))
    channels = client.get(f"{API}/connectors/slack/channels")
    assert channels.json() == {"items": [{"id": "C-public", "name": "editorial", "isPrivate": False}, {"id": "G-private", "name": "investigación", "isPrivate": True}]}
    assert client.put(f"{API}/connectors/slack/channel", json={"channelId": "C-public"}).json() == {"saved": True}
    assert client.put(f"{API}/connectors/slack/notifications", json={"enabled": True, "channelId": "C-public", "statuses": ["aprobado_como_borrador"]}).json() == {"saved": True}

    posts = []
    monkeypatch.setattr("umbral_api.connectors.httpx.post", lambda url, **kwargs: posts.append((url, kwargs)) or _response({"ok": True, "ts": "1.23"}))
    event = {"eventId": "review:case-x:3:aprobado_como_borrador", "caseId": "case-x", "caseVersion": 3, "title": "Tema de ejemplo", "status": "aprobado_como_borrador", "fromStatus": "en_revision", "snapshotId": "20261008-aabbccdd"}
    sent = client.post(f"{API}/connectors/slack/review-event", json=event)
    duplicate = client.post(f"{API}/connectors/slack/review-event", json=event)
    skipped = client.post(f"{API}/connectors/slack/review-event", json={**event, "eventId": "review:case-x:4:descartado", "status": "descartado"})
    assert sent.json() == {"sent": True, "duplicate": False, "skippedReason": None}
    assert duplicate.json()["duplicate"] is True
    assert skipped.json()["sent"] is False
    assert len(posts) == 1
    assert posts[0][0] == "https://slack.com/api/chat.postMessage"
    assert posts[0][1]["json"]["channel"] == "C-public"
    assert posts[0][1]["json"]["mrkdwn"] is False
    assert TOKEN_NOT_FOR_RESPONSE not in sent.text
    assert all(value != TOKEN_NOT_FOR_RESPONSE for value in store.credentials.values())


def test_slack_refresh_rotates_tokens_and_revocation_clears_connection(make_app, monkeypatch):
    client, store, manager = _client(make_app)
    _connect_slack(client, monkeypatch)
    manager._put_credential("ana", "slack", {
        "access_token": "slack-old-access",
        "refresh_token": "slack-old-refresh",
        "expires_at": int(time.time()) - 1,
        "team_id": "team-1",
        "workspace_name": "Mesa editorial",
    })
    refresh_calls = []

    def refresh(url, **kwargs):
        refresh_calls.append((url, kwargs))
        return _response({"ok": True, "access_token": "slack-new-access", "refresh_token": "slack-new-refresh", "expires_in": 43_200})

    monkeypatch.setattr("umbral_api.connectors.httpx.post", refresh)
    requests = []
    monkeypatch.setattr("umbral_api.connectors.httpx.get", lambda url, **kwargs: requests.append((url, kwargs)) or _response({"ok": True, "channels": [], "response_metadata": {"next_cursor": ""}}))
    channels = client.get(f"{API}/connectors/slack/channels")
    assert channels.status_code == 200
    assert refresh_calls[0][0] == "https://slack.com/api/oauth.v2.access"
    assert refresh_calls[0][1]["data"]["grant_type"] == "refresh_token"
    assert refresh_calls[0][1]["data"]["refresh_token"] == "slack-old-refresh"
    assert requests[0][1]["headers"]["Authorization"] == "Bearer slack-new-access"
    assert manager._get_credential("ana", "slack")["refresh_token"] == "slack-new-refresh"
    assert "slack-new-access" not in channels.text

    monkeypatch.setattr("umbral_api.connectors.httpx.get", lambda *args, **kwargs: _response({"ok": False, "error": "token_revoked"}))
    revoked = client.get(f"{API}/connectors/slack/channels")
    assert revoked.status_code == 401
    assert client.get(f"{API}/connectors").json()["providers"]["slack"]["connected"] is False
    assert store.credentials == {}


def test_slack_failure_and_wrong_channel_are_sanitized_and_retryable(make_app, monkeypatch):
    client, store, manager = _client(make_app)
    _connect_slack(client, monkeypatch)
    channels = [{"id": "C-public", "name": "editorial", "is_private": False, "is_member": True}]
    monkeypatch.setattr("umbral_api.connectors.httpx.get", lambda *args, **kwargs: _response({"ok": True, "channels": channels, "response_metadata": {"next_cursor": ""}}))
    assert client.put(f"{API}/connectors/slack/channel", json={"channelId": "C-public"}).status_code == 200
    assert client.put(f"{API}/connectors/slack/notifications", json={"enabled": True, "channelId": "C-public", "statuses": ["en_revision"]}).status_code == 200
    assert client.put(f"{API}/connectors/slack/notifications", json={"enabled": True, "channelId": "C-forged", "statuses": ["en_revision"]}).status_code == 403

    monkeypatch.setattr("umbral_api.connectors.httpx.post", lambda *args, **kwargs: _response({"ok": False, "error": "channel_not_found", "detail": TOKEN_NOT_FOR_RESPONSE}))
    event = {"eventId": "review:case-x:4:en_revision", "caseId": "case-x", "caseVersion": 4, "title": "Tema", "status": "en_revision", "fromStatus": "nuevo", "snapshotId": "20261008-aabbccdd"}
    failed = client.post(f"{API}/connectors/slack/review-event", json=event)
    assert failed.status_code == 503
    assert TOKEN_NOT_FOR_RESPONSE not in failed.text
    assert "channel_not_found" not in failed.text
    assert manager._preferences("ana")["slack_enabled"] is True
    assert store.events[("ana", event["eventId"])] == "failed"


def test_oauth_callbacks_and_disconnect_never_return_or_cross_user_tokens(make_app, monkeypatch):
    client, store, _ = _client(make_app)
    _connect_notion(client, monkeypatch)
    result = client.delete(f"{API}/connectors/notion")
    assert result.json() == {"disconnected": True}
    assert client.get(f"{API}/connectors").json()["providers"]["notion"]["connected"] is False
    assert store.credentials == {}
