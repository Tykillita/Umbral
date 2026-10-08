"""Revisión: máquina de estados, concurrencia optimista, reinicio, aislamiento entre usuarios, impacto y exportación."""

from __future__ import annotations

from umbral_api.app import create_app
from umbral_api.services import Services

from .conftest import find_topic, make_settings

API = "/api/v1"


def review(c, case, status, *, reviewer="Marta", comment=None, confirmed=None, expect=200, headers=None):
    body = {"expectedVersion": case["version"], "status": status, "reviewer": reviewer}
    if comment:
        body["comment"] = comment
    if confirmed is not None:
        body["evidenceConfirmed"] = confirmed
    r = c.patch(f"{API}/cases/{case['caseId']}/review", json=body, headers=headers or {})
    assert r.status_code == expect, r.text
    return r.json()


def new_case(c, topic):
    tid = find_topic(c, topic)
    return tid, c.get(f"{API}/cases/case-{tid}").json()


def test_new_case_is_not_persisted_and_starts_as_nuevo(make_app):
    c = make_app()
    _, case = new_case(c, "calado")
    assert case["status"] == "nuevo" and case["version"] == 0 and case["persisted"] is False
    assert case["allowedTransitions"] == ["en_revision"]


def test_full_happy_path_to_approved_with_responsible_and_history(make_app):
    c = make_app(offline=True)
    tid, case = new_case(c, "calado")
    case = c.post(f"{API}/topics/{tid}/drafts", json={}).json()["case"]
    case = review(c, case, "en_revision", reviewer="Marta")
    assert case["status"] == "en_revision" and case["reviewer"] == "Marta"
    case = review(c, case, "aprobado_como_borrador", reviewer="Marta")
    assert case["status"] == "aprobado_como_borrador" and case["version"] == 3
    kinds = [(e["kind"], e["toStatus"]) for e in case["history"]]
    assert kinds == [("borrador", None), ("revision", "en_revision"), ("revision", "aprobado_como_borrador")]
    assert [e["version"] for e in case["history"]] == [1, 2, 3]


def test_invalid_transition_is_rejected(make_app):
    c = make_app()
    _, case = new_case(c, "calado")
    out = review(c, case, "aprobado_como_borrador", expect=422)
    assert out["code"] == "transicion_invalida" and out["details"]["allowed"] == ["en_revision"]


def test_comment_required_for_requires_evidence_and_discard(make_app):
    c = make_app()
    _, case = new_case(c, "calado")
    case = review(c, case, "en_revision")
    assert review(c, case, "requiere_evidencia", expect=422)["code"] == "no_procesable"
    case = review(c, case, "requiere_evidencia", comment="Falta fuente primaria.")
    assert case["status"] == "requiere_evidencia"
    case = review(c, case, "en_revision")
    case = review(c, case, "descartado", comment="No es de interés.")
    assert case["status"] == "descartado" and case["allowedTransitions"] == ["en_revision"]


def test_cannot_approve_without_draft(make_app):
    c = make_app()
    _, case = new_case(c, "calado")
    case = review(c, case, "en_revision")
    assert review(c, case, "aprobado_como_borrador", expect=422)["message"].startswith("No se puede aprobar")


def test_insufficient_evidence_blocks_approval_unless_reviewer_confirms(make_app):
    c = make_app(offline=True)
    tid, case = new_case(c, "alerta por lluvias")  # evidencia insuficiente, prioridad alta (T08)
    top = c.get(f"{API}/topics/{tid}").json()
    assert top["evidence"]["status"] == "insuficiente" and top["summary"]["needsInvestigation"]
    assert top["summary"]["band"] == "alto"
    assert "requiere investigación" in top["recommendedAction"].lower() or "investigar" in top["recommendedAction"].lower()
    case = c.post(f"{API}/topics/{tid}/drafts", json={}).json()["case"]
    case = review(c, case, "en_revision")
    out = review(c, case, "aprobado_como_borrador", expect=422)
    assert "insuficiente" in out["message"]
    out = review(c, case, "aprobado_como_borrador", confirmed=False, comment="No alcanza.", expect=422)
    assert "niega" in out["message"]
    ok = review(c, case, "aprobado_como_borrador", confirmed=True, comment="Confirmo con fuente interna.")
    assert ok["status"] == "aprobado_como_borrador" and ok["evidenceConfirmed"] is True


def test_optimistic_concurrency_conflict_409(make_app):
    c = make_app()
    _, stale = new_case(c, "calado")
    fresh = review(c, stale, "en_revision", reviewer="Ana")
    out = review(c, stale, "en_revision", reviewer="Beto", expect=409)  # otro revisor con la versión vieja
    assert out["code"] == "conflicto_de_version"
    assert out["details"]["currentVersion"] == fresh["version"] == 1
    assert c.get(f"{API}/cases/{fresh['caseId']}").json()["reviewer"] == "Ana"  # no se sobrescribió


