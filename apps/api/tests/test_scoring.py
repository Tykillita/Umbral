"""scoring-v1: bandas, desempates, componentes y límites (T08)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest

from umbral_api.models import GeoRelevance, ImpactAssignment, ImpactLevel, ScoreBand
from umbral_api.scoring import (
    WEIGHTS,
    ScoreInputs,
    band_for,
    score_topic,
    sort_key,
    urgency_value,
)

CUT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def inputs(**kw) -> ScoreInputs:
    base = dict(
        geo=GeoRelevance.panama,
        geo_evidence_ids=["a1"],
        impact=ImpactAssignment(level=ImpactLevel.alto, justification="x", origin="editorial"),
        first_published=CUT - timedelta(hours=2),
        publish_date_issue=None,
        cutoff=CUT,
        is_recirculation=False,
        recirculation_reason=None,
        independent_provenances=2,
        primary_source_linked=True,
        primary_source_ids=["i1"],
        has_outlet_original=True,
        provenance_known=True,
        article_ids=["a1", "a2"],
    )
    base.update(kw)
    return ScoreInputs(**base)


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100 and WEIGHTS == {"R": 30, "I": 25, "U": 20, "N": 15, "E": 10}


@pytest.mark.parametrize(
    ("total", "band"),
    [(0, ScoreBand.bajo), (39.99, ScoreBand.bajo), (40, ScoreBand.medio), (69.99, ScoreBand.medio),
     (70, ScoreBand.alto), (100, ScoreBand.alto), (Fraction(6995, 100), ScoreBand.medio)],
)
def test_band_boundaries(total, band):
    assert band_for(total) == band


def test_max_score_is_100_and_components_exposed():
    s = score_topic(inputs())
    assert s.total == 100.0 and s.band == ScoreBand.alto
    assert [c.key for c in s.components] == ["R", "I", "U", "N", "E"]
    for c in s.components:
        assert c.rule and c.justification and c.weight == WEIGHTS[c.key]
        assert c.points == pytest.approx(c.weight * c.value)
    assert s.rules_version == "scoring-v1"


def test_relevance_rules():
    assert score_topic(inputs(geo=GeoRelevance.regional)).components[0].value == 0.5
    for g in (GeoRelevance.none, GeoRelevance.indeterminate):
        c = score_topic(inputs(geo=g)).components[0]
        assert c.value == 0 and any("no se fuerza" in lim for lim in c.limits)


@pytest.mark.parametrize(
    ("delta", "value"),
    [(timedelta(hours=0), 1), (timedelta(hours=24), 1), (timedelta(hours=24, minutes=1), 0.5),
     (timedelta(days=7), 0.5), (timedelta(days=7, minutes=1), 0), (timedelta(days=200), 0)],
)
def test_urgency_thresholds_against_cutoff(delta, value):
    v, _, _ = urgency_value(CUT - delta, CUT)
    assert float(v) == value


def test_urgency_unknown_or_future_date_is_zero_with_visible_limit():
    v, _, limits = urgency_value(None, CUT)
    assert v == 0 and limits
    v, _, limits = urgency_value(CUT + timedelta(hours=1), CUT)
    assert v == 0 and limits


def test_urgency_is_reproducible_against_cutoff_not_wall_clock():
    a = score_topic(inputs(first_published=CUT - timedelta(hours=30))).components[2].value
    later = CUT + timedelta(days=30)
    b = score_topic(inputs(first_published=CUT - timedelta(hours=30), cutoff=later)).components[2].value
    assert a == 0.5 and b == 0


def test_novelty_recirculation_zero_and_duplicates_do_not_change_score():
    assert score_topic(inputs(is_recirculation=True, recirculation_reason="x")).components[3].value == 0
    a = score_topic(inputs(article_ids=["a1"])).total
    b = score_topic(inputs(article_ids=["a1", "a2", "a3", "a4"])).total
    assert a == b


@pytest.mark.parametrize(
    ("kw", "value"),
    [
        (dict(independent_provenances=0, primary_source_linked=False, has_outlet_original=False), 0),
        (dict(independent_provenances=1, primary_source_linked=False, has_outlet_original=False), 0.33),
        (dict(independent_provenances=2, primary_source_linked=False, has_outlet_original=True), 0.67),
        (dict(independent_provenances=2, primary_source_linked=True, has_outlet_original=True), 1),
        (dict(independent_provenances=1, primary_source_linked=True, has_outlet_original=False), 0.33),
    ],
)
def test_evidence_component_rules(kw, value):
    assert score_topic(inputs(**kw)).components[4].value == value


def test_impact_levels():
    for lvl, v in ((ImpactLevel.bajo, 0.25), (ImpactLevel.medio, 0.5), (ImpactLevel.alto, 1)):
        s = score_topic(inputs(impact=ImpactAssignment(level=lvl, justification="x", origin="editorial")))
        assert s.components[1].value == v


def test_automatic_impact_carries_visible_limit():
    s = score_topic(inputs(impact=ImpactAssignment(level=ImpactLevel.medio, justification="x", origin="propuesta_automatica")))
    assert any("confirmación editorial" in lim for lim in s.components[1].limits)


def test_tiebreak_urgency_then_id():
    rows = [(70.0, 0.5, "b"), (70.0, 1.0, "z"), (70.0, 1.0, "a"), (80.0, 0.0, "m")]
    assert [r[2] for r in sorted(rows, key=lambda r: sort_key(*r))] == ["m", "a", "z", "b"]


def test_agenda_orders_by_score_urgency_id(make_app):
    items = make_app().get("/api/v1/topics", params={"limit": 100}).json()["items"]
    keys = [(-i["score"], -i["urgency"], i["id"]) for i in items]
    assert keys == sorted(keys)
    assert items[0]["rank"] == 1


def test_sponsored_caps_evidence_at_033_even_with_primary_confirmed():
    s = score_topic(inputs(sponsored=True, independent_provenances=3, primary_source_linked=True))
    e = s.components[4]
    assert e.value == 0.33 and any("patrocinado" in lim for lim in e.limits)


def test_evidence_one_requires_confirmed_primary_not_just_two_provenances():
    assert score_topic(inputs(primary_source_linked=False)).components[4].value == 0.67
    assert score_topic(inputs(primary_source_linked=True)).components[4].value == 1
