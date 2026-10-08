"""Publicación: solo archivos publicables, sin rutas personales ni créditos de IA, y despliegue verificado por SHA."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


public = load("check_public_files")
deploy = load("wait_for_deploy")


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    monkeypatch.setattr(public, "ROOT", tmp_path)
    return tmp_path


def write(root: Path, name: str, text: str = "contenido\n") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(root: Path, *, candidates: bool = False) -> list[str]:
    git(root, "add", "-f", "-A")
    return public.check_files(public.listed_files(candidates))


def test_publishable_files_pass(repo):
    write(repo, "README.md", "# Umbral\n\nVer [arquitectura](docs/public/ARCHITECTURE.md).\n")
    write(repo, "docs/public/ARCHITECTURE.md", "# Arquitectura\n")
    write(repo, "apps/api/main.py", "print('hola')\n")
    assert run(repo) == []


@pytest.mark.parametrize("name", [
    "CLAUDE.md", "AGENTS.md", "apps/web/CLAUDE.md", ".claude/settings.json", "docs/board/events.log",
    "docs/notion/01-inicio.md", "docs/COORDINATION.md", "docs/CONTINUIDAD.md", "docs/CODEX-GOAL-CHATGPT.md",
    "apps/web/public/brand/concepts/prompts.md", "docs/reto-tvn-media.pdf",
])
def test_private_files_are_rejected_even_when_force_added(repo, name):
    write(repo, name)
    problems = run(repo)
    assert any(name in problem for problem in problems), problems


def test_markdown_outside_the_allowlist_is_rejected(repo):
    write(repo, "docs/TODO.md")
    write(repo, "README.es.md")
    problems = run(repo)
    assert any("docs/TODO.md" in problem and "lista publicable" in problem for problem in problems)
    assert not any("README.es.md" in problem for problem in problems)


def test_allowlist_matches_gitignore():
    """Lo que el verificador permite debe poder versionarse, y lo demás debe estar ignorado."""
    if not (REPO / ".git").exists():
        pytest.skip("Requiere un checkout con .git para consultar las reglas de ignorado.")
    allowed = ["README.md", "README.es.md", "CHANGELOG.md", "SECURITY.md", "apps/web/README.md", "docs/public/X.md",
               "docs/contracts/api-draft.md", "docs/contracts/api-public.md", "docs/contracts/snapshot-schema.md",
               "eval/README.md", "eval/labels/LEEME.md", "tests/e2e/TESTIDS.md",
               "data/snapshots/20261007-cfa338b6/DATA_DICTIONARY.md", "data/snapshots/20261007-cfa338b6/TERMS_OF_USE.md"]
    denied = ["CLAUDE.md", "AGENTS.md", "docs/TODO.md", "docs/INFORME.md", "docs/board/frontend.md", "docs/notion/README.md",
              "apps/desktop/README.md", "docs/contracts/api-provider-validation.md", "docs/public/sub/X.md"]
    for name in allowed:
        assert public.is_public_markdown(name), name
        assert not ignored(name), f"{name} está permitido pero .gitignore lo excluye"
    for name in denied:
        assert not public.is_public_markdown(name), name
        assert ignored(name), f"{name} debería estar excluido por .gitignore"


def ignored(name: str) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", name], cwd=REPO, capture_output=True)
    return result.returncode == 0


@pytest.mark.parametrize("text", [
    "ruta C:\\Users\\alguien\\Documents\\proyecto", "ruta C:/Users/alguien/proyecto", "ruta /Users/alguien/proyecto",
    "D:\\\\Obsidian\\\\MyVault\\\\Notas",
])
def test_personal_paths_are_rejected(repo, text):
    write(repo, "eval/results/informe.json", json.dumps({"ruta": text}))
    assert any("ruta personal" in problem for problem in run(repo))


def test_generic_paths_and_firestore_paths_are_allowed(repo):
    write(repo, "docs/public/X.md", "Datos en `C:\\Users\\<usuario>\\AppData` y `/users/{uid}/cases`.\n")
    assert run(repo) == []


@pytest.mark.parametrize("text", [
    "Co-Authored-By: Claude <noreply@anthropic.com>", "co-authored-by: Codex <bot@example.com>",
    "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
])
def test_ai_tool_credits_are_rejected(repo, text):
    write(repo, "CHANGELOG.md", f"## Unreleased\n\n{text}\n")
    assert any("coautoría" in problem for problem in run(repo))


def test_functional_provider_names_are_not_credits(repo):
    write(repo, "README.md", "Usa Gemini y el modelo Laya; Claude y ChatGPT son conexiones locales opcionales.\n")
    assert run(repo) == []


def test_broken_links_to_unpublished_documents_are_reported(repo):
    write(repo, "README.md", "[plan](docs/TODO.md) [ok](LICENSE) [ancla](#x) [web](https://example.com)\n")
    write(repo, "LICENSE", "MIT\n")
    problems = run(repo)
    assert len(problems) == 1 and "docs/TODO.md" in problems[0]


def test_commit_messages_are_checked(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    write(repo, "README.md", "# ok\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: algo\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    write(repo, "a.txt")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "docs: limpio")
    assert public.check_commits("HEAD~1..HEAD") == []
    assert any("coautoría" in problem for problem in public.check_commits("HEAD~2..HEAD"))


# ---- wait_for_deploy -------------------------------------------------------------------------------------------

SHA = "a" * 40
GOOD = {"status": "ok", "deployCommit": SHA, "authMode": "public", "localMode": False, "persistence": "none",
        "containsFixtures": False, "classifier": "laya", "snapshotId": "20261007-cfa338b6", "apiVersion": "0.4.0",
        "counts": {"articles": 991}, "integrity": {"manifestVerified": True, "predictionsHashVerified": True}}


class Server:
    def __init__(self, responses):
        self.responses, self.hits = list(responses), 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                owner.hits += 1
                status, body = owner.responses[min(owner.hits - 1, len(owner.responses) - 1)]
                payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(status)
                self.send_header("Content-Type", "application/json" if status == 200 else "text/html")
                self.send_header("Access-Control-Allow-Origin", "https://site-umbral.web.app")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server():
    created = []

    def make(responses):
        created.append(Server(responses))
        return created[-1]

    yield make
    for item in created:
        item.close()


def test_deploy_waits_through_cold_start_and_old_commit(server):
    api = server([(503, b"<html>Service Unavailable</html>"), (200, GOOD | {"deployCommit": "b" * 40}), (200, GOOD)])
    receipt = deploy.wait(api.url, SHA, "https://site-umbral.web.app", timeout=10, interval=0.01)
    assert receipt["status"] == "passed" and receipt["attempts"] == 3 and receipt["deployCommit"] == SHA


@pytest.mark.parametrize("change", [
    {"status": "degradado"}, {"authMode": "local"}, {"persistence": "sqlite"}, {"localMode": True},
    {"containsFixtures": True}, {"classifier": "baseline"}, {"deployCommit": None},
    {"integrity": {"manifestVerified": True, "predictionsHashVerified": None}},
    {"integrity": {"manifestVerified": False, "predictionsHashVerified": True}},
])
def test_deploy_never_passes_an_unsafe_api(server, change):
    api = server([(200, GOOD | change)])
    with pytest.raises(TimeoutError, match="Último estado"):
        deploy.wait(api.url, SHA, None, timeout=0.2, interval=0.05)


def test_deploy_requires_cors_for_the_hosting_origin(server):
    api = server([(200, GOOD)])
    with pytest.raises(TimeoutError, match="CORS"):
        deploy.wait(api.url, SHA, "https://otro-sitio.web.app", timeout=0.2, interval=0.05)


def test_deploy_origin_and_sha_validation():
    assert deploy.api_origin("https://umbral-api.onrender.com/") == "https://umbral-api.onrender.com"
    for bad in ["http://umbral-api.onrender.com", "https://u:p@umbral-api.onrender.com", "https://x.onrender.com/api",
                "https://x.onrender.com?k=1"]:
        with pytest.raises(ValueError):
            deploy.api_origin(bad)
    assert deploy.SHA.fullmatch(SHA) and not deploy.SHA.fullmatch("abc123") and not deploy.SHA.fullmatch(SHA.upper())
