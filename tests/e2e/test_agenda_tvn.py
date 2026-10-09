"""Filtro de oportunidad TVN: composición, teclado, tamaños móviles y toque real."""

from __future__ import annotations

import pytest
from e2e.helpers import open_app, settle_motion, tid
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("width", [1440, 1024, 768, 640, 390, 320])
def test_filtro_tvn_se_alinea_con_busqueda_y_accesible_por_teclado(page: Page, stack, width: int):
    page.set_viewport_size({"width": width, "height": 900 if width >= 768 else 844})
    open_app(page, stack.url)
    search = tid(page, "agenda-search")
    toggle = tid(page, "agenda-tvn-gap")
    expect(toggle).to_be_visible()
    assert toggle.get_attribute("aria-pressed") == "false"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    search.focus()
    page.keyboard.press("Tab")
    expect(toggle).to_be_focused()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-pressed", "true")

    search.fill("canal")
    expect(tid(page, "agenda-count")).to_be_visible()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    settle_motion(page)

    search_box = search.bounding_box()
    toggle_box = toggle.bounding_box()
    assert search_box and toggle_box
    if width >= 640:
        assert toggle_box["x"] >= search_box["x"] + search_box["width"], "el filtro debe quedar a la derecha del buscador"
        assert toggle_box["y"] < search_box["y"] + search_box["height"] and toggle_box["y"] + toggle_box["height"] > search_box["y"], \
            "el filtro debe compartir la fila del campo"
    else:
        assert abs(toggle_box["x"] - search_box["x"]) <= 2
        assert toggle_box["y"] >= search_box["y"] + search_box["height"] - 2


def test_filtro_tvn_acepta_toque(browser: Browser, stack):
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    page = context.new_page()
    try:
        open_app(page, stack.url)
        toggle = tid(page, "agenda-tvn-gap")
        toggle.scroll_into_view_if_needed()
        bounds = toggle.bounding_box()
        assert bounds
        page.touchscreen.tap(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
        expect(toggle).to_have_attribute("aria-pressed", "true")
    finally:
        context.close()
