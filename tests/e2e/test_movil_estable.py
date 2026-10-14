"""Móvil y PWA: la interfaz abre, cierra y cuadra en pantallas táctiles estrechas, y la app se puede instalar y abrir sin red.

Usa contextos con emulación real de teléfono (`is_mobile`, `has_touch`, factor de escala 3) y no solo un viewport pequeño:
así el meta viewport, `(pointer: coarse)` y los toques se comportan como en un móvil. Solo hay Chromium instalado:
lo propio de Safari/iOS (teclado virtual, zonas seguras reales, PWA instalada) queda como verificación manual pendiente.
"""

from __future__ import annotations

import json

import pytest
from helpers import open_app, settle_motion, tid
from playwright.sync_api import Browser, expect

pytestmark = pytest.mark.e2e

WIDTHS = [320, 360, 375, 390, 430, 600, 767]


def mobile_context(browser: Browser, width: int = 390, height: int = 844):
    return browser.new_context(
        viewport={"width": width, "height": height}, has_touch=True, is_mobile=True, device_scale_factor=3,
        locale="es-PA", timezone_id="America/Panama",
    )


def test_el_viewport_cubre_la_pantalla_completa_y_declara_la_pwa(browser, stack):
    ctx = mobile_context(browser)
    try:
        page = ctx.new_page()
        page.goto(stack.url + "/app")
        assert "viewport-fit=cover" in page.locator('meta[name="viewport"]').get_attribute("content")
        assert page.locator('link[rel="manifest"]').get_attribute("href") == "/manifest.webmanifest"
        assert page.locator('link[rel="apple-touch-icon"]').count() == 1
        assert page.locator('meta[name="apple-mobile-web-app-capable"]').get_attribute("content") == "yes"
    finally:
        ctx.close()


def test_la_pantalla_de_elegir_rol_se_puede_recorrer_entera_en_un_telefono_pequeno(browser, stack):
    """La pantalla vive fuera de #app-root: antes quedaba en un <body> sin scroll y el final era inalcanzable."""
    ctx = mobile_context(browser, 320, 568)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        tid(page, "role-change").tap()  # vuelve a la pantalla de elegir rol
        expect(tid(page, "session-gate")).to_be_visible()
        scroller = page.locator(".app-screen")
        assert scroller.evaluate("el => el.scrollHeight > el.clientHeight"), "se esperaba contenido más alto que la pantalla"
        scroller.evaluate("el => el.scrollTo(0, el.scrollHeight)")
        last = page.get_by_text("Qué se guarda y dónde")
        box = last.bounding_box()
        assert box is not None and box["y"] + box["height"] <= 568 + 1, f"el final no es alcanzable: {box}"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        ctx.close()


def test_el_asistente_abre_completo_y_el_boton_atras_lo_cierra(browser, stack):
    ctx = mobile_context(browser)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        url = page.url
        tid(page, "assistant-toggle").tap()
        expect(tid(page, "assistant-panel")).to_be_visible()
        expect(tid(page, "assistant-input")).to_be_visible()
        settle_motion(page)  # la entrada del panel dura 180 ms: se mide ya asentado
        box = tid(page, "assistant-panel").bounding_box()
        assert box is not None
        assert box["x"] <= 0.5 and box["y"] <= 0.5, f"el panel no está pegado a la esquina: {box}"
        assert abs(box["width"] - 390) <= 1 and abs(box["height"] - 844) <= 1, f"el panel no ocupa la pantalla: {box}"
        # Con pantalla táctil no se enfoca solo el campo: el teclado no debe abrirse sin que la persona lo pida.
        assert not page.evaluate("document.activeElement && document.activeElement.tagName === 'TEXTAREA'")
        page.go_back()
        expect(tid(page, "assistant-panel")).to_have_count(0)
        assert page.url == url, "Atrás debe cerrar el panel sin cambiar de vista"
        assert page.evaluate("document.body.style.overflow") != "hidden"
        # Y la cabecera vuelve a responder (no queda inerte).
        tid(page, "assistant-toggle").tap()
        expect(tid(page, "assistant-panel")).to_be_visible()
    finally:
        ctx.close()


def test_tocar_el_fondo_de_la_hoja_de_seleccion_no_activa_lo_que_hay_debajo(browser, stack):
    ctx = mobile_context(browser)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        url = page.url
        tid(page, "filters-toggle").tap()
        tid(page, "filter-band").tap()
        expect(tid(page, "select-sheet")).to_be_visible()
        # Abrir la hoja no debe desplazar los contenedores fijos (antes la cabecera salía 116 px por arriba).
        assert page.evaluate("document.body.scrollTop + document.getElementById('app-root').scrollTop") == 0
        brand = page.locator(".comic-brand").first.bounding_box()
        assert brand is not None
        # El toque cae sobre el enlace de inicio que hay bajo el fondo: antes lo activaba además de cerrar la hoja.
        page.touchscreen.tap(brand["x"] + brand["width"] / 2, brand["y"] + brand["height"] / 2)
        expect(tid(page, "select-sheet")).to_have_count(0)
        page.wait_for_timeout(300)
        assert page.url == url, "el toque atravesó la hoja y navegó"
        assert tid(page, "filter-band").get_attribute("data-open") == "false"
    finally:
        ctx.close()


