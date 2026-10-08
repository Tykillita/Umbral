"""E2E del pulido de interfaz: zonas táctiles, navegación móvil, simetría de filtros y menús sin texto cortado.

Complementa test_responsive_accesibilidad.py. Mide geometría real en Chromium contra el backend y el build de Astro.
No sustituye una revisión visual humana.
"""

from __future__ import annotations

import pytest
from e2e.helpers import open_app, open_first_ficha, settle_motion, tid
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Alto mínimo táctil: 44 px (con 0,5 px de tolerancia por redondeo del navegador).
MIN_TOUCH = 43.5

JS_SMALL_TARGETS = """(min) => {
  const small = [];
  const sel = 'button, [role=combobox], [role=checkbox], input:not([type=hidden]), a.comic-nav, a.comic-brand, a.comic-link';
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('[inert]') || el.matches('.skip-link')) continue;
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (r.height < min) small.push((el.getAttribute('data-testid') || el.tagName.toLowerCase()) + ':' + (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 30) + ' ' + Math.round(r.height) + 'px');
  }
  return small.slice(0, 12);
}"""

JS_SELECT_TRUNCATED = """() => {
  // Menús propios: el texto del valor no debe quedar recortado con puntos suspensivos.
  const bad = [];
  for (const v of document.querySelectorAll('[role=combobox] .select-value')) {
    const r = v.getBoundingClientRect(); if (r.width === 0) continue;
    if (v.scrollWidth > v.clientWidth + 1) bad.push((v.parentElement.getAttribute('data-testid') || '?') + ': «' + v.textContent.trim() + '» ' + v.scrollWidth + '>' + v.clientWidth);
  }
  return bad;
}"""


def box(page: Page, testid: str) -> dict:
    b = tid(page, testid).first.bounding_box()
    assert b is not None, f"{testid} no es visible"
    return b


@pytest.mark.parametrize("w,h", [(390, 844), (320, 640)], ids=lambda v: str(v))
def test_zonas_tactiles_de_44px_en_movil(page: Page, stack, w, h):
    page.set_viewport_size({"width": w, "height": h})
    open_app(page, stack.url)
    problems: list[str] = []
    tid(page, "filters-toggle").click()
    settle_motion(page)  # la animación de pulsación escala el botón (~0,98) y falsearía la medida
    problems += [f"agenda: {x}" for x in page.evaluate(JS_SMALL_TARGETS, MIN_TOUCH)]
    open_first_ficha(page)
    tid(page, "impact-form").locator("button[aria-expanded]").first.click()
    settle_motion(page)
    problems += [f"ficha: {x}" for x in page.evaluate(JS_SMALL_TARGETS, MIN_TOUCH)]
    tid(page, "nav-borradores").click()
    page.wait_for_timeout(400)
    settle_motion(page)
    problems += [f"borradores: {x}" for x in page.evaluate(JS_SMALL_TARGETS, MIN_TOUCH)]
    tid(page, "nav-fuentes").click()
    page.wait_for_timeout(500)
    settle_motion(page)
    problems += [f"fuentes: {x}" for x in page.evaluate(JS_SMALL_TARGETS, MIN_TOUCH)]
    assert not problems, "zonas táctiles menores de 44 px: " + "; ".join(problems)


@pytest.mark.parametrize("w,h", [(390, 844), (320, 640)], ids=lambda v: str(v))
def test_cuatro_pestanas_siempre_visibles_en_barra_inferior(page: Page, stack, w, h):
    page.set_viewport_size({"width": w, "height": h})
    open_app(page, stack.url)
    boxes = [box(page, n) for n in ("nav-agenda", "nav-ficha", "nav-borradores", "nav-fuentes")]
    for b in boxes:
        assert b["x"] >= -1 and b["x"] + b["width"] <= w + 1, f"pestaña fuera de la pantalla: {b}"
    # Barra inferior simétrica: cuatro pestañas del mismo ancho, en la misma fila y pegadas al borde inferior.
    widths = {round(b["width"]) for b in boxes}
    assert len(widths) == 1, f"pestañas de distinto ancho: {widths}"
    assert len({round(b["y"]) for b in boxes}) == 1, "las pestañas no están en la misma fila"
    assert abs((boxes[0]["y"] + boxes[0]["height"]) - h) <= 1, "la barra no está pegada al borde inferior"
    assert boxes[0]["height"] >= 48, f"zona táctil de pestaña baja: {boxes[0]['height']}"


def test_en_escritorio_la_navegacion_va_en_la_cabecera(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, stack.url)
    nav = box(page, "nav-agenda")
    assert nav["y"] < 80, f"en escritorio las pestañas deben estar arriba, no abajo: y={nav['y']}"
    assert box(page, "assistant-toggle")["y"] < 80


