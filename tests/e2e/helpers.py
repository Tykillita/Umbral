"""Utilidades de los E2E: navegación por data-testid de la interfaz real (hash router: #/ficha/<id>, #/borradores/<id>)."""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect


def tid(page: Page, name: str):
    return page.get_by_test_id(name)


# Las animaciones de entrada (src/lib/motion.ts) son finitas y duran < 600 ms; las infinitas (spinner) no cuentan.
_MOTION_IDLE = """() => document.getAnimations().every(a =>
  (a.effect && a.effect.getComputedTiming().iterations === Infinity) || (a.playState !== 'running' && a.playState !== 'pending'))"""


def settle_motion(page: Page) -> None:
    """Espera a que terminen las animaciones decorativas antes de medir geometría (alturas, posiciones)."""
    page.wait_for_function(_MOTION_IDLE, timeout=5000)


def open_app(page: Page, base: str) -> None:
    page.goto(base + "/app")
    try:
        page.get_by_test_id("app-root").wait_for(timeout=8000)
    except Exception:  # noqa: BLE001
        msg = "el frontend no expone data-testid='app-root' en /app (ver tests/e2e/TESTIDS.md)"
        if os.environ.get("UMBRAL_TESTS_STRICT"):
            pytest.fail(msg, pytrace=False)
        pytest.skip(msg)
    expect(tid(page, "topic-card").first).to_be_visible(timeout=30_000)
    settle_motion(page)


def open_assistant(page: Page) -> None:
    if not tid(page, "assistant-input").is_visible():
        tid(page, "assistant-toggle").click()
    expect(tid(page, "assistant-input")).to_be_visible()


def ask(page: Page, question: str, expected_turns: int) -> None:
    open_assistant(page)
    tid(page, "assistant-input").fill(question)
    tid(page, "assistant-send").click()
    expect(tid(page, "assistant-answer")).to_have_count(expected_turns, timeout=40_000)


def open_first_ficha(page: Page, index: int = 0) -> str:
    """Abre la ficha del tema `index` de la agenda y devuelve su topicId (de la URL)."""
    tid(page, "topic-card").nth(index).get_by_test_id("open-ficha").click()
    expect(tid(page, "ficha")).to_be_visible(timeout=30_000)
    settle_motion(page)
    return page.url.split("/ficha/")[-1]


def draft_and_review(page: Page, reviewer: str = "Revisora E2E") -> None:
    """Desde una ficha abierta: crear borrador, revisar (en_revision) y exportar a Markdown."""
    if tid(page, "assistant-panel").is_visible():
        tid(page, "assistant-close").click()
        expect(tid(page, "assistant-panel")).to_have_count(0)
    tid(page, "go-drafts").click()
    expect(tid(page, "draft-generate")).to_be_visible(timeout=30_000)
    tid(page, "draft-generate").click()
    expect(tid(page, "draft-origin-label")).to_be_visible(timeout=60_000)
    expect(tid(page, "draft-brief")).not_to_be_empty()
    tid(page, "review-reviewer").fill(reviewer)
    tid(page, "review-action-en_revision").click()
    expect(tid(page, "review-status")).to_have_attribute("data-status", "en_revision", timeout=30_000)
    tid(page, "export-markdown").click()
    expect(tid(page, "export-preview")).to_be_visible(timeout=30_000)


def choose(page: Page, testid: str, value: str) -> None:
    """Elige una opción de un menú desplegable PROPIO (rol combobox): abre la lista y pulsa la opción por su valor."""
    tid(page, testid).click()
    option = page.locator(f'[role="listbox"] [role="option"][data-value="{value}"]')
    expect(option).to_be_visible()
    option.click()
    expect(page.locator('[role="listbox"]')).to_have_count(0)
