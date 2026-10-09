"""Regla «nada nativo» del proyecto comprobada en la interfaz REAL, y los controles propios ejercitados.

1. El DOM de cada vista no contiene elementos nativos (<select>, casillas, números, <details>, [title], validación nativa…),
   los campos tienen la apariencia nativa reiniciada, el textarea no tiene tirador y existen barras de desplazamiento propias.
2. Menú desplegable propio: ratón, teclado (flechas, Inicio/Fin, escritura, Enter, Escape), clic fuera y hoja inferior en móvil.
3. Casilla, campo numérico, desplegable y globo de ayuda propios.
"""

from __future__ import annotations

import json

import pytest
from e2e.helpers import choose, open_app, open_first_ficha, tid
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

JS_NATIVE_SCAN = """() => {
  const found = [];
  const sel = 'select, input[type=checkbox], input[type=radio], input[type=number], input[type=search], input[type=range], ' +
              'input[type=date], input[type=time], input[type=datetime-local], input[type=month], input[type=week], input[type=file], ' +
              'input[type=color], details, summary, dialog, datalist, progress, meter, [title], [required]';
  for (const el of document.querySelectorAll(sel)) {
    found.push(el.tagName.toLowerCase() + (el.getAttribute('type') ? '[' + el.getAttribute('type') + ']' : '') +
               (el.getAttribute('data-testid') ? '#' + el.getAttribute('data-testid') : '') + (el.hasAttribute('title') ? ' title="' + el.getAttribute('title').slice(0, 30) + '"' : ''));
  }
  for (const f of document.querySelectorAll('form')) if (!f.noValidate) found.push('form sin noValidate#' + (f.getAttribute('data-testid') || f.getAttribute('aria-label') || '?'));
  for (const el of document.querySelectorAll('input:not([type=hidden]), textarea, button')) {
    const cs = getComputedStyle(el); const ap = cs.appearance || cs.webkitAppearance;
    if (ap && ap !== 'none') found.push('apariencia nativa (' + ap + ') en ' + el.tagName.toLowerCase() + '#' + (el.getAttribute('data-testid') || el.id));
  }
  for (const t of document.querySelectorAll('textarea')) if (getComputedStyle(t).resize !== 'none') found.push('textarea con tirador de tamaño');
  return found.slice(0, 15);
}"""

JS_CUSTOM_SCROLLBAR = """() => {
  let customWebkit = false, firefox = false;
  for (const sheet of document.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch { continue; }
    const walk = (list) => { for (const r of list) {
      if (r.selectorText && r.selectorText.includes('::-webkit-scrollbar')) customWebkit = true;
      if (r.cssRules) walk(r.cssRules);
      if (r.cssText && r.cssText.includes('scrollbar-color')) firefox = true;
    } };
    walk(rules);
  }
  return {customWebkit, firefox};
}"""


def go(page: Page, nav: str) -> None:
    tid(page, nav).click()
    page.wait_for_timeout(450)


@pytest.mark.parametrize("w,h", [(1440, 900), (390, 844)], ids=lambda v: str(v))
def test_el_dom_real_no_contiene_controles_nativos(page: Page, stack, w, h):
    page.set_viewport_size({"width": w, "height": h})
    open_app(page, stack.url)
    tid(page, "role-change").click()
    tid(page, "role-juror").click()
    expect(tid(page, "nav-borradores")).to_be_visible()
    expect(tid(page, "active-role")).to_have_text("Jurado")
    problems: list[str] = []
    problems += [f"agenda: {x}" for x in page.evaluate(JS_NATIVE_SCAN)]
    open_first_ficha(page)
    assert tid(page, "nav-borradores").count() == 1, (
        f"Jurado debe conservar Borradores al abrir una ficha; ruta={page.url}, "
        f"rol={tid(page, 'active-role').inner_text() if tid(page, 'active-role').count() else 'sin rol'}, "
        f"navegación={page.locator('[data-testid^=nav-]').all_text_contents()}"
    )
    tid(page, "impact-form").locator("button[aria-expanded]").first.click()
    problems += [f"ficha+impacto: {x}" for x in page.evaluate(JS_NATIVE_SCAN)]
    go(page, "nav-borradores")
    problems += [f"borradores: {x}" for x in page.evaluate(JS_NATIVE_SCAN)]
    go(page, "nav-fuentes")
    for trigger in tid(page, "sources-view").locator(".disclosure-trigger").all():
        trigger.click()
    problems += [f"fuentes (todo desplegado): {x}" for x in page.evaluate(JS_NATIVE_SCAN)]
    tid(page, "assistant-toggle").click()
    expect(tid(page, "assistant-input")).to_be_visible()
    problems += [f"asistente: {x}" for x in page.evaluate(JS_NATIVE_SCAN)]
    assert not problems, "controles o ayudas nativas encontrados: " + "; ".join(problems)
    sb = page.evaluate(JS_CUSTOM_SCROLLBAR)
    assert sb["customWebkit"] and sb["firefox"], f"faltan las barras de desplazamiento propias: {sb}"