def test_filtros_se_pliegan_en_movil(page: Page, stack):
    page.set_viewport_size({"width": 390, "height": 844})
    open_app(page, stack.url)
    expect(tid(page, "agenda-search")).to_be_visible()
    expect(tid(page, "filter-category")).to_be_hidden()
    tid(page, "filters-toggle").click()
    expect(tid(page, "filter-category")).to_be_visible()
    assert tid(page, "filters-toggle").get_attribute("aria-expanded") == "true"
    # Una columna en móvil: los cinco menús tienen el mismo ancho y el mismo alto.
    ids = ("filter-scope", "filter-category", "filter-evidence", "filter-band", "filter-review")
    sizes = {(round(box(page, i)["width"]), round(box(page, i)["height"])) for i in ids}
    assert len(sizes) == 1, f"filtros de distinto tamaño en móvil: {sizes}"


@pytest.mark.parametrize("w", [1440, 1024, 768])
def test_filtros_forman_una_rejilla_simetrica_y_sin_texto_cortado(page: Page, stack, w):
    page.set_viewport_size({"width": w, "height": 900})
    open_app(page, stack.url)
    ids = ("filter-scope", "filter-category", "filter-evidence", "filter-band", "filter-review", "filters-clear")
    b = [box(page, i) for i in ids]
    row1, row2 = b[:3], b[3:]
    assert len({round(x["y"]) for x in row1}) == 1, f"primera fila desalineada: {[round(x['y']) for x in row1]}"
    assert len({round(x["y"]) for x in row2}) == 1, f"segunda fila desalineada: {[round(x['y']) for x in row2]}"
    assert len({round(x["width"]) for x in b}) <= 2, f"anchos desiguales en la rejilla: {[round(x['width']) for x in b]}"
    assert len({round(x["height"]) for x in b}) == 1, f"alturas desiguales: {[round(x['height']) for x in b]}"
    # El buscador ocupa todo el ancho de la barra y queda sobre la rejilla.
    search = box(page, "agenda-search")
    assert search["y"] < row1[0]["y"] and search["width"] >= (row2[2]["x"] + row2[2]["width"]) - row1[0]["x"] - 40
    assert search["height"] >= 43.5
    assert not page.evaluate(JS_SELECT_TRUNCATED), f"menús con el texto cortado: {page.evaluate(JS_SELECT_TRUNCATED)}"


def test_botones_de_cada_tarjeta_tienen_el_mismo_ancho_en_movil(page: Page, stack):
    page.set_viewport_size({"width": 390, "height": 844})
    open_app(page, stack.url)
    card = tid(page, "topic-card").first
    buttons = card.locator(".topic-action-group button")
    assert buttons.count() == 2
    a, c = buttons.nth(0).bounding_box(), buttons.nth(1).bounding_box()
    assert a and c and abs(a["width"] - c["width"]) <= 1 and c["y"] >= a["y"] + a["height"] - 1, f"botones desiguales: {a} {c}"


@pytest.mark.parametrize("w", [1440, 1024, 768, 390, 320])
def test_tarjetas_alinean_puntuacion_y_pies_con_detalles_abiertos(page: Page, stack, w):
    page.set_viewport_size({"width": w, "height": 900 if w >= 768 else 844})
    open_app(page, stack.url)
    cards = tid(page, "topic-card")
    if w >= 1024:
        _, second, third = (cards.nth(i).bounding_box() for i in range(3))
        assert second and third and second["y"] == pytest.approx(third["y"], abs=1)
    else:
        for index in range(4):
            current, following = cards.nth(index).bounding_box(), cards.nth(index + 1).bounding_box()
            assert current and following and following["y"] > current["y"]

    if w >= 1024:
        card = cards.nth(1)
        details = card.get_by_test_id("topic-card-details")
        details.get_by_role("button").click()
        expect(details.get_by_role("region")).to_be_visible()
        settle_motion(page)
        peers = [cards.nth(i) for i in (1, 2)]
        for selector in (".topic-score-box", ".topic-panel-footer"):
            positions = [item.locator(selector).bounding_box() for item in peers]
            assert positions[0] and positions[1]
            assert positions[0]["y"] == pytest.approx(positions[1]["y"], abs=1), f"{selector} desalineado en {w}px: {positions}"
        action_widths = [item.locator(".topic-action-group button").nth(0).bounding_box()["width"] for item in peers]
        assert action_widths[0] == pytest.approx(action_widths[1], abs=1)
    else:
        for card in cards.all():
            assert card.locator(".topic-score-box").count() == 1
            assert card.locator(".topic-panel-footer").count() == 1


def test_estado_de_datos_plegable_en_movil_y_visible_en_escritorio(page: Page, stack):
    page.set_viewport_size({"width": 390, "height": 844})
    open_app(page, stack.url)
    expect(tid(page, "snapshot-badge")).to_be_hidden()
    tid(page, "status-toggle").click()
    expect(tid(page, "snapshot-badge")).to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.reload()
    open_app(page, stack.url)
    expect(tid(page, "snapshot-badge")).to_be_visible()
    expect(tid(page, "status-toggle")).to_be_hidden()


