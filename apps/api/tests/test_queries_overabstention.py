"""Preguntas económicas con redacción natural: se responden si el paquete tiene el dato y se rechazan solo si falta de verdad."""

from __future__ import annotations

import pytest


def ask(client, q, **kw):
    r = client.post("/api/v1/queries", json={"question": q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    "q",
    [
        "¿Cuánto creció el PIB de Panamá?",
        "¿Cómo ha crecido la economía de Panamá según el Banco Mundial?",
        "¿Qué tan alto es el desempleo en Colombia?",
        "Dime el desempleo de Panamá en el último año disponible",
        "¿Cuál es el valor del PIB de Panamá en el dato más reciente?",
        "¿Cuántos habitantes tiene Panamá?",
        "¿Cuál es la población de Panamá en total?",
    ],
)
def test_natural_wording_is_not_a_reason_to_abstain(make_app, q):
    r = ask(make_app(), q)
    assert r["answerStatus"] != "abstencion", r["abstentionReason"]
    assert r["intent"] == "contexto_economico" and r["citations"]


@pytest.mark.parametrize(
    "q",
    [
        "¿Cuál es el PIB de Panamá según el FMI?",
        "¿Cuál es la inflación de alimentos en Panamá?",
        "población de jóvenes en Colombia",
        "inflación en Narnia",
        "pib de marte",
    ],
)
def test_unlinked_entities_still_abstain_without_inventing(make_app, q):
    r = ask(make_app(), q)
    assert r["answerStatus"] == "abstencion" and r["citations"] == []
    assert not any(ch.isdigit() for ch in r["answer"])


def test_missing_country_defaults_to_panama_and_says_so(make_app):
    r = ask(make_app(), "¿Cuánto creció el PIB?")
    assert r["answerStatus"] != "abstencion"
    assert any("No indicaste un país" in w for w in r["warnings"])
    r2 = ask(make_app(), "¿Cuánto creció el PIB de Panamá?")
    assert not any("No indicaste un país" in w for w in r2["warnings"])


def test_year_range_expands_to_each_year(make_app):
    r = ask(make_app(), "crecimiento del PIB de Panamá entre 2021 y 2023")
    cited = {c["passage"] for c in r["citations"] if c["field"] == "year"}
    reported_missing = " ".join(r["missing"])
    for year in ("2021", "2022", "2023"):  # cada año pedido aparece citado o declarado como faltante, nunca se omite en silencio
        assert year in cited or year in reported_missing
    assert len(cited) >= 2


def test_partial_search_states_what_is_covered(make_app):
    r = ask(make_app(), "calado Canal Gatún sequía récord")
    assert r["answerStatus"] == "parcial"
    assert "Cubierto:" in r["answer"] and "Sin respaldo en las fuentes recuperadas" in r["answer"]
    assert any(item.startswith("Evidencia que mencione:") for item in r["missing"])


def test_claim_questions_get_the_figure_but_not_as_proof(make_app):
    r = ask(make_app(), "¿La inflación anual permite afirmar que todos los productos subieron igual?")
    assert r["answerStatus"] == "parcial" and r["citations"]
    assert "ni la respalda ni la refuta" in r["answer"]
    assert any("afirmación planteada" in item for item in r["missing"])
    plain = ask(make_app(), "¿Cuál es la inflación de Panamá?")
    assert "ni la respalda ni la refuta" not in plain["answer"]