def test_atras_cierra_la_hoja_de_seleccion(browser, stack):
    ctx = mobile_context(browser)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        url = page.url
        tid(page, "filters-toggle").tap()
        tid(page, "filter-band").tap()
        expect(tid(page, "select-sheet")).to_be_visible()
        page.go_back()
        expect(tid(page, "select-sheet")).to_have_count(0)
        assert page.url == url
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [500, 600, 767])
def test_configuracion_ocupa_toda_la_pantalla_en_telefonos_grandes(browser, stack, width: int):
    ctx = mobile_context(browser, width, 900)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        tid(page, "settings-toggle").tap()
        panel = tid(page, "settings-dialog")
        expect(panel).to_be_visible()
        box = panel.bounding_box()
        assert box is not None and box["x"] <= 0.5 and abs(box["width"] - width) <= 1, f"el panel queda a medias: {box}"
        page.go_back()
        expect(panel).to_have_count(0)
    finally:
        ctx.close()


def test_los_campos_de_texto_miden_16px_en_pantalla_tactil(browser, stack):
    """Con menos de 16 px, iOS amplía la página al enfocar el campo y ya no se vuelve a alinear."""
    ctx = mobile_context(browser)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        search = tid(page, "agenda-search")
        assert float(search.evaluate("el => getComputedStyle(el).fontSize.replace('px','')")) >= 16
        tid(page, "assistant-toggle").tap()
        field = tid(page, "assistant-input")
        expect(field).to_be_visible()
        assert float(field.evaluate("el => getComputedStyle(el).fontSize.replace('px','')")) >= 16
    finally:
        ctx.close()


@pytest.mark.parametrize("width", WIDTHS)
def test_sin_desbordamiento_y_barra_inferior_pegada_al_borde(browser, stack, width: int):
    height = 844
    ctx = mobile_context(browser, width, height)
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        settle_motion(page)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"desborda a {width}px"
        bar = page.locator(".comic-tabbar").bounding_box()
        if width <= 767:
            assert bar is not None and abs((bar["y"] + bar["height"]) - height) <= 1, f"la barra no está en el borde inferior: {bar}"
            assert bar["x"] <= 0.5 and abs(bar["width"] - width) <= 1
            for item in page.locator(".comic-tabbar .comic-nav:visible, .comic-tabbar .comic-mobile-more-trigger:visible").all():
                box = item.bounding_box()
                assert box is not None and box["x"] >= -0.5 and box["x"] + box["width"] <= width + 0.5, f"un botón sale de la pantalla: {box}"
    finally:
        ctx.close()


# ----------------------------------------------------------------------------------------------------- PWA

def test_el_manifest_cumple_los_requisitos_de_instalacion(page, stack):
    response = page.request.get(stack.url + "/manifest.webmanifest")
    assert response.ok
    assert "manifest+json" in response.headers["content-type"]
    manifest = json.loads(response.text())
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/app"
    assert manifest["lang"] == "es"
    sizes = {(icon["sizes"], icon.get("purpose", "any")) for icon in manifest["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes and ("512x512", "maskable") in sizes
    for icon in manifest["icons"]:
        assert page.request.get(stack.url + icon["src"]).ok, f"falta el icono {icon['src']}"


def test_el_service_worker_lleva_version_y_no_se_cachea_en_el_navegador(page, stack):
    response = page.request.get(stack.url + "/sw.js")
    assert response.ok
    assert "no-cache" in response.headers.get("cache-control", ""), "sw.js debe revalidarse siempre"
    body = response.text()
    assert "__BUILD_VERSION__'" not in body and "__PRECACHE_URLS__'" not in body, "el build no sustituyó los marcadores"
    assert "/_astro/" in body, "la lista de precaché debe incluir los recursos del build"
    # La API jamás pasa por la caché del worker.
    assert "startsWith('/api/')" in body


def test_la_app_abre_sin_conexion_y_nunca_cachea_la_api(browser, stack):
    ctx = browser.new_context(locale="es-PA", timezone_id="America/Panama", viewport={"width": 1366, "height": 900})
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        page.evaluate("navigator.serviceWorker.ready.then(() => true)")
        # Hasta que el worker toma el control (clients.claim) la página no está controlada.
        page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=15_000)
        cached = page.evaluate(
            """async () => {
              const urls = [];
              for (const name of await caches.keys()) for (const req of await (await caches.open(name)).keys()) urls.push(new URL(req.url).pathname);
              return urls;
            }"""
        )
        assert any(url.startswith("/_astro/") for url in cached), "el shell no se precacheó"
        assert "/app" in cached or "/app/" in cached, f"la página de la app no quedó guardada: {cached}"
        assert not any(url.startswith("/api/") for url in cached), "la API no debe guardarse en caché"

        ctx.set_offline(True)
        page.goto(stack.url + "/app")
        assert "Umbral" in page.title(), "sin conexión debe abrir el shell guardado"
        expect(page.locator("#app-root, [data-testid='session-gate'], [data-testid='app-loading'], [data-testid='app-boot-error']").first).to_be_visible(timeout=15_000)
    finally:
        ctx.close()
