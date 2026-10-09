"""Recorrido offline sobre CURRENT real; la revisión automatizada usa SQLite temporal."""

from pathlib import Path
from urllib.parse import urlparse

import pytest
from e2e.helpers import ask, draft_and_review, open_app, open_first_ficha, tid
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_snapshot_real_carga_consulta_ficha_borrador_revision_y_export(context, page, delivered_stack):
    blocked = []

    def guard(route):
        if urlparse(route.request.url).hostname in {"localhost", "127.0.0.1"}:
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort("internetdisconnected")

    context.route("**/*", guard)
    with delivered_stack.client(user=None) as api:
        health = api.get("/health").json()
        assert health["containsFixtures"] is False and health["classifier"] == "laya"
        assert health["offline"] and health["integrity"]["manifestVerified"]
        first = api.get("/topics", params={"limit": 1}).json()["items"][0]
        detail = api.get(f"/topics/{first['id']}").json()
        title = detail["articles"][0]["title"]

    open_app(page, delivered_stack.url, role="juror")
    expect(tid(page, "snapshot-badge")).to_contain_text(health["snapshotId"])
    expect(tid(page, "offline-indicator")).to_be_visible()
    assert tid(page, "mock-banner").count() == 0
    ask(page, f"¿Qué evidencia hay sobre {title}?", 1)
    expect(tid(page, "assistant-answer")).not_to_have_attribute("data-status", "abstencion")
    assert tid(page, "assistant-citation").count() >= 1
    assert open_first_ficha(page) == first["id"]
    draft_and_review(page, "Prueba automatizada: no constituye aprobación humana")
    expect(tid(page, "draft-origin-label")).to_have_attribute("data-mode", "plantilla")
    expect(tid(page, "draft-factual-coverage")).to_have_attribute("data-value", "1")
    expect(tid(page, "export-preview")).to_contain_text(health["snapshotId"])
    assert blocked == [], f"el navegador intentó salir a internet: {blocked[:5]}"
    log = Path(delivered_stack.workdir) / "netblock.log"
    assert not log.exists() or not log.read_text(encoding="utf-8").strip()