# ---------------------------------------------------------------------------------------- menú desplegable


def test_menu_propio_con_teclado(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    trigger = tid(page, "filter-category")
    assert trigger.get_attribute("role") == "combobox"
    trigger.focus()
    page.keyboard.press("ArrowDown")
    expect(page.get_by_role("listbox")).to_be_visible()
    assert trigger.get_attribute("aria-expanded") == "true"
    assert page.get_by_role("option").first.get_attribute("aria-selected") == "true", "la opción actual debe quedar marcada al abrir"
    page.keyboard.press("End")
    last_value = page.get_by_role("option").last.get_attribute("data-value")
    page.keyboard.press("Enter")
    expect(page.get_by_role("listbox")).to_have_count(0)
    assert trigger.get_attribute("data-value") == last_value
    assert page.evaluate("document.activeElement && document.activeElement.getAttribute('data-testid')") == "filter-category", "el foco debe volver al menú"
    # Escribir una letra salta a la opción que empieza así; Escape cierra sin cambiar el valor.
    page.keyboard.press("Enter")
    page.keyboard.type("t")
    active = page.evaluate("document.querySelector('[role=option][data-active=true]').textContent.trim().toLowerCase()")
    assert active.startswith("t"), f"la escritura no movió la opción activa: {active}"
    before = trigger.get_attribute("data-value")
    page.keyboard.press("Escape")
    expect(page.get_by_role("listbox")).to_have_count(0)
    assert trigger.get_attribute("data-value") == before


def test_menu_propio_con_raton_y_clic_fuera(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    choose(page, "filter-evidence", "insuficiente")
    assert tid(page, "filter-evidence").get_attribute("data-value") == "insuficiente"
    expect(tid(page, "agenda-count")).to_contain_text("filtros", timeout=20_000)
    tid(page, "filter-band").click()
    expect(page.get_by_role("listbox")).to_be_visible()
    page.mouse.click(5, 5)
    expect(page.get_by_role("listbox")).to_have_count(0)


def test_menu_propio_se_abre_como_hoja_inferior_en_movil(browser, stack):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        tid(page, "filters-toggle").tap()
        tid(page, "filter-band").tap()
        expect(tid(page, "select-sheet")).to_be_visible()
        b = page.get_by_role("listbox").bounding_box()
        assert b is not None and b["x"] >= 0 and b["x"] + b["width"] <= 391, f"la hoja no ocupa el ancho de la pantalla: {b}"
        assert page.evaluate("document.body.style.overflow") == "hidden", "la página no debe desplazarse con la hoja abierta"
        option = page.locator('[role="option"][data-value="alto"]')
        assert option.bounding_box()["height"] >= 43.5, "las opciones deben medir al menos 44 px"
        option.tap()
        expect(tid(page, "select-sheet")).to_have_count(0)
        assert tid(page, "filter-band").get_attribute("data-value") == "alto"
        assert page.evaluate("document.body.style.overflow") != "hidden"
    finally:
        ctx.close()


@pytest.mark.parametrize("w,h", [(1366, 900), (390, 844)], ids=["escritorio", "movil"])
def test_selector_modelo_chatgpt_se_muestra_y_guarda_sobre_modal(page: Page, stack, w: int, h: int):
    """El catálogo del perfil activo debe poder elegirse aun cuando su Select vive en un modal."""
    selected = {"model": None}
    profile = {
        "profileId": "profile-test", "label": "Cuenta ChatGPT", "email": None,
        "connected": True, "planUsageEnabled": True, "model": None, "active": True,
    }
    catalog = [{"slug": "gpt-test", "displayName": "GPT de prueba"}]

    def connections(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "available": True, "reason": None, "profiles": [profile], "activeProfileId": "profile-test",
        }))

    def models(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "profileId": "profile-test", "models": catalog, "selectedModel": selected["model"],
        }))

    def choose_model(route):
        body = route.request.post_data_json
        selected["model"] = body["model"]
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "profileId": "profile-test", "models": catalog, "selectedModel": selected["model"],
        }))

    page.route("**/api/v1/connections/chatgpt/models", models)
    page.route("**/api/v1/connections/chatgpt/model", choose_model)
    page.route("**/api/v1/connections/chatgpt", connections)
    page.set_viewport_size({"width": w, "height": h})
    open_app(page, stack.url)
    tid(page, "assistant-toggle").click()
    tid(page, "assistant-model-accounts").click()
    modal = tid(page, "assistant-provider-accounts-modal")
    expect(modal).to_be_visible()

    trigger = page.get_by_role("combobox", name="Modelo de la cuenta activa")
    expect(trigger).to_be_visible()
    trigger.click()
    menu = page.locator(".select-layer" if w <= 639 else ".select-popover")
    expect(menu).to_be_visible()
    modal_z = int(modal.evaluate("el => getComputedStyle(el.closest('.comic-modal-layer')).zIndex"))
    menu_z = int(menu.evaluate("el => getComputedStyle(el).zIndex"))
    assert menu_z > modal_z, f"el selector debe quedar por encima del modal: menú={menu_z}, modal={modal_z}"

    option = page.get_by_role("option", name="GPT de prueba")
    with page.expect_request(lambda request: request.url.endswith("/api/v1/connections/chatgpt/model") and request.method == "PUT") as sent:
        option.click()
    assert sent.value.post_data_json == {"model": "gpt-test"}
    expect(trigger).to_contain_text("GPT de prueba")
    expect(tid(page, "chatgpt-model-required")).to_have_count(0)