@pytest.mark.parametrize("w,h", [(390, 844), (320, 640)], ids=lambda v: str(v))
def test_formulario_de_impacto_abierto_no_desborda_en_movil(page: Page, stack, w, h):
    page.set_viewport_size({"width": w, "height": h})
    open_app(page, stack.url)
    open_first_ficha(page)
    tid(page, "impact-form").locator("button[aria-expanded]").first.click()
    expect(tid(page, "impact-save")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= w, "el formulario abierto desborda la página"
    for box in tid(page, "impact-evidence").all():
        label = box.locator("xpath=ancestor::label").bounding_box()
        assert label and label["x"] >= 0 and label["x"] + label["width"] <= w + 1, f"una etiqueta de casilla sale de la pantalla: {label}"
    # El texto largo se abrevia con puntos suspensivos en lugar de salirse.
    spans = tid(page, "impact-evidence").first.locator("xpath=ancestor::label").locator("span.truncate")
    assert spans.first.evaluate("el => el.scrollWidth > el.clientWidth || el.getBoundingClientRect().right <= window.innerWidth")


@pytest.mark.parametrize("w,h", [(390, 844), (320, 640)], ids=lambda v: str(v))
def test_borradores_no_desborda_en_movil(page: Page, stack, w, h):
    page.set_viewport_size({"width": w, "height": h})
    open_app(page, stack.url)
    tid(page, "nav-borradores").click()
    page.wait_for_timeout(500)
    assert page.evaluate("document.documentElement.scrollWidth") <= w, "Borradores (selector de tema) desborda la pantalla"
    tid(page, "nav-agenda").click()
    open_first_ficha(page)
    tid(page, "go-drafts").click()
    # Dos versiones: aparece el selector de versión junto al título de la sección.
    for _ in range(2):
        expect(tid(page, "draft-generate")).to_be_visible(timeout=30_000)
        tid(page, "draft-generate").click()
        expect(tid(page, "draft-origin-label")).to_be_visible(timeout=60_000)
    expect(tid(page, "draft-version-select")).to_be_visible()
    page.wait_for_timeout(600)
    assert page.evaluate("document.documentElement.scrollWidth") <= w, "Borradores con editor y versiones desborda la pantalla"
    b = tid(page, "draft-version-select").bounding_box()
    assert b and b["x"] >= 0 and b["x"] + b["width"] <= w + 1, f"el selector de versión sale de la pantalla: {b}"


@pytest.mark.parametrize("w,h", [(1440, 900), (390, 844), (320, 640)], ids=lambda v: str(v))
def test_respuesta_del_asistente_viene_organizada(page: Page, stack, w, h):
    """La respuesta se lee como texto estructurado: párrafos, lista numerada, negritas y sin desborde."""
    page.set_viewport_size({"width": w, "height": h})
    open_app(page, stack.url)
    tid(page, "assistant-toggle").click()
    tid(page, "assistant-input").fill("Qué cinco temas merecen revisión para la agenda de Panamá")
    if w < 1024:
        tid(page, "assistant-send").click()
    else:
        page.keyboard.press("Enter")
    expect(tid(page, "assistant-answer")).to_have_count(1, timeout=40_000)
    text = tid(page, "assistant-answer-text").first
    assert text.locator("p").count() >= 2, "la respuesta debe separar párrafos"
    assert text.locator("ol > li").count() >= 2, "los temas deben ir en una lista numerada"
    assert text.locator("strong").count() >= 3, "los titulares y el puntaje deben ir en negrita"
    assert "**" not in text.inner_text() and "`" not in text.inner_text(), "no deben verse marcas de formato crudas"
    assert page.evaluate("document.documentElement.scrollWidth") <= w


@pytest.mark.parametrize("w", [1440, 1024, 768])
def test_pestanas_de_la_cabecera_estan_centradas(page: Page, stack, w):
    """En escritorio y tableta las pestañas quedan centradas en la cabecera (marca a la izquierda, asistente a la derecha)."""
    page.set_viewport_size({"width": w, "height": 900})
    open_app(page, stack.url)
    first, last = box(page, "nav-agenda"), box(page, "nav-fuentes")
    brand = page.locator("header .comic-brand").bounding_box()
    asistente = box(page, "assistant-toggle")
    nav_center = (first["x"] + last["x"] + last["width"]) / 2
    assert abs(nav_center - w / 2) <= 2, f"las pestañas no están centradas: centro {nav_center} vs {w / 2}"
    assert brand and brand["x"] + brand["width"] < first["x"], "la marca debe quedar a la izquierda de las pestañas"
    assert asistente["x"] > last["x"] + last["width"], "el asistente debe quedar a la derecha de las pestañas"
