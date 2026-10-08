"""E2E responsive y accesibilidad básica: 1440 / 390 / 320 px, teclado, foco visible y movimiento reducido.

Backend real (snapshot sintético etiquetado) + build de Astro. Guarda capturas en tests/.results/responsive/.
No sustituye una auditoría de accesibilidad con lector de pantalla ni una revisión humana del diseño.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from e2e.helpers import open_app, open_first_ficha, tid
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

RESULTS = Path(__file__).resolve().parents[1] / ".results" / "responsive"
WIDTHS = [(1440, 900), (390, 844), (320, 640)]

JS_OVERFLOW = """() => {
  // Desborde de PÁGINA: scrollWidth > innerWidth, o elementos que sobresalen sin estar dentro de un contenedor con
  // desplazamiento/recorte propio (nav, tablas con overflow-x). Lo contenido en un scroller no cuenta.
  const d = document.documentElement;
  const inScroller = (el) => {
    for (let p = el.parentElement; p && p !== document.body && p !== d; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return true;
    }
    return false;
  };
  const wide = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > window.innerWidth + 1 && getComputedStyle(el).position !== 'fixed' && !inScroller(el)) {
      wide.push(el.tagName.toLowerCase() + (el.getAttribute('data-testid') ? '[' + el.getAttribute('data-testid') + ']' : ''));
    }
  }
  return {scrollWidth: d.scrollWidth, innerWidth: window.innerWidth, wide: wide.slice(0, 8)};
}"""

JS_UNLABELLED = """() => {
  const bad = [];
  const sel = 'button, a[href], input, select, textarea, [role=button], [role=tab]';
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('[hidden], [inert]') || getComputedStyle(el).display === 'none') continue;
    const name = (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.textContent || el.getAttribute('title') || '').trim();
    const labelled = el.labels && el.labels.length > 0;
    if (!name && !labelled) bad.push(el.tagName.toLowerCase() + (el.getAttribute('data-testid') ? '[' + el.getAttribute('data-testid') + ']' : ''));
  }
  return bad.slice(0, 10);
}"""

JS_FOCUS_STYLE = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const cs = getComputedStyle(el);
  return {tag: el.tagName.toLowerCase(), testid: el.getAttribute('data-testid'), outlineStyle: cs.outlineStyle,
          outlineWidth: parseFloat(cs.outlineWidth), boxShadow: cs.boxShadow};
}"""

JS_MOTION = """() => {
  const moving = [];
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    const anim = cs.animationName !== 'none' && parseFloat(cs.animationDuration) > 0.011 && cs.animationIterationCount !== '1';
    const animOnce = cs.animationName !== 'none' && parseFloat(cs.animationDuration) > 0.011;
    const trans = cs.transitionProperty !== 'none' && cs.transitionProperty !== '' && parseFloat(cs.transitionDuration) > 0.011;
    if (anim || animOnce || trans) moving.push(el.tagName.toLowerCase() + (el.getAttribute('data-testid') ? '[' + el.getAttribute('data-testid') + ']' : '') + ':' + (anim || animOnce ? cs.animationName : cs.transitionProperty));
  }
  return {count: moving.length, sample: moving.slice(0, 8), scroll: getComputedStyle(document.documentElement).scrollBehavior};
}"""


def go_view(page: Page, nav: str) -> None:
    tid(page, nav).click()
    page.wait_for_timeout(400)


@pytest.mark.parametrize("w,h", WIDTHS, ids=lambda v: str(v))
def test_vistas_sin_desborde_ni_controles_sin_nombre(page: Page, stack, w, h):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_viewport_size({"width": w, "height": h})
    RESULTS.mkdir(parents=True, exist_ok=True)
    open_app(page, stack.url)
    problems: list[str] = []
    for nav, label in (("nav-agenda", "agenda"), ("nav-ficha", "ficha"), ("nav-borradores", "borradores"), ("nav-fuentes", "fuentes")):
        if nav == "nav-ficha":
            go_view(page, "nav-agenda")
            open_first_ficha(page)
        else:
            go_view(page, nav)
        page.screenshot(path=str(RESULTS / f"{label}-{w}.png"), full_page=True)
        o = page.evaluate(JS_OVERFLOW)
        if o["scrollWidth"] > o["innerWidth"] + 1 or o["wide"]:
            problems.append(f"{label}@{w}: desborde horizontal {o}")
        bad = page.evaluate(JS_UNLABELLED)
        if bad:
            problems.append(f"{label}@{w}: controles sin nombre accesible {bad}")
    assert not errors, f"errores JS: {errors[:3]}"
    assert not problems, "; ".join(problems)


def test_teclado_recorre_la_cabecera_y_el_foco_es_visible(page: Page, stack):
    open_app(page, stack.url)
    seen: list[dict] = []
    for _ in range(14):
        page.keyboard.press("Tab")
        info = page.evaluate(JS_FOCUS_STYLE)
        assert info is not None, "el foco se perdió en el cuerpo del documento"
        seen.append(info)
    invisible = [s for s in seen if (s["outlineStyle"] == "none" or s["outlineWidth"] == 0) and s["boxShadow"] == "none"]
    assert not invisible, f"elementos enfocados sin indicador visible: {invisible[:3]}"
    assert any(s["testid"] and s["testid"].startswith("nav-") for s in seen) or any(s["tag"] == "a" for s in seen), \
        "el recorrido por Tab no llega a la navegación"


def test_asistente_con_teclado_enter_abre_y_escape_devuelve_el_foco(page: Page, stack):
    page.set_viewport_size({"width": 390, "height": 844})
    open_app(page, stack.url)
    toggle = tid(page, "assistant-toggle")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(tid(page, "assistant-input")).to_be_visible()
    page.keyboard.press("Escape")
    expect(tid(page, "assistant-input")).to_be_hidden()
    assert page.evaluate("document.activeElement && document.activeElement.getAttribute('data-testid')") == "assistant-toggle"


def test_agenda_se_opera_solo_con_teclado(page: Page, stack):
    open_app(page, stack.url)
    first_link = tid(page, "topic-card").first.get_by_test_id("open-ficha")
    first_link.focus()
    page.keyboard.press("Enter")
    expect(tid(page, "ficha")).to_be_visible(timeout=30_000)


def test_movimiento_reducido_se_respeta(browser, stack):
    ctx = browser.new_context(reduced_motion="reduce", viewport={"width": 1440, "height": 900})
    try:
        page = ctx.new_page()
        open_app(page, stack.url)
        m = page.evaluate(JS_MOTION)
        assert m["count"] == 0 and m["scroll"] != "smooth", (
            f"con prefers-reduced-motion hay {m['count']} elementos con animación/transición > 10 ms "
            f"(muestra {m['sample']}); scroll-behavior={m['scroll']}")
    finally:
        ctx.close()