def test_user_isolation(make_app):
    c = make_app(offline=True)
    tid, case = new_case(c, "calado")
    review(c, case, "en_revision", reviewer="Ana")
    c.post(f"{API}/topics/{tid}/drafts", json={})
    beto = {"X-Umbral-User": "beto"}
    other = c.get(f"{API}/cases/case-{tid}", headers=beto).json()
    assert other["status"] == "nuevo" and other["version"] == 0 and other["drafts"] == []
    assert c.get(f"{API}/topics/{tid}", headers=beto).json()["case"]["persisted"] is False
    # el estado de revisión de Ana no aparece en la agenda de Beto
    item = next(i for i in c.get(f"{API}/topics", params={"limit": 50}, headers=beto).json()["items"] if i["id"] == tid)
    assert item["reviewStatus"] == "nuevo"
    # Beto escribe con versión 0 sin chocar con el caso de Ana
    r = c.patch(f"{API}/cases/case-{tid}/review", headers=beto,
                json={"expectedVersion": 0, "status": "en_revision", "reviewer": "Beto"})
    assert r.status_code == 200
    ana = c.get(f"{API}/cases/case-{tid}").json()
    assert ana["reviewer"] == "Ana"


def test_requires_authentication_in_header_mode(make_app):
    c = make_app()
    r = c.get(f"{API}/topics", headers={"X-Umbral-User": ""})
    assert r.status_code == 401 and r.json()["code"] == "no_autenticado"


def test_restart_keeps_reviews_and_drafts_in_sqlite(fixture_dir, tmp_path):
    def boot():
        s = make_settings(fixture_dir, tmp_path, persistence="sqlite", offline=True)
        svc = Services(s)
        from fastapi.testclient import TestClient

        return TestClient(create_app(s, services=svc), headers={"X-Umbral-User": "ana"}), svc

    c1, svc1 = boot()
    tid, case = new_case(c1, "calado")
    case = c1.post(f"{API}/topics/{tid}/drafts", json={}).json()["case"]
    case = review(c1, case, "en_revision", reviewer="Marta", comment="Empiezo.")
    c1.put(f"{API}/topics/{tid}/impact", json={
        "expectedVersion": case["version"], "level": "medio", "author": "Marta", "reason": "Bajo según editorial",
        "justification": "Afecta el calado pero no detiene el tránsito según el titular.",
        "evidenceIds": [case["currentDraft"]["package"]["claims"][0]["citations"][0]["evidenceId"]],
    })
    svc1.repo.close()
    del c1, svc1  # «reinicio»: nuevo proceso, misma SQLite
    c2, _ = boot()
    again = c2.get(f"{API}/cases/case-{tid}").json()
    assert again["persisted"] and again["status"] == "en_revision" and again["reviewer"] == "Marta"
    assert len(again["drafts"]) == 1 and again["version"] == 3
    assert again["impact"]["level"] == "medio" and again["impact"]["origin"] == "editorial"
    item = next(i for i in c2.get(f"{API}/topics", params={"limit": 50}).json()["items"] if i["id"] == tid)
    assert item["reviewStatus"] == "en_revision"
    # y la concurrencia sigue funcionando tras el reinicio
    assert c2.patch(f"{API}/cases/case-{tid}/review",
                    json={"expectedVersion": 1, "status": "requiere_evidencia", "reviewer": "X", "comment": "c"}).status_code == 409


def test_editorial_impact_changes_score_with_reason_and_version(make_app):
    c = make_app()
    tid = find_topic(c, "ajedrez")
    before = c.get(f"{API}/topics/{tid}").json()
    case = before["case"]
    ev = before["articles"][0]["id"]
    body = {"expectedVersion": 0, "level": "alto", "author": "Marta", "reason": "Interés masivo comprobado",
            "justification": "El torneo tiene alcance de audiencia nacional según el titular citado.", "evidenceIds": [ev]}
    r = c.put(f"{API}/topics/{tid}/impact", json=body)
    assert r.status_code == 200 and r.json()["impact"]["version"] == 1
    after = c.get(f"{API}/topics/{tid}").json()
    i_before = next(x for x in before["score"]["components"] if x["key"] == "I")
    i_after = next(x for x in after["score"]["components"] if x["key"] == "I")
    assert i_after["value"] == 1.0 and i_after["points"] > i_before["points"]
    assert after["impact"]["origin"] == "editorial" and after["impact"]["reason"] == "Interés masivo comprobado"
    assert r.json()["history"][-1]["kind"] == "impacto"
    # evidencia inexistente y conflicto
    bad = c.put(f"{API}/topics/{tid}/impact", json={**body, "expectedVersion": 1, "evidenceIds": ["x"]})
    assert bad.status_code == 422
    stale = c.put(f"{API}/topics/{tid}/impact", json=body)
    assert stale.status_code == 409
    assert case["version"] == 0


def test_export_markdown_for_notion(make_app):
    c = make_app(offline=True)
    tid, case = new_case(c, "sismo")
    case = c.post(f"{API}/topics/{tid}/drafts", json={}).json()["case"]
    review(c, case, "en_revision", reviewer="Marta")
    r = c.get(f"{API}/cases/case-{tid}/export")
    assert r.status_code == 200
    md = r.json()["markdown"]
    for needle in ["# Ficha:", "## Puntaje desglosado", "| R · Relevancia |", "## Contradicciones", "3 heridos", "5 heridos",
                   "## Borrador", "Construido mediante plantilla", "En revisión", "Marta", "scoring-v1", "fixture"]:
        assert needle in md, needle
    raw = c.get(f"{API}/cases/case-{tid}/export", params={"format": "markdown"})
    assert raw.headers["content-type"].startswith("text/markdown") and raw.text == md or raw.text.startswith("# Ficha")
    assert c.get(f"{API}/cases/case-nope/export").status_code == 404
