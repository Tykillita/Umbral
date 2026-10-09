"""Web pública real: trabajo por navegador, copia portable y CAS entre pestañas."""
from __future__ import annotations

import json
import re

import pytest
from e2e.helpers import draft_and_review, open_app, open_first_ficha, settle_motion, tid
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def generate(page):
    open_first_ficha(page)
    tid(page, "go-drafts").click()
    expect(tid(page, "draft-generate")).to_be_visible(timeout=30_000)
    tid(page, "draft-generate").click()
    expect(tid(page, "draft-origin-label")).to_be_visible(timeout=60_000)
    expect(tid(page, "draft-brief")).not_to_be_empty()


def test_centro_de_advertencias_en_build_publico(page, public_stack):
    open_app(page, public_stack.url, role="juror")
    expect(tid(page, "fixture-notice")).to_have_count(0)
    trigger = tid(page, "warning-center-toggle")
    trigger.click()
    expect(tid(page, "warning-center")).to_be_visible()
    expect(tid(page, "warning-fixture-notice")).to_contain_text("Este snapshot contiene datos de fixture")


def test_entrada_publica_y_revision_persisten_sin_autenticacion(page, public_stack):
    calls = []
    page.on("request", lambda request: calls.append((request.url, request.method, request.headers)))
    open_app(page, public_stack.url, role="juror")
    expect(tid(page, "status-bar")).to_contain_text("Público")
    assert tid(page, "mock-banner").count() == 0
    open_first_ficha(page)
    draft_and_review(page, "Automatización de prueba pública")
    page.reload()
    expect(tid(page, "review-status")).to_have_attribute("data-status", "en_revision", timeout=30_000)
    expect(tid(page, "draft-brief")).not_to_be_empty()
    assert any("/api/v1/public/drafts" in url for url, _, _ in calls)
    assert not any("identitytoolkit" in url or "securetoken" in url for url, _, _ in calls)
    assert not any("authorization" in headers for _, _, headers in calls)
    assert not any("/api/v1/cases/" in url and method in {"PUT", "PATCH"} for url, method, _ in calls)


def test_dos_navegadores_no_comparten_borradores(browser, public_stack):
    first_context = browser.new_context(locale="es-PA", timezone_id="America/Panama")
    second_context = browser.new_context(locale="es-PA", timezone_id="America/Panama")
    try:
        first = first_context.new_page()
        second = second_context.new_page()
        open_app(first, public_stack.url, role="juror")
        generate(first)
        draft_url = first.url
        open_app(second, public_stack.url, role="juror")
        second.goto(draft_url)
        expect(tid(second, "draft-generate")).to_be_visible(timeout=30_000)
        expect(tid(second, "draft-brief")).to_have_count(0)
        first.reload()
        expect(tid(first, "draft-brief")).not_to_be_empty(timeout=30_000)
    finally:
        first_context.close()
        second_context.close()


def test_copia_json_restaura_versiones_en_otro_navegador(browser, public_stack, tmp_path):
    source_context = browser.new_context(accept_downloads=True)
    destination_context = browser.new_context()
    try:
        source = source_context.new_page()
        destination = destination_context.new_page()
        open_app(source, public_stack.url, role="juror")
        generate(source)
        before = tid(source, "draft-brief").input_value()
        tid(source, "draft-brief").fill(before + "\nRevisión automatizada para probar una copia local.")
        tid(source, "draft-save").click()
        expect(tid(source, "draft-saved")).to_be_visible(timeout=30_000)
        source.get_by_test_id("nav-fuentes").click()
        expect(tid(source, "workspace-export")).to_be_visible(timeout=30_000)
        with source.expect_download() as downloaded:
            tid(source, "workspace-export").click()
        copy_file = tmp_path / "workspace.json"
        downloaded.value.save_as(copy_file)
        archive = json.loads(copy_file.read_text(encoding="utf-8"))
        assert archive["format"] == "umbral-workspace" and archive["version"] == 1
        assert len(archive["cases"]) == 1
        assert len(archive["cases"][0]["case"]["drafts"]) == 2
        open_app(destination, public_stack.url, role="juror")
        destination.get_by_test_id("nav-fuentes").click()
        destination.get_by_role("button", name="Importar una copia").click()
        tid(destination, "workspace-json").fill(copy_file.read_text(encoding="utf-8"))
        tid(destination, "workspace-import").click()
        expect(tid(destination, "workspace-notice")).to_be_visible(timeout=30_000)
        topic_id = archive["cases"][0]["case"]["topicId"]
        destination.goto(public_stack.url + "/app#/borradores/" + topic_id)
        expect(tid(destination, "draft-brief")).to_have_value(re.compile(".*copia local.*", re.S), timeout=30_000)
    finally:
        source_context.close()
        destination_context.close()


def test_pestana_antigua_no_sobrescribe_edicion_nueva(page, public_stack):
    open_app(page, public_stack.url, role="juror")
    generate(page)
    other = page.context.new_page()
    try:
        other.goto(page.url)
        expect(tid(other, "draft-brief")).not_to_be_empty(timeout=30_000)
        # Ambas empiezan con la misma versión; mantener edits sin guardar antes del broadcast.
        tid(other, "draft-brief").fill(tid(other, "draft-brief").input_value() + "\nEdición antigua sin guardar.")
        tid(page, "draft-brief").fill(tid(page, "draft-brief").input_value() + "\nEdición nueva confirmada.")
        tid(page, "draft-save").click()
        expect(tid(page, "draft-saved")).to_be_visible(timeout=30_000)
        settle_motion(other)
        tid(other, "draft-save").click()
        expect(other.get_by_text("cambió", exact=False).first).to_be_visible(timeout=30_000)
        page.reload()
        expect(tid(page, "draft-brief")).to_have_value(re.compile(".*Edición nueva confirmada.*", re.S), timeout=30_000)
        assert "Edición antigua sin guardar" not in tid(page, "draft-brief").input_value()
    finally:
        other.close()
