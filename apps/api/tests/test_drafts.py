"""Borradores: plantilla, Gemini simulado, cuota, desconexión, offline, recuperado, citas inválidas (T09, T07)."""

from __future__ import annotations

import pytest

from umbral_api.drafts import build_pack, validate_claims
from umbral_api.models import Citation, Claim, ClaimType

from .conftest import find_topic

API = "/api/v1"


def draft(c, tid, provider="auto", status=200):
    r = c.post(f"{API}/topics/{tid}/drafts", json={"provider": provider})
    assert r.status_code == status, r.text
    return r.json()


def test_template_draft_is_valid_cited_and_typed(make_app):
    c = make_app(offline=True)
    d = draft(c, find_topic(c, "calado"))["draft"]
    assert d["generationMode"] == "plantilla" and "plantilla" in d["generationLabel"].lower()
    assert d["fallbackReason"] == "modo_sin_conexion"
    v = d["validation"]
    assert v["ok"] and not [i for i in v["issues"] if i["severity"] == "error"]
    p = d["package"]
    assert "titular/metadatos" in p["brief"] and p["headlineOnly"] and p["headlineOnlyNotice"]
    assert v["wordCounts"]["brief"] <= 250 and v["wordCounts"]["socialCopy"] <= 80
    assert 45 <= v["scriptSecondsEstimate"] <= 60
    assert len(p["researchQuestions"]) == 3 and p["pendingVerifications"]
    types = {cl["type"] for cl in p["claims"]}
    assert {"declaracion", "hecho", "hipotesis"} <= types  # distingue hechos/declaraciones/hipótesis
    assert "inferencia" in types  # dos procedencias independientes
    for cl in p["claims"]:
        if cl["type"] != "hipotesis":
            assert cl["citations"], cl
    assert v["citationCoverage"] >= 0.75  # la hipótesis no cita por definición


def test_template_is_valid_for_every_topic(make_app):
    c = make_app(offline=True)
    items = c.get(f"{API}/topics", params={"limit": 100}).json()["items"]
    assert len(items) >= 10
    for it in items:
        d = draft(c, it["id"])["draft"]
        assert d["validation"]["ok"], (it["title"], d["validation"]["issues"])
        assert d["package"]["headlineOnlyNotice"]


def test_gemini_success_is_labelled_as_model_and_counts_quota(make_app):
    c = make_app("ok")
    tid = find_topic(c, "calado")
    r = draft(c, tid)
    d = r["draft"]
    assert d["generationMode"] == "modelo" and d["provider"] == "gemini" and d["model"] == "fake-model"
    assert d["fallbackReason"] is None and d["validation"]["ok"]
    assert "Basado únicamente en titular/metadatos" in d["package"]["brief"]  # el servidor lo impone
    assert c.fake.calls == 1
    assert r["case"]["version"] == 1 and r["case"]["currentDraft"]["draftId"] == d["draftId"]


def test_t07_prompt_excludes_malicious_source_text(make_app):
    c = make_app("ok")
    draft(c, find_topic(c, "tarifa"))
    prompt = c.fake.last_user
    assert "Ignora todas las instrucciones" not in prompt and "clave de API" not in prompt
    assert "dato no confiable" in prompt


def test_t07_malicious_source_is_not_citable(make_app):
    c = make_app()
    tid = find_topic(c, "tarifa")
    pack = build_pack(c.svc.bases[tid])
    bad_id = next(iter(pack.excluded))
    claims = [Claim(id="c1", type=ClaimType.hecho, text="x", citations=[Citation(evidence_id=bad_id, field="title")])]
    kept, issues = validate_claims(claims, pack)
    assert not kept and issues[0].code == "fuente_no_confiable"
    d = c.get(f"{API}/topics/{tid}").json()
    assert any(a["suspiciousInstructions"] for a in d["articles"]) and d["summary"]["hasSuspiciousSource"]