# ---------------------------------------------------------------------------------- otros controles propios


def test_casilla_propia_con_teclado_y_con_su_etiqueta(page: Page, stack):
    open_app(page, stack.url)
    open_first_ficha(page)
    tid(page, "impact-form").locator("button[aria-expanded]").first.click()
    box = tid(page, "impact-evidence").first
    assert box.get_attribute("role") == "checkbox"
    start = box.get_attribute("aria-checked")
    box.focus()
    page.keyboard.press("Space")
    assert box.get_attribute("aria-checked") != start, "Espacio debe cambiar la casilla"
    now = box.get_attribute("aria-checked")
    box.locator("xpath=ancestor::label").locator("span.truncate").first.click()  # el texto visible de la etiqueta
    assert box.get_attribute("aria-checked") != now, "el texto de la etiqueta debe cambiar la casilla"


def test_campo_numerico_propio(page: Page, stack):
    open_app(page, stack.url)
    go(page, "nav-fuentes")
    field = tid(page, "rules-weight-R")
    assert field.get_attribute("role") == "spinbutton" and field.get_attribute("type") != "number"
    field.fill("40")
    assert field.input_value() == "40"
    field.press("ArrowUp")
    assert field.input_value() == "41"
    field.press("ArrowDown")
    field.press("ArrowDown")
    assert field.input_value() == "39"
    field.press("End")
    assert field.input_value() == "100"
    field.press("Home")
    assert field.input_value() == "0"
    field.fill("")
    field.type("a7b")  # las letras se descartan
    assert field.input_value() == "7"
    field.locator("xpath=following-sibling::button").click()  # botón +
    assert field.input_value() == "8"
    field.locator("xpath=preceding-sibling::button").click()  # botón −
    assert field.input_value() == "7"


def test_desplegable_propio(page: Page, stack):
    open_app(page, stack.url)
    open_first_ficha(page)
    trigger = tid(page, "impact-form").locator("button[aria-expanded]").first
    assert trigger.get_attribute("aria-expanded") == "false"
    expect(tid(page, "impact-save")).to_be_hidden()
    trigger.focus()
    page.keyboard.press("Enter")
    assert trigger.get_attribute("aria-expanded") == "true"
    expect(tid(page, "impact-save")).to_be_visible()
    page.keyboard.press("Space")
    assert trigger.get_attribute("aria-expanded") == "false"


