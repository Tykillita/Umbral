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


# ------------------------------------------------------------------------------------------------ Actualizar noticias


def _refresh(status: str, message: str, items: list[dict], **extra) -> str:
    return json.dumps({
        "checkedAt": "2026-10-14T20:05:00Z", "windowHours": 24, "items": items, "warnings": [],
        "classification": {"status": status, "message": message, "nextAllowedAt": None, "runUrl": extra.get("runUrl")},
    })


def _live(index: int, minutes: int) -> dict:
    from datetime import UTC, datetime, timedelta

    published = (datetime.now(UTC) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": f"live_{index}", "title": f"Titular en vivo {index}", "outlet": "TVN Panamá", "url": f"https://www.tvn-2.com/nacionales/vivo-{index}.html", "publishedAt": published, "classified": False}


@pytest.mark.parametrize("ancho,alto,tactil", [(1366, 900, False), (390, 844, True)])
def test_actualizar_noticias_muestra_lo_nuevo_sin_clasificar_y_avisa_que_la_clasificacion_tarda(browser: Browser, stack, ancho: int, alto: int, tactil: bool):
    ctx = browser.new_context(viewport={"width": ancho, "height": alto}, has_touch=tactil, is_mobile=tactil, locale="es-PA", timezone_id="America/Panama")
    try:
        page = ctx.new_page()
        calls = {"n": 0}
        message = "Clasificación solicitada. Puede tardar entre 15 y 25 minutos; mientras tanto se muestran las noticias recién consultadas SIN clasificar."

        def handler(route):
            calls["n"] += 1
            route.fulfill(status=200, content_type="application/json", body=_refresh("solicitada", message, [_live(1, 4), _live(2, 30)]))

        page.route("**/api/v1/public/news/refresh", handler)
        open_app(page, stack.url)
        button = tid(page, "today-refresh")
        expect(button).to_be_visible(timeout=30_000)
        box = button.bounding_box()
        assert box is not None and box["height"] >= 43.5, "el botón debe medir al menos 44 px"
        button.click()
        result = tid(page, "today-refresh-result")
        expect(result).to_be_visible(timeout=15_000)
        expect(tid(page, "today-classification")).to_contain_text("Clasificación en curso")
        expect(tid(page, "today-classification")).to_contain_text("entre 15 y 25 minutos")
        items = tid(page, "today-live-item")
        expect(items).to_have_count(2)
        for index in range(2):
            expect(items.nth(index)).to_contain_text("Sin clasificar")
            link = items.nth(index).get_by_role("link")
            assert link.get_attribute("target") == "_blank" and "noopener" in (link.get_attribute("rel") or "")
        expect(result).to_contain_text("Aún no están en la agenda ni en el puntaje")
        assert calls["n"] == 1
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"desborda a {ancho}px"
        # El resultado sobrevive a cambiar de vista y volver (se guarda en la sesión del navegador).
        tid(page, "nav-fuentes").click()
        tid(page, "nav-agenda").click()
        expect(tid(page, "today-live-item")).to_have_count(2, timeout=15_000)
    finally:
        ctx.close()


def test_actualizar_noticias_sin_token_explica_que_no_puede_clasificar(page: Page, stack):
    msg = "La clasificación automática no está configurada en este servicio. Las noticias recién consultadas se muestran sin clasificar."
    page.route("**/api/v1/public/news/refresh", lambda route: route.fulfill(status=200, content_type="application/json", body=_refresh("no_disponible", msg, [_live(1, 2)])))
    open_app(page, stack.url)
    tid(page, "today-refresh").click()
    expect(tid(page, "today-classification")).to_contain_text("Clasificación no disponible por ahora", timeout=15_000)
    expect(tid(page, "today-classification")).to_contain_text("no está configurada")
    expect(tid(page, "today-live-item")).to_have_count(1)


def test_actualizar_noticias_con_el_servicio_caido_muestra_un_aviso_claro_y_sin_ruido(page: Page, stack):
    open_app(page, stack.url)
    page.route("**/api/v1/public/news/refresh", lambda route: route.fulfill(status=404, content_type="text/html", body="<h1>Not Found</h1>"))
    tid(page, "today-refresh").click()
    expect(tid(page, "today-refresh-error")).to_contain_text("no está disponible", timeout=15_000)
    assert "Error HTTP" not in page.inner_text("body")
