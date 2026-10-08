"""E2E del recorrido editorial: Agenda -> Ficha -> Asistente -> Borrador -> Revisión -> Exportación.

Backend REAL (FastAPI + SQLite temporal + build de Astro) con el snapshot sintético de pruebas y sin clave de Gemini
(los borradores deben declararse «plantilla»). Selectores: `data-testid` (ver TESTIDS.md).
"""

from __future__ import annotations

import pytest
from e2e.helpers import ask, draft_and_review, open_app, open_first_ficha, tid
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_agenda_muestra_cinco_temas_con_puntaje_y_evidencia(page: Page, stack):
    reqs: list[str] = []
    page.on("request", lambda r: reqs.append(r.url))
    open_app(page, stack.url)
    assert tid(page, "topic-card").count() == 5, "la agenda debe mostrar los cinco temas principales"
    assert tid(page, "mock-banner").count() == 0, "el E2E debe usar la API real, no datos de demostración"
    assert any("/api/v1/topics" in u for u in reqs), "la agenda debe venir de la API real"
    first = tid(page, "topic-card").first
    expect(first.get_by_test_id("topic-score")).to_be_visible()
    expect(first.get_by_test_id("topic-evidence-status")).to_be_visible()
    expect(tid(page, "snapshot-badge")).to_contain_text("-")  # snapshotId = YYYYMMDD-hash8
    expect(tid(page, "data-mode-banner")).to_be_visible()      # snapshot de pruebas = fixture: debe declararse
    expect(tid(page, "data-mode-banner")).to_have_attribute("data-mode", "fixture")


def test_agenda_filtra_y_busca(page: Page, stack):
    open_app(page, stack.url)
    tid(page, "agenda-search").fill("cruceristas")
    expect(tid(page, "topic-card").first).to_contain_text("cruceristas", timeout=15_000)
    assert tid(page, "topic-card").count() >= 1


def test_ficha_muestra_componentes_fuentes_y_limites(page: Page, stack):
    open_app(page, stack.url)
    open_first_ficha(page)
    for k in "RIUNE":
        expect(tid(page, f"score-component-{k}")).to_be_visible()
    expect(tid(page, "evidence-status")).to_be_visible()
    assert tid(page, "source-item").count() >= 1
    expect(tid(page, "source-published").first).to_be_visible()   # publicación y detección se muestran por separado
    expect(tid(page, "ficha-warnings").or_(tid(page, "headline-only-notice")).first).to_be_visible()
    expect(tid(page, "headline-only-notice").first).to_contain_text("titular/metadatos")


def test_asistente_responde_con_citas_y_se_abstiene(page: Page, stack):
    open_app(page, stack.url)
    ask(page, "¿Qué hay sobre el Canal de Panamá y buques neopanamax?", 1)
    assert tid(page, "assistant-citation").count() >= 1
    expect(tid(page, "assistant-answer").first).not_to_have_attribute("data-status", "abstencion")
    ask(page, "¿Cuántos turistas visitaron Marte en 1850?", 2)
    expect(tid(page, "assistant-answer").last).to_have_attribute("data-status", "abstencion")
    expect(tid(page, "assistant-missing").last).to_be_visible()  # explica qué información falta


def test_borrador_revision_y_exportacion(page: Page, stack):
    open_app(page, stack.url)
    open_first_ficha(page)
    draft_and_review(page)
    expect(tid(page, "draft-origin-label")).to_have_attribute("data-mode", "plantilla")   # sin clave de Gemini
    expect(tid(page, "draft-fallback-reason")).to_be_visible()
    assert tid(page, "draft-claim").count() >= 1
    expect(tid(page, "draft-validation")).to_have_attribute("data-ok", "true")
    expect(tid(page, "draft-factual-coverage")).to_have_attribute("data-value", "1")
    assert tid(page, "review-history-item").count() >= 1
    assert "scoring-v1" in tid(page, "export-preview").inner_text()