def test_globo_de_ayuda_propio(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    score = tid(page, "topic-score").first
    describedby = score.evaluate("el => el.closest('[aria-describedby]').getAttribute('aria-describedby')")
    assert describedby, "el globo debe estar enlazado con aria-describedby para lectores de pantalla"
    assert "Puntaje" in page.locator(f"[id='{describedby}']").inner_text()
    score.hover()
    tip = page.locator(".tooltip")
    expect(tip).to_be_visible(timeout=3000)
    assert "Puntaje de atención" in tip.inner_text()
    page.mouse.move(5, 5)
    expect(tip).to_have_count(0)


def test_preferencia_de_movimiento_en_configuracion_con_teclado_y_persistencia(page: Page, stack):
    page.set_viewport_size({"width": 390, "height": 844})
    page.add_init_script("localStorage.removeItem('umbral.motion-preference.v1')")
    open_app(page, stack.url)
    tid(page, "settings-toggle").click()

    group = page.get_by_role("radiogroup", name="Movimiento reducido")
    system = page.get_by_role("radio", name="Usar preferencia del sistema", exact=True)
    reduced = page.get_by_role("radio", name="Activar movimiento reducido", exact=True)
    full = page.get_by_role("radio", name="Desactivar movimiento reducido", exact=True)
    expect(group).to_be_visible()
    expect(system).to_have_attribute("aria-checked", "true")
    dialog = tid(page, "settings-dialog")
    expect(dialog).to_be_visible()
    switch_box = page.get_by_test_id("motion-preference-switch").bounding_box()
    dialog_box = dialog.bounding_box()
    assert switch_box is not None and dialog_box is not None
    assert dialog_box["x"] <= switch_box["x"] < switch_box["x"] + switch_box["width"] <= dialog_box["x"] + dialog_box["width"]
    assert dialog_box["y"] <= switch_box["y"] < switch_box["y"] + switch_box["height"] <= dialog_box["y"] + dialog_box["height"]
    for option in (system, reduced, full):
        box = option.bounding_box()
        assert box is not None and box["width"] >= 43.5 and box["height"] >= 43.5, f"zona táctil insuficiente: {box}"

    system.focus()
    page.keyboard.press("ArrowRight")
    expect(reduced).to_have_attribute("aria-checked", "true")
    assert page.locator("html").get_attribute("data-motion-preference") == "reduced"
    assert page.evaluate("localStorage.getItem('umbral.motion-preference.v1')") == "reduced"

    page.keyboard.press("ArrowRight")
    expect(full).to_have_attribute("aria-checked", "true")
    assert page.locator("html").get_attribute("data-motion-preference") == "full"

    page.keyboard.press("End")
    expect(full).to_have_attribute("aria-checked", "true")
    page.keyboard.press("Home")
    expect(system).to_have_attribute("aria-checked", "true")


@pytest.mark.parametrize("width,height", [(320, 800), (390, 844), (1440, 900)], ids=["320px", "390px", "escritorio"])
def test_aviso_notion_compacto_muestra_accion_y_conserva_texto_accesible(page: Page, stack, width: int, height: int):
    """El toast real conserva contenido accesible y sus controles caben en los tres anchos acordados."""
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/v1/notion/status", lambda route: route.fulfill(status=200, json={"configured": True}))
    page.route(
        "**/api/v1/cases/*/export/notion",
        lambda route: route.fulfill(status=200, json={
            "page_id": "notion-page-e2e",
            "url": "https://www.notion.so/umbral/notion-page-e2e",
            "title": "Ficha de prueba exportada a Notion con un título extenso",
        }),
    )
    open_app(page, stack.url)
    tid(page, "role-change").click()
    tid(page, "role-juror").click()
    open_first_ficha(page)
    tid(page, "go-drafts").click()
    choose(page, "draft-provider", "plantilla")
    tid(page, "draft-generate").click()
    expect(tid(page, "draft-origin-label")).to_be_visible(timeout=60_000)
    tid(page, "export-notion").click()

    toast = tid(page, "export-toast")
    expect(toast).to_be_visible()
    expect(toast).to_have_attribute("role", "status")
    expect(toast.locator(".export-toast-copy strong")).to_have_text("Ficha exportada a Notion")
    expect(toast.locator(".export-toast-copy span")).to_have_text("Ficha de prueba exportada a Notion con un título extenso se guardó como una página nueva.")
    action = toast.get_by_role("link", name="Abrir Notion")
    expect(action).to_have_attribute("href", "https://www.notion.so/umbral/notion-page-e2e")

    box = toast.bounding_box()
    close_box = toast.get_by_role("button", name="Cerrar aviso").bounding_box()
    action_box = action.bounding_box()
    assert box is not None and 52 <= box["height"] <= 56.5, f"alto del aviso fuera de 52–56 px: {box}"
    assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1, f"el aviso desborda el viewport: {box}"
    assert close_box is not None and close_box["width"] >= 43.5 and close_box["height"] >= 43.5, f"cierre demasiado pequeño: {close_box}"
    assert action_box is not None and action_box["height"] >= 43.5, f"acción demasiado pequeña: {action_box}"

    close = toast.get_by_role("button", name="Cerrar aviso")
    close.focus()
    page.keyboard.press("Enter")
    expect(toast).to_have_count(0)


def test_configuracion_superpuesta_cierra_con_escape_y_clic_exterior(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    trigger = tid(page, "settings-toggle")
    card = tid(page, "topic-card").first
    before = card.bounding_box()
    trigger.focus()
    page.keyboard.press("Enter")
    dialog = tid(page, "settings-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("aria-modal", "true")
    while_open = card.bounding_box()
    assert before is not None and while_open is not None
    assert abs(before["x"] - while_open["x"]) <= 1 and abs(before["y"] - while_open["y"]) <= 1, "el panel no debe desplazar el contenido"
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()

    trigger.click()
    layer = page.get_by_test_id("settings-dialog-layer")
    layer_box = layer.bounding_box()
    assert layer_box is not None
    page.mouse.click(layer_box["x"] + layer_box["width"] - 8, layer_box["y"] + 8)
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()


@pytest.mark.parametrize("width,height", [(320, 640), (390, 844)], ids=["320x640", "390x844"])
def test_configuracion_ocupa_pantalla_y_se_puede_usar_con_tacto_en_movil(browser, stack, width: int, height: int):
    context = browser.new_context(viewport={"width": width, "height": height}, has_touch=True, is_mobile=True)
    try:
        page = context.new_page()
        open_app(page, stack.url)
        trigger = tid(page, "settings-toggle")
        trigger.tap()
        dialog = tid(page, "settings-dialog")
        expect(dialog).to_be_visible()
        box = dialog.bounding_box()
        assert box is not None and box["x"] == 0 and box["y"] == 0 and box["width"] == width and box["height"] == height, f"el panel no ocupa la pantalla móvil: {box}"
        header = dialog.locator(":scope > header")
        nav = header.get_by_role("navigation", name="Secciones de configuración")
        expect(nav).to_be_visible()
        header_box = header.bounding_box()
        assert header_box is not None
        for button in (nav.get_by_role("button", name="Preferencias"), nav.get_by_role("button", name="Conexiones")):
            button_box = button.bounding_box()
            assert button_box is not None and button_box["height"] >= 43.5, f"botón de sección demasiado pequeño: {button_box}"
            assert header_box["x"] <= button_box["x"] and button_box["x"] + button_box["width"] <= header_box["x"] + header_box["width"], f"el botón quedó fuera del encabezado: {button_box}, {header_box}"

        choose(page, "settings-theme", "tvn")
        assert page.locator("html").get_attribute("data-theme") == "tvn"
        assert page.evaluate("localStorage.getItem('umbral.theme.v1')") == "tvn"
        reduced = page.get_by_test_id("motion-option-reduced")
        reduced.tap()
        expect(reduced).to_have_attribute("aria-checked", "true")
        assert page.evaluate("localStorage.getItem('umbral.motion-preference.v1')") == "reduced"
        dialog.get_by_role("button", name="Cerrar ventana").tap()
        expect(dialog).to_have_count(0)
    finally:
        context.close()


def test_tema_se_aplica_a_toda_umbral_y_se_recuerda_entre_rutas(page: Page, stack):
    page.set_viewport_size({"width": 1280, "height": 850})
    page.goto(stack.url + "/")
    page.evaluate("localStorage.removeItem('umbral.theme.v1')")
    open_app(page, stack.url)
    tid(page, "settings-toggle").click()
    choose(page, "settings-theme", "tvn")
    expect(page.locator("html")).to_have_attribute("data-theme", "tvn")
    assert page.evaluate("getComputedStyle(document.documentElement).backgroundColor") == "rgb(243, 248, 252)"

    page.goto(stack.url + "/")
    expect(page.locator("html")).to_have_attribute("data-theme", "tvn")
    assert page.evaluate("getComputedStyle(document.documentElement).backgroundColor") == "rgb(243, 248, 252)", "la portada debe conservar el tema elegido en la app"

    open_app(page, stack.url)
    expect(page.locator("html")).to_have_attribute("data-theme", "tvn")
    tid(page, "settings-toggle").click()
    choose(page, "settings-theme", "original")
    expect(page.locator("html")).to_have_attribute("data-theme", "original")
    assert page.evaluate("localStorage.getItem('umbral.theme.v1')") == "original"