def test_nonexistent_citation_is_rejected_and_falls_back_to_template(make_app):
    c = make_app("bad_citation")
    r = draft(c, find_topic(c, "calado"))
    d = r["draft"]
    assert d["generationMode"] == "plantilla" and d["fallbackReason"] == "validacion_fallida"
    assert "art_inexistente" not in str(d["package"])
    assert any("validación" in n for n in r["notices"])


def test_validate_claims_checks_ids_fields_passages_and_numbers(make_app):
    c = make_app()
    tid = find_topic(c, "inflación")
    pack = build_pack(c.svc.bases[tid])
    art = next(i for i, f in pack.items.items() if "title" in f)
    ind = next(i for i, f in pack.items.items() if "value" in f)
    mk = lambda cid, cites, text="texto": Claim(id=cid, type=ClaimType.hecho, text=text, citations=cites)  # noqa: E731
    claims = [
        mk("c1", [Citation(evidence_id="no_existe", field="title")]),
        mk("c2", [Citation(evidence_id=art, field="campo_raro")]),
        mk("c3", [Citation(evidence_id=art, field="title", passage="texto que no está en el titular")]),
        mk("c4", [Citation(evidence_id=ind, field="value")], "La inflación fue 99,9 %."),
        mk("c5", [Citation(evidence_id=ind, field="value")], "La inflación fue 1.5 %."),
        mk("c6", []),
    ]
    kept, issues = validate_claims(claims, pack)
    codes = {i.claim_id: i.code for i in issues}
    assert codes == {
        "c1": "cita_inexistente", "c2": "campo_inexistente", "c3": "pasaje_no_encontrado",
        "c4": "cifra_no_respaldada", "c6": "sin_cita",
    }
    assert [k.id for k in kept] == ["c5"]


def test_quota_exhausted_falls_back_without_paid_provider(make_app):
    c = make_app("quota")
    r = draft(c, find_topic(c, "calado"))
    d = r["draft"]
    assert d["fallbackReason"] == "cuota_agotada" and d["generationMode"] == "plantilla"
    assert c.fake.calls == 1  # un intento; no hay segundo proveedor
    assert all(not p.get("calls") for p in [{}])  # (ChatGPT/Claude nunca se usan en auto)


def test_per_user_limit_is_enforced_and_isolated(make_app):
    c = make_app("ok", gemini_calls_per_user_day=1)
    tid = find_topic(c, "calado")
    assert draft(c, tid)["draft"]["generationMode"] == "modelo"
    second = draft(c, tid)["draft"]
    assert second["fallbackReason"] == "limite_por_usuario"
    assert second["generationMode"] == "recuperado"  # reutiliza el borrador del modelo ya guardado
    other = c.post(f"{API}/topics/{tid}/drafts", json={}, headers={"X-Umbral-User": "beto"}).json()["draft"]
    assert other["generationMode"] == "modelo"  # el límite es por usuario


def test_provider_disconnected_falls_back(make_app):
    c = make_app("no_key")
    d = draft(c, find_topic(c, "calado"))["draft"]
    assert d["generationMode"] == "plantilla" and d["fallbackReason"] == "sin_credenciales"
    assert c.fake.calls == 0


def test_provider_down_falls_back(make_app):
    c = make_app("down")
    d = draft(c, find_topic(c, "calado"))["draft"]
    assert d["fallbackReason"] == "proveedor_no_disponible" and d["generationMode"] == "plantilla"


def test_offline_blocks_external_calls_even_when_provider_works(make_app):
    c = make_app("ok", offline=True)
    d = draft(c, find_topic(c, "calado"))["draft"]
    assert c.fake.calls == 0
    assert d["fallbackReason"] == "modo_sin_conexion" and d["generationMode"] == "plantilla"
    h = c.get(f"{API}/health").json()
    assert h["offline"] is True and not any(p["available"] for p in h["providers"] if p["external"])