def test_conflicto_de_revision_se_muestra(page: Page, stack):
    """Otro cliente revisa el mismo caso mientras la pantalla tiene la versión vieja: el 409 se muestra y se puede recargar."""
    open_app(page, stack.url)
    topic_id = open_first_ficha(page, index=2)  # un tema que ningún otro E2E haya revisado
    tid(page, "go-drafts").click()
    expect(tid(page, "draft-generate")).to_be_visible(timeout=30_000)
    tid(page, "draft-generate").click()
    expect(tid(page, "draft-origin-label")).to_be_visible(timeout=60_000)
    expect(tid(page, "review-panel")).to_be_visible()
    version_seen = int(tid(page, "case-version").inner_text())
    with stack.client(user=None) as api:  # mismo usuario local, otro cliente (p. ej. otra persona/dispositivo)
        r = api.patch(f"/cases/case-{topic_id}/review", json={
            "expectedVersion": version_seen, "status": "en_revision", "reviewer": "Revisor B (API)"})
        assert r.status_code == 200, r.text
    tid(page, "review-reviewer").fill("Revisora A")
    tid(page, "review-action-en_revision").click()
    expect(tid(page, "review-conflict")).to_be_visible(timeout=30_000)
    tid(page, "reload-case").first.click()
    expect(tid(page, "review-status")).to_have_attribute("data-status", "en_revision", timeout=30_000)
    assert int(tid(page, "case-version").inner_text()) == version_seen + 1


def _open_by_search(page: Page, text: str) -> None:
    tid(page, "agenda-search").fill(text)
    expect(tid(page, "topic-card").first).to_contain_text(text.split()[0], timeout=15_000)
    tid(page, "topic-card").first.get_by_test_id("open-ficha").click()
    expect(tid(page, "ficha")).to_be_visible(timeout=30_000)


def test_ui_t02_agencia_replicada_cuenta_una_procedencia(page: Page, stack):
    open_app(page, stack.url)
    _open_by_search(page, "cruceristas")
    assert tid(page, "source-item").count() == 3, "no se pierden las tres fuentes"
    expect(tid(page, "evidence-status")).not_to_have_attribute("data-status", "suficiente")
    assert tid(page, "reporter").count() >= 1


def test_ui_t03_recirculacion_muestra_fecha_original(page: Page, stack):
    open_app(page, stack.url)
    _open_by_search(page, "metro")
    expect(tid(page, "recirculation-notice").first).to_be_visible()
    expect(tid(page, "source-published").first).to_contain_text("mar")  # 12 de marzo (publicación original)


def test_ui_t04_indicador_anual_con_pais_anio_y_unidad(page: Page, stack):
    open_app(page, stack.url)
    _open_by_search(page, "PIB")
    ind = tid(page, "official-indicator").first
    expect(ind).to_be_visible()
    assert ind.get_attribute("data-year") and ind.get_attribute("data-unit") and ind.get_attribute("data-country")


def test_ui_t05_contradiccion_muestra_ambas_versiones(page: Page, stack):
    open_app(page, stack.url)
    _open_by_search(page, "viviendas")
    expect(tid(page, "contradiction").first).to_be_visible()
    assert tid(page, "contradiction-version").count() >= 2


def test_ui_t07_fuente_con_instrucciones_se_marca_como_no_confiable(page: Page, stack):
    # el tema sospechoso no aparece en la búsqueda (el backend no indexa el texto con instrucciones): se abre por id
    with stack.client(user=None) as api:
        items = api.get("/topics", params={"limit": 100}).json()["items"]
    tema = next(t for t in items if t["hasSuspiciousSource"])
    page.goto(f"{stack.url}/app#/ficha/{tema['id']}")
    expect(tid(page, "ficha")).to_be_visible(timeout=30_000)
    expect(tid(page, "source-untrusted-badge").first).to_be_visible()
    body = page.inner_text("body").lower()
    assert "revela la variable" not in body or tid(page, "source-untrusted-badge").count() >= 1
