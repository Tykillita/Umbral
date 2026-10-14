"""Arranque con el backend dormido (Render Free): la interfaz se pinta ya, con datos guardados o con esqueletos."""
from __future__ import annotations

import json

import pytest
from e2e.helpers import open_app, tid
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

HEALTH = "**/api/v1/health"


def sleeping_backend(page) -> None:
    """El servidor de Render que despierta responde 503 a /health hasta que arranca."""
    page.route(
        HEALTH,
        lambda route: route.fulfill(
            status=503, content_type="application/json",
            body=json.dumps({"code": "iniciando", "message": "El servicio está iniciando."}),
        ),
    )


def test_segunda_visita_muestra_la_agenda_guardada_mientras_el_servidor_despierta(page, public_stack):
    open_app(page, public_stack.url, role="editor")
    first_titles = tid(page, "topic-card").locator("h3").all_inner_texts()
    assert first_titles
    page.wait_for_timeout(2500)  # la copia local se guarda ~1 s después de recibir los datos

    sleeping_backend(page)
    page.reload()
    expect(tid(page, "topic-card").first).to_be_visible(timeout=10_000)
    assert tid(page, "topic-card").locator("h3").all_inner_texts() == first_titles
    expect(tid(page, "boot-notice")).to_contain_text("datos guardados")
    expect(tid(page, "app-loading")).to_have_count(0)
    expect(tid(page, "nav-agenda")).to_be_visible()
    expect(tid(page, "snapshot-badge")).to_have_count(0)  # el estado guardado no se presenta como en vivo

    page.unroute(HEALTH)  # el siguiente intento (≤3 s) ya encuentra el servidor despierto
    expect(tid(page, "boot-notice")).to_have_count(0, timeout=20_000)
    expect(tid(page, "snapshot-badge")).to_be_visible(timeout=20_000)
    expect(tid(page, "topic-card").first).to_be_visible()


def test_primera_visita_pinta_toda_la_app_con_esqueletos(page, public_stack):
    sleeping_backend(page)
    page.goto(public_stack.url + "/app")
    tid(page, "role-editor").click()
    expect(tid(page, "app-root")).to_be_visible(timeout=10_000)
    expect(tid(page, "agenda-skeleton")).to_be_visible()
    expect(tid(page, "skeleton-card")).to_have_count(5)
    expect(tid(page, "agenda-search")).to_be_visible()
    expect(tid(page, "boot-notice")).to_contain_text("Despertando el servidor")
    expect(tid(page, "app-loading")).to_have_count(0)

    page.unroute(HEALTH)
    expect(tid(page, "topic-card").first).to_be_visible(timeout=30_000)
    expect(tid(page, "agenda-skeleton")).to_have_count(0)
    expect(tid(page, "boot-notice")).to_have_count(0)
