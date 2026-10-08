"""Redacción opcional con IA de una consulta: se acepta solo si el código la valida; ante cualquier fallo queda la respuesta por reglas."""

from __future__ import annotations

import pytest

from .test_public import API, context, public_app

Q = "calado del Canal por el lago Gatún"


def compose(client, question=Q, **kw):
    r = client.post("/api/v1/queries/compose", json={"question": question, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_valid_composition_is_accepted_with_numbered_markers_and_keeps_the_rules_answer(make_app):
    client = make_app(gemini_stub="ok")
    data = compose(client)
    assert data["answerMode"] == "modelo" and data["provider"] == "gemini" and data["model"] == "gemini-stub"
    shown = data["response"]
    assert shown["answer"].startswith("Respuesta redactada con IA") and "[1]" in shown["answer"]
    assert data["rulesAnswer"] != shown["answer"] and "titular/metadatos" in data["rulesAnswer"]
    assert shown["citations"]  # las fuentes son las mismas de la respuesta por reglas
    assert any("verificada por código" in w for w in shown["warnings"])
    assert "Confirmar la fuente primaria." in shown["missing"]
    assert data["fallbackReason"] is None and data["attempts"] == 1


@pytest.mark.parametrize(("behavior", "reason"), [
    ("bad_citation", "validacion_fallida"), ("bad_number", "validacion_fallida"), ("injection", "validacion_fallida"),
    ("quota", "cuota_agotada"), ("down", "proveedor_no_disponible"), ("no_key", "sin_credenciales"),
])
def test_any_failure_keeps_the_rules_answer(make_app, behavior, reason):
    client = make_app(gemini_stub=behavior)
    data = compose(client)
    assert data["answerMode"] == "reglas" and data["fallbackReason"] == reason
    assert data["response"]["answer"] == data["rulesAnswer"] and data["response"]["citations"]
    assert data["notices"]


def test_invalid_first_attempt_gets_one_correction_retry(make_app):
    client = make_app(gemini_stub="bad_number")
    compose(client)
    assert client.svc.providers["gemini"].calls == 2  # un intento + un único reintento con la retroalimentación
    assert compose(make_app(gemini_stub="bad_number"))["attempts"] == 2


def test_abstentions_and_contradictions_are_never_composed(make_app):
    client = make_app(gemini_stub="ok")
    abstain = compose(client, "¿Cuál es el precio del petróleo en Marte?")
    assert abstain["answerMode"] == "reglas" and abstain["fallbackReason"] == "sin_evidencia"
    contradiction = compose(client, "sismo en Chiriquí heridos")
    assert contradiction["answerMode"] == "reglas" and contradiction["fallbackReason"] == "sin_evidencia"
    assert client.svc.providers["gemini"].calls == 0  # sin evidencia utilizable no se gasta cuota


def test_offline_mode_blocks_the_external_call(make_app):
    data = compose(make_app(gemini_stub="ok", offline=True))
    assert data["answerMode"] == "reglas" and data["fallbackReason"] == "modo_sin_conexion" and data["attempts"] == 0


def test_composition_counts_against_the_per_user_daily_quota(make_app):
    client = make_app(gemini_stub="ok", gemini_calls_per_user_day=1, drafts_per_minute=50)
    assert compose(client)["answerMode"] == "modelo"
    second = compose(client)
    assert second["answerMode"] == "reglas" and second["fallbackReason"] == "limite_por_usuario"


def test_economic_answer_is_composed_from_the_indicator_values(make_app):
    data = compose(make_app(gemini_stub="ok"), "desempleo de Panamá en 2023")
    assert data["answerMode"] == "modelo" and "[1]" in data["response"]["answer"]


def test_follow_up_questions_can_be_composed_too(make_app):
    client = make_app(gemini_stub="ok", drafts_per_minute=50)
    ctx = client.post("/api/v1/queries", json={"question": "desempleo de Panamá en 2023"}).json()["followUpContext"]
    data = compose(client, "¿Y en Colombia?", followUp=ctx)
    assert data["answerMode"] == "modelo" and data["response"]["resolvedQuestion"] == "Desempleo de Colombia en 2023"


def test_compose_is_rate_limited_separately(make_app):
    client = make_app(gemini_stub="ok", drafts_per_minute=1)
    compose(client)
    assert client.post("/api/v1/queries/compose", json={"question": Q}).status_code == 429


def test_public_compose_uses_the_global_counter_and_reuses_verified_results(fixture_dir):
    client, svc = public_app(fixture_dir, behavior="ok", queries_per_minute=10)
    body = {"context": context(svc), "question": Q}
    first = client.post(API + "/public/queries/compose", json=body).json()
    assert first["answerMode"] == "modelo" and svc.providers["gemini"].calls == 1
    again = client.post(API + "/public/queries/compose", json=body).json()
    assert again["answerMode"] == "modelo" and svc.providers["gemini"].calls == 1  # reutilizada: no gastó otra llamada
    assert any("no se llamó de nuevo" in n for n in again["notices"]) and again["usage"] is None


def test_public_compose_without_the_global_counter_falls_back_to_rules(fixture_dir):
    client, svc = public_app(fixture_dir, behavior="ok", counter=False)
    data = client.post(API + "/public/queries/compose", json={"context": context(svc), "question": Q}).json()
    assert data["answerMode"] == "reglas" and data["fallbackReason"] == "contador_no_disponible"
    assert svc.providers["gemini"].calls == 0


def test_public_compose_global_limit_falls_back_to_rules(fixture_dir):
    client, svc = public_app(fixture_dir, behavior="ok", gemini_global_calls_per_day=1)
    first = client.post(API + "/public/queries/compose", json={"context": context(svc), "question": Q}).json()
    assert first["answerMode"] == "modelo"
    other = client.post(API + "/public/queries/compose", json={"context": context(svc), "question": "desempleo de Panamá en 2023"}).json()
    assert other["answerMode"] == "reglas" and other["fallbackReason"] == "limite_global"


AGENDA = "¿Qué cinco temas merecen revisión para la agenda y por qué?"


def test_agenda_composition_keeps_every_topic_attribution_and_score(make_app):
    client = make_app(gemini_stub="ok", drafts_per_minute=50)
    data = compose(client, AGENDA)
    assert data["answerMode"] == "modelo"
    lines = [line for line in data["response"]["answer"].split("\n") if line.startswith("- ")]
    assert len(lines) == len({c["evidenceId"] for c in data["response"]["citations"]})  # un enunciado por tema
    assert all("Puntaje" in line and "reporta" in line for line in lines)  # puntaje conservado y titular atribuido al medio


def test_verification_composition_lists_the_pending_items_not_the_headline(make_app):
    client = make_app(gemini_stub="ok", drafts_per_minute=50)
    ctx = client.post("/api/v1/queries", json={"question": AGENDA}).json()["followUpContext"]
    data = compose(client, "¿Qué falta verificar del primero?", followUp=ctx)
    assert data["answerMode"] == "modelo"
    lines = [line for line in data["response"]["answer"].split("\n") if line.startswith("- ")]
    assert lines and not any("reporta:" in line for line in lines)  # lista de pendientes, no el titular repetido
    assert set(data["response"]["missing"]) >= {line[2:].split(" [")[0] for line in lines}


@pytest.mark.parametrize(("behavior", "question", "needle"), [
    ("no_attribution", Q, "no atribuye el titular"),
    ("restate_headline", "¿Qué falta verificar del primero?", "qué falta verificar"),
])
def test_loss_of_attribution_or_answer_type_is_rejected_and_the_rules_answer_kept(make_app, behavior, question, needle):
    client = make_app(gemini_stub=behavior, drafts_per_minute=50)
    body: dict = {"question": question}
    if behavior == "restate_headline":
        body["followUp"] = client.post("/api/v1/queries", json={"question": AGENDA}).json()["followUpContext"]
    data = client.post("/api/v1/queries/compose", json=body).json()
    assert data["answerMode"] == "reglas" and data["fallbackReason"] == "validacion_fallida" and data["attempts"] == 2
    assert needle in data["fallbackDetail"]
    assert data["response"]["answer"] == data["rulesAnswer"]


def test_validator_requires_the_score_of_each_agenda_topic():
    from umbral_api.compose import ComposeCitation, ComposeStatement, ModelCompose, validate_composition
    from umbral_api.drafts import EvidencePack
    from umbral_api.models import QueryIntent

    pack = EvidencePack(items={"a1": {"title": "Canal sube tránsitos", "outlet": "TVN Panamá", "publishedAt": ""},
                               "reglas": {"nota_1": "Puntaje 76.70 (alto) · evidencia parcial."}},
                        kinds={"a1": "articulo", "reglas": "reglas"})
    cites = [ComposeCitation(evidence_id="a1", field="title", passage="Canal sube tránsitos"),
             ComposeCitation(evidence_id="a1", field="outlet", passage="TVN Panamá")]
    without = ModelCompose(statements=[ComposeStatement(text="TVN Panamá informa: Canal sube tránsitos", citations=cites)])
    _, errors = validate_composition(without, pack, ["a1"], QueryIntent.agenda)
    assert any("reglas.nota_1" in e for e in errors)
    with_note = ModelCompose(statements=[ComposeStatement(
        text="TVN Panamá informa: Canal sube tránsitos (Puntaje 76.70, alto)",
        citations=[*cites, ComposeCitation(evidence_id="reglas", field="nota_1", passage="Puntaje 76.70 (alto) · evidencia parcial.")])])
    assert validate_composition(with_note, pack, ["a1"], QueryIntent.agenda)[1] == []
