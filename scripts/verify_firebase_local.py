"""Verificación real Firebase local, sin credenciales ni servicios cloud.

Requiere Auth 9099 y Firestore 8088 ya iniciados para demo-umbral-audit.
Ejecutar con apps/api/.venv/Scripts/python.exe; el navegador usa tests/.venv.
La build aislada debe estar en .umbral-local/firebase-audit/web-dist.
Solo modifica usuarios nuevos en los emuladores. Nunca registra tokens.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "demo-umbral-audit"
AUTH_HOST = "127.0.0.1:9099"
FIRESTORE_HOST = "127.0.0.1:8088"
OUT = ROOT / "tests" / ".results"
NETWORK_GUARD_CODE = '''
import socket, os, json
_original_lookup = socket.getaddrinfo
_original_connect = socket.socket.connect
def _local_host(host):
    if host is None or host in {"127.0.0.1", "localhost", "::1", b"localhost", b"127.0.0.1"}:
        return
    with open(os.environ["UMBRAL_FIREBASE_NETLOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"host": str(host)}) + "\\n")
    raise OSError("External network blocked by Firebase-local verification")
def _lookup(host, *args, **kwargs):
    _local_host(host)
    return _original_lookup(host, *args, **kwargs)
def _connect(sock, address):
    if isinstance(address, tuple):
        _local_host(address[0])
    return _original_connect(sock, address)
socket.getaddrinfo = _lookup
socket.socket.connect = _connect
'''


def browser_check(base: str, result_path: Path) -> None:
    """SDK web real: no intercepta/resuelve solicitudes Firebase/API con mocks."""
    from playwright.sync_api import expect, sync_playwright

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "tests" / ".browsers"))
    report = {"checks": [], "pageErrors": [], "externalAttempts": [], "apiRequests": [],
              "authEmulatorRequests": 0}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(locale="es-PA", timezone_id="America/Panama")

        def guard(route):
            if urlsplit(route.request.url).hostname not in {"127.0.0.1", "localhost", "::1"}:
                report["externalAttempts"].append(urlsplit(route.request.url).hostname)
                route.abort("internetdisconnected")
            else:
                route.continue_()

        def request_seen(request):
            parsed = urlsplit(request.url)
            if parsed.port == 9099:
                report["authEmulatorRequests"] += 1
            if parsed.path.startswith("/api/v1/"):
                header = request.headers.get("authorization", "")
                report["apiRequests"].append({"path": parsed.path, "method": request.method,
                    "bearer": header.startswith("Bearer ")})
                if header.startswith("Bearer "):
                    payload = header[7:].split(".")[1]
                    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                    report["userIdSha256"] = hashlib.sha256(claims["sub"].encode()).hexdigest()

        context.route("**/*", guard)
        context.on("request", request_seen)
        page = context.new_page()
        page.on("pageerror", lambda err: report["pageErrors"].append(str(err)))
        page.goto(base + "/app/")
        expect(page.get_by_test_id("topic-card")).to_have_count(5, timeout=45000)
        expect(page.get_by_test_id("mock-banner")).to_have_count(0)
        report["checks"].append("Firebase web SDK anonymous login and real protected agenda")
        topic = page.get_by_test_id("topic-card").first.get_attribute("data-topic-id")
        page.get_by_test_id("open-ficha").first.click()
        expect(page.get_by_test_id("ficha")).to_be_visible()
        page.get_by_test_id("go-drafts").click()
        page.get_by_test_id("draft-provider").select_option("plantilla")
        page.get_by_test_id("draft-generate").click()
        expect(page.get_by_test_id("draft-origin-label")).to_have_attribute("data-mode", "plantilla", timeout=45000)
        expect(page.get_by_test_id("draft-validation")).to_have_attribute("data-ok", "true")
        page.get_by_test_id("review-reviewer").fill("QA Firebase automática; no revisión editorial")
        page.get_by_test_id("draft-title").fill("Título de prueba de persistencia Firebase local")
        with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/draft")) as saved:
            page.get_by_test_id("draft-save").click()
        assert saved.value.status == 200
        edited = saved.value.json()
        assert len(edited["drafts"]) == 2 and edited["currentDraft"]["previousDraftId"]
        with page.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith("/review")) as reviewed:
            page.get_by_test_id("review-action-en_revision").click()
        assert reviewed.value.status == 200
        final_case = reviewed.value.json()
        expect(page.get_by_test_id("review-status")).to_have_attribute("data-status", "en_revision")
        page.get_by_test_id("export-markdown").click()
        expect(page.get_by_test_id("export-preview")).to_contain_text(final_case["snapshotId"])
        report["checks"].append("Browser template, immutable edition, automated en_revision and export")
        page.reload()
        expect(page.get_by_test_id("review-status")).to_have_attribute("data-status", "en_revision", timeout=30000)
        expect(page.get_by_test_id("draft-title")).to_have_value("Título de prueba de persistencia Firebase local")
        report["checks"].append("Anonymous identity and case persisted after browser reload")
        # Capture only UID as a one-way digest; token values never enter a receipt.
        token_request = next(r for r in report["apiRequests"] if r["path"].endswith("/draft") and r["method"] == "PUT")
        assert token_request["bearer"] and report["authEmulatorRequests"] > 0
        assert all(r["bearer"] for r in report["apiRequests"] if r["path"] not in {"/api/v1/health", "/api/v1/snapshot"})
        report["caseId"] = final_case["caseId"]
        report["topicId"] = topic
        report["caseVersion"] = final_case["version"]
        report["snapshotId"] = final_case["snapshotId"]
        page.screenshot(path=str(OUT / "firebase-local-browser.png"), full_page=True)
        assert not report["pageErrors"] and not report["externalAttempts"], report
        report["passed"] = True
        browser.close()
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Browser Firebase SDK flow passed; no token values recorded.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8013)
    parser.add_argument("--browser-only", action="store_true")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    OUT.mkdir(exist_ok=True)
    if args.browser_only:
        browser_check(base, OUT / "firebase-local-browser.json")
        return
    assert PROJECT.startswith("demo-")
    for host in (AUTH_HOST, FIRESTORE_HOST):
        name, port = host.split(":")
        with socket.create_connection((name, int(port)), timeout=3):
            pass
    # Fail before replacing/interrupting any unrelated server.
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", args.port))
    finally:
        probe.close()
    netlog = OUT / "firebase-local-netblock.jsonl"
    netlog.write_text("", encoding="utf-8")
    os.environ.update({"FIRESTORE_EMULATOR_HOST": FIRESTORE_HOST,
        "FIREBASE_AUTH_EMULATOR_HOST": AUTH_HOST, "FIREBASE_PROJECT_ID": PROJECT,
        "UMBRAL_FIREBASE_NETLOG": str(netlog), "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
        "NO_PROXY": "127.0.0.1,localhost,::1"})
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    exec(NETWORK_GUARD_CODE, globals())  # noqa: S102 - código constante local de la guardia de red.
    from firebase_admin import auth, initialize_app
    from google.cloud import firestore
    from umbral_api.storage import FirestoreRepository

    admin = initialize_app(options={"projectId": PROJECT}, name="umbral-emulator-verifier")
    db = firestore.Client(project=PROJECT)
    report = {"startedAtUtc": datetime.now(timezone.utc).isoformat(), "project": PROJECT,
        "firebaseAuthEmulator": AUTH_HOST, "firestoreEmulator": FIRESTORE_HOST,
        "checks": [], "humanReview": False,
        "networkGuard": "Python DNS/connect deny external hosts; native Firestore gRPC target is explicit loopback emulator",
        "notVerified": ["Firebase production service account and hosted auth domain",
            "Cloud Spark quota and deployed Hosting/Render behavior", "Production Firebase RS256 signature verification",
            "Human editorial approval"]}
    report["sdkVersions"] = {name: importlib.metadata.version(name)
        for name in ("firebase-admin", "google-cloud-firestore", "google-auth")}
    report["sdkVersions"]["firebase-web"] = json.loads(
        (ROOT / "apps/web/node_modules/firebase/package.json").read_text(encoding="utf-8"))["version"]
    assert (ROOT / "firestore.rules").read_bytes() == (ROOT / ".umbral-local/firebase-audit/firestore.rules").read_bytes()
    env = os.environ.copy()
    env.update({"UMBRAL_PERSISTENCE": "firestore", "UMBRAL_AUTH_MODE": "firebase",
        "UMBRAL_LOCAL_MODE": "0", "UMBRAL_OFFLINE": "1", "GEMINI_API_KEY": "",
        "UMBRAL_GEMINI_STUB": "", "GOOGLE_APPLICATION_CREDENTIALS": "",
        "CHATGPT_TOKEN_FILE": "", "CHATGPT_MODEL": "", "CLAUDE_MODEL": "",
        "UMBRAL_ALLOW_FIXTURE": "0", "UMBRAL_STRICT_INTEGRITY": "1",
        "UMBRAL_QUERIES_PER_MINUTE": "100", "UMBRAL_DRAFTS_PER_MINUTE": "100",
        "UMBRAL_WEB_DIST": str(ROOT / ".umbral-local" / "firebase-audit" / "web-dist")})
    current = (ROOT / "data" / "snapshots" / "CURRENT").read_text().strip()
    env["UMBRAL_SNAPSHOT_DIR"] = str(ROOT / "data" / "snapshots" / current)
    server = None
    log_handle = None

    def check(name: str) -> None:
        report["checks"].append(name)
        print(f"PASS {name}", flush=True)

    def start():
        nonlocal server, log_handle
        log_handle = (OUT / "firebase-local-api.log").open("a", encoding="utf-8")
        server_code = NETWORK_GUARD_CODE + f'\nimport uvicorn; uvicorn.run("umbral_api.main:app", host="127.0.0.1", port={args.port}, access_log=False)'
        server = subprocess.Popen([sys.executable, "-c", server_code], env=env, cwd=ROOT,
            stdout=log_handle, stderr=subprocess.STDOUT)
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError("La API se detuvo al arrancar; ver firebase-local-api.log.")
            try:
                r = httpx.get(base + "/api/v1/health", timeout=1, trust_env=False)
                if r.status_code == 200:
                    return r.json()
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        raise RuntimeError("La API no quedó lista en 30 s.")

    def stop():
        nonlocal server, log_handle
        if server:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            server = None
        if log_handle:
            log_handle.close()
            log_handle = None

    def signup():
        r = httpx.post(f"http://{AUTH_HOST}/identitytoolkit.googleapis.com/v1/accounts:signUp",
            params={"key": "demo-public-emulator-key"}, json={"returnSecureToken": True},
            timeout=10, trust_env=False)
        assert r.status_code == 200, f"Auth emulator signup HTTP {r.status_code}"
        obj = r.json()
        return obj["localId"], obj["idToken"]

    def mutated_token(token: str, updates: dict) -> str:
        header, payload, signature = token.split(".")
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        data.update(updates)
        payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
        return f"{header}.{payload}.{signature}"

    try:
        health = start()
        assert health["snapshotId"] == current and health["counts"]["articles"] == 991
        assert health["persistence"] == "firestore" and health["authMode"] == "firebase"
        assert not health["localMode"] and health["offline"] and not health["containsFixtures"]
        assert health["integrity"]["manifestVerified"]
        report["health"] = health
        check("Firebase web settings; strict real 991-news snapshot; Firestore SDK startup")
        uid_a, token_a = signup()
        uid_b, token_b = signup()
        decoded = auth.verify_id_token(token_a, app=admin, check_revoked=True)
        assert decoded["uid"] == uid_a
        with httpx.Client(base_url=base + "/api/v1", timeout=30, trust_env=False) as api:
            def call(method, path, token=token_a, expected=200, **kw):
                headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
                r = api.request(method, path, headers=headers, **kw)
                assert r.status_code == expected, f"{method} {path}: HTTP {r.status_code}, expected {expected}"
                return r.json()

            for invalid in (None, "malformed", mutated_token(token_a, {"exp": int(time.time()) - 60}),
                            mutated_token(token_a, {"iat": int(time.time()) + 60}),
                            mutated_token(token_a, {"aud": "wrong-demo-project"})):
                call("GET", "/topics", token=invalid, expected=401)
            call("GET", "/connections/chatgpt", expected=403)
            check("Real Admin ID-token verification; missing/malformed/expired/future-iat/wrong-audience rejected; web personal routes denied")
            topics = call("GET", "/topics")
            topic = topics["items"][0]["id"]
            initial = call("GET", f"/topics/{topic}")
            created = call("POST", f"/topics/{topic}/drafts", json={"provider": "plantilla"})
            case = created["case"]
            case_id = case["caseId"]
            old_draft = created["draft"]
            other = call("GET", f"/topics/{topic}", token=token_b)["case"]
            assert other["drafts"] == [] and other["version"] == 0 and not other["persisted"]
            other_direct = call("GET", f"/cases/{case_id}", token=token_b)
            assert not other_direct["persisted"] and not other_direct["drafts"]
            assert db.collection("users").document(uid_a).collection("cases").document(case_id).get().exists
            assert not db.collection("users").document(uid_b).collection("cases").document(case_id).get().exists
            check("Two real anonymous users: cases/drafts isolated in Firestore paths")
            edited = call("PUT", f"/cases/{case_id}/draft", json={"expectedVersion": case["version"],
                "editor": "QA Firebase automática", "proposedTitle": "Título QA Firebase local"})
            assert edited["drafts"][0] == old_draft and len(edited["drafts"]) == 2
            assert edited["currentDraft"]["previousDraftId"] == old_draft["draftId"]
            call("PUT", f"/cases/{case_id}/draft", expected=409, json={"expectedVersion": case["version"],
                "editor": "QA obsoleta", "proposedTitle": "No debe sobrescribir"})
            reviewed = call("PATCH", f"/cases/{case_id}/review", json={"expectedVersion": edited["version"],
                "status": "en_revision", "reviewer": "QA automática; no revisión editorial", "comment": "Control técnico local."})
            assert reviewed["status"] == "en_revision" and reviewed["version"] == edited["version"] + 1
            call("PATCH", f"/cases/{case_id}/review", expected=409, json={"expectedVersion": edited["version"],
                "status": "en_revision", "reviewer": "QA obsoleta"})
            check("Immutable edited draft, real Firestore optimistic 409 and review history")
            weights = {"R": 10, "I": 10, "U": 10, "N": 10, "E": 60}
            rules_body = {"expectedVersion": 0, "weights": weights,
                "author": "QA Firebase automática", "reason": "Prueba técnica de pesos; no decisión editorial."}
            rules = call("PUT", "/rules", json=rules_body)
            call("PUT", "/rules", expected=409, json=rules_body)
            assert rules["version"] == 1 and rules["rulesVersion"] == "scoring-v2"
            assert rules["history"][0]["author"] == rules_body["author"]
            weighted = call("GET", f"/topics/{topic}")
            assert weighted["rulesVersion"] == "scoring-v2"
            assert all(c["weight"] == weights[c["key"]] for c in weighted["score"]["components"])
            assert weighted["score"]["total"] != initial["score"]["total"]
            assert call("GET", "/rules", token=token_b)["version"] == 0
            assert call("GET", "/topics")["rulesVersion"] == "scoring-v2"
            assert call("POST", "/queries", json={"question": "Qué cinco temas merecen revisión"})["rulesVersion"] == "scoring-v2"
            check("Per-user scoring weights actually applied; rules CAS409 and author/reason/version retained")
            parallel_body = {**rules_body, "expectedVersion": 1, "weights": {"R": 30, "I": 25, "U": 20, "N": 15, "E": 10},
                "reason": "Prueba técnica CAS simultánea de reglas."}
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(lambda _: api.put("/rules", json=parallel_body,
                    headers={"Authorization": f"Bearer {token_a}"}).status_code, range(2)))
            assert sorted(statuses) == [200, 409], statuses
            rules = call("GET", "/rules")
            assert rules["version"] == 2 and len(rules["history"]) == 2
            report["parallelRulesStatuses"] = sorted(statuses)
            check("Two concurrent rules writes with same expectedVersion produce exactly one200 and one409")
            saved_before = call("GET", f"/cases/{case_id}")
            repo = FirestoreRepository(PROJECT)
            counter_key = "firebase-audit/" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            with ThreadPoolExecutor(max_workers=12) as pool:
                counter_results = list(pool.map(lambda _: repo.incr_counter(uid_a, counter_key, 7), range(12)))
            assert sum(ok for ok, _ in counter_results) == 7
            assert repo.incr_counter(uid_a, counter_key, 7) == (False, 7)
            assert repo.incr_counter(uid_b, counter_key, 7) == (True, 1)
            report["counter"] = {"workers": 12, "attempts": 12, "accepted": 7, "limit": 7, "anotherUserValue": 1,
                "scope": "One repository instance; Firestore transactions retain cross-instance authority, not stress-tested here"}
            check("Firestore real concurrent counter transactions cap quota exactly and isolate users")
            direct_url = f"http://{FIRESTORE_HOST}/v1/projects/{PROJECT}/databases/(default)/documents/users/{uid_a}/cases/{case_id}"
            denied = httpx.get(direct_url, headers={"Authorization": f"Bearer {token_a}"}, timeout=10, trust_env=False)
            assert denied.status_code == 403, f"Direct client read HTTP {denied.status_code}"
            denied_write = httpx.patch(direct_url, headers={"Authorization": f"Bearer {token_a}"},
                json={"fields": {"bypass": {"booleanValue": True}}}, timeout=10, trust_env=False)
            assert denied_write.status_code == 403
            check("Loaded firestore.rules reject direct authenticated client read/write; Admin path works")
            stop()
            start()
            assert call("GET", f"/cases/{case_id}") == saved_before
            assert call("GET", "/rules") == rules
            assert repo.incr_counter(uid_a, counter_key, 7) == (False, 7)
            export = call("GET", f"/cases/{case_id}/export")
            assert export["snapshotId"] == current and rules["rulesVersion"] in export["markdown"]
            check("Real API process restart retains drafts/review/rules/counters/export in Firestore")
            # Revocation timestamps have whole-second precision; separate issuance and revoke.
            time.sleep(1.1)
            auth.revoke_refresh_tokens(uid_a, app=admin)
            call("GET", "/topics", expected=401)
            auth.update_user(uid_b, disabled=True, app=admin)
            call("GET", "/topics", token=token_b, expected=401)
            check("Admin check_revoked rejects previously accepted revoked and disabled-user tokens")
        browser_python = ROOT / "tests" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(browser_python), str(Path(__file__).resolve()), "--browser-only", "--port", str(args.port)],
            cwd=ROOT, env=env, check=True, timeout=180)
        report["browser"] = json.loads((OUT / "firebase-local-browser.json").read_text(encoding="utf-8"))
        browser_user_hash = report["browser"]["userIdSha256"]
        browser_saved = next(doc for doc in db.collection_group("cases").stream()
            if hashlib.sha256(doc.reference.parent.parent.id.encode()).hexdigest() == browser_user_hash)
        persisted_case = json.loads(browser_saved.to_dict()["data"])
        assert persisted_case["version"] == report["browser"]["caseVersion"]
        assert persisted_case["status"] == "en_revision"
        report["browser"]["adminSdkConfirmedPersistedCase"] = True
        check("Actual browser Firebase SDK to Bearer API to Firestore complete flow, reload and zero external attempts")
        report["backendExternalAttempts"] = [json.loads(line) for line in netlog.read_text().splitlines() if line]
        assert report["backendExternalAttempts"] == []
        report["manifestSha256"] = hashlib.sha256((ROOT / "data" / "snapshots" / current / "manifest.json").read_bytes()).hexdigest()
        report["sourceSha256"] = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__).resolve(), ROOT / "apps/api/src/umbral_api/auth.py", ROOT / "apps/api/src/umbral_api/storage.py",
                ROOT / "apps/web/src/lib/auth.ts", ROOT / "firestore.rules"]}
        report["webDistSha256"] = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / ".umbral-local/firebase-audit/web-dist").rglob("*")) if p.is_file()}
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        stop()
        report["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        report["command"] = "apps/api/.venv/Scripts/python.exe scripts/verify_firebase_local.py --port 8013"
        (OUT / "firebase-local.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report.get("passed"), "checks": len(report["checks"]),
            "receipt": "tests/.results/firebase-local.json"}), flush=True)


if __name__ == "__main__":
    main()
