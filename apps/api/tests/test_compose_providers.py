"""Elección del proveedor que redacta las respuestas del asistente: Gemini por defecto; ChatGPT/Claude solo en local."""

from __future__ import annotations

import pytest

from umbral_api.compose import ModelCompose, stub_compose_from_prompt
from umbral_api.models import FallbackReason
from umbral_api.providers import DraftProvider, ModelOutput, ProviderError, ProviderResult

from .conftest import FakeProvider
from .test_public import API, context, public_app

Q = "calado del Canal por el lago Gatún"


class FakeLocal(DraftProvider):
    """Adaptador de cuenta personal simulado (solo localhost); no hace red."""

    local_only = True

    def __init__(self, settings, name, *, available=True):
        super().__init__(settings)
        self.name = name
        self.available = available
        self.calls = 0

    def status(self):
        return self._status(self.available, None if self.available else "Sin sesión.", f"{self.name}-model")

    def generate(self, system, user, *, schema=ModelOutput):
        self.calls += 1
        if schema is not ModelCompose:
            raise ProviderError(FallbackReason.proveedor_no_disponible, "solo compose en esta prueba")
        return ProviderResult(stub_compose_from_prompt(user, "ok"), f"{self.name}-model")


def compose(client, **kw):
    r = client.post("/api/v1/queries/compose", json={"question": Q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def install(client, name, **kw):
    provider = FakeLocal(client.svc.settings, name, **kw)
    client.svc.providers[name] = provider
    return provider


@pytest.mark.parametrize("name", ["chatgpt", "claude"])
def test_a_personal_provider_composes_without_touching_the_gemini_quota(make_app, name):
    client = make_app("ok", gemini_calls_per_user_day=1, drafts_per_minute=50)
    local = install(client, name)
    for _ in range(2):  # con la cuota de Gemini en 1, dos redacciones locales seguirían pasando
        data = compose(client, provider=name)
        assert data["answerMode"] == "modelo" and data["provider"] == name and data["model"] == f"{name}-model"
    assert local.calls == 2 and client.fake.calls == 0
    assert compose(client)["provider"] == "gemini"  # sin `provider` sigue siendo Gemini


def test_the_composition_is_validated_by_code_whoever_writes_it(make_app):
    client = make_app("ok", drafts_per_minute=50)
    local = install(client, "claude")
    local.generate = lambda system, user, *, schema=ModelOutput: ProviderResult(  # type: ignore[method-assign]
        stub_compose_from_prompt(user, "bad_citation"), "claude-model")
    data = compose(client, provider="claude")
    assert data["answerMode"] == "reglas" and data["fallbackReason"] == "validacion_fallida"


@pytest.mark.parametrize("name", ["chatgpt", "claude"])
def test_a_disconnected_provider_keeps_the_rules_answer_without_calling(make_app, name):
    client = make_app("ok", drafts_per_minute=50)
    local = install(client, name, available=False)
    data = compose(client, provider=name)
    assert data["answerMode"] == "reglas" and data["fallbackReason"] == "proveedor_no_conectado"
    assert data["attempts"] == 0 and local.calls == 0 and "Sin sesión" in data["fallbackDetail"]


def test_an_unknown_provider_is_rejected_by_the_contract(make_app):
    client = make_app("ok")
    assert client.post("/api/v1/queries/compose", json={"question": Q, "provider": "otro"}).status_code == 422


def test_the_public_api_only_composes_with_gemini_and_never_reuses_another_providers_cache(fixture_dir):
    client, svc = public_app(fixture_dir, behavior="ok", queries_per_minute=10)
    local = FakeLocal(svc.settings, "chatgpt")
    svc.providers["chatgpt"] = local
    body = {"context": context(svc), "question": Q}
    assert client.post(API + "/public/queries/compose", json=body).json()["answerMode"] == "modelo"
    other = client.post(API + "/public/queries/compose", json=body | {"provider": "chatgpt"}).json()
    assert other["answerMode"] == "reglas" and other["fallbackReason"] == "solo_localhost"
    assert other["attempts"] == 0 and local.calls == 0 and not any("reutiliz" in n for n in other["notices"])
    assert svc.providers["gemini"].calls == 1


def test_health_tells_the_interface_how_to_sign_in_only_in_local_mode(make_app, fixture_dir):
    local = make_app("ok", auth_mode="local").get("/api/v1/health").json()["providers"]
    by_name = {p["name"]: p for p in local}
    assert by_name["chatgpt"]["signIn"] == "oauth" and by_name["claude"]["signIn"] == "cli"
    assert by_name["gemini"]["signIn"] is None
    _, svc = public_app(fixture_dir, behavior="ok")
    assert "claude" not in {p.name for p in svc.provider_statuses()}


def test_gemini_stub_is_still_treated_as_gemini(make_app):
    client = make_app(gemini_stub="ok")
    assert not isinstance(client.svc.providers["gemini"], FakeProvider)
    assert compose(client, provider="gemini")["provider"] == "gemini"
