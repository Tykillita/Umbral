"""Copia de trabajo compartida con web y conservación de evidencia al renovar datos."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.services import Services

from .conftest import find_topic, make_settings
from .test_snapshot_feed import snapshot_for_transport_test

API = "/api/v1"


def local_client(fixture_dir, tmp_path, *, sqlite=False, relay=None):
    settings = replace(make_settings(fixture_dir, tmp_path), auth_mode="local", persistence="sqlite" if sqlite else "memory",
                       public_api_url=relay)
    svc = Services(settings)
    return TestClient(create_app(settings, services=svc)), svc


def create_case(client, needle="calado"):
    tid = find_topic(client, needle)
    response = client.post(API + f"/topics/{tid}/drafts", json={"provider": "plantilla"})
    assert response.status_code == 200, response.text
    return response.json()["case"]


@pytest.mark.parametrize("sqlite", [False, True])
def test_workspace_roundtrip_and_identical_import_are_lossless(fixture_dir, tmp_path, sqlite):
    original, original_svc = local_client(fixture_dir, tmp_path / "original", sqlite=sqlite)
    case = create_case(original)
    archive = original.get(API + "/workspace/export").json()
    assert archive["format"] == "umbral-workspace" and archive["version"] == 1
    assert archive["cases"][0]["case"]["drafts"] == case["drafts"]
    assert archive["cases"][0]["detail"]["articles"]
    fresh, fresh_svc = local_client(fixture_dir, tmp_path / "fresh", sqlite=sqlite)
    response = fresh.post(API + "/workspace/import", json=archive)
    assert response.status_code == 200, response.text
    assert response.json() == {"imported": 1, "identical": 0}
    assert fresh.get(API + "/cases/" + case["caseId"]).json() == case
    repeat = fresh.post(API + "/workspace/import", json=archive)
    assert repeat.status_code == 200, repeat.text
    assert repeat.json() == {"imported": 0, "identical": 1}
    original_svc.repo.close()
    fresh_svc.repo.close()


@pytest.mark.parametrize("sqlite", [False, True])
def test_workspace_conflict_cancels_whole_import(fixture_dir, tmp_path, sqlite):
    source, source_svc = local_client(fixture_dir, tmp_path / "source", sqlite=sqlite)
    first = create_case(source)
    target, target_svc = local_client(fixture_dir, tmp_path / "target", sqlite=sqlite)
    assert target.post(API + "/workspace/import", json=source.get(API + "/workspace/export").json()).status_code == 200
    second = create_case(source, "inflación")
    source.patch(API + "/cases/" + first["caseId"] + "/review",
                 json={"expectedVersion": 1, "status": "en_revision", "reviewer": "Editor"})
    archive = source.get(API + "/workspace/export").json()
    archive["cases"].reverse()
    response = target.post(API + "/workspace/import", json=archive)
    assert response.status_code == 409
    assert target.get(API + "/cases/" + second["caseId"]).json()["persisted"] is False
    assert target.get(API + "/cases/" + first["caseId"]).json()["version"] == 1
    source_svc.repo.close()
    target_svc.repo.close()


def test_workspace_rejects_history_and_evidence_mismatch(fixture_dir, tmp_path):
    source, _ = local_client(fixture_dir, tmp_path)
    create_case(source)
    archive = source.get(API + "/workspace/export").json()
    archive["cases"][0]["case"]["version"] = 500
    fresh, svc = local_client(fixture_dir, tmp_path / "fresh")
    assert fresh.post(API + "/workspace/import", json=archive).status_code == 422
    assert not svc.repo.list_cases("local")
    archive["cases"][0]["case"]["version"] = 1
    archive["cases"][0]["detail"]["snapshotId"] = "other"
    assert fresh.post(API + "/workspace/import", json=archive).status_code == 422


def test_workspace_roundtrip_preserves_full_impact_assignments(fixture_dir, tmp_path):
    source, source_svc = local_client(fixture_dir, tmp_path / "source")
    tid = find_topic(source, "calado")
    evidence_id = source.get(API + "/topics/" + tid).json()["articles"][0]["id"]
    for index, level in enumerate(("medio", "alto")):
        response = source.put(API + "/topics/" + tid + "/impact", json={
            "expectedVersion": index, "level": level, "evidenceIds": [evidence_id], "author": "Editor",
            "reason": f"Motivo de impacto {index}", "justification": f"Justificación editorial con citas originales, versión {index}",
        })
        assert response.status_code == 200, response.text
    archive = source.get(API + "/workspace/export").json()
    assert [item["version"] for item in archive["cases"][0]["impactHistory"]] == [1, 2]
    target, target_svc = local_client(fixture_dir, tmp_path / "target")
    imported = target.post(API + "/workspace/import", json=archive)
    assert imported.status_code == 200, imported.text
    assert target.get(API + "/workspace/export").json()["cases"][0]["impactHistory"] == archive["cases"][0]["impactHistory"]
    source_svc.repo.close()
    target_svc.repo.close()


def test_case_can_be_edited_reviewed_and_exported_after_snapshot_swap(fixture_dir, tmp_path):
    client, svc = local_client(fixture_dir, tmp_path)
    case = create_case(client)
    original = client.get(API + "/topics/" + case["topicId"]).json()
    svc.activate_snapshot(snapshot_for_transport_test(fixture_dir, tmp_path / "updated", change="Laboratorio"))
    assert case["topicId"] not in svc.bases
    saved = client.get(API + "/cases/" + case["caseId"])
    assert saved.status_code == 200 and saved.json() == case
    detail = client.get(API + "/topics/" + case["topicId"])
    assert detail.status_code == 200 and detail.json()["articles"] == original["articles"]
    assert detail.json()["snapshotId"] == original["snapshotId"] != svc.corpus.snapshot_id
    edited = client.put(API + "/cases/" + case["caseId"] + "/draft",
                        json={"expectedVersion": 1, "editor": "Editor", "proposedTitle": "Título revisado"})
    assert edited.status_code == 200 and edited.json()["currentDraft"]["validation"]["ok"]
    reviewed = client.patch(API + "/cases/" + case["caseId"] + "/review",
                            json={"expectedVersion": 2, "status": "en_revision", "reviewer": "Editor"})
    assert reviewed.status_code == 200 and reviewed.json()["version"] == 3
    assert client.get(API + "/cases/" + case["caseId"] + "/export").status_code == 200
    assert client.get(API + "/workspace/export").json()["cases"][0]["detail"]["snapshotId"] == original["snapshotId"]


def test_public_archived_topic_recomputes_weights_and_retains_evidence(fixture_dir, tmp_path):
    client, svc = local_client(fixture_dir, tmp_path)
    case = create_case(client)
    original = client.get(API + "/topics/" + case["topicId"]).json()
    svc.activate_snapshot(snapshot_for_transport_test(fixture_dir, tmp_path / "updated", change="Laboratorio"))
    evidence = {"snapshotId": original["snapshotId"], "topicId": case["topicId"], "articles": original["articles"],
                "officialContext": original["officialContext"], "cutoffUtc": original["cutoffUtc"]}
    ctx = {"snapshotId": original["snapshotId"], "weights": {"R": 100, "I": 0, "U": 0, "N": 0, "E": 0},
           "topicOverrides": [{"topicId": case["topicId"], "status": "en_revision"}]}
    result = client.post(API + "/public/topics/" + case["topicId"], json={"context": ctx, "evidence": evidence})
    assert result.status_code == 200, result.text
    assert result.json()["articles"] == original["articles"]
    assert result.json()["score"]["components"][0]["weight"] == 100
    assert result.json()["summary"]["reviewStatus"] == "en_revision"
    assert result.json()["case"]["persisted"] is False


def test_archived_impact_is_checked_against_original_membership(fixture_dir, tmp_path):
    from umbral_api.services import build_snapshot_state

    client, svc = local_client(fixture_dir, tmp_path)
    tid = find_topic(client, "calado")
    original = client.get(API + "/topics/" + tid).json()
    removed = original["impact"]["evidenceIds"][0]
    cluster = dict(svc.corpus.clusters[tid])
    cluster["memberArticleIds"] = [aid for aid in cluster["memberArticleIds"] if aid != removed]
    assert cluster["memberArticleIds"]
    cluster["representativeArticleId"] = cluster["memberArticleIds"][0]
    clusters = dict(svc.corpus.clusters) | {tid: cluster}
    corpus = replace(svc.corpus, snapshot_id="20261008-aaaaaaaa", clusters=clusters,
                     articles={aid: article for aid, article in svc.corpus.articles.items() if aid != removed})
    svc._state = build_snapshot_state(corpus)
    evidence = {"snapshotId": original["snapshotId"], "topicId": tid, "articles": original["articles"],
                "officialContext": original["officialContext"], "cutoffUtc": original["cutoffUtc"]}
    ctx = {"snapshotId": original["snapshotId"], "topicOverrides": [{"topicId": tid, "impact": original["impact"]}]}
    response = client.post(API + "/public/topics/" + tid, json={"context": ctx, "evidence": evidence})
    assert response.status_code == 200, response.text
    assert removed in {a["id"] for a in response.json()["articles"]}


def test_desktop_relay_retains_honest_template_mode(fixture_dir, tmp_path, monkeypatch):
    import httpx

    offline, _ = local_client(fixture_dir, tmp_path)
    tid = find_topic(offline, "calado")
    result = offline.post(API + f"/topics/{tid}/drafts", json={"provider": "plantilla"}).json()
    detail = offline.get(API + "/topics/" + tid).json()
    public = {"draft": result["draft"], "notices": ["Cuota pública: plantilla"], "evidence": {
        "snapshotId": detail["snapshotId"], "topicId": tid, "articles": detail["articles"], "officialContext": detail["officialContext"]}}
    original_client = httpx.Client
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=public)

    online, _ = local_client(fixture_dir, tmp_path / "online", relay="https://public.example")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    response = online.post(API + f"/topics/{tid}/drafts", json={"provider": "auto"})
    assert response.status_code == 200, response.text
    assert response.json()["draft"]["generationMode"] == "plantilla"
    assert response.json()["case"]["persisted"] is True
    assert requests[0].url == "https://public.example/api/v1/public/drafts"
