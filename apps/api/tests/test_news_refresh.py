"""Refresco manual de noticias: titulares recientes sin clasificar y solicitud de clasificación al workflow de GitHub."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.live_sources import LiveItem, LiveResult, LiveSources
from umbral_api.news_refresh import NewsRefreshDispatcher
from umbral_api.services import Services

from .conftest import make_settings

TOKEN = "ghp_TOKEN_DE_PRUEBA_que_nunca_debe_salir_en_una_respuesta"
API = "/api/v1"


def _settings(fixture_dir, **kw):
    return make_settings(fixture_dir, github_dispatch_token=TOKEN, **kw)


class FakeGitHub:
    """GitHub simulado con httpx.MockTransport; registra cada petición."""

    def __init__(self, *, active: str | None = None, dispatch_status: int = 204, explode: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.active, self.dispatch_status, self.explode = active, dispatch_status, explode

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.explode:
            raise httpx.ConnectError("sin red")
        if request.method == "GET":
            status = request.url.params.get("status")
            runs = [{"html_url": "https://github.com/Tykillita/Umbral/actions/runs/1"}] if self.active == status else []
            return httpx.Response(200, json={"workflow_runs": runs})
        return httpx.Response(self.dispatch_status, json={"message": f"detalle interno con {TOKEN}"})

    def factory(self, **kwargs):
        return httpx.Client(transport=httpx.MockTransport(self.handler), **kwargs)


def _dispatcher(fixture_dir, github: FakeGitHub, clock=lambda: 1000.0, **kw):
    return NewsRefreshDispatcher(_settings(fixture_dir, **kw), client_factory=github.factory, clock=clock)


# ------------------------------------------------------------------------------------------------ dispatcher


def test_sin_token_no_hace_ninguna_llamada_y_lo_dice(fixture_dir):
    github = FakeGitHub()
    outcome = NewsRefreshDispatcher(make_settings(fixture_dir), client_factory=github.factory).request()
    assert outcome.status == "no_disponible" and "no está configurada" in outcome.message
    assert github.requests == []


def test_solicita_la_clasificacion_con_el_token_y_solo_contra_api_github(fixture_dir):
    github = FakeGitHub()
    outcome = _dispatcher(fixture_dir, github).request()
    assert outcome.status == "solicitada" and "15 y 25 minutos" in outcome.message and "SIN clasificar" in outcome.message
    assert outcome.next_allowed_at is not None
    post = github.requests[-1]
    assert post.method == "POST" and post.url.path == "/repos/Tykillita/Umbral/actions/workflows/daily-data.yml/dispatches"
    assert json.loads(post.content) == {"ref": "main"}
    assert post.headers["authorization"] == f"Bearer {TOKEN}"
    assert {request.url.host for request in github.requests} == {"api.github.com"}


def test_el_enfriamiento_evita_pedirlo_dos_veces_seguidas(fixture_dir):
    github = FakeGitHub()
    now = {"t": 1000.0}
    dispatcher = _dispatcher(fixture_dir, github, clock=lambda: now["t"])
    assert dispatcher.request().status == "solicitada"
    calls = len(github.requests)
    now["t"] += 600
    cooldown = dispatcher.request()
    assert cooldown.status == "enfriamiento" and "hace 10 min" in cooldown.message and cooldown.next_allowed_at
    assert len(github.requests) == calls, "en enfriamiento no se llama a GitHub"
    now["t"] += 1300  # ya pasaron los 30 min
    assert dispatcher.request().status == "solicitada"


def test_si_ya_hay_una_ejecucion_en_curso_o_en_cola_no_lanza_otra(fixture_dir):
    for state in ("in_progress", "queued"):
        github = FakeGitHub(active=state)
        outcome = _dispatcher(fixture_dir, github).request()
        assert outcome.status == "en_curso" and outcome.run_url == "https://github.com/Tykillita/Umbral/actions/runs/1"
        assert all(request.method == "GET" for request in github.requests), "no debe haber POST"


@pytest.mark.parametrize("github", [FakeGitHub(dispatch_status=403), FakeGitHub(dispatch_status=404), FakeGitHub(explode=True)])
def test_los_errores_se_resumen_sin_filtrar_el_token_ni_el_detalle(fixture_dir, github):
    outcome = _dispatcher(fixture_dir, github).request()
    assert outcome.status == "error"
    assert TOKEN not in outcome.message and "detalle interno" not in outcome.message and "ghp_" not in outcome.message


def test_el_token_no_aparece_en_el_repr_de_la_configuracion(fixture_dir):
    assert TOKEN not in repr(_settings(fixture_dir))


# ------------------------------------------------------------------------------------------------ noticias recientes en vivo


def _rss(entries: list[tuple[str, str, datetime | None]]) -> str:
    rows = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        + (f"<pubDate>{format_datetime(published)}</pubDate>" if published else "")
        + "</item>"
        for title, link, published in entries
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{rows}</channel></rss>'


def _live(entries_tvn, entries_bing=(), *, tvn_fails=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.tvn-2.com":
            return httpx.Response(500) if tvn_fails else httpx.Response(200, text=_rss(entries_tvn))
        return httpx.Response(200, text=_rss(list(entries_bing)))

    return LiveSources(client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw))


def test_latest_devuelve_solo_lo_publicado_en_las_ultimas_24_horas_mas_reciente_primero():
    now = datetime.now(UTC)
    live = _live(
        [
            ("Hace 3 horas", "https://www.tvn-2.com/nacionales/a.html", now - timedelta(hours=3)),
            ("Hace 20 minutos", "https://www.tvn-2.com/nacionales/b.html", now - timedelta(minutes=20)),
            ("Hace 3 días", "https://www.tvn-2.com/nacionales/c.html", now - timedelta(days=3)),
            ("Sin fecha", "https://www.tvn-2.com/nacionales/d.html", None),
        ],
        [("De Bing hace 1 hora", "https://example.com/e.html", now - timedelta(hours=1))],
    )
    result = live.latest()
    titles = [item.title for item in result.items]
    assert titles == ["Hace 20 minutos", "De Bing hace 1 hora", "Hace 3 horas"]
    assert all(item.published_at and item.published_at > now - timedelta(hours=24) for item in result.items)


def test_latest_tolera_que_una_fuente_falle_y_lo_avisa():
    now = datetime.now(UTC)
    result = _live([], [("Solo Bing", "https://example.com/x.html", now - timedelta(minutes=5))], tvn_fails=True).latest()
    assert [item.title for item in result.items] == ["Solo Bing"]
    assert any("TVN" in warning for warning in result.warnings)


def test_latest_no_vuelve_a_consultar_dentro_del_minimo_de_20_segundos():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=_rss([]))

    live = LiveSources(client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw))
    live.latest()
    first = calls["n"]
    live.latest()
    assert calls["n"] == first


def test_latest_sin_conexion_no_consulta_nada():
    assert LiveSources(offline=True).latest().items == ()


# ------------------------------------------------------------------------------------------------ ruta HTTP


def _client(fixture_dir, **kw) -> tuple[TestClient, Services]:
    settings = _settings(fixture_dir, **kw)
    services = Services(settings)
    return TestClient(create_app(settings, services=services), headers={"X-Umbral-User": "a"}), services


def test_la_ruta_devuelve_titulares_sin_clasificar_y_el_estado_de_la_clasificacion(fixture_dir):
    client, services = _client(fixture_dir)
    now = datetime.now(UTC)
    item = LiveItem("x1", "noticia", "Titular de prueba", "TVN", "https://www.tvn-2.com/nacionales/x.html", now - timedelta(minutes=7))
    services.live_sources.latest = lambda **kw: LiveResult((item,), now, ("aviso",))  # type: ignore[method-assign]
    github = FakeGitHub()
    services.news_refresh = _dispatcher(fixture_dir, github)
    response = client.post(f"{API}/public/news/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["windowHours"] == 24 and body["warnings"] == ["aviso"]
    assert body["items"][0]["title"] == "Titular de prueba" and body["items"][0]["classified"] is False
    assert body["classification"]["status"] == "solicitada"
    assert TOKEN not in response.text


def test_la_ruta_sin_token_sigue_mostrando_noticias_y_explica_que_no_clasifica(fixture_dir):
    settings = make_settings(fixture_dir)
    services = Services(settings)
    client = TestClient(create_app(settings, services=services), headers={"X-Umbral-User": "a"})
    now = datetime.now(UTC)
    item = LiveItem("x2", "noticia", "Otro titular", "TVN", "https://www.tvn-2.com/nacionales/y.html", now - timedelta(minutes=1))
    services.live_sources.latest = lambda **kw: LiveResult((item,), now, ())  # type: ignore[method-assign]
    body = client.post(f"{API}/public/news/refresh").json()
    assert body["classification"]["status"] == "no_disponible" and len(body["items"]) == 1


def test_la_ruta_limita_las_peticiones_por_minuto(fixture_dir):
    settings = make_settings(fixture_dir, offline=True)
    services = Services(settings)
    client = TestClient(create_app(settings, services=services), headers={"X-Umbral-User": "a"})
    statuses = [client.post(f"{API}/public/news/refresh").status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200] and statuses[3] == 429
