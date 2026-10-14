"""«Hoy» (titulares más recientes fuera del puntaje) y estado vacío por antigüedad del corte."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.models import Category
from umbral_api.services import Services

from .conftest import make_settings

API = "/api/v1"


def _client(fixture_dir, **kw) -> tuple[TestClient, Services]:
    settings = make_settings(fixture_dir, **kw)
    services = Services(settings)
    return TestClient(create_app(settings, services=services), headers={"X-Umbral-User": "a"}), services


# ------------------------------------------------------------------------------------------------ estado vacío


def test_un_corte_antiguo_se_oculta_y_la_agenda_queda_vacia(fixture_dir):
    client, services = _client(fixture_dir, hide_stale_snapshot_hours=36)
    health = client.get(f"{API}/health").json()
    assert health["dataMode"] == "empty" and health["snapshotId"] == "sin-datos"
    assert health["hiddenSnapshotId"] and health["hiddenSnapshotCutoffUtc"]
    assert health["counts"]["topics"] == 0 and health["counts"]["articles"] == 0
    assert any("se oculta" in note for note in health["notes"])
    topics = client.get(f"{API}/topics").json()
    assert topics["total"] == 0 and topics["items"] == [] and topics["dataMode"] == "empty"
    assert services.hidden_snapshot is not None


def test_con_el_corte_oculto_la_ficha_no_existe_y_las_consultas_no_inventan(fixture_dir):
    client, _ = _client(fixture_dir, hide_stale_snapshot_hours=36)
    assert client.get(f"{API}/topics/evt_inexistente").status_code == 404
    response = client.post(f"{API}/queries", json={"question": "¿Qué pasó hoy con el Canal de Panamá?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answerStatus"] == "abstencion" and body["citations"] == [] and body["hits"] == []


def test_sin_la_politica_se_sirve_el_ultimo_corte_como_siempre(fixture_dir):
    client, services = _client(fixture_dir)
    assert services.hidden_snapshot is None
    health = client.get(f"{API}/health").json()
    assert health["dataMode"] == "fixture" and health["hiddenSnapshotId"] is None
    assert client.get(f"{API}/topics").json()["total"] > 0


def test_un_corte_dentro_del_limite_no_se_oculta(fixture_dir):
    # El corte del fixture es de octubre de 2026: un límite enorme equivale a «reciente».
    client, services = _client(fixture_dir, hide_stale_snapshot_hours=24 * 365 * 5)
    assert services.hidden_snapshot is None
    assert client.get(f"{API}/health").json()["dataMode"] == "fixture"


def test_el_estado_vacio_acepta_cualquier_corte_nuevo(fixture_dir):
    _, services = _client(fixture_dir, hide_stale_snapshot_hours=36)
    # Un corte más antiguo que el oculto no lo reemplaza; el oculto no se vuelve a descargar.
    assert services.hidden_snapshot is not None
    hidden_id, hidden_cutoff = services.hidden_snapshot
    assert services.corpus.cutoff == hidden_cutoff
    assert services.corpus.snapshot_id != hidden_id


# ------------------------------------------------------------------------------------------------ hoy


def test_hoy_devuelve_lo_mas_reciente_dentro_de_la_ventana_y_ordenado(fixture_dir):
    _, services = _client(fixture_dir)
    now = services.corpus.cutoff + timedelta(hours=1)
    today = services.today(limit=50, window_hours=24, now=now)
    assert today.window_hours == 24 and today.snapshot_id == services.corpus.snapshot_id
    published = [item.published_at for item in today.items]
    assert published == sorted(published, reverse=True), "debe ir de más reciente a más antiguo"
    assert all(now - timedelta(hours=24) <= p <= now + timedelta(minutes=10) for p in published)
    # Ningún tema fuera de alcance ni sin fecha de publicación conocida.
    for item in today.items:
        base = services.bases[item.id]
        assert base.category != Category.indeterminado
        assert any(a.published_at == item.published_at for a in base.usable_articles)


def test_hoy_respeta_el_limite_y_no_altera_el_ranking_de_la_agenda(fixture_dir):
    client, services = _client(fixture_dir)
    before = [item["id"] for item in client.get(f"{API}/topics", params={"limit": 20}).json()["items"]]
    now = services.corpus.cutoff + timedelta(hours=1)
    assert len(services.today(limit=2, now=now).items) <= 2
    after = [item["id"] for item in client.get(f"{API}/topics", params={"limit": 20}).json()["items"]]
    assert before == after


def test_hoy_con_el_corte_oculto_explica_por_que_esta_vacio(fixture_dir):
    client, _ = _client(fixture_dir, hide_stale_snapshot_hours=36)
    body = client.get(f"{API}/today").json()
    assert body["items"] == [] and body["dataMode"] == "empty"
    assert "Aún no hay noticias vigentes" in body["note"] and "cada 6 horas" in body["note"]


def test_hoy_avisa_cuando_el_corte_es_viejo_y_no_hay_noticias_de_las_ultimas_horas(fixture_dir):
    client, _ = _client(fixture_dir)
    body = client.get(f"{API}/today").json()  # «ahora» real: el corte del fixture es de otro día
    assert body["items"] == [] and body["note"]


def test_hoy_valida_sus_parametros(fixture_dir):
    client, _ = _client(fixture_dir)
    assert client.get(f"{API}/today", params={"limit": 0}).status_code == 422
    assert client.get(f"{API}/today", params={"windowHours": 500}).status_code == 422
