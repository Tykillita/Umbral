"""Pruebas adicionales del reto (PDF §5/§9 del plan): aislamiento entre usuarios, citas inexistentes, cuotas agotadas,
proveedor desconectado, conflicto de revisión, reinicio del backend, hash de Laya vs snapshot servido,
límites por usuario y paridad con el contrato OpenAPI.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _first_topic(c) -> dict:
    return c.get("/topics", params={"limit": 1}).json()["items"][0]


# ------------------------------------------------------------------------------------ X01 aislamiento
class TestAislamientoEntreUsuarios:
    def test_un_usuario_no_ve_ni_afecta_los_casos_de_otro(self, api):
        with api.client("usuario-a") as a, api.client("usuario-b") as b:
            tid = _first_topic(a)["id"]
            dr = a.post(f"/topics/{tid}/drafts", json={}).json()
            cid = dr["case"]["caseId"]
            ra = a.patch(f"/cases/{cid}/review", json={"expectedVersion": dr["case"]["version"], "status": "en_revision",
                                                       "reviewer": "Persona A"})
            assert ra.status_code == 200
            # B ve el mismo caseId pero su propio espacio: sin persistir, versión 0, sin borradores
            cb = b.get(f"/cases/{cid}").json()
            assert cb["persisted"] is False and cb["version"] == 0 and cb["status"] == "nuevo"
            assert cb["drafts"] == [] and cb["history"] == []
            assert b.get(f"/topics/{tid}").json()["case"]["status"] == "nuevo"
            # lo que B escribe no cambia lo de A
            rb = b.patch(f"/cases/{cid}/review", json={"expectedVersion": 0, "status": "en_revision",
                                                       "reviewer": "Persona B"})
            assert rb.status_code == 200
            assert a.get(f"/cases/{cid}").json()["reviewer"] == "Persona A"

    def test_sin_identidad_en_modo_dev_header_es_401(self, api):
        with api.client(user=None) as anon:
            assert anon.get("/topics").status_code == 401

    def test_identidad_invalida_rechazada(self, api):
        with api.client(user="../../etc/passwd") as bad:
            assert bad.get("/topics").status_code == 401


# ------------------------------------------------------------------------------------ X02 citas inexistentes
class TestCitasInexistentes:
    def test_edicion_con_cita_a_evidencia_inexistente_no_se_acepta_como_valida(self, api):
        with api.client("citas") as c:
            tid = _first_topic(c)["id"]
            dr = c.post(f"/topics/{tid}/drafts", json={}).json()
            cid, ver = dr["case"]["caseId"], dr["case"]["version"]
            r = c.put(f"/cases/{cid}/draft", json={
                "expectedVersion": ver, "editor": "Editora",
                "claims": [{"id": "cx", "type": "hecho", "text": "Afirmación con fuente inventada",
                            "citations": [{"evidenceId": "art_inexistente_000", "field": "title"}]}],
            })
            if r.status_code in (400, 422):
                return  # rechazada por validación: correcto
            assert r.status_code == 200, r.text
            v = r.json()["currentDraft"]["validation"]
            assert v["ok"] is False or "cx" in v["rejectedClaimIds"], "una cita inexistente no puede validarse"
            assert any(i["code"] for i in v["issues"])

    def test_cita_con_campo_vacio_se_marca(self, api):
        with api.client("citas2") as c:
            tid = _first_topic(c)["id"]
            dr = c.post(f"/topics/{tid}/drafts", json={}).json()
            r = c.put(f"/cases/{dr['case']['caseId']}/draft", json={
                "expectedVersion": dr["case"]["version"], "editor": "Editora",
                "claims": [{"id": "cy", "type": "hecho", "text": "Hecho sin cita", "citations": []}]})
            if r.status_code == 200:
                v = r.json()["currentDraft"]["validation"]
                assert v["ok"] is False or "cy" in v["rejectedClaimIds"] or v["citationCoverage"] < 1.0


# ------------------------------------------------------------------------------------ X03 cuota agotada
class TestCuotaAgotada:
    def test_limite_por_usuario_cae_a_plantilla_y_conserva_la_evidencia(self, server_factory):
        with server_factory(GEMINI_API_KEY="TESTKEY_NOT_A_REAL_KEY_0123456789", GEMINI_CALLS_PER_USER_DAY="0") as srv:
            with srv.client("sin-cuota") as c:
                tid = _first_topic(c)["id"]
                r = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"})
                assert r.status_code == 200, r.text
                d = r.json()["draft"]
                assert d["generationMode"] in {"plantilla", "recuperado"}
                assert d["fallbackReason"] in {"cuota_agotada", "limite_por_usuario"}
                assert d["fallbackDetail"]
                # la consulta de evidencia sigue funcionando
                q = c.post("/queries", json={"question": "¿Qué temas hay sobre turismo y cruceristas en Panamá?"})
                assert q.status_code == 200 and q.json()["citations"]
                # y nunca cambia a un proveedor pago por su cuenta
                assert d["provider"] not in {"openai", "chatgpt", "claude", "anthropic"}

    def test_limite_de_consultas_por_minuto_devuelve_429_con_retry_after(self, server_factory):
        with server_factory(UMBRAL_QUERIES_PER_MINUTE="2") as srv:
            with srv.client("rafaga") as c:
                codes = [c.post("/queries", json={"question": "¿Qué hay de turismo en Panamá?"}) for _ in range(5)]
            assert 429 in [r.status_code for r in codes]
            r429 = next(r for r in codes if r.status_code == 429)
            assert "retry-after" in {k.lower() for k in r429.headers}
            assert r429.json()["code"] == "limite_excedido"


# ------------------------------------------------------------------------------------ X04 proveedor desconectado
class TestProveedorDesconectado:
    def test_sin_credenciales_de_gemini_se_degrada_y_lo_dice(self, api):
        with api.client("sin-clave") as c:
            tid = _first_topic(c)["id"]
            r = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"})
            assert r.status_code == 200, r.text
            d = r.json()["draft"]
            assert d["generationMode"] in {"plantilla", "recuperado"}
            assert d["fallbackReason"] in {"sin_credenciales", "proveedor_no_conectado", "proveedor_no_disponible"}
            assert d["generationLabel"]

    def test_chatgpt_sin_conexion_personal_no_esta_conectado(self, api):
        with api.client("sin-chatgpt") as c:
            tid = _first_topic(c)["id"]
            r = c.post(f"/topics/{tid}/drafts", json={"provider": "chatgpt"})
            assert r.status_code in (200, 403, 422, 503)
            if r.status_code == 200:
                assert r.json()["draft"]["fallbackReason"] in {"proveedor_no_conectado", "sin_credenciales",
                                                                "proveedor_no_disponible"}

    @pytest.mark.parametrize("auth,persistence", [
        ("local", "sqlite"), ("dev-header", "sqlite"), ("firebase", "sqlite"),
    ])
    def test_modo_web_no_arranca_con_sesion_compartida_o_sqlite(self, auth, persistence, tmp_path):
        """El límite web se aplica antes de abrir rutas o crear una base efímera."""
        api_dir = Path(__file__).resolve().parents[2] / "apps" / "api"
        env = {**os.environ,
               "UMBRAL_LOCAL_MODE": "0", "UMBRAL_AUTH_MODE": auth,
               "UMBRAL_PERSISTENCE": persistence, "GEMINI_API_KEY": "",
               "UMBRAL_GEMINI_STUB": "", "FIREBASE_PROJECT_ID": "fixture-test",
               "UMBRAL_SQLITE_PATH": str(tmp_path / "no-debe-crearse.sqlite")}
        env.pop("VIRTUAL_ENV", None)
        result = subprocess.run(
            ["uv", "run", "--no-sync", "python", "-c", "import umbral_api.main"],
            cwd=api_dir, env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0, "el modo web inseguro no debe arrancar"
        assert "Modo web requiere" in result.stderr
        assert not (tmp_path / "no-debe-crearse.sqlite").exists()


# ------------------------------------------------------------------------------------ X05 conflicto de revisión
class TestConflictoDeRevision:
    def test_segunda_escritura_con_version_vieja_es_409_sin_sobrescribir(self, api):
        with api.client("conflicto") as c:
            tid = _first_topic(c)["id"]
            dr = c.post(f"/topics/{tid}/drafts", json={}).json()
            cid, v0 = dr["case"]["caseId"], dr["case"]["version"]
            ok = c.patch(f"/cases/{cid}/review", json={"expectedVersion": v0, "status": "en_revision",
                                                       "reviewer": "Revisora 1"})
            assert ok.status_code == 200
            stale = c.patch(f"/cases/{cid}/review", json={"expectedVersion": v0, "status": "descartado",
                                                          "reviewer": "Revisor 2", "comment": "descarte tardío"})
            assert stale.status_code == 409
            body = stale.json()
            assert body["code"] == "conflicto_de_version"
            assert body["details"]["currentVersion"] == ok.json()["version"]
            now = c.get(f"/cases/{cid}").json()
            assert now["status"] == "en_revision" and now["reviewer"] == "Revisora 1", "no debe sobrescribirse"

    def test_transicion_invalida_es_422(self, api):
        with api.client("transicion") as c:
            tid = _first_topic(c)["id"]
            case = c.get(f"/cases/case-{tid}").json()
            r = c.patch(f"/cases/case-{tid}/review", json={"expectedVersion": case["version"],
                                                           "status": "aprobado_como_borrador", "reviewer": "X"})
            assert r.status_code == 422
            assert r.json()["code"] == "transicion_invalida"

    def test_descartar_exige_comentario(self, api):
        with api.client("comentario") as c:
            tid = _first_topic(c)["id"]
            case = c.get(f"/cases/case-{tid}").json()
            r1 = c.patch(f"/cases/case-{tid}/review", json={"expectedVersion": case["version"], "status": "en_revision",
                                                            "reviewer": "R"}).json()
            r2 = c.patch(f"/cases/case-{tid}/review", json={"expectedVersion": r1["version"], "status": "descartado",
                                                            "reviewer": "R"})
            assert r2.status_code == 422


# ------------------------------------------------------------------------------------ X06 reinicio
class TestReinicioDelBackend:
    def test_borradores_y_revisiones_persisten_tras_reiniciar(self, server_factory, tmp_path):
        db = tmp_path / "persist.sqlite"
        with server_factory(sqlite=db) as s1:
            with s1.client("persistente") as c:
                tid = _first_topic(c)["id"]
                dr = c.post(f"/topics/{tid}/drafts", json={}).json()
                cid = dr["case"]["caseId"]
                rv = c.patch(f"/cases/{cid}/review", json={"expectedVersion": dr["case"]["version"],
                                                           "status": "en_revision", "reviewer": "Persona",
                                                           "comment": "antes del reinicio"}).json()
                before = c.get(f"/cases/{cid}").json()
        assert db.exists()
        with server_factory(sqlite=db) as s2:  # proceso nuevo, misma base
            with s2.client("persistente") as c:
                after = c.get(f"/cases/{cid}").json()
        assert after["persisted"] is True
        assert after["version"] == before["version"] == rv["version"]
        assert after["status"] == "en_revision" and after["reviewer"] == "Persona"
        assert len(after["drafts"]) == len(before["drafts"]) >= 1
        assert [h["version"] for h in after["history"]] == [h["version"] for h in before["history"]]

    def test_sin_borrador_de_modelo_previo_recuperado_cae_a_plantilla(self, server_factory, tmp_path):
        db = tmp_path / "recuperado.sqlite"
        with server_factory(sqlite=db) as s1:
            with s1.client("rec") as c:
                tid = _first_topic(c)["id"]
                c.post(f"/topics/{tid}/drafts", json={})
        with server_factory(sqlite=db, UMBRAL_OFFLINE="1") as s2:
            with s2.client("rec") as c:
                r = c.post(f"/topics/{tid}/drafts", json={"provider": "recuperado"})
                assert r.status_code == 200, r.text
                d = r.json()["draft"]
                # solo se recuperan borradores generados por un modelo; aquí no hay ninguno
                assert d["generationMode"] == "plantilla"



# ------------------------------------------------------------------------------------ X07 hash de Laya vs snapshot
class TestHashLayaVsSnapshot:
    def test_hash_de_predicciones_coincide_con_el_snapshot_servido(self, api, snapshot):
        d = snapshot["dir"]
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        arts = [json.loads(line) for line in (d / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
        preds = [json.loads(line) for line in (d / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        lines = "".join(f"{p['articleId']}:{p['inputHash']}\n" for p in sorted(preds, key=lambda x: x["articleId"]))
        mine = hashlib.sha256(lines.encode()).hexdigest()
        assert mine == manifest["classifier"]["predictionsInputSha256"]
        assert hashlib.sha256((d / "articles.jsonl").read_bytes()).hexdigest() == manifest["classifier"]["articlesSha256"]
        assert len(arts) == len(preds)
        with api.client() as c:
            h = c.get("/health").json()
        assert h["snapshotId"] == manifest["snapshotId"]
        assert h["integrity"]["predictionsHashVerified"] is True
        assert h["integrity"]["predictionsSha256"] == mine
        assert h["integrity"]["manifestVerified"] is True and h["integrity"]["errors"] == []

    def test_snapshot_alterado_se_detecta(self, server_factory, snapshot, tmp_path):
        bad_root = tmp_path / "alterado"
        shutil.copytree(snapshot["dir"], bad_root / snapshot["id"])
        f = bad_root / snapshot["id"] / "articles.jsonl"
        f.write_text(f.read_text(encoding="utf-8").replace("Autoridad del Canal", "Autoridad del CANAL (alterado)", 1),
                     encoding="utf-8")
        with server_factory(snapshot_dir=bad_root / snapshot["id"]) as srv:
            with srv.client() as c:
                h = c.get("/health").json()
        assert h["integrity"]["manifestVerified"] is False or h["integrity"]["predictionsHashVerified"] is False
        assert h["integrity"]["errors"], "la alteración debe quedar registrada"
        assert h["status"] == "degradado"

    def test_snapshot_de_prueba_se_declara_fixture(self, api):
        with api.client() as c:
            h = c.get("/health").json()
        assert h["containsFixtures"] is True and h["provisional"] is True
        assert h["dataMode"] in {"fixture", "provisional"}


# ------------------------------------------------------------------------------------ contrato OpenAPI
class TestContratoOpenApi:
    def test_rutas_del_openapi_publicado_existen_en_el_servidor(self, api):
        repo = Path(__file__).resolve().parents[2]
        spec = json.loads((repo / "apps" / "api" / "openapi.json").read_text(encoding="utf-8"))
        with api.client() as c:
            live = c.get("/openapi.json").json()
        assert set(spec["paths"]) == set(live["paths"]), "apps/api/openapi.json desactualizado respecto al servidor"
        for path, ops in spec["paths"].items():
            assert set(ops) == set(live["paths"][path])

    def test_respuestas_incluyen_snapshot_y_version_de_reglas(self, api):
        with api.client() as c:
            for r in (c.get("/topics").json(),
                      c.post("/queries", json={"question": "¿Qué hay de turismo?"}).json()):
                assert r["snapshotId"] and r["rulesVersion"] == "scoring-v1" and r["dataMode"]

    def test_json_en_camel_case(self, api):
        with api.client() as c:
            body = c.get("/topics").text
        assert "snapshotId" in body and "snapshot_id" not in body


# ------------------------------------------------------------------------------------ proveedor simulado (stub)
class TestGeminiSimulado:
    """Con UMBRAL_GEMINI_STUB (sin red) se prueban las rutas de modelo, cuota, caída y recuperación."""

    def test_modelo_ok_luego_cuota_recupera_borrador_previo(self, server_factory, tmp_path):
        db = tmp_path / "stub.sqlite"
        with server_factory(sqlite=db, UMBRAL_GEMINI_STUB="ok") as s1:
            with s1.client("stub") as c:
                tid = _first_topic(c)["id"]
                r = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"})
                assert r.status_code == 200, r.text
                d = r.json()["draft"]
                assert d["generationMode"] == "modelo" and d["model"]
                assert d["validation"]["factualCitationCoverage"] in (1.0, None)
                assert any("stub" in n.lower() or "simulad" in n.lower() for n in c.get("/health").json()["notes"]), \
                    "el /health debe rotular que Gemini está simulado"
        with server_factory(sqlite=db, UMBRAL_GEMINI_STUB="quota") as s2:
            with s2.client("stub") as c:
                r = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"})
                assert r.status_code == 200, r.text
                d2 = r.json()["draft"]
                assert d2["generationMode"] == "recuperado", "con cuota agotada debe recuperar el borrador de modelo previo"
                assert d2["fallbackReason"] in {"cuota_agotada", "limite_por_usuario"}
                assert d2["recoveredFromDraftId"]

    def test_proveedor_caido_cae_a_plantilla_sin_perder_la_evidencia(self, server_factory):
        with server_factory(UMBRAL_GEMINI_STUB="down") as s:
            with s.client("caido") as c:
                tid = _first_topic(c)["id"]
                d = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"}).json()["draft"]
                assert d["generationMode"] == "plantilla"
                assert d["fallbackReason"] == "proveedor_no_disponible"
                assert c.post("/queries", json={"question": "¿Qué hay de turismo en Panamá?"}).status_code == 200

    def test_cuota_429_sin_borrador_previo_cae_a_plantilla_y_nunca_a_un_proveedor_pago(self, server_factory):
        with server_factory(UMBRAL_GEMINI_STUB="quota") as s:
            with s.client("cuota") as c:
                tid = _first_topic(c)["id"]
                d = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"}).json()["draft"]
                assert d["generationMode"] == "plantilla" and d["fallbackReason"] == "cuota_agotada"
                assert d["provider"] not in {"openai", "chatgpt", "claude", "anthropic"}

    def test_sin_clave_simulada_esta_desconectado(self, server_factory):
        with server_factory(UMBRAL_GEMINI_STUB="no_key") as s:
            with s.client("nokey") as c:
                tid = _first_topic(c)["id"]
                d = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"}).json()["draft"]
                assert d["generationMode"] == "plantilla"
                assert d["fallbackReason"] in {"sin_credenciales", "proveedor_no_conectado"}

    def test_offline_gana_sobre_el_stub(self, server_factory):
        with server_factory(UMBRAL_GEMINI_STUB="ok", UMBRAL_OFFLINE="1") as s:
            with s.client("off") as c:
                tid = _first_topic(c)["id"]
                d = c.post(f"/topics/{tid}/drafts", json={"provider": "gemini"}).json()["draft"]
                assert d["generationMode"] != "modelo" and d["fallbackReason"] == "modo_sin_conexion"


# ------------------------------------------------------------------------------------ filtro de alcance (API 0.3)
class TestFiltroDeAlcance:
    def test_agenda_por_defecto_excluye_indeterminado_pero_no_pierde_trazabilidad(self, api, topics):
        with api.client() as c:
            vis = c.get("/topics", params={"limit": 100}).json()
            todo = c.get("/topics", params={"limit": 100, "scope": "all"}).json()
        assert all(t["category"] != "indeterminado" for t in vis["items"])
        assert any(t["category"] == "indeterminado" for t in todo["items"]), "el snapshot de prueba trae uno"
        assert vis["outOfScopeCount"] == len(todo["items"]) - len(vis["items"]) >= 1
        assert todo["outOfScopeCount"] == 0
        # sigue accesible por ID, marcado fuera de alcance
        oculto = next(t for t in todo["items"] if t["category"] == "indeterminado")
        with api.client() as c:
            d = c.get(f"/topics/{oculto['id']}").json()
        assert d["summary"]["outOfScope"] is True

    def test_rank_se_numera_sobre_los_visibles(self, api):
        with api.client() as c:
            vis = c.get("/topics", params={"limit": 100}).json()["items"]
        assert [t["rank"] for t in vis] == list(range(1, len(vis) + 1))
