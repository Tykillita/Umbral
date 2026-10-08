"""Sesión de Claude: reconocimiento con `claude auth status` y login del CLI oficial, sin leer credenciales ni facturar por API."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

import umbral_api.connections_claude as module
from umbral_api.config import Settings
from umbral_api.connections_claude import ClaudeSession
from umbral_api.errors import Unprocessable


@pytest.fixture
def cli(monkeypatch):
    """CLI simulado: `status` devuelve lo configurado; `login` registra el lanzamiento."""
    state = {"status": {"loggedIn": True, "authMethod": "claude.ai", "email": "ana@example.org"}, "calls": [], "popen": [], "alive": True}
    monkeypatch.setattr(module.shutil, "which", lambda name: "claude-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "synthetic-token")

    def run(cmd, **kw):
        state["calls"].append((cmd, kw))
        if state["status"] == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1)
        text = state["status"] if isinstance(state["status"], str) else json.dumps(state["status"])
        return SimpleNamespace(returncode=0, stdout=text)

    class Proc:
        def __init__(self, cmd, **kw):
            state["popen"].append((cmd, kw))

        def poll(self):
            return None if state["alive"] else 0

        def kill(self):
            state["alive"] = False

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.subprocess, "Popen", Proc)
    return state


def session() -> ClaudeSession:
    return ClaudeSession(Settings())


def test_an_open_subscription_session_is_recognised_without_reading_credentials(cli):
    conn = session().status()
    assert conn.logged_in and conn.installed and conn.account == "ana@example.org" and conn.reason is None
    cmd, kw = cli["calls"][0]
    assert cmd == ["claude-test", "auth", "status", "--json"] and kw.get("shell", False) is False


def test_the_child_process_never_inherits_api_credentials(cli):
    session().status()
    env = cli["calls"][0][1]["env"]
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env


def test_no_session_is_reported_with_a_reason(cli):
    cli["status"] = {"loggedIn": False, "authMethod": "none"}
    conn = session().status()
    assert not conn.logged_in and "inicia sesión" in conn.reason


@pytest.mark.parametrize("bad", ["timeout", "no es json", "[]"])
def test_unreadable_status_is_not_a_session(cli, bad):
    cli["status"] = bad
    conn = session().status()
    assert not conn.logged_in and conn.installed and conn.reason


def test_a_console_or_api_login_is_refused_because_it_bills_by_usage(cli):
    cli["status"] = {"loggedIn": True, "authMethod": "console"}
    conn = session().status()
    assert not conn.logged_in and "factura por API" in conn.reason


def test_missing_cli_and_offline_mode(cli, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    conn = session().status()
    assert not conn.available and not conn.installed and "no encontrado" in conn.reason
    assert not ClaudeSession(Settings(offline=True)).status().available


def test_status_is_cached_briefly(cli):
    s = session()
    s.status()
    s.status()
    assert len(cli["calls"]) == 1
    s.status(fresh=True)
    assert len(cli["calls"]) == 2


def test_login_launches_the_official_cli_once_and_never_with_console(cli):
    cli["status"] = {"loggedIn": False, "authMethod": "none"}
    s = session()
    first = s.login()
    cmd, kw = cli["popen"][0]
    assert cmd == ["claude-test", "auth", "login", "--claudeai"] and "--console" not in cmd
    assert "ANTHROPIC_API_KEY" not in kw["env"] and kw["stdin"] == subprocess.DEVNULL and kw.get("shell", False) is False
    assert first.login_pending and not first.logged_in
    s.login()  # mientras hay un inicio en curso no se lanza otro
    assert len(cli["popen"]) == 1
    cli["status"] = {"loggedIn": True, "authMethod": "claude.ai"}
    done = s.status(fresh=True)
    assert done.logged_in and not done.login_pending


def test_login_is_skipped_when_a_session_already_exists_and_fails_clearly_without_cli(cli, monkeypatch):
    assert session().login().logged_in and not cli["popen"]
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    with pytest.raises(Unprocessable) as error:
        session().login()
    assert error.value.details == {"command": "claude auth login"}


def test_logout_runs_the_official_command(cli):
    cli["status"] = {"loggedIn": False, "authMethod": "none"}
    conn = session().logout()
    assert any(c[0][1:3] == ["auth", "logout"] for c in cli["calls"]) and not conn.logged_in


def test_the_routes_are_local_only(make_app, cli):
    local = make_app(auth_mode="local")
    ok = local.get("/api/v1/connections/claude")
    assert ok.status_code == 200 and ok.json()["loggedIn"] is True and "token" not in ok.text.lower()
    assert local.post("/api/v1/connections/claude/login").status_code == 200
    assert local.get("/api/v1/connections/claude", headers={"Origin": "https://example.com"}).status_code == 403
    assert make_app().get("/api/v1/connections/claude").status_code == 403  # auth dev-header: no es una sesión local


def test_the_provider_is_available_only_with_an_open_session(cli):
    from umbral_api.providers import ClaudeCliProvider

    provider = ClaudeCliProvider(Settings())
    assert provider.status().available
    cli["status"] = {"loggedIn": False, "authMethod": "none"}
    provider.session.status(fresh=True)
    assert not provider.status().available
