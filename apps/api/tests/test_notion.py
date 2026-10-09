"""Exportación a Notion: rutas locales y transporte externo simulado."""

from __future__ import annotations

from types import SimpleNamespace

API = "/api/v1"


def _existing_case_id(client) -> str:
    topic_id = client.get(f"{API}/topics", params={"limit": 1}).json()["items"][0]["id"]
    return f"case-{topic_id}"


def test_notion_status_and_export_use_current_markdown_without_exposing_secret(make_app, monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return SimpleNamespace(
            is_success=True,
            status_code=200,
            json=lambda: {"id": "page-id-test", "url": "https://www.notion.so/page-id-test"},
        )

    monkeypatch.setattr("umbral_api.notion.httpx.post", fake_post)
    client = make_app(
        auth_mode="local",
        notion_api_key="secret-not-for-response",
        notion_parent_page_id="parent-page-id",
    )

    status = client.get(f"{API}/notion/status")
    assert status.status_code == 200
    assert status.json() == {"configured": True}
    assert "secret-not-for-response" not in status.text
    assert calls == []  # Consultar el estado no llama a Notion.

    result = client.post(f"{API}/cases/{_existing_case_id(client)}/export/notion")
    assert result.status_code == 200
    body = result.json()
    assert body == {
        "pageId": "page-id-test",
        "url": "https://www.notion.so/page-id-test",
        "title": body["title"],
    }
    assert body["title"].startswith("Ficha:")
    assert "secret-not-for-response" not in result.text
    assert len(calls) == 1
    url, headers, payload, timeout = calls[0]
    assert url == "https://api.notion.com/v1/pages"
    assert headers["Authorization"] == "Bearer secret-not-for-response"
    assert headers["Notion-Version"] == "2026-03-11"
    assert payload["parent"] == {"page_id": "parent-page-id"}
    assert payload["markdown"].startswith("# Ficha:")
    assert "children" not in payload
    assert timeout > 0


def test_notion_missing_config_is_boolean_and_export_does_not_call_network(make_app, monkeypatch):
    calls = []
    monkeypatch.setattr("umbral_api.notion.httpx.post", lambda *args, **kwargs: calls.append((args, kwargs)))
    client = make_app(auth_mode="local")

    assert client.get(f"{API}/notion/status").json() == {"configured": False}
    result = client.post(f"{API}/cases/{_existing_case_id(client)}/export/notion")
    assert result.status_code == 503
    assert result.json()["code"] == "no_disponible"
    assert calls == []


def test_notion_routes_are_forbidden_outside_local_auth(make_app, monkeypatch):
    calls = []
    monkeypatch.setattr("umbral_api.notion.httpx.post", lambda *args, **kwargs: calls.append((args, kwargs)))
    client = make_app()  # dev-header; no localhost personal connections or writes

    assert client.get(f"{API}/notion/status").status_code == 403
    assert client.post(f"{API}/cases/{_existing_case_id(client)}/export/notion").status_code == 403
    assert calls == []


def test_notion_error_does_not_forward_remote_body_or_secret(make_app, monkeypatch):
    class FakeResponse:
        is_success = False
        status_code = 403

        @staticmethod
        def json():
            return {"message": "secret-not-for-response leaked"}

        @property
        def text(self):
            return "secret-not-for-response leaked"

    monkeypatch.setattr("umbral_api.notion.httpx.post", lambda *args, **kwargs: FakeResponse())
    client = make_app(auth_mode="local", notion_api_key="secret-not-for-response", notion_parent_page_id="parent")

    result = client.post(f"{API}/cases/{_existing_case_id(client)}/export/notion")
    assert result.status_code == 503
    assert "integración" in result.json()["message"]
    assert "secret-not-for-response" not in result.text
    assert "leaked" not in result.text
