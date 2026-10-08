from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.compose import ModelCompose, stub_compose_from_prompt
from umbral_api.config import Settings
from umbral_api.fixture_builder import build_fixture
from umbral_api.models import FallbackReason
from umbral_api.providers import (
    DraftProvider,
    ModelOutput,
    ProviderError,
    ProviderResult,
    stub_output_from_prompt,
)
from umbral_api.services import Services


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory) -> Path:
    return build_fixture(tmp_path_factory.mktemp("snapshot-fixture"))


def make_settings(fixture_dir: Path, tmp_path: Path | None = None, **kw) -> Settings:
    base = Settings(
        snapshot_dir=fixture_dir,
        persistence="memory",
        auth_mode="dev-header",
        gemini_api_key=None,
        offline=False,
        local_mode=True,
        web_dist=Path("__no_dist__"),
        queries_per_minute=1000,
        drafts_per_minute=1000,
    )
    if tmp_path is not None:
        base = replace(base, sqlite_path=tmp_path / "umbral.sqlite")
    return replace(base, **kw)


class FakeProvider(DraftProvider):
    """Proveedor de redacción controlable para pruebas (no hace red)."""

    name = "gemini"

    def __init__(self, settings, behavior="ok"):
        super().__init__(settings)
        self.behavior = behavior
        self.calls = 0
        self.last_user: str | None = None

    def status(self):
        if self.settings.offline:
            return self._status(False, "Modo sin conexión.", "fake-model")
        return self._status(self.behavior != "no_key", None if self.behavior != "no_key" else "sin clave", "fake-model")

    def generate(self, system: str, user: str, *, schema=ModelOutput) -> ProviderResult:
        self.calls += 1
        self.last_user = user
        if self.behavior == "quota":
            raise ProviderError(FallbackReason.cuota_agotada, "Cuota agotada (429).")
        if self.behavior == "down":
            raise ProviderError(FallbackReason.proveedor_no_disponible, "Servicio no disponible.")
        if schema is ModelCompose:
            return ProviderResult(stub_compose_from_prompt(user, self.behavior), "fake-model")
        return ProviderResult(model_output_from_prompt(user, self.behavior), "fake-model")


def model_output_from_prompt(user: str, behavior: str) -> ModelOutput:
    return stub_output_from_prompt(user, behavior)


@pytest.fixture
def make_app(fixture_dir, tmp_path):
    """Fábrica: make_app(provider_behavior='ok'|'quota'|'down'|'no_key'|'bad_citation'|None, **settings)."""

    def _make(behavior: str | None = None, *, sqlite: bool = False, **kw):
        settings = make_settings(fixture_dir, tmp_path, persistence="sqlite" if sqlite else "memory", **kw)
        svc = Services(settings)
        fake = None
        if behavior is not None:
            fake = FakeProvider(settings, behavior)
            svc.providers["gemini"] = fake
        app = create_app(settings, services=svc)
        client = TestClient(app, headers={"X-Umbral-User": "ana"})
        client.fake = fake  # type: ignore[attr-defined]
        client.svc = svc  # type: ignore[attr-defined]
        return client

    return _make


@pytest.fixture
def topic_ids(make_app):
    """Mapa título parcial -> id de tema del fixture."""
    c = make_app()
    items = c.get("/api/v1/topics", params={"limit": 100}).json()["items"]
    out = {}
    for it in items:
        out[it["title"]] = it["id"]
    return out


def find_topic(client, needle: str) -> str:
    items = client.get("/api/v1/topics", params={"limit": 100, "scope": "all"}).json()["items"]
    for it in items:
        if needle.lower() in it["title"].lower():
            return it["id"]
    raise AssertionError(f"tema no encontrado: {needle}")
