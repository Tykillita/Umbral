"""Comprueba un start-local ya arrancado: navegador, API, snapshot y red offline.

Ejecutar con el Python de tests (extra e2e instalado). Revisión rotulada automática.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from e2e.helpers import ask, draft_and_review, open_app, open_first_ficha, tid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--label", choices=["ps", "bash"], required=True)
    args = parser.parse_args()
    if urlparse(args.api).hostname not in {"localhost", "127.0.0.1"}:
        parser.error("solo se verifica un servidor loopback local")
    out = ROOT / "tests" / ".results"
    out.mkdir(exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "tests" / ".browsers"))
    with httpx.Client(base_url=args.api + "/api/v1", timeout=30) as api:
        health = api.get("/health").json()
        assert health["offline"] and health["authMode"] == "local" and health["persistence"] == "sqlite"
        assert not health["containsFixtures"] and health["classifier"] == "laya"
        first = api.get("/topics", params={"limit": 1}).json()["items"][0]
        article = api.get("/topics/" + first["id"]).json()["articles"][0]
    blocked, page_errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(locale="es-PA", timezone_id="America/Panama")

        def guard(route):
            host = urlparse(route.request.url).hostname
            if host in {"localhost", "127.0.0.1"}:
                route.continue_()
            else:
                blocked.append(host)
                route.abort("internetdisconnected")

        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        open_app(page, args.api)
        expect(tid(page, "offline-indicator")).to_be_visible()
        ask(page, "¿Qué evidencia hay sobre " + article["title"] + "?", 1)
        assert tid(page, "assistant-citation").count() >= 1
        assert open_first_ficha(page) == first["id"]
        draft_and_review(page, "Prueba automatizada del script; no aprobación humana")
        expect(tid(page, "draft-origin-label")).to_have_attribute("data-mode", "plantilla")
        expect(tid(page, "export-preview")).to_contain_text(health["snapshotId"])
        page.screenshot(path=str(out / f"start-local-{args.label}.png"), full_page=True)
        browser.close()
    assert blocked == [] and page_errors == [], (blocked, page_errors)
    netblock = out / f"start-local-{args.label}-netblock.log"
    assert not netblock.exists() or not netblock.read_text(encoding="utf-8").strip()
    manifest = ROOT / "data" / "snapshots" / health["snapshotId"] / "manifest.json"
    result = {
        "status": "passed", "label": args.label, "api": args.api,
        "ranAtUtc": datetime.now(timezone.utc).isoformat(), "health": health,
        "topicId": first["id"], "articleId": article["id"],
        "flow": ["build", "load", "ranking", "query_with_citations", "ficha", "template", "automated_review", "export"],
        "command": f"python scripts/verify_local_story.py --label {args.label} --api {args.api}",
        "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "distSha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted((ROOT / "apps" / "web" / "dist").rglob("*")) if p.is_file()},
        "browserExternalAttempts": blocked, "pageErrors": page_errors, "backendExternalAttempts": 0,
        "reviewNote": "Revisión de prueba automatizada en SQLite dedicado; no constituye aprobación humana.",
    }
    (out / f"start-local-{args.label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"start-local {args.label}: recorrido offline completo OK, snapshot {health['snapshotId']}")


if __name__ == "__main__":
    main()
