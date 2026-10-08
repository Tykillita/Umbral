"""Cambios de pesos reales en API, persistencia y versiones inmutables de borrador."""

from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.services import Services

from .conftest import find_topic, make_settings

API = "/api/v1"
BODY = {"expectedVersion": 0, "weights": {"R": 10, "I": 10, "U": 10, "N": 10, "E": 60},
    "author": "Editora", "reason": "Priorizar procedencia corroborada en esta revisión."}


def test_weight_change_applies_to_full_flow_and_preserves_history(make_app):
    client = make_app(offline=True)
    topic = find_topic(client, "calado")
    before = client.get(f"{API}/topics/{topic}").json()
    old = client.post(f"{API}/topics/{topic}/drafts", json={"provider": "plantilla"}).json()["draft"]
    rule = client.put(f"{API}/rules", json=BODY)
    assert rule.status_code == 200, rule.text
    rules = rule.json()
    assert rules["rulesVersion"] == "scoring-v2" and rules["version"] == 1
    assert rules["history"][0]["reason"] == BODY["reason"]
    after = client.get(f"{API}/topics/{topic}").json()
    assert after["score"]["total"] != before["score"]["total"]
    assert after["rulesVersion"] == after["score"]["rulesVersion"] == "scoring-v2"
    assert after["score"]["total"] == round(sum(c["points"] for c in after["score"]["components"]), 2)
    assert all(c["weight"] == BODY["weights"][c["key"]] for c in after["score"]["components"])
    assert "60E" in after["score"]["formula"]
    agenda = client.get(f"{API}/topics").json()
    assert agenda["rulesVersion"] == "scoring-v2"
    query = client.post(f"{API}/queries", json={"question": "¿Qué temas merecen revisión?"}).json()
    assert query["rulesVersion"] == "scoring-v2"
    newer = client.post(f"{API}/topics/{topic}/drafts", json={"provider": "plantilla"}).json()
    assert newer["draft"]["rulesVersion"] == newer["case"]["rulesVersion"] == "scoring-v2"
    assert newer["case"]["drafts"][0] == old
    exported = client.get(f"{API}/cases/case-{topic}/export").json()
    assert exported["rulesVersion"] == "scoring-v2" and "60E" in exported["markdown"]
    assert client.put(f"{API}/rules", json=BODY).status_code == 409
    unchanged = client.get(f"{API}/rules", headers={"X-Umbral-User": "beto"}).json()
    assert unchanged["rulesVersion"] == "scoring-v1" and unchanged["history"] == []
    assert client.get(f"{API}/health").json()["rulesVersion"] == "scoring-v1"


def test_rule_changes_survive_restart_without_overwriting_previous_revision(fixture_dir, tmp_path):
    settings = make_settings(fixture_dir, tmp_path, persistence="sqlite", offline=True)
    service = Services(settings)
    client = TestClient(create_app(settings, services=service), headers={"X-Umbral-User": "ana"})
    assert client.put(f"{API}/rules", json=BODY).status_code == 200
    service.repo.close()
    service2 = Services(settings)
    client2 = TestClient(create_app(settings, services=service2), headers={"X-Umbral-User": "ana"})
    current = client2.get(f"{API}/rules").json()
    assert current["history"][0]["weights"] == BODY["weights"]
    changed = client2.put(f"{API}/rules", json={**BODY, "expectedVersion": 1,
        "weights": {"R": 30, "I": 25, "U": 20, "N": 15, "E": 10}, "reason": "Restaurar ponderación inicial."}).json()
    assert changed["rulesVersion"] == "scoring-v3" and len(changed["history"]) == 2
    assert changed["history"][0] == current["history"][0]
    service2.repo.close()


def test_bad_weights_or_empty_actor_reason_are_rejected(make_app):
    client = make_app()
    bad = [{"R": 100}, {"R": 30, "I": 25, "U": 20, "N": 15, "E": 11},
        {"R": -1, "I": 25, "U": 20, "N": 15, "E": 41},
        {"R": True, "I": 25, "U": 20, "N": 15, "E": 39}]
    for weights in bad:
        assert client.put(f"{API}/rules", json={**BODY, "weights": weights}).status_code == 422
    assert client.put(f"{API}/rules", json={**BODY, "reason": "   "}).status_code == 422
    assert client.put(f"{API}/rules", json={**BODY, "author": " "}).status_code == 422


def test_draft_edits_keep_content_and_ids_of_previous_versions(make_app):
    client = make_app(offline=True)
    topic = find_topic(client, "calado")
    original = client.post(f"{API}/topics/{topic}/drafts", json={"provider": "plantilla"}).json()
    case = original["case"]
    edited = client.put(f"{API}/cases/{case['caseId']}/draft", json={"expectedVersion": case["version"],
        "editor": "Marta", "proposedTitle": "Título propuesto por la editora"})
    assert edited.status_code == 200, edited.text
    out = edited.json()
    assert len(out["drafts"]) == 2 and out["drafts"][0] == original["draft"]
    current = out["currentDraft"]
    assert current["previousDraftId"] == original["draft"]["draftId"]
    assert current["draftId"] != original["draft"]["draftId"] and current["number"] == 2
    assert current["editedBy"] == "Marta"
    assert client.put(f"{API}/cases/{case['caseId']}/draft", json={"expectedVersion": case["version"],
        "editor": "Otro", "proposedTitle": "Sobrescritura"}).status_code == 409
    assert client.get(f"{API}/cases/{case['caseId']}").json()["drafts"][0] == original["draft"]
