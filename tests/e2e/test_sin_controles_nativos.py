"""Regla «nada nativo» del proyecto comprobada en la interfaz REAL, y los controles propios ejercitados.

1. El DOM de cada vista no contiene elementos nativos (<select>, casillas, números, <details>, [title], validación nativa…),
   los campos tienen la apariencia nativa reiniciada, el textarea no tiene tirador y existen barras de desplazamiento propias.
2. Menú desplegable propio: ratón, teclado (flechas, Inicio/Fin, escritura, Enter, Escape), clic fuera y hoja inferior en móvil.
3. Casilla, campo numérico, desplegable y globo de ayuda propios.
"""

from __future__ import annotations

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
    problems: list[str] = []
    problems += [f"agenda: {x}" for x in page.evaluate(JS_NATIVE_SCAN)]
    open_first_ficha(page)
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
