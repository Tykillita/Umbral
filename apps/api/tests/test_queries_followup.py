"""Preguntas de seguimiento: el cliente reenvía solo el contexto estructurado y las reglas lo resuelven (o piden aclaración)."""

from __future__ import annotations


def ask(client, q, follow_up=None, **kw):
    body = {"question": q, **kw}
    if follow_up is not None:
        body["followUp"] = follow_up
    r = client.post("/api/v1/queries", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_agenda_answer_offers_resolvable_follow_ups(make_app):
    first = ask(make_app(), "¿Qué cinco temas merecen revisión para la agenda y por qué?")
    ctx = first["followUpContext"]
    assert ctx["intent"] == "agenda" and ctx["topicIds"] and ctx["evidenceIds"]
    assert ctx["snapshotId"] == first["snapshotId"]
    assert "¿Qué falta verificar del primero?" in first["followUpSuggestions"]
    assert "¿Cuáles son las fuentes?" in first["followUpSuggestions"]


def test_ordinal_follow_up_scopes_to_the_shown_topic(make_app):
    client = make_app()
    first = ask(client, "¿Qué cinco temas merecen revisión para la agenda y por qué?")
    ctx = first["followUpContext"]
    r = ask(client, "¿Qué falta verificar del primero?", ctx)
    assert r["intent"] == "verificaciones" and r["relatedTopicIds"] == [ctx["topicIds"][0]]
    assert r["question"] == "¿Qué falta verificar del primero?" and r["resolvedQuestion"]
    if len(ctx["topicIds"]) >= 2:
        r2 = ask(client, "¿Cuáles son las fuentes del segundo?", ctx)
        assert r2["answer"].startswith("Fuentes de la respuesta anterior") and r2["citations"]
        assert r2["relatedTopicIds"] == [ctx["topicIds"][1]]


def test_sources_follow_up_lists_the_previous_citations(make_app):
    client = make_app()
    first = ask(client, "crecimiento del PIB de Panamá en 2023")
    r = ask(client, "¿Cuáles son las fuentes?", first["followUpContext"])
    assert r["answerStatus"] == "respondida" and r["answer"].startswith("Fuentes de la respuesta anterior")
    assert {c["evidenceId"] for c in r["citations"]} == {c["evidenceId"] for c in first["citations"]}


def test_economic_follow_up_fills_missing_country_and_keeps_indicator_and_year(make_app):
    client = make_app()
    first = ask(client, "desempleo de Panamá en 2023")
    ctx = first["followUpContext"]
    assert ctx["countries"] == ["PAN"] and ctx["indicators"] == ["SL.UEM.TOTL.ZS"] and ctx["years"] == [2023]
    assert "¿Y en Costa Rica?" in first["followUpSuggestions"]
    r = ask(client, "¿Y en Colombia?", ctx)
    assert r["resolvedQuestion"] == "Desempleo de Colombia en 2023"
    assert r["intent"] == "contexto_economico" and r["answerStatus"] != "abstencion"
    assert r["followUpContext"]["countries"] == ["COL"]
    assert any("COL" in c["evidenceId"] for c in r["citations"])


def test_economic_follow_up_keeps_country_when_only_the_indicator_changes(make_app):
    client = make_app()
    ctx = ask(client, "crecimiento del PIB de Panamá")["followUpContext"]
    r = ask(client, "¿Y la inflación?", ctx)
    assert r["resolvedQuestion"] == "Inflación (precios al consumidor) de Panamá"
    assert any("mantuvo el país" in w for w in r["warnings"])
    assert r["followUpContext"]["indicators"] == ["FP.CPI.TOTL.ZG"]


def test_self_contained_question_ignores_the_context(make_app):
    client = make_app()
    ctx = ask(client, "desempleo de Panamá")["followUpContext"]
    r = ask(client, "¿Cuál fue el crecimiento del PIB de Panamá en 2023?", ctx)
    assert r["resolvedQuestion"] is None and "7.3" in r["answer"]


def test_unresolvable_follow_up_asks_for_clarification_instead_of_guessing(make_app):
    client = make_app()
    ctx = ask(client, "desempleo de Panamá")["followUpContext"]
    r = ask(client, "¿y eso?", ctx)
    assert r["answerStatus"] == "abstencion" and "no pude resolver" in r["answer"]
    assert r["citations"] == [] and r["followUpContext"] is None
    assert not any(ch.isdigit() for ch in r["answer"])


def test_ambiguous_verification_follow_up_after_agenda_asks_which_topic(make_app):
    client = make_app()
    ctx = ask(client, "¿Qué cinco temas merecen revisión para la agenda y por qué?")["followUpContext"]
    if len(ctx["topicIds"]) >= 2:
        r = ask(client, "¿y qué falta verificar?", ctx)
        assert r["answerStatus"] == "abstencion" and "varios temas" in r["answer"]


def test_context_from_another_snapshot_is_ignored_with_a_warning(make_app):
    client = make_app()
    ctx = ask(client, "desempleo de Panamá")["followUpContext"]
    ctx["snapshotId"] = "otro-snapshot"
    r = ask(client, "¿Y en Colombia?", ctx)
    assert r["resolvedQuestion"] is None
    assert any("otro snapshot" in w for w in r["warnings"])


def test_follow_up_context_is_validated_and_bounded(make_app):
    client = make_app()
    ctx = ask(client, "desempleo de Panamá")["followUpContext"]
    bad = dict(ctx, topicIds=[f"t{i}" for i in range(6)])
    assert client.post("/api/v1/queries", json={"question": "¿Y en Colombia?", "followUp": bad}).status_code == 422
    extra = dict(ctx, answerText="no debe viajar")
    r = client.post("/api/v1/queries", json={"question": "¿Y en Colombia?", "followUp": extra})
    assert r.status_code in {200, 422}  # los campos de texto no forman parte del contrato
    assert "answerText" not in ctx and "answer" not in ctx
