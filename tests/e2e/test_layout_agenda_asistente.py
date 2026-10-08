"""Verifica la geometría de las viñetas y las capas del chat y de la advertencia editorial."""

from __future__ import annotations

from pathlib import Path

import pytest
from e2e.helpers import ask, open_app, open_assistant, settle_motion, tid
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
RESULTS = Path(__file__).resolve().parents[1] / ".results" / "responsive"


def use_laya_classifier(page: Page) -> None:
    """El snapshot E2E usa baseline; simula la respuesta de salud de Laya para esta prueba visual."""
    def as_laya(route):
        response = route.fetch()
        payload = response.json()
        payload["classifier"] = "laya"
        route.fulfill(response=response, json=payload)

    page.route("**/api/v1/health", as_laya)


@pytest.mark.parametrize("width", [1440, 1024, 768, 390, 320])
def test_asistente_no_redimensiona_el_contenido(page: Page, stack, width: int):
    height = 900 if width >= 768 else 844
    page.set_viewport_size({"width": width, "height": height})
    open_app(page, stack.url)
    settle_motion(page)
    page.evaluate("window.scrollTo(0, Math.min(600, document.documentElement.scrollHeight - innerHeight))")
    scroll_before = page.evaluate("window.scrollY")
    main = page.locator("#contenido")
    before = main.bounding_box()
    assert before is not None

    toggle = tid(page, "assistant-toggle")
    toggle_box = toggle.bounding_box()
    assert toggle_box and 0 <= toggle_box["y"] < height, f"el botón del asistente no está visible al desplazarse: {toggle_box}"
    page.mouse.click(toggle_box["x"] + toggle_box["width"] / 2, toggle_box["y"] + toggle_box["height"] / 2)
    expect(tid(page, "assistant-input")).to_be_visible()
    settle_motion(page)
    assert page.evaluate("window.scrollY") == pytest.approx(scroll_before, abs=1)
    RESULTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(RESULTS / f"assistant-after-{width}.png"), full_page=True)
    after = main.bounding_box()
    assert after is not None
    assert {key: after[key] for key in ("x", "y", "width", "height")} == pytest.approx(
        {key: before[key] for key in ("x", "y", "width", "height")}, abs=1
    ), f"el panel del asistente cambió la geometría del contenido a {width}px: {before} -> {after}"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    if width >= 1024:
        expect(tid(page, "assistant-panel")).not_to_have_attribute("aria-modal", "true")
    else:
        expect(tid(page, "assistant-panel")).to_have_attribute("aria-modal", "true")
        expect(main).to_have_attribute("inert", "")

    tid(page, "assistant-input").fill("Texto que debe conservarse al cerrar y reabrir")
    if width < 1024:
        send = tid(page, "assistant-send")
        close = tid(page, "assistant-close")
        send.focus()
        page.keyboard.press("Tab")
        expect(close).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(send).to_be_focused()
    page.keyboard.press("Escape")
    expect(tid(page, "assistant-input")).to_be_hidden()
    expect(toggle).to_be_focused()
    assert page.evaluate("window.scrollY") == pytest.approx(scroll_before, abs=1)
    toggle_box = toggle.bounding_box()
    assert toggle_box
    page.mouse.click(toggle_box["x"] + toggle_box["width"] / 2, toggle_box["y"] + toggle_box["height"] / 2)
    expect(tid(page, "assistant-input")).to_have_value("Texto que debe conservarse al cerrar y reabrir")


@pytest.mark.parametrize("width", [1440, 390, 320])
def test_advertencia_de_laya_es_modal_accesible(page: Page, stack, width: int):
    page.set_viewport_size({"width": width, "height": 900 if width == 1440 else 844})
    use_laya_classifier(page)
    open_app(page, stack.url)
    trigger = tid(page, "classification-warning-toggle")
    expect(trigger).to_be_visible()
    expect(page.get_by_test_id("classification-limit")).to_have_count(0)

    trigger.click()
    dialog = tid(page, "classification-warning")
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("aria-modal", "true")
    expect(dialog).to_contain_text("Clasificación automática sin calibración validada")
    expect(dialog).to_contain_text(
        "Laya puede asignar categorías erróneas y sus porcentajes no son confianza editorial: revisa categoría e impacto antes de usar el ranking."
    )
    RESULTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(RESULTS / f"classification-warning-{width}.png"), full_page=True)
    assert page.evaluate("document.body.style.overflow") == "hidden"
    assert page.evaluate("document.documentElement.style.overflow") == "hidden"
    close = dialog.get_by_role("button", name="Cerrar ventana")
    expect(close).to_be_focused()
    page.keyboard.press("Tab")
    expect(close).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(close).to_be_focused()

    if width < 768:
        bounds = dialog.bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()
    assert page.evaluate("document.body.style.overflow") != "hidden"
    assert page.evaluate("document.documentElement.style.overflow") != "hidden"

    trigger.click()
    expect(dialog).to_be_visible()
    page.mouse.click(width / 2, 3)
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()


