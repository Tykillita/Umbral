"""Invariantes del contrato sobre el snapshot REAL de data/snapshots/ (el que se entrega), no el sintético.

No asume contenido: comprueba reglas que deben cumplirse con cualquier snapshot (integridad, puntaje, citas,
etiquetado fixture/provisional, abstención). Se salta si todavía no hay snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SNAPS = REPO / "data" / "snapshots"


def current_snapshot() -> Path | None:
    cur = SNAPS / "CURRENT"
    if cur.exists():
        d = SNAPS / cur.read_text(encoding="utf-8").strip()
        if (d / "manifest.json").exists():
            return d
    cands = sorted(p for p in SNAPS.iterdir() if (p / "manifest.json").exists()) if SNAPS.is_dir() else []
    return cands[-1] if cands else None


@pytest.fixture(scope="module")
def real(server_factory):
    d = current_snapshot()
    if d is None:
        pytest.skip("no hay snapshot en data/snapshots/")
    with server_factory(snapshot_dir=d) as srv:
        srv.snapshot_dir = d  # type: ignore[attr-defined]
        yield srv


def test_integridad_y_etiquetado(real):
    m = json.loads((real.snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    with real.client() as c:
        h = c.get("/health").json()
    assert h["snapshotId"] == m["snapshotId"]
    assert h["integrity"]["manifestVerified"] is True and h["integrity"]["errors"] == []
    assert h["integrity"]["predictionsHashVerified"] is True
    assert h["provisional"] == m["provisional"] and h["containsFixtures"] == m["containsFixtures"]
    if m["containsFixtures"]:
        assert h["dataMode"] in {"fixture", "provisional"}, "datos fixture deben declararse"
    if m["classifier"]["classifier"] == "baseline":
        assert h["classifier"] == "baseline"


def test_agenda_puntaje_bandas_y_orden(real):
    with real.client() as c:
        items = c.get("/topics", params={"limit": 100}).json()["items"]
    assert items, "la agenda no puede estar vacía"
    for t in items:
        comp = {x["key"]: x for x in t["scoreComponents"]}
        assert set(comp) == {"R", "I", "U", "N", "E"}
        assert abs(sum(x["points"] for x in comp.values()) - t["score"]) < 0.05
        assert t["band"] == ("bajo" if t["score"] < 40 else "medio" if t["score"] < 70 else "alto")
        if t["band"] == "alto" and t["evidenceStatus"] == "insuficiente":
            assert t["needsInvestigation"] is True
    keys = [(-round(t["score"], 6), -t["urgency"], t["id"]) for t in items]
    assert keys == sorted(keys)


def test_toda_cita_apunta_a_evidencia_existente(real):
    with real.client("citas-real") as c:
        items = c.get("/topics", params={"limit": 5}).json()["items"]
        for t in items:
            det = c.get(f"/topics/{t['id']}").json()
            ev = {a["id"] for a in det["articles"]} | {p["id"] for p in det["officialContext"]["indicators"]}
            for cl in det["supportedClaims"]:
                for ci in cl["citations"]:
                    assert ci["evidenceId"] in ev
            dr = c.post(f"/topics/{t['id']}/drafts", json={"provider": "plantilla"}).json()["draft"]
            for cl in dr["package"]["claims"]:
                if cl["type"] in {"hecho", "declaracion"}:
                    assert cl["citations"], "afirmación factual sin cita"
                for ci in cl["citations"]:
                    assert ci["evidenceId"] in ev, f"cita inexistente {ci['evidenceId']}"
            v = dr["validation"]
            assert v["factualCitationCoverage"] in (1.0, None)
            assert dr["generationMode"] == "plantilla"


def test_abstencion_en_el_snapshot_real(real):
    with real.client() as c:
        for q in ("¿Cuántos turistas visitaron Marte en 1850?", "¿Cuál fue el PIB de Wakanda en 2024?"):
            r = c.post("/queries", json={"question": q}).json()
            assert r["answerStatus"] == "abstencion" and r["citations"] == []


def test_indicadores_540_con_nulos_conservados(real):
    rows = [json.loads(line) for line in (real.snapshot_dir / "indicators.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 540, "6 países x 6 indicadores x 15 años (el PDF dice 1.350: ver D-09)"
    assert all((r["value"] is None) == (r["status"] == "missing") for r in rows)
    assert all(r["year"] in range(2010, 2025) and r["unit"] for r in rows)


def test_benchmark_reservado_no_esta_en_el_repo():
    assert not (REPO / "eval" / "held-out").exists() and not (REPO / "eval" / "reserved").exists()
    ev = REPO / "eval"
    assert not (ev.is_dir() and list(ev.rglob("*.reserved.*")))


def test_serie_vinculada_no_eleva_e_y_patrocinados_limitados(real):
    """Regla D-15: serie oficial por palabra clave = contexto (no sube E); /publirreportajes/ => E <= 0,33."""
    with real.client() as c:
        items = []
        for band in ("alto", "medio", "bajo"):
            items += c.get("/topics", params={"limit": 100, "band": band}).json()["items"]
        assert items
        spons = [t for t in items if t["possibleSponsored"]]
        assert spons, "el corpus real trae contenido de /publirreportajes/ de TVN"
        for t in items:
            e = next(x for x in t["scoreComponents"] if x["key"] == "E")["value"]
            if t["possibleSponsored"]:
                assert e <= 0.33 + 1e-9, f"patrocinado con E={e}: {t['id']}"
            if t["independentProvenances"] < 2:
                assert e <= 0.33 + 1e-9, f"E={e} con una sola procedencia sin confirmación de revisor: {t['id']}"
