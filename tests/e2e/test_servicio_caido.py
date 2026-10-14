"""Con el backend caído (sin despliegue activo, iniciando o sin conexión) la página debe seguir viéndose bien:
mensaje claro y sin ruido, nunca «Error HTTP 404» crudo ni varios avisos rojos repetidos, y sin romper la maquetación.
"""

from __future__ import annotations

import pytest
from helpers import open_app, tid
from playwright.sync_api import Browser, expect

pytestmark = pytest.mark.e2e

NOT_FOUND_HTML = "<!DOCTYPE html><html><head><title>404</title></head><body><h1>Not Found</h1></body></html>"


@pytest.mark.parametrize("ancho,alto,tactil", [(1366, 900, False), (390, 844, True), (320, 640, True)])
def test_con_el_backend_caido_la_agenda_muestra_un_aviso_claro_y_sin_ruido(
    browser: Browser, stack, ancho: int, alto: int, tactil: bool,
):
    ctx = browser.new_context(
        viewport={"width": ancho, "height": alto}, has_touch=tactil, is_mobile=tactil,
        locale="es-PA", timezone_id="America/Panama",
    )
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        # El proxy del servicio alojado sin despliegue activo responde 404 con HTML, no con el cuerpo de error de Umbral.
        page.route("**/api/**", lambda route: route.fulfill(status=404, content_type="text/html", body=NOT_FOUND_HTML))
        tid(page, "agenda-search").fill("canal")
        expect(page.get_by_text("Datos no disponibles por ahora").first).to_be_visible(timeout=20_000)

        text = page.inner_text("body")
        assert "Error HTTP" not in text, "no debe mostrarse el error HTTP crudo"
        assert "No se pudo completar la operación" not in text, "un servicio caído no es un error rojo de la operación"
        assert page.get_by_text("Datos no disponibles por ahora").count() == 1, "el aviso no debe repetirse"
        # La maquetación sigue entera: buscador, filtros y barra de navegación visibles y sin desbordamiento.
        expect(tid(page, "agenda-search")).to_be_visible()
        expect(tid(page, "filter-band")).to_be_visible() if ancho >= 768 else expect(tid(page, "filters-toggle")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"desborda a {ancho}px"
    finally:
        ctx.close()