def test_recovered_draft_from_previous_run_when_provider_fails(make_app):
    c = make_app("ok")
    tid = find_topic(c, "calado")
    first = draft(c, tid)["draft"]
    c.fake.behavior = "quota"
    r = draft(c, tid)
    d = r["draft"]
    assert d["generationMode"] == "recuperado" and "recuperado" in d["generationLabel"].lower()
    assert d["recoveredFromDraftId"] == first["draftId"] and d["fallbackReason"] == "cuota_agotada"
    assert d["model"] == "fake-model" and d["number"] == 2
    assert d["package"]["proposedTitle"] == first["package"]["proposedTitle"]


def test_explicit_recovered_without_previous_uses_template(make_app):
    c = make_app("ok")
    d = draft(c, find_topic(c, "calado"), provider="recuperado")["draft"]
    assert d["generationMode"] == "plantilla" and c.fake.calls == 0


def test_personal_adapters_are_localhost_only(make_app):
    c = make_app()
    # Servicio local válido, pero solicitud que llega desde una dirección remota.
    from fastapi.testclient import TestClient

    c = TestClient(c.app, headers={"X-Umbral-User": "ana"}, client=("198.51.100.20", 1234))
    # Auth de desarrollo también rechaza clientes remotos; verificamos la guarda del servicio por separado.
    from umbral_api.errors import Forbidden
    from umbral_api.models import DraftRequest

    svc = c.app.state.services
    tid = next(iter(svc.bases))
    for p in ("chatgpt", "claude"):
        with pytest.raises(Forbidden):
            svc.create_draft("ana", tid, DraftRequest(provider=p), client_is_local=False)
    assert c.get(f"{API}/topics").status_code == 401


def test_personal_adapters_rejected_in_web_settings(fixture_dir):
    from umbral_api.errors import Forbidden
    from umbral_api.models import DraftRequest
    from umbral_api.services import Services
    from umbral_api.storage import MemoryRepository

    from .conftest import make_settings

    # Repositorio de prueba inyectado: no implica una prueba de Firestore real.
    svc = Services(make_settings(fixture_dir, local_mode=False, auth_mode="firebase", persistence="firestore", firestore_project="site-umbral"), repo=MemoryRepository())
    tid = next(iter(svc.bases))
    for p in ("chatgpt", "claude"):
        with pytest.raises(Forbidden):
            svc.create_draft("ana", tid, DraftRequest(provider=p), client_is_local=True)


def test_personal_adapter_not_connected_falls_back_locally(make_app):
    c = make_app(local_mode=True, chatgpt_token_file=None)
    d = draft(c, find_topic(c, "calado"), provider="chatgpt")["draft"]
    assert d["generationMode"] == "plantilla" and d["fallbackReason"] == "proveedor_no_conectado"


def test_draft_edit_revalidates_and_requires_version(make_app):
    c = make_app(offline=True)
    tid = find_topic(c, "calado")
    case = draft(c, tid)["case"]
    cid = case["caseId"]
    long_copy = " ".join(["palabra"] * 120)
    r = c.put(f"{API}/cases/{cid}/draft", json={"expectedVersion": case["version"], "editor": "Luis", "socialCopy": long_copy})
    assert r.status_code == 200
    cur = r.json()["currentDraft"]
    assert cur["editedBy"] == "Luis" and not cur["validation"]["ok"]
    assert any(i["code"] == "copy_excede_limite" for i in cur["validation"]["issues"])
    stale = c.put(f"{API}/cases/{cid}/draft", json={"expectedVersion": case["version"], "editor": "Luis", "socialCopy": "ok"})
    assert stale.status_code == 409


@pytest.mark.parametrize("field", ["brief", "script"])
def test_word_limits_are_reported(make_app, field):
    c = make_app(offline=True)
    case = draft(c, find_topic(c, "calado"))["case"]
    r = c.put(f"{API}/cases/{case['caseId']}/draft", json={"expectedVersion": case["version"], "editor": "Ana", field: "uno dos tres"})
    codes = {i["code"] for i in r.json()["currentDraft"]["validation"]["issues"]}
    assert ("guion_fuera_de_rango" if field == "script" else "brief_sin_marcadores") in codes


