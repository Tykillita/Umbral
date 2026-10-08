"""Fixtures E2E: backend real sirviendo el build de Astro (apps/web/dist) + Playwright (Chromium)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DIST = REPO / "apps" / "web" / "dist"
PUBLIC_DIST = REPO / "apps" / "web" / "dist-public"


def _need_build():
    if not (DIST / "index.html").exists():
        msg = "falta apps/web/dist (ejecuta `scripts/build-web.ps1`); el frontend aún no tiene build"
        if os.environ.get("UMBRAL_TESTS_STRICT"):
            pytest.fail(msg, pytrace=False)
        pytest.skip(msg)


@pytest.fixture(scope="session")
def stack(server_factory):
    """Stack local: FastAPI + SQLite temporal + build de Astro; usuario único (auth local)."""
    _need_build()
    with server_factory(web_dist=DIST, UMBRAL_AUTH_MODE="local") as srv:
        yield srv


@pytest.fixture(scope="session")
def offline_stack(server_factory):
    """Mismo stack pero con la red del backend bloqueada de verdad y UMBRAL_OFFLINE=1 (T10)."""
    _need_build()
    with server_factory(web_dist=DIST, UMBRAL_AUTH_MODE="local", netblock=True, UMBRAL_OFFLINE="1") as srv:
        yield srv


@pytest.fixture(scope="session")
def delivered_stack(server_factory):
    """Snapshot CURRENT real, SQLite temporal y bloqueo de salida a internet."""
    _need_build()
    current = REPO / "data" / "snapshots" / "CURRENT"
    if not current.is_file():
        pytest.fail("falta snapshot CURRENT para verificar la entrega real", pytrace=False)
    snapshot_dir = current.parent / current.read_text(encoding="utf-8").strip()
    with server_factory(snapshot_dir=snapshot_dir, web_dist=DIST, UMBRAL_AUTH_MODE="local",
                        netblock=True, UMBRAL_OFFLINE="1") as srv:
        yield srv


@pytest.fixture
def public_stack(server_factory):
    """API pública por caso de prueba: evita que el rate limit local comparta IP entre E2E."""
    if not (PUBLIC_DIST / "index.html").is_file():
        pytest.fail("Falta build público apps/web/dist-public (PUBLIC_AUTH_MODE=public).", pytrace=False)
    with server_factory(web_dist=PUBLIC_DIST, UMBRAL_AUTH_MODE="public", UMBRAL_LOCAL_MODE="0",
                        UMBRAL_PERSISTENCE="none", netblock=True, UMBRAL_OFFLINE="1") as srv:
        yield srv


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "locale": "es-PA", "timezone_id": "America/Panama",
            "viewport": {"width": 1366, "height": 900}}
