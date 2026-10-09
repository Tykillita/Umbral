"""T10 E2E: sin internet. Navegador sin red (solo loopback) + backend con red bloqueada y UMBRAL_OFFLINE=1.

Carga -> ranking -> consulta -> ficha -> borrador de respaldo -> revisión -> exportación, sin ninguna salida a internet.
(La re-ejecución de Laya local requiere el extra `laya` y los pesos; no se ejecuta aquí.)
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from e2e.helpers import ask, draft_and_review, open_app, open_first_ficha, tid
from playwright.sync_api import BrowserContext, Page, expect

pytestmark = pytest.mark.e2e


def test_flujo_completo_con_la_red_bloqueada(context: BrowserContext, page: Page, offline_stack):
    blocked: list[str] = []

    def guard(route):
        host = urlparse(route.request.url).hostname or ""
        if host in ("127.0.0.1", "localhost"):
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort("internetdisconnected")

    context.route("**/*", guard)
    open_app(page, offline_stack.url, role="juror")                     # carga + ranking y flujo completo
    expect(tid(page, "offline-indicator")).to_be_visible()
    ask(page, "¿Qué hay sobre turismo y cruceristas en Panamá?", 1)       # consulta con evidencia
    assert tid(page, "assistant-citation").count() >= 1
    open_first_ficha(page)                                               # ficha
    draft_and_review(page, "Revisora Offline")                           # borrador de respaldo + revisión + exportación
    mode = tid(page, "draft-origin-label").get_attribute("data-mode")
    assert mode in {"plantilla", "recuperado"}, f"sin internet no puede ser 'modelo' (fue {mode})"
    expect(tid(page, "draft-fallback-reason")).to_contain_text("conexión")

    assert blocked == [], f"el navegador intentó salir a internet: {blocked[:5]}"
    log = Path(offline_stack.workdir) / "netblock.log"
    assert not log.exists() or log.read_text(encoding="utf-8").strip() == "", "el backend intentó salir a internet"
