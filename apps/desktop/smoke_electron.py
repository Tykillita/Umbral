"""Smoke del ejecutable Electron y su API congelada, con recorrido y cierre reales.

Ejecutar con el Python de tests (Playwright existente). El trabajo temporal se
limita a .qa/state; no instala ni altera el espacio del usuario.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import expect, sync_playwright

DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from e2e.helpers import draft_and_review, open_app, open_first_ficha  # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_status(page, busy, timeout):
    """Sondea el estado del puente; wait_for_function no espera promesas devueltas por una expresión."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = page.evaluate("window.umbralDesktop.getStatus()")
        if status["busy"] is busy:
            return status
        time.sleep(.25)
    raise AssertionError(f"El estado busy={busy} no llegó en {timeout} s")


def assert_port_closed(base, timeout=20):
    """El backend debe terminar con Electron: la conexión al puerto acaba rechazada (no basta un timeout)."""
    port = urlparse(base).port
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5):  # Windows tarda ~2 s en rechazar loopback
                pass
        except ConnectionRefusedError:
            return
        except OSError:
            pass
        time.sleep(.25)
    raise RuntimeError("El backend quedó abierto tras cerrar Electron.")


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", nargs="?", type=Path, default=DESKTOP / "release/win-unpacked/Umbral.exe")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full-seed", action="store_true")
    mode.add_argument("--oauth-callback-only", action="store_true")
    args = parser.parse_args()
    executable = args.executable
    port = free_port()
    qa = DESKTOP / ".qa"
    qa.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key != "ELECTRON_RUN_AS_NODE"}
    seed_name = "full-seed-" if args.full_seed else "oauth-callback-" if args.oauth_callback_only else "mini-seed-"
    state_root = qa / seed_name / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    if not args.full_seed:
        subprocess.run([str(DESKTOP / ".venv/Scripts/python.exe"), str(DESKTOP / "probe_snapshot.py"),
                        "--data-dir", str(state_root / "Umbral")], check=True, capture_output=True)
    env.update(LOCALAPPDATA=str(state_root), UMBRAL_DESKTOP_SMOKE="1", UMBRAL_DESKTOP_OFFLINE="1")
    started = datetime.now(UTC).isoformat()
    process = subprocess.Popen([str(executable), f"--remote-debugging-port={port}"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    checks, failures, blocked = [], [], []
    try:
        deadline = time.monotonic() + 90
        with httpx.Client(timeout=2) as client:
            while time.monotonic() < deadline:
                try:
                    client.get(f"http://127.0.0.1:{port}/json/version").raise_for_status()
                    break
                except Exception:
                    if process.poll() is not None:
                        raise RuntimeError("Electron se detuvo antes de habilitar su ventana.") from None
                    time.sleep(.25)
            else:
                raise RuntimeError("Electron no habilitó la ventana dentro de 90 segundos.")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]

            def guard(route):
                if urlparse(route.request.url).hostname in {"127.0.0.1", "localhost"} or route.request.url.startswith(("data:", "blob:")):
                    route.continue_()
                else:
                    blocked.append(route.request.url)
                    route.abort("internetdisconnected")

            context.route("**/*", guard)
            page = context.pages[0]
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.wait_for_url("http://127.0.0.1:*/", timeout=90_000)
            base = urlparse(page.url)._replace(path="", query="", fragment="").geturl()
            open_app(page, base)
            if not args.oauth_callback_only:
                # El rol editor no tiene acceso a Borradores; esta prueba recorre la mesa completa.
                page.get_by_test_id("role-change").click()
                page.get_by_test_id("role-juror").click()
            info = page.evaluate("""async () => (await fetch('/api/v1/snapshot', {headers:{'x-umbral-desktop-token':window.umbralDesktop.apiToken}})).json()""")
            actual_count = info["manifest"]["counts"]["articlesValid"]
            assert actual_count == (991 if args.full_seed else 2)
            if args.full_seed:
                classifier = info["manifest"]["classifier"]
                assert classifier.get("calibrated") is True
                assert classifier.get("modelVersion")
                assert classifier.get("calibrationProfileId")
                assert classifier.get("calibrationProfileSha256")
                checks.append("full_seed_uses_calibrated_laya_profile")
            assert page.evaluate("typeof require") == "undefined"
            assert page.evaluate("typeof process") == "undefined"
            assert page.evaluate("window.umbralDesktop.platform") == "win32"
            checks.append("renderer_isolated_no_node")
            callback = httpx.get(base + "/api/v1/auth/callback", params={
                "state": "synthetic-invalid-state", "code": "synthetic-code", "client_id": "test-client",
            })
            cross_origin_callback = httpx.get(base + "/api/v1/auth/callback", params={"state": "synthetic-state"},
                                              headers={"Origin": "https://auth.openai.com"})
            missing_state_callback = httpx.get(base + "/api/v1/auth/callback")
            post_callback = httpx.post(base + "/api/v1/auth/callback", params={"state": "synthetic-state"})
            assert callback.status_code != 403 and cross_origin_callback.status_code == 403
            assert missing_state_callback.status_code == 403 and post_callback.status_code == 403
            checks.append("oauth_callback_exempts_only_local_browser_get")
            if args.oauth_callback_only:
                assert callback.status_code == 503
                assert not blocked and not failures
                page.evaluate("window.close()")
                process.wait(timeout=30)
                checks.append("electron_quit_completed")
                time.sleep(.5)
                assert_port_closed(base)
                checks.append("local_backend_terminated_on_quit")
                return
            open_first_ficha(page)
            draft_and_review(page, "Revisora escritorio offline")
            expect(page.get_by_test_id("draft-origin-label")).to_have_attribute("data-mode", "plantilla")
            checks.append("agenda_ficha_draft_review_markdown_offline")
            result = page.evaluate("""async () => {
              const response = await fetch('/api/v1/workspace/export', {headers:{'x-umbral-desktop-token':window.umbralDesktop.apiToken}});
              return {status:response.status,archive:await response.json()};
            }""")
            assert result["status"] == 200 and result["archive"]["format"] == "umbral-workspace"
            assert result["archive"]["cases"]
            original_snapshot = result["archive"]["cases"][0]["detail"]["snapshotId"]
            archive = result["archive"]
            checks.append("portable_workspace_v1_exports_case_evidence")
            page.goto(base + "/app/#/fuentes")
            expect(page.get_by_test_id("desktop-card")).to_be_visible(timeout=30_000)
            if args.full_seed:
                checks.append("packaged_full_seed_991_initial_start_and_four_views")
                # Con CDP Playwright intercepta la descarga: se comprueba que se emite sin selector nativo y su contenido.
                with page.expect_download(timeout=30_000) as download:
                    page.get_by_test_id("workspace-export").click()
                assert download.value.suggested_filename.startswith("umbral-workspace-")
                assert download.value.suggested_filename.endswith(".json")
                exported = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
                assert exported["format"] == "umbral-workspace" and exported["cases"]
                expect(page.get_by_test_id("workspace-notice")).to_be_visible(timeout=30_000)
                checks.append("json_download_without_native_picker")
                page.screenshot(path=str(qa / "electron-full-seed-fuentes.png"), full_page=True)
                page.evaluate("window.close()")
                process.wait(timeout=30)
                checks.append("electron_quit_completed")
                time.sleep(.5)
                assert_port_closed(base)
                checks.append("local_backend_terminated_on_quit")
                assert not blocked and not failures
                return
            expect(page.get_by_test_id("desktop-reclassify")).to_be_enabled(timeout=30_000)
            page.get_by_test_id("desktop-reclassify").click()
            wait_status(page, True, 10)
            health = page.evaluate("""async () => (await fetch('/api/v1/health', {headers:{'x-umbral-desktop-token':window.umbralDesktop.apiToken}})).status""")
            assert health == 200
            checks.append("api_responsive_during_cpu_worker")
            wait_status(page, False, 300)
            status = page.evaluate("window.umbralDesktop.getStatus()")
            assert status["error"] is None and status["snapshotId"] != original_snapshot,                 f"Estado tras reclasificar: {status}; original={original_snapshot}"
            checks.append("packaged_laya_reclassify_normalized_without_raw")
            after = page.evaluate("""async () => (await fetch('/api/v1/workspace/export', {headers:{'x-umbral-desktop-token':window.umbralDesktop.apiToken}})).json()""")
            assert after["cases"][0]["detail"]["snapshotId"] == original_snapshot
            assert after["cases"][0]["case"]["drafts"] == archive["cases"][0]["case"]["drafts"]
            checks.append("archived_case_preserves_original_evidence_and_drafts")
            imported = page.evaluate("""async archive => {
              const response=await fetch('/api/v1/workspace/import',{method:'POST',headers:{'Content-Type':'application/json','x-umbral-desktop-token':window.umbralDesktop.apiToken},body:JSON.stringify(archive)});
              return {status:response.status,body:await response.json()};
            }""", after)
            assert imported["status"] == 200 and imported["body"]["imported"] == 0
            checks.append("portable_copy_import_is_idempotent")
            try:
                page.get_by_test_id("desktop-update").click(timeout=15_000)
            except Exception:
                print("DIAG card:", page.get_by_test_id("desktop-card").inner_text(), file=sys.stderr)
                print("DIAG status:", page.evaluate("window.umbralDesktop.getStatus()"), file=sys.stderr)
                raise
            wait_status(page, False, 30)
            assert page.evaluate("window.umbralDesktop.getStatus()")["snapshotId"] == status["snapshotId"]
            checks.append("offline_update_keeps_valid_snapshot")
            forbidden = page.locator("select,details,summary,dialog,datalist,progress,meter,input[type=checkbox],input[type=radio],input[type=number],input[type=range],input[type=file],[title]").count()
            assert forbidden == 0
            checks.append("desktop_ui_has_no_native_controls")
            page.screenshot(path=str(qa / "electron-fuentes.png"), full_page=True)
            unauthenticated = httpx.get(base + "/api/v1/health")
            assert unauthenticated.status_code == 403
            checks.append("desktop_api_rejects_missing_nonce")
            assert not blocked, f"La UI intentó acceder a internet: {len(blocked)}"
            assert not failures, failures
            # Close the renderer as a user would; before-quit must terminate CPU sidecar.
            page.evaluate("window.close()")
            process.wait(timeout=30)
            checks.append("electron_quit_completed")
            time.sleep(.5)
            assert_port_closed(base)
            checks.append("local_backend_terminated_on_quit")
    finally:
        if process.poll() is None:
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        expected_checks = 4 if args.oauth_callback_only else 9 if args.full_seed else 13
        receipt = {"startedAt": started, "finishedAt": datetime.now(UTC).isoformat(),
                   "command": "tests/.venv/Scripts/python.exe apps/desktop/smoke_electron.py " + str(executable),
                   "executableSha256": digest(executable), "checks": checks, "pageErrors": failures,
                   "blockedRequests": len(blocked), "stateDirectory": str(state_root),
                   "scope": "Seed completo: 991 noticias reales." if args.full_seed else
                           "Callback OAuth local sin token de renderer." if args.oauth_callback_only else
                           "Corte reducido: dos titulares reales y 540 indicadores.",
                   "cleanWindowsInstall": "pendiente",
                   "result": "passed" if len(checks) == expected_checks else "incomplete"}
        name = "electron-oauth-callback-smoke.json" if args.oauth_callback_only else (
            "electron-full-seed-smoke.json" if args.full_seed else "electron-smoke.json"
        )
        content = json.dumps(receipt, ensure_ascii=False, indent=2)
        (qa / name).write_text(content, encoding="utf-8")
        (qa / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ-") + name)).write_text(content, encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