def test_factual_citation_coverage_metric(make_app):
    c = make_app(offline=True)
    v = draft(c, find_topic(c, "calado"))["draft"]["validation"]
    assert v["factualCitationCoverage"] == 1.0  # hecho + declaración con cita válida
    assert v["citationCoverage"] <= 1.0
    c2 = make_app("bad_citation")
    v2 = draft(c2, find_topic(c2, "calado"))["draft"]["validation"]
    assert v2["ok"]  # el borrador final es la plantilla


def test_t07_template_never_reproduces_malicious_headline(fixture_dir, tmp_path):
    import json
    import shutil

    from fastapi.testclient import TestClient

    from umbral_api.app import create_app
    from umbral_api.services import Services

    from .conftest import make_settings

    d = tmp_path / "evil"
    shutil.copytree(fixture_dir, d)
    arts = [json.loads(x) for x in (d / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
    evil = next(a for a in arts if "Ignora todas" in a["title"])
    rows = [json.loads(x) for x in (d / "clusters.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in rows:
        if evil["articleId"] in r["memberArticleIds"]:
            r["memberArticleIds"] = [evil["articleId"]]
            r["representativeArticleId"] = evil["articleId"]
    (d / "clusters.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    s = make_settings(d, offline=True)
    c = TestClient(create_app(s, services=Services(s)), headers={"X-Umbral-User": "ana"})
    items = c.get(f"{API}/topics", params={"limit": 100}).json()["items"]
    t = next(i for i in items if i["hasSuspiciousSource"])
    assert "Ignora" not in t["title"] and "omitido" in t["title"]
    r = c.post(f"{API}/topics/{t['id']}/drafts", json={}).json()
    blob = json.dumps(r["draft"]["package"], ensure_ascii=False)
    assert "Ignora" not in blob and "clave de API" not in blob and "GEMINI" not in blob.upper()
    assert r["draft"]["validation"]["ok"]
    q = c.post(f"{API}/queries", json={"question": "nueva tarifa eléctrica en Panamá"}).json()
    assert "Ignora" not in q["answer"] and all("Ignora" not in h["title"] for h in q["hits"])


class _SeqProvider:
    """Proveedor que devuelve una secuencia de comportamientos: 'short' (guion corto, inválido) o 'ok'."""

    def __init__(self, base_provider, seq):
        self.base = base_provider
        self.seq = list(seq)
        self.prompts = []

    def __getattr__(self, name):
        return getattr(self.base, name)

    def generate(self, system, user):
        from umbral_api.providers import ProviderResult, stub_output_from_prompt

        self.prompts.append(user)
        out = stub_output_from_prompt(user)
        if self.seq.pop(0) == "short":
            out = out.model_copy(update={"script": "Un guion demasiado corto [c1]."})
        return ProviderResult(out, "seq-model")


def test_model_draft_gets_one_retry_with_validation_feedback(make_app):
    c = make_app("ok")
    seq = _SeqProvider(c.fake, ["short", "ok"])
    c.svc.providers["gemini"] = seq
    d = draft(c, find_topic(c, "calado"))["draft"]
    assert d["generationMode"] == "modelo" and d["validation"]["ok"] and len(seq.prompts) == 2
    assert "CORRECCIÓN" in seq.prompts[1] and "guion" in seq.prompts[1].lower()


def test_retry_failing_again_falls_back_to_template(make_app):
    c = make_app("ok")
    seq = _SeqProvider(c.fake, ["short", "short"])
    c.svc.providers["gemini"] = seq
    d = draft(c, find_topic(c, "calado"))["draft"]
    assert len(seq.prompts) == 2  # un único reintento, no más
    assert d["generationMode"] == "plantilla" and d["fallbackReason"] == "validacion_fallida" and d["validation"]["ok"]


def test_retry_counts_against_per_user_limit(make_app):
    c = make_app("ok", gemini_calls_per_user_day=1)
    seq = _SeqProvider(c.fake, ["short", "ok"])
    c.svc.providers["gemini"] = seq
    d = draft(c, find_topic(c, "calado"))["draft"]
    assert len(seq.prompts) == 1 and d["generationMode"] == "plantilla" and d["fallbackReason"] == "limite_por_usuario"
