from __future__ import annotations

from datetime import UTC, datetime

from umbral_api.live_sources import (
    LiveItem,
    LiveResult,
    _date_in_title,
    _diverse,
    _matches_query,
    _search_terms,
    is_current_question,
)


def _live_result() -> LiveResult:
    checked = datetime(2026, 10, 9, 12, 1, tzinfo=UTC)
    return LiveResult((
        LiveItem(
            id="live_tvn_1", kind="noticia", title="TVN informa sobre el sismo",
            source="TVN", url="https://www.tvn-2.com/noticias/sismo/",
            published_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
        ),
        LiveItem(
            id="live_usgs_1", kind="sismo", title="USGS registra un sismo",
            source="USGS", url="https://earthquake.usgs.gov/earthquakes/eventpage/us6000test",
            published_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
        ),
    ), checked)


def test_public_alert_feed_is_exposed_separately_from_agenda(make_app):
    client = make_app()
    client.svc.live_sources.alerts = lambda: _live_result()

    response = client.get("/api/v1/public/alerts")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["source"] == "TVN"
    assert body["items"][0]["publishedAt"] == "2026-10-09T12:00:00Z"
    assert body["checkedAt"] == "2026-10-09T12:01:00Z"


def test_live_query_returns_linked_current_headlines(make_app):
    client = make_app()
    client.svc.live_sources.search = lambda question, mode="auto": _live_result()

    response = client.post("/api/v1/queries", json={
        "question": "¿Qué noticias recientes hay sobre el sismo?", "searchMode": "live",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["searchMode"] == "live"
    assert body["answerStatus"] == "parcial" and body["abstentionReason"] is None
    assert body["citations"][0]["url"] == "https://www.tvn-2.com/noticias/sismo/"
    assert "TVN informa sobre el sismo" in body["answer"]
    assert "USGS registra un sismo" in body["answer"]


def test_auto_mode_does_not_search_live_for_historical_questions(make_app):
    client = make_app()
    calls = []
    client.svc.live_sources.search = lambda *args, **kwargs: calls.append(args)

    response = client.post("/api/v1/queries", json={
        "question": "¿Qué sismos registró USGS en 2024?", "searchMode": "auto",
    })

    assert response.status_code == 200, response.text
    assert response.json()["searchMode"] == "snapshot"
    assert calls == []


def test_auto_search_detects_current_questions_but_not_historical_years():
    assert is_current_question("Acaba de temblar, ¿qué se sabe?")
    assert not is_current_question("¿Qué sismos hubo en 2024?")


def test_curated_headlines_are_filtered_by_the_user_topic():
    item = _live_result().items[0]
    terms = _search_terms("¿Qué noticias recientes hay sobre el terremoto?")
    assert _matches_query(item, terms) is False
    temblor = LiveItem(
        id="t", kind="noticia", title="Temblor de 7.2 en Panamá", source="TVN",
        url="https://www.tvn-2.com/temblor/", published_at=None,
    )
    assert _matches_query(temblor, _search_terms("Acaba de temblar 7.2 en Panamá"))


def test_imhpa_published_date_is_converted_from_panama_time_to_utc():
    assert _date_in_title("Aviso 08/10/2026 04:41 pm") == datetime(2026, 10, 8, 21, 41, tzinfo=UTC)


def test_recent_search_keeps_multiple_publishers_visible():
    tvn, usgs = _live_result().items
    items = [usgs, usgs, usgs, tvn]
    assert {item.source for item in _diverse(items, limit=3, per_source=2)} == {"USGS", "TVN"}
