"""Contrato HTTP: health, agenda, ficha, OpenAPI al día, arranque con estáticos."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.services import Services

from .conftest import find_topic, make_settings

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[1]


def test_health_reports_version_integrity_and_modes(make_app):
    h = make_app().get(f"{API}/health").json()
    assert h["status"] == "ok" and h["dataMode"] == "fixture" and h["containsFixtures"] and h["provisional"]
    assert re.fullmatch(r"\d{8}-[0-9a-f]{8}", h["snapshotId"])
    assert h["rulesVersion"] == "scoring-v1" and h["integrity"]["manifestVerified"]
    assert h["integrity"]["predictionsHashVerified"] is True
    names = {p["name"] for p in h["providers"]}
    assert {"gemini", "chatgpt", "claude", "recuperado", "plantilla"} <= names


SHA = "0123456789abcdef0123456789abcdef01234567"


def test_health_reports_deploy_commit_when_known(make_app):
    assert make_app(deploy_commit=SHA).get(f"{API}/health").json()["deployCommit"] == SHA
    assert make_app().get(f"{API}/health").json()["deployCommit"] is None


def test_deploy_commit_comes_from_environment_and_must_be_hexadecimal(monkeypatch):
    from umbral_api.config import _deploy_commit

    monkeypatch.delenv("UMBRAL_DEPLOY_COMMIT", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", SHA.upper())
    assert _deploy_commit() == SHA
    monkeypatch.setenv("UMBRAL_DEPLOY_COMMIT", "abcdef1")  # tiene prioridad sobre el valor de Render
    assert _deploy_commit() == "abcdef1"
    monkeypatch.setenv("UMBRAL_DEPLOY_COMMIT", "not-a-sha; rm -rf /")
    assert _deploy_commit() is None


def _public_client(fixture_dir, **kwargs):
    settings = make_settings(fixture_dir, auth_mode="public", persistence="none", local_mode=False, **kwargs)
    return TestClient(create_app(settings, services=Services(settings)))


def _preflight(client, origin):
    return client.options(f"{API}/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})


def test_cors_preview_channels_are_limited_to_the_configured_firebase_project(fixture_dir):
    client = _public_client(fixture_dir, cors_origins=("https://site-umbral.web.app",), cors_preview_project="site-umbral")
    allowed = ["https://site-umbral.web.app", "https://site-umbral--pr-12-a1b2c3d4.web.app",
               "https://site-umbral--pr-7-zz9.firebaseapp.com"]
    for origin in allowed:
        assert _preflight(client, origin).headers.get("access-control-allow-origin") == origin
    denied = ["https://otro-proyecto--pr-12-a1b2c3d4.web.app", "https://site-umbral--feature-x-a1b2.web.app",
              "https://site-umbral--pr-12-a1b2c3d4.web.app.evil.example", "http://site-umbral--pr-12-a1b2.web.app",
              "http://localhost:4321"]
    for origin in denied:
        assert "access-control-allow-origin" not in _preflight(client, origin).headers


def test_cors_without_preview_project_keeps_only_listed_origins(fixture_dir):
    client = _public_client(fixture_dir, cors_origins=("https://site-umbral.web.app",))
    assert "access-control-allow-origin" not in _preflight(client, "https://site-umbral--pr-1-abc.web.app").headers


def test_health_degraded_when_integrity_fails(fixture_dir, tmp_path):
    import shutil

    d = tmp_path / "s"
    shutil.copytree(fixture_dir, d)
    (d / "articles.jsonl").write_text((d / "articles.jsonl").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    s = make_settings(d)
    c = TestClient(create_app(s, services=Services(s)), headers={"X-Umbral-User": "a"})
    h = c.get(f"{API}/health").json()
    assert h["status"] == "degradado" and h["integrity"]["errors"]


def test_topics_default_is_top5_with_components_and_camel_case(make_app):
    r = make_app().get(f"{API}/topics").json()
    assert len(r["items"]) == 5 and r["total"] >= 10
    assert {"snapshotId", "rulesVersion", "dataMode", "cutoffUtc", "facets"} <= set(r)
    it = r["items"][0]
    assert [c["key"] for c in it["scoreComponents"]] == ["R", "I", "U", "N", "E"]
    assert {"evidenceStatus", "reviewStatus", "needsInvestigation", "headlineOnly", "isRecirculation"} <= set(it)
    scores = [i["score"] for i in r["items"]]
    assert scores == sorted(scores, reverse=True)


def test_topics_filters_and_search(make_app):
    c = make_app()
    ev = c.get(f"{API}/topics", params={"evidence": "insuficiente", "limit": 50}).json()
    assert ev["items"] and all(i["evidenceStatus"] == "insuficiente" for i in ev["items"])
    cat = c.get(f"{API}/topics", params={"category": "eventos_naturales", "limit": 50}).json()
    assert {i["category"] for i in cat["items"]} == {"eventos_naturales"}
    q = c.get(f"{API}/topics", params={"q": "inflacion panama"}).json()
    assert q["items"][0]["title"].lower().startswith("la inflación")
    nocomp = c.get(f"{API}/topics", params={"includeComponents": "false"}).json()["items"][0]
    assert nocomp["scoreComponents"] == []


def test_tvn_gap_filter_requires_independent_sources_and_composes(make_app):
    c = make_app()
    expected = {
        base.id for base in c.svc.bases.values()
        if base.independent >= 2 and not any(article.is_tvn for article in base.articles)
    }
    response = c.get(f"{API}/topics", params={"limit": 100, "scope": "all", "tvnGap": "true"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert {item["id"] for item in data["items"]} == expected
    assert data["applied"]["tvnGap"] is True
    if expected:
        category = c.svc.bases[next(iter(expected))].category.value
        combined = c.get(f"{API}/topics", params={
            "limit": 100, "scope": "all", "tvnGap": "true", "category": category,
        }).json()
        assert all(item["id"] in expected and item["category"] == category for item in combined["items"])


def test_t03_recirculated_old_news_shows_original_date_and_zero_novelty(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'puente')}").json()
    assert d["summary"]["isRecirculation"] and d["summary"]["firstPublishedAt"].startswith("2026-03-12")
    n = next(x for x in d["score"]["components"] if x["key"] == "N")
    assert n["value"] == 0 and "ecirculación" in n["justification"]
    assert any(g["code"] == "recirculacion" for g in d["evidence"]["gaps"])


def test_t08_high_priority_exposes_components_rules_and_limits(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'darién')}").json()
    assert d["score"]["band"] == "alto" and d["score"]["total"] >= 70
    for comp in d["score"]["components"]:
        assert comp["rule"] and comp["justification"]
    assert any(comp["limits"] for comp in d["score"]["components"])
    assert "no habilita publicación" in d["score"]["disclaimer"]
    assert d["summary"]["needsInvestigation"]


def test_t04_official_context_keeps_year_unit_and_nulls(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'inflación')}").json()
    pts = d["officialContext"]["indicators"]
    valid = next(p for p in pts if not p["isMissing"])
    assert valid["year"] == 2023 and valid["unit"] == "% anual" and valid["value"] == 1.5
    assert "no es una medición de hoy" in valid["note"]
    assert any(p["isMissing"] and p["value"] is None and p["year"] == 2024 for p in pts)  # el nulo no se rellena con 0
    assert any("hoy" in lim for lim in d["officialContext"]["limitations"])
    assert any(cl["type"] == "hecho" for cl in d["supportedClaims"])


def test_no_forced_official_relation(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'ajedrez')}").json()
    assert d["officialContext"]["indicators"] == [] and "no se fuerza" in d["officialContext"]["relationRationale"]


def test_t01_null_publication_date_means_zero_urgency_with_limit(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'costa rica')}").json()
    u = next(x for x in d["score"]["components"] if x["key"] == "U")
    assert u["value"] == 0 and any("desconocida" in lim for lim in u["limits"])
    assert d["articles"][0]["publishedAt"] is None and d["articles"][0]["detectedAt"]
    assert any(g["code"] == "fecha_publicacion_desconocida" for g in d["evidence"]["gaps"])


def test_unknown_topic_and_case_404(make_app):
    c = make_app()
    assert c.get(f"{API}/topics/nope").status_code == 404
    assert c.get(f"{API}/cases/nope").status_code == 404
    assert c.post(f"{API}/topics/nope/drafts", json={}).json()["code"] == "no_encontrado"


def test_rules_and_snapshot_endpoints(make_app):
    c = make_app()
    rules = c.get(f"{API}/rules").json()
    assert rules["weights"] == {"R": 30, "I": 25, "U": 20, "N": 15, "E": 10} and rules["changelog"]
    s = c.get(f"{API}/snapshot").json()
    assert s["manifest"]["snapshotId"] == s["snapshotId"] and s["qualityReport"] and s["sources"]
    assert s["metrics"] is None  # sin ejecución real de métricas: no se inventan


def test_openapi_json_is_up_to_date():
    from umbral_api.config import Settings

    app = create_app(Settings(), build_services=False)
    fresh = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert (ROOT / "openapi.json").read_text(encoding="utf-8") == fresh, "ejecuta scripts/export_openapi.py"
    paths = set(app.openapi()["paths"])
    for p in ("/health", "/topics", "/topics/{topic_id}", "/queries", "/topics/{topic_id}/drafts",
              "/cases/{case_id}/review", "/cases/{case_id}/export"):
        assert API + p in paths


def test_input_validation_matches_declared_error_contract(make_app):
    client = make_app()
    response = client.put("/api/v1/rules", json={"expectedVersion": 0, "weights": {"R": 100},
        "author": "QA", "reason": "Entrada inválida para comprobar el contrato."})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == "entrada_invalida" and body["details"]["fields"]


def test_validation_errors_never_echo_the_rejected_input_value(make_app):
    client = make_app()
    private_value = "synthetic-sensitive-placeholder"
    response = client.get("/api/v1/topics", params={"limit": private_value})
    assert response.status_code == 422
    assert private_value not in response.text
    assert response.json()["details"]["fields"][0]["field"] == "query.limit"


def test_serves_astro_build_when_present(fixture_dir, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Umbral web</body></html>", encoding="utf-8")
    s = make_settings(fixture_dir, web_dist=dist)
    c = TestClient(create_app(s, services=Services(s)), headers={"X-Umbral-User": "a"})
    assert "Umbral web" in c.get("/").text
    assert c.get(f"{API}/health").status_code == 200  # la API sigue accesible


def test_agenda_excludes_out_of_scope_by_default_and_reports_count(make_app):
    c = make_app()
    default = c.get(f"{API}/topics", params={"limit": 100}).json()
    everything = c.get(f"{API}/topics", params={"limit": 100, "scope": "all"}).json()
    assert default["scope"] == "in_scope" and everything["scope"] == "all"
    assert all(i["category"] != "indeterminado" and not i["outOfScope"] for i in default["items"])
    hidden = [i for i in everything["items"] if i["category"] == "indeterminado"]
    assert hidden and all(i["outOfScope"] for i in hidden)
    assert default["outOfScopeCount"] == len(hidden) and everything["outOfScopeCount"] == 0
    assert default["total"] + default["outOfScopeCount"] == everything["total"]
    # el ranking y el desempate de los visibles no cambian
    visible_in_all = [i["id"] for i in everything["items"] if i["category"] != "indeterminado"]
    assert [i["id"] for i in default["items"]] == visible_in_all
    assert [i["rank"] for i in default["items"]] == list(range(1, len(default["items"]) + 1))


def test_explicit_indeterminate_category_filter_shows_them(make_app):
    items = make_app().get(f"{API}/topics", params={"category": "indeterminado", "limit": 50}).json()["items"]
    assert items and all(i["category"] == "indeterminado" for i in items)


def test_out_of_scope_topic_still_reachable_by_id_query_and_search(make_app):
    c = make_app()
    tid = find_topic(c, "ajedrez")
    d = c.get(f"{API}/topics/{tid}").json()
    assert d["summary"]["outOfScope"] and any("alcance temático" in w for w in d["warnings"])
    assert d["score"]["total"] >= 0 and d["score"]["components"]  # trazabilidad intacta
    q = c.post(f"{API}/queries", json={"question": "torneo de ajedrez en Europa"}).json()
    assert q["answerStatus"] in {"respondida", "parcial"} and tid in q["relatedTopicIds"]
    assert not c.get(f"{API}/topics", params={"q": "ajedrez"}).json()["items"]
    assert c.get(f"{API}/topics", params={"q": "ajedrez", "scope": "all"}).json()["items"][0]["id"] == tid


def test_agenda_query_uses_in_scope_topics_only(make_app):
    c = make_app()
    r = c.post(f"{API}/queries", json={"question": "¿Qué cinco temas merecen revisión para la agenda de Panamá y por qué?"}).json()
    assert len(r["relatedTopicIds"]) == 5
    hidden = {i["id"] for i in c.get(f"{API}/topics", params={"limit": 100, "scope": "all"}).json()["items"] if i["category"] == "indeterminado"}
    assert not hidden & set(r["relatedTopicIds"])


def test_automatic_impact_does_not_credit_category_alone(make_app):
    c = make_app()
    # «Alerta por lluvias en Darién»: eventos_naturales con una sola procedencia y sin serie oficial
    d = c.get(f"{API}/topics/{find_topic(c, 'darién')}").json()
    assert d["impact"]["origin"] == "propuesta_automatica"
    assert "alcance público amplio" not in d["impact"]["justification"]
    assert "no suma por sí sola" in d["impact"]["justification"]
    # «Calado»: logistica_canal con 2 procedencias independientes => la categoría sí cuenta, con su corroboración
    d2 = c.get(f"{API}/topics/{find_topic(c, 'calado')}").json()
    assert "con evidencia que lo corrobora" in d2["impact"]["justification"]


def test_relevance_reason_explains_rule_headline_and_classifier_evidence(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'calado')}").json()
    r = next(x for x in d["score"]["components"] if x["key"] == "R")
    for needle in ("Regla aplicada", "Panamá: 1", "Titular que la justifica", "«"):
        assert needle in r["justification"], needle
    assert any("no se edita" in lim.lower() for lim in r["limits"])
    assert d["summary"]["relevanceReason"] == r["justification"]
    card = c.get(f"{API}/topics", params={"limit": 3, "includeComponents": "false"}).json()["items"][0]
    assert card["scoreComponents"] == [] and "Regla aplicada" in card["relevanceReason"]


def test_relevance_reason_flags_weak_classifier_evidence(fixture_dir, tmp_path):
    import json
    import shutil

    from fastapi.testclient import TestClient

    from umbral_api.app import create_app
    from umbral_api.services import Services

    from .conftest import make_settings

    d = tmp_path / "weak"
    shutil.copytree(fixture_dir, d)
    rows = [json.loads(x) for x in (d / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    for p in rows:
        p["geoEvidence"] = ["laya:panama=0.512"]
    (d / "predictions.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in rows), encoding="utf-8")
    s = make_settings(d)
    c = TestClient(create_app(s, services=Services(s)), headers={"X-Umbral-User": "a"})
    det = c.get(f"{API}/topics/{find_topic(c, 'calado')}").json()
    r = next(x for x in det["score"]["components"] if x["key"] == "R")
    assert "laya:panama=0.512" in r["justification"]
    assert any("Evidencia débil" in lim and "0.51" in lim for lim in r["limits"])


def test_editorial_impact_requires_reason_justification_evidence_and_leaves_version_trail(make_app):
    c = make_app()
    tid = find_topic(c, "calado")
    ev = c.get(f"{API}/topics/{tid}").json()["articles"][0]["id"]
    ok = {"expectedVersion": 0, "level": "medio", "author": "Marta", "reason": "Alcance acotado",
          "justification": "El titular describe una restricción operativa sin paro total.", "evidenceIds": [ev]}
    for missing in ("reason", "justification", "evidenceIds", "author", "expectedVersion"):
        body = {k: v for k, v in ok.items() if k != missing}
        assert c.put(f"{API}/topics/{tid}/impact", json=body).status_code == 422, missing
    assert c.put(f"{API}/topics/{tid}/impact", json={**ok, "reason": "   "}).status_code == 422
    assert c.put(f"{API}/topics/{tid}/impact", json={**ok, "justification": "corta"}).status_code == 422
    assert c.put(f"{API}/topics/{tid}/impact", json={**ok, "evidenceIds": []}).status_code == 422
    r1 = c.put(f"{API}/topics/{tid}/impact", json=ok)
    assert r1.status_code == 200 and r1.json()["version"] == 1 and r1.json()["impact"]["version"] == 1
    r2 = c.put(f"{API}/topics/{tid}/impact", json={**ok, "expectedVersion": 1, "level": "alto", "reason": "Nueva evidencia"})
    assert r2.json()["version"] == 2 and r2.json()["impact"]["version"] == 2
    hist = [e for e in r2.json()["history"] if e["kind"] == "impacto"]
    assert [e["version"] for e in hist] == [1, 2] and "Nueva evidencia" in hist[1]["comment"] and hist[1]["actor"] == "Marta"
    assert c.put(f"{API}/topics/{tid}/impact", json=ok).status_code == 409
