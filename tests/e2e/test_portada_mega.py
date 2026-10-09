"""Estructura, accesibilidad e interacciones de la nueva portada editorial."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("width,height", [(1440, 900), (1024, 900), (768, 900), (390, 844), (320, 640)])
def test_portada_muestra_estructura_y_snapshot_actual(page: Page, stack, width: int, height: int):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(stack.url + "/")

    expect(page.get_by_role("link", name="Umbral, inicio")).to_be_visible()
    expect(page.locator("header.landing-header.comic-masthead")).to_have_count(1)
    expect(page.get_by_role("heading", name="¿Qué cinco temas merecen revisión para la agenda de Panamá, y por qué?")).to_be_visible()
    expect(page.locator("#landing-steps-track > ol > li")).to_have_count(5)
    expect(page.locator("[data-testid^='landing-promise-'][data-promise-id]")).to_have_count(4)
    expect(page.locator("[data-testid^='landing-faq-']")).to_have_count(7)
    expect(page.get_by_role("link", name="Ver la agenda de hoy")).to_have_attribute("href", "/app/")
    expect(page.get_by_role("link", name="Preguntas frecuentes")).to_have_attribute("href", "#preguntas")
    expect(page.get_by_test_id("landing-snapshot-status")).to_contain_text("Corte", timeout=15_000)
    expect(page.locator(".landing-stat").nth(0)).to_contain_text("titulares y metadatos")
    expect(page.locator(".landing-stat").nth(1)).to_contain_text("temas en las 6 categorías")
    assert page.locator(".landing-stat strong").nth(0).inner_text() != "Cargando…"
    assert page.locator(".landing-stat strong").nth(1).inner_text() != "Cargando…"

    cards_geometry = page.get_by_test_id("landing-steps-track").evaluate(
        """track => {
          const clip = track.getBoundingClientRect();
          const cards = [...track.querySelectorAll('li')].map(card => card.getBoundingClientRect())
            .filter(rect => rect.right > clip.left && rect.left < clip.right);
          return {
            fits: cards.length > 0 && cards.every(rect => rect.left >= clip.left - 1 && rect.right <= clip.right + 1),
            track: {left: clip.left, right: clip.right, clientWidth: track.clientWidth, scrollWidth: track.scrollWidth},
            cards: cards.map(rect => ({left: rect.left, right: rect.right, width: rect.width}))
          };
        }"""
    )
    assert cards_geometry["fits"], f"Una tarjeta de pasos queda recortada en {width}px: {json.dumps(cards_geometry)}"

    native = page.locator(
        "select, input[type=checkbox], input[type=radio], input[type=number], input[type=search], "
        "input[type=range], input[type=date], input[type=time], input[type=month], input[type=week], "
        "input[type=file], input[type=color], details, summary, dialog, datalist, progress, meter, [title], [required]"
    )
    expect(native).to_have_count(0)


def test_carrusel_tarjetas_y_preguntas_se_operan_con_teclado(page: Page, stack):
    page.goto(stack.url + "/")
    track = page.get_by_test_id("landing-steps-track")
    track.focus()
    page.keyboard.press("ArrowRight")
    page.wait_for_function("document.querySelector('[data-testid=landing-steps-track]').scrollLeft > 0")

    card = page.get_by_test_id("landing-promise-cita-datos")
    flip = card.locator(".landing-promise-flip")
    flip.focus()
    page.keyboard.press("Enter")
    expect(flip).to_have_attribute("aria-pressed", "true")

    first = page.get_by_test_id("landing-promise-handle-cita-datos")
    before = page.locator("[data-testid^='landing-promise-'][data-promise-id]").evaluate_all(
        "cards => cards.map(card => card.dataset.promiseId)"
    )
    first.focus()
    page.keyboard.press("Alt+ArrowRight")
    page.wait_for_function(
        "() => document.querySelector('[data-testid^=landing-promise-][data-promise-id]').dataset.promiseId !== 'cita-datos'"
    )
    after = page.locator("[data-testid^='landing-promise-'][data-promise-id]").evaluate_all(
        "cards => cards.map(card => card.dataset.promiseId)"
    )
    assert after == [before[1], before[0], *before[2:]]
    assert page.evaluate("localStorage.getItem('umbral.landing-promises.order.v1')") == json.dumps(after, ensure_ascii=False, separators=(",", ":"))

    page.reload()
    expect(page.locator("[data-testid^='landing-promise-'][data-promise-id]").first).to_have_attribute("data-promise-id", after[0])

    faq_one = page.get_by_test_id("landing-faq-1").get_by_role("button")
    faq_two = page.get_by_test_id("landing-faq-2").get_by_role("button")
    faq_one.click()
    expect(faq_one).to_have_attribute("aria-expanded", "true")
    faq_two.click()
    expect(faq_two).to_have_attribute("aria-expanded", "true")
    expect(faq_one).to_have_attribute("aria-expanded", "false")


def test_orden_de_promesas_se_puede_cambiar_arrastrando(page: Page, stack):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(stack.url + "/")
    page.evaluate("localStorage.removeItem('umbral.landing-promises.order.v1')")
    page.reload()
    cards = page.locator("[data-testid^='landing-promise-'][data-promise-id]")
    cards.first.scroll_into_view_if_needed()
    before = cards.evaluate_all("items => items.map(item => item.dataset.promiseId)")
    source_handle = cards.first.locator(".landing-promise-handle")
    target_card = page.get_by_test_id("landing-promise-muestra-procedencia")
    target_card.scroll_into_view_if_needed()
    source = source_handle.bounding_box()
    target = target_card.bounding_box()
    assert source and target
    page.mouse.move(source["x"] + source["width"] / 2, source["y"] + source["height"] / 2)
    page.mouse.down()
    page.mouse.move(source["x"] + source["width"] / 2 + 32, source["y"] + source["height"] / 2 + 24, steps=2)
    expect(cards.first).to_have_class("landing-promise-card comic-panel is-dragging")
    assert cards.first.evaluate("card => getComputedStyle(card).transform") != "none"
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + target["height"] / 2, steps=5)
    page.mouse.up()

    after = page.locator("[data-testid^='landing-promise-'][data-promise-id]").evaluate_all(
        "items => items.map(item => item.dataset.promiseId)"
    )
    expected = list(before)
    moved = expected.pop(0)
    expected.insert(expected.index("muestra-procedencia"), moved)
    assert after == expected
    page.wait_for_function(
        """() => {
          const card = document.querySelector('[data-promise-id="cita-datos"]');
          return card && getComputedStyle(card).transform === 'none';
        }"""
    )


def test_cinta_de_categorias_se_mueve_en_bucle(page: Page, stack):
    page.emulate_media(reduced_motion="no-preference")
    page.goto(stack.url + "/")
    page.locator("html").evaluate("element => element.dataset.motionPreference = 'full'")
    ticker = page.locator(".landing-ticker-track")
    animation = ticker.evaluate(
        "element => ({name: getComputedStyle(element).animationName, iterations: getComputedStyle(element).animationIterationCount})"
    )
    assert animation == {"name": "landing-marquee", "iterations": "infinite"}
    page.wait_for_function(
        """() => {
          const ticker = document.querySelector('.landing-ticker');
          const track = document.querySelector('.landing-ticker-track');
          const copies = [...document.querySelectorAll('.landing-ticker-copy')];
          const width = copies[0]?.getBoundingClientRect().width ?? 0;
          return track.dataset.ready === 'true' && copies.length === 2 && width >= ticker.clientWidth - 1 &&
            Math.abs(width - copies[1].getBoundingClientRect().width) < 0.5;
        }"""
    )
    geometry = ticker.evaluate(
        """track => {
          const copies = [...track.querySelectorAll('.landing-ticker-copy')];
          const width = copies[0].getBoundingClientRect().width;
          const duration = Number.parseFloat(getComputedStyle(track).animationDuration);
          return {width, duration, expectedDuration: Math.max(11, width / 64)};
        }"""
    )
    assert abs(geometry["duration"] - geometry["expectedDuration"]) < 0.2, geometry
    before = ticker.evaluate("element => getComputedStyle(element).transform")
    page.wait_for_function(
        """initial => getComputedStyle(document.querySelector('.landing-ticker-track')).transform !== initial""",
        arg=before,
    )


def test_tarjetas_y_faq_aceptan_toque_en_movil(browser, stack):
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    try:
        page = context.new_page()
        page.goto(stack.url + "/")
        flip = page.get_by_test_id("landing-promise-cita-datos").locator(".landing-promise-flip")
        flip.tap()
        expect(flip).to_have_attribute("aria-pressed", "true")
        trigger = page.get_by_test_id("landing-faq-1").get_by_role("button")
        trigger.tap()
        expect(trigger).to_have_attribute("aria-expanded", "true")
    finally:
        context.close()


def test_movimiento_reducido_detiene_la_cinta_y_el_desplazamiento_suave(browser, stack):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    try:
        page = context.new_page()
        page.goto(stack.url + "/")
        motion = page.evaluate(
            """() => ({
              ticker: getComputedStyle(document.querySelector('.landing-ticker-track')).animationName,
              scroll: getComputedStyle(document.querySelector('.landing-step-track')).scrollBehavior
            })"""
        )
        assert motion["ticker"] == "none"
        assert motion["scroll"] == "auto"
    finally:
        context.close()
