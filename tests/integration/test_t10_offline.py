"""T10: sin internet durante la demo.

El backend corre con la red BLOQUEADA DE VERDAD: `tests/support/netblock/sitecustomize.py` hace fallar
cualquier conexión/DNS no-loopback en el proceso Python y deja un registro de cada intento. Además se activa
UMBRAL_OFFLINE=1. Se demuestra el flujo: carga -> consulta -> ranking -> ficha -> (Laya local: ver nota) ->
fallback de borradores -> revisión -> exportación.

Nota sobre «Laya local»: aquí se verifica que las predicciones del snapshot corresponden a su hash
(sin red). La re-ejecución de Laya requiere el extra opcional `laya` y los pesos descargados; esa parte se
prueba con `pytest -m laya` en `pipeline/` y queda marcada como no ejecutada en CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def offline_server(server_factory):
    with server_factory(netblock=True, UMBRAL_OFFLINE="1", GEMINI_API_KEY="CLAVE_QUE_NO_DEBE_USARSE_EN_OFFLINE") as s:
        yield s


def netblock_attempts(srv) -> list[str]:
    log = Path(srv.workdir) / "netblock.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_netblock_funciona_de_verdad():
    """Sanidad del bloqueo: sin esto, la prueba T10 no demostraría nada."""
    import subprocess
    import sys
    import tempfile

    support = Path(__file__).resolve().parent.parent / "support" / "netblock"
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "nb.log"
        code = ("import socket,sys\n"
                "try:\n socket.create_connection(('example.com',80),timeout=3)\n print('CONECTO')\n"
                "except OSError as e:\n print('BLOQUEADO', e)\n")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env={"PYTHONPATH": str(support), "UMBRAL_NETBLOCK_LOG": str(log), "PATH": ""}, timeout=30)
        assert "BLOQUEADO" in out.stdout, out.stdout + out.stderr
        assert log.exists() and "example.com" in log.read_text()


def test_health_declara_modo_sin_conexion(offline_server):
    with offline_server.client() as c:
        h = c.get("/health").json()
    assert h["offline"] is True
    assert h["integrity"]["manifestVerified"] is True
    assert h["integrity"]["predictionsHashVerified"] is True, "las predicciones deben corresponder al hash del snapshot"
    ext = [p for p in h["providers"] if p["external"]]
    assert all(not p["available"] for p in ext), "los proveedores externos no pueden estar disponibles sin conexión"


def test_flujo_completo_sin_internet(offline_server, snapshot):
    srv = offline_server
    with srv.client("demo-offline") as c:
        # carga + snapshot
        assert c.get("/snapshot").json()["snapshotId"] == snapshot["id"]
        # ranking / agenda
        agenda = c.get("/topics", params={"limit": 5}).json()
        assert 1 <= len(agenda["items"]) <= 5
        scores = [t["score"] for t in agenda["items"]]
        assert scores == sorted(scores, reverse=True)
        # consulta con evidencia
        q = c.post("/queries", json={"question": "¿Qué hay sobre el Canal de Panamá y buques neopanamax?"}).json()
        assert q["answerStatus"] != "abstencion" and q["citations"]
        # consulta sin respuesta -> abstención (sin LLM)
        q2 = c.post("/queries", json={"question": "¿Cuántos turistas visitaron Marte en 1850?"}).json()
        assert q2["answerStatus"] == "abstencion"
        # ficha
        tid = agenda["items"][0]["id"]
        ficha = c.get(f"/topics/{tid}").json()
        assert ficha["score"]["components"] and ficha["articles"]
        # borrador: fallback sin conexión (plantilla con citas) y declarado como tal
        dr = c.post(f"/topics/{tid}/drafts", json={})
        assert dr.status_code == 200, dr.text
        draft = dr.json()["draft"]
        assert draft["generationMode"] in {"plantilla", "recuperado"}, "sin internet no puede ser 'modelo'"
        assert draft["fallbackReason"] == "modo_sin_conexion"
        facts = [cl for cl in draft["package"]["claims"] if cl["type"] in {"hecho", "declaracion"}]
        assert facts and all(cl["citations"] for cl in facts), "toda afirmación factual debe citar evidencia"
        assert draft["validation"]["factualCitationCoverage"] == 1.0
        # revisión humana
        case = dr.json()["case"]
        rv = c.patch(f"/cases/{case['caseId']}/review",
                     json={"expectedVersion": case["version"], "status": "en_revision", "reviewer": "Revisora Demo",
                           "comment": "Revisión sin conexión"})
        assert rv.status_code == 200, rv.text
        assert rv.json()["status"] == "en_revision"
        # exportación a Markdown (para pegar en Notion)
        ex = c.get(f"/cases/{case['caseId']}/export", params={"format": "markdown"})
        assert ex.status_code == 200 and ex.headers["content-type"].startswith("text/markdown")
        assert snapshot["id"] in ex.text and "scoring-v1" in ex.text


def test_no_hubo_ningun_intento_de_conexion_externa(offline_server):
    """Se ejecuta tras el flujo (orden del módulo): el servidor no debe ni intentar salir a internet."""
    attempts = netblock_attempts(offline_server)
    assert attempts == [], f"el backend intentó conexiones externas estando en modo offline: {attempts[:5]}"


def test_chatgpt_y_claude_no_estan_disponibles_offline(offline_server):
    with offline_server.client("demo-offline-2") as c:
        agenda = c.get("/topics", params={"limit": 1}).json()
        tid = agenda["items"][0]["id"]
        for prov in ("gemini", "chatgpt", "claude"):
            r = c.post(f"/topics/{tid}/drafts", json={"provider": prov})
            assert r.status_code in (200, 403, 422, 503), r.text
            if r.status_code == 200:
                assert r.json()["draft"]["generationMode"] != "modelo"
    assert netblock_attempts(offline_server) == []