def test_advertencia_abierta_sobre_asistente_conserva_la_conversacion(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    use_laya_classifier(page)
    open_app(page, stack.url)
    toggle = tid(page, "assistant-toggle")
    toggle.click()
    field = tid(page, "assistant-input")
    expect(field).to_be_visible()
    field.fill("Consulta pendiente conservada mientras reviso la advertencia")

    trigger = tid(page, "classification-warning-toggle")
    trigger.click()
    expect(tid(page, "classification-warning")).to_be_visible()
    expect(tid(page, "assistant-input")).to_have_value("Consulta pendiente conservada mientras reviso la advertencia")
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    expect(tid(page, "classification-warning")).to_have_count(0)
    expect(tid(page, "assistant-panel")).to_be_visible()
    expect(tid(page, "assistant-input")).to_have_value("Consulta pendiente conservada mientras reviso la advertencia")


def test_tamano_minimizar_historial_y_borrador_persisten(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    settle_motion(page)
    main = page.locator("#contenido")
    before = main.bounding_box()
    scroll_before = page.evaluate("window.scrollY")

    tid(page, "assistant-toggle").click()
    field = tid(page, "assistant-input")
    expect(field).to_be_visible()
    field.fill("Borrador del asistente que debe sobrevivir una recarga")
    tid(page, "assistant-resize").click()
    panel = tid(page, "assistant-panel")
    expect(panel).to_have_attribute("data-size", "expanded")
    bounds = panel.bounding_box()
    assert bounds and bounds["width"] == pytest.approx(608, abs=1)
    assert main.bounding_box() == pytest.approx(before, abs=1)
    assert page.evaluate("window.scrollY") == pytest.approx(scroll_before, abs=1)

    tid(page, "assistant-minimize").click()
    dock = tid(page, "assistant-dock")
    expect(dock).to_be_visible()
    dock_box = dock.bounding_box()
    assert dock_box and dock_box["width"] == pytest.approx(240, abs=1) and dock_box["height"] == pytest.approx(52, abs=1)
    assert main.bounding_box() == pytest.approx(before, abs=1)
    dock.click()
    expect(tid(page, "assistant-input")).to_have_value("Borrador del asistente que debe sobrevivir una recarga")

    tid(page, "assistant-close").click()
    expect(tid(page, "assistant-panel")).to_have_count(0)
    page.reload()
    open_app(page, stack.url)
    tid(page, "assistant-toggle").click()
    field = tid(page, "assistant-input")
    expect(field).to_have_value("Borrador del asistente que debe sobrevivir una recarga")
    expect(tid(page, "assistant-panel")).to_have_attribute("data-size", "expanded")

    tid(page, "assistant-history-toggle").click()
    search = tid(page, "assistant-history-search")
    search.fill("sobrevivir una recarga")
    expect(page.locator(".assistant-history-item")).to_have_count(1)
    with page.expect_download() as download:
        page.get_by_role("button", name="Exportar Nueva conversación").click()
    assert download.value.suggested_filename.endswith(".md")

    page.get_by_role("button", name="Eliminar Nueva conversación").click()
    dialog = tid(page, "assistant-delete-modal")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Eliminar conversación").click()
    expect(dialog).to_have_count(0)


@pytest.mark.parametrize("width,columns", [(1440, 5), (1024, 5), (768, 2), (390, 1), (320, 1)])
def test_pesos_de_fuentes_se_redistribuyen_por_ancho(page: Page, stack, width: int, columns: int):
    page.set_viewport_size({"width": width, "height": 900 if width >= 768 else 844})
    open_app(page, stack.url)
    tid(page, "nav-fuentes").click()
    grid = tid(page, "rules-weight-grid")
    expect(grid).to_be_visible(timeout=30_000)
    settle_motion(page)

    fields = grid.locator(":scope > *")
    assert fields.count() == 5
    boxes = [field.bounding_box() for field in fields.all()]
    assert all(box is not None for box in boxes)
    rows = {}
    for box in boxes:
        assert box is not None
        rows.setdefault(round(box["y"]), []).append(box)
    assert len(rows) == (5 + columns - 1) // columns, f"número de filas inesperado a {width}px: {rows}"
    for row in rows.values():
        assert len(row) <= columns
        assert max(box["y"] for box in row) - min(box["y"] for box in row) <= 1
        assert max(box["width"] for box in row) - min(box["width"] for box in row) <= 1


def test_consulta_en_curso_se_cancela_se_anuncia_y_se_puede_reintentar(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    page.route("**/api/v1/queries", lambda route: None)  # la petición queda sin respuesta
    open_assistant(page)
    tid(page, "assistant-input").fill("¿Qué temas merecen revisión hoy?")
    tid(page, "assistant-input").press("Enter")
    cancel = tid(page, "assistant-cancel")
    expect(cancel).to_be_visible()
    box = cancel.bounding_box()
    assert box and box["height"] >= 43.5
    cancel.click()
    expect(tid(page, "assistant-error")).to_contain_text("Consulta cancelada")
    expect(tid(page, "assistant-announcer")).to_have_text("Consulta cancelada.")
    page.unroute("**/api/v1/queries")
    tid(page, "assistant-retry").click()
    expect(tid(page, "assistant-answer")).to_be_visible(timeout=40_000)
    expect(tid(page, "assistant-announcer")).to_contain_text("Respuesta lista")


def test_historial_expone_su_estado_y_busca_sin_distinguir_tildes(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    open_assistant(page)
    ask(page, "¿Qué pasa en Panamá con el Canal?", 1)
    toggle = tid(page, "assistant-history-toggle")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    search = tid(page, "assistant-history-search")
    search.fill("PANAMA")
    expect(page.locator(".assistant-history-item")).to_have_count(1)
    search.fill("zzzz")
    expect(page.get_by_text("No hay conversaciones que coincidan.")).to_be_visible()
    search.fill("")
    page.get_by_role("button", name="Eliminar", exact=False).first.click()
    page.get_by_role("button", name="Eliminar conversación").click()
    expect(page.get_by_text("Todavía no hay conversaciones guardadas.")).to_be_visible()
    expect(search).to_be_focused()



@pytest.mark.parametrize("width", [1440, 390])
def test_marcadores_de_cita_enfocan_su_fuente_y_el_pasaje_es_legible(page: Page, stack, width: int):
    page.set_viewport_size({"width": width, "height": 900 if width >= 768 else 844})
    open_app(page, stack.url)
    open_assistant(page)
    ask(page, "¿Qué cinco temas merecen revisión para la agenda y por qué?", 1)
    text = tid(page, "assistant-answer-text")
    markers = text.get_by_test_id("assistant-cite-marker")
    expect(markers.first).to_be_visible()
    assert "fx_" not in text.inner_text() and "art_" not in text.inner_text()  # sin ids crudos de evidencia
    markers.first.click()
    expect(page.locator('[data-source-index="1"]')).to_be_focused()
    overflow = page.evaluate("() => { const p = document.querySelector('[data-testid=assistant-panel]'); return p.scrollWidth - p.clientWidth; }")
    assert overflow <= 1
    passage = page.get_by_test_id("assistant-passage").first
    passage.get_by_role("button", name="Pasaje citado").click()
    expect(passage.locator("q").first).to_be_visible()
    expect(page.locator("[data-testid=assistant-panel] mark.assistant-mark")).to_have_count(0)  # una consulta de agenda no resalta términos


@pytest.mark.parametrize("width", [1440, 390])
def test_pregunta_de_seguimiento_se_resuelve_con_el_contexto_de_la_respuesta(page: Page, stack, width: int):
    page.set_viewport_size({"width": width, "height": 900 if width >= 768 else 844})
    open_app(page, stack.url)
    open_assistant(page)
    ask(page, "¿Qué cinco temas merecen revisión para la agenda y por qué?", 1)
    continuar = page.get_by_role("checkbox", name="Continuar con el contexto de la respuesta anterior")
    expect(continuar).to_be_visible()
    expect(continuar).to_be_checked()
    chip = tid(page, "assistant-followup").filter(has_text="falta verificar del primero")
    expect(chip).to_be_visible()
    box = chip.bounding_box()
    assert box and box["height"] >= 43.5
    chip.click()
    expect(tid(page, "assistant-answer")).to_have_count(2, timeout=40_000)
    expect(tid(page, "assistant-resolved")).to_contain_text("Entendí tu pregunta como")
    # Con el contexto apagado, el mismo texto ya no puede resolverse y se pide aclaración.
    continuar.click()
    expect(continuar).not_to_be_checked()
    tid(page, "assistant-input").fill("¿Y el segundo?")
    tid(page, "assistant-send").click()
    expect(tid(page, "assistant-answer")).to_have_count(3, timeout=40_000)
    assert page.evaluate("() => { const p = document.querySelector('[data-testid=assistant-panel]'); return p.scrollWidth - p.clientWidth; }") <= 1


def test_respuesta_con_el_panel_cerrado_se_indica_en_la_cabecera_y_se_limpia_al_verla(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    held = []
    page.route("**/api/v1/queries", lambda route: held.append(route))  # la petición queda retenida hasta quitar la ruta
    open_assistant(page)
    tid(page, "assistant-input").fill("¿Qué temas merecen revisión hoy?")
    tid(page, "assistant-input").press("Enter")
    expect(tid(page, "assistant-cancel")).to_be_visible()
    tid(page, "assistant-close").click()
    expect(tid(page, "assistant-panel")).to_have_count(0)
    page.unroute("**/api/v1/queries")  # al quitar la ruta, la petición retenida sigue su curso real
    badge = tid(page, "assistant-toggle-unread")
    expect(badge).to_have_text("1", timeout=40_000)
    assert "1 respuesta nueva" in tid(page, "assistant-toggle").inner_text()
    tid(page, "assistant-toggle").click()
    expect(tid(page, "assistant-answer")).to_be_visible()
    tid(page, "assistant-close").click()
    expect(tid(page, "assistant-panel")).to_have_count(0)
    expect(badge).to_have_count(0)


@pytest.mark.parametrize("width", [1440, 390])
def test_redactar_con_ia_verifica_rotula_y_se_conserva_tras_recargar(page: Page, stub_stack, width: int):
    page.set_viewport_size({"width": width, "height": 900 if width >= 768 else 844})
    open_app(page, stub_stack.url)
    open_assistant(page)
    ask(page, "¿Qué cinco temas merecen revisión para la agenda y por qué?", 1)
    expect(tid(page, "assistant-mode")).to_have_attribute("data-mode", "reglas")
    boton = tid(page, "assistant-compose")
    box = boton.bounding_box()
    assert box and box["height"] >= 43.5
    boton.click()
    expect(tid(page, "assistant-mode")).to_have_attribute("data-mode", "modelo", timeout=40_000)
    expect(tid(page, "assistant-mode")).to_contain_text("verificada por código")
    expect(tid(page, "assistant-answer-text")).to_contain_text("Respuesta redactada con IA")
    expect(tid(page, "assistant-compose")).to_have_count(0)
    # La respuesta por reglas sigue disponible y las citas del texto redactado siguen enlazando su fuente.
    tid(page, "assistant-rules-answer").get_by_role("button", name="Ver la respuesta por reglas").click()
    expect(tid(page, "assistant-rules-answer")).to_contain_text("Temas que merecen revisión")
    tid(page, "assistant-answer-text").get_by_test_id("assistant-cite-marker").first.click()
    expect(page.locator('[data-source-index="1"]')).to_be_focused()
    assert page.evaluate("() => { const p = document.querySelector('[data-testid=assistant-panel]'); return p.scrollWidth - p.clientWidth; }") <= 1
    # El resultado vive en el historial local: sobrevive a una recarga.
    page.wait_for_timeout(600)
    page.reload()
    open_app(page, stub_stack.url)
    open_assistant(page)
    expect(tid(page, "assistant-mode")).to_have_attribute("data-mode", "modelo")


def test_sin_proveedor_conectado_no_se_ofrece_redactar_y_se_explica(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    open_assistant(page)
    ask(page, "¿Qué cinco temas merecen revisión para la agenda y por qué?", 1)
    expect(tid(page, "assistant-compose")).to_have_count(0)
    expect(tid(page, "assistant-compose-unavailable")).to_contain_text("no está disponible")
