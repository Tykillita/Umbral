"""«Hoy» y estado vacío: sin corte vigente la agenda queda en blanco con un mensaje claro; el rol Jurado ve una demostración rotulada."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import open_app, tid
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.e2e

DIST = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"


@pytest.fixture(scope="module")
def empty_stack(server_factory):
    """API con la política de antigüedad activa: el corte sintético (7 de octubre) ya es más viejo que 36 h."""
    if not (DIST / "index.html").exists():
        pytest.fail("falta apps/web/dist (ejecuta scripts/build-web.ps1)", pytrace=False)
    with server_factory(web_dist=DIST, UMBRAL_AUTH_MODE="local", UMBRAL_HIDE_STALE_SNAPSHOT_HOURS="36") as srv:
        yield srv


def _open(page: Page, base: str, role: str) -> None:
    """Abre /app con el rol pedido, haya o no pantalla de elegir rol al entrar."""
    page.goto(base + "/app")
    gate = page.get_by_test_id(f"role-{role}")
    page.locator("[data-testid='app-root'], [data-testid='session-gate']").first.wait_for(timeout=20_000)
    if gate.is_visible():
        gate.click()
    expect(page.get_by_test_id("app-root")).to_be_visible(timeout=15_000)
    if role != "editor" or page.get_by_test_id("active-role").count():
        label = page.get_by_test_id("active-role").inner_text()
        wanted = {"juror": "Jurado", "editor": "Editor"}[role]
        if wanted.lower() not in label.lower():
            page.get_by_test_id("role-change").click()
            page.get_by_test_id(f"role-{role}").click()
            expect(page.get_by_test_id("app-root")).to_be_visible(timeout=15_000)


@pytest.mark.parametrize("ancho,alto,tactil", [(1366, 900, False), (390, 844, True), (320, 640, True)])
def test_sin_corte_vigente_la_agenda_queda_vacia_y_lo_explica(browser: Browser, empty_stack, ancho: int, alto: int, tactil: bool):
    ctx = browser.new_context(viewport={"width": ancho, "height": alto}, has_touch=tactil, is_mobile=tactil, locale="es-PA", timezone_id="America/Panama")
    try:
        page = ctx.new_page()
        _open(page, empty_stack.url, "editor")
        notice = tid(page, "agenda-no-news-notice")
        expect(notice).to_be_visible(timeout=20_000)
        expect(notice).to_contain_text("Aún no hay noticias vigentes")
        expect(notice).to_contain_text("cada 6 horas")
        expect(notice).to_contain_text("no rellena la agenda con noticias viejas")
        assert tid(page, "topic-card").count() == 0, "la agenda no debe mostrar noticias viejas"
        assert tid(page, "jury-demo").count() == 0, "la demostración es solo para el rol Jurado"
        expect(tid(page, "today-empty")).to_contain_text("Aún no hay noticias vigentes")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"desborda a {ancho}px"
    finally:
        ctx.close()


def test_el_jurado_ve_una_demostracion_rotulada_de_unos_pocos_titulares(browser: Browser, empty_stack):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, locale="es-PA", timezone_id="America/Panama")
    try:
        page = ctx.new_page()
        _open(page, empty_stack.url, "juror")
        demo = tid(page, "jury-demo")
        expect(demo).to_be_visible(timeout=20_000)
        expect(demo).to_contain_text("Demostración para el jurado")
        expect(demo).to_contain_text("No son noticias de hoy")
        items = tid(page, "jury-demo-item")
        assert items.count() == 5
        for index in range(items.count()):
            link = items.nth(index).get_by_role("link")
            assert link.get_attribute("target") == "_blank" and "noopener" in (link.get_attribute("rel") or "")
            assert (link.get_attribute("href") or "").startswith("https://")
    finally:
        ctx.close()


def _today(items: list[dict], note: str | None = None) -> str:
    return json.dumps({
        "checkedAt": "2026-10-14T20:00:00Z", "windowHours": 24, "snapshotId": "20261014-aaaaaaaa", "dataMode": "provisional",
        "cutoffUtc": "2026-10-14T19:00:00Z", "items": items, "note": note,
    })


def test_hoy_muestra_los_titulares_mas_recientes_primero_con_su_fuente(page: Page, stack):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    def item(index: int, minutes: int) -> dict:
        return {
            "id": f"evt_hoy_{index}", "title": f"Titular reciente número {index}", "category": "economia", "categoryLabel": "Economía",
            "outlet": "TVN Panamá", "url": f"https://www.tvn-2.com/nacionales/titular-{index}.html",
            "publishedAt": (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"), "publishedAtBasis": "rss_pubdate",
            "articleCount": 2, "independentProvenances": 1,
        }
    body = _today([item(1, 5), item(2, 50), item(3, 180), item(4, 400), item(5, 900)])
    page.route("**/api/v1/today**", lambda route: route.fulfill(status=200, content_type="application/json", body=body))
    page.set_viewport_size({"width": 1366, "height": 900})
    open_app(page, stack.url)
    expect(tid(page, "agenda-today")).to_be_visible(timeout=30_000)
    rows = tid(page, "today-item")
    expect(rows).to_have_count(5)
    titles = [rows.nth(i).inner_text() for i in range(5)]
    assert [f"número {n}" in titles[n - 1] for n in range(1, 6)] == [True] * 5, "debe ir de más reciente a más antiguo"
    expect(rows.nth(0)).to_contain_text("hace 5 min")
    expect(rows.nth(2)).to_contain_text("hace 3 h")
    link = rows.nth(0).get_by_role("link", name="Abrir la fuente original en TVN Panamá (se abre en otra pestaña)")
    assert link.get_attribute("href") == "https://www.tvn-2.com/nacionales/titular-1.html"
    assert link.get_attribute("target") == "_blank"
    # El ranking de la agenda de prioridad sigue debajo y no cambia.
    expect(tid(page, "topic-card").first).to_be_visible(timeout=30_000)


def test_hoy_sin_noticias_recientes_explica_por_que(page: Page, stack):
    note = "No hay noticias con fecha de publicación en las últimas 24 horas en el corte actual (2026-10-07 12:00 UTC)."
    page.route("**/api/v1/today**", lambda route: route.fulfill(status=200, content_type="application/json", body=_today([], note)))
    open_app(page, stack.url)
    expect(tid(page, "today-empty")).to_contain_text("No hay noticias con fecha de publicación", timeout=30_000)
