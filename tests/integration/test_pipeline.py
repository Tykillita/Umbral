"""Pruebas de integración del pipeline de `datos` (CLI y funciones reales), sin red y sin PyTorch.

- Contrato: mi snapshot sintético y los snapshots reales de data/snapshots/ pasan `umbral_pipeline verify`.
- T01: un lote sucio (fechas inválidas, nulos, filas vacías) se valida, se separan los errores y NO se bloquea la carga.
- T02/T03: tres titulares del mismo evento -> un cluster con una procedencia; recirculación detectada.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PIPELINE = REPO / "pipeline"
pytestmark = pytest.mark.needs_pipeline


def run_pipeline(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PYTHONUTF8"] = "1"
    return subprocess.run(["uv", "run", "python", *args], cwd=PIPELINE, env=env, input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=300)


def test_el_snapshot_sintetico_cumple_el_contrato_del_pipeline(snapshot):
    r = run_pipeline("-m", "umbral_pipeline", "verify", str(snapshot["dir"]))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().endswith("OK")


def _real_snapshots() -> list[Path]:
    root = REPO / "data" / "snapshots"
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")) if root.is_dir() else []


@pytest.mark.parametrize("snap", _real_snapshots() or [None], ids=lambda p: p.name if p else "sin-snapshots")
def test_los_snapshots_del_repo_verifican(snap):
    if snap is None:
        pytest.skip("todavía no hay snapshots en data/snapshots/")
    if not (snap / "manifest.json").exists():
        pytest.skip(f"{snap.name} ya no existe (datos regeneró el snapshot durante la ejecución)")
    r = run_pipeline("-m", "umbral_pipeline", "verify", str(snap))
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    assert m["provisional"] in (True, False)
    # el hash de predicciones de Laya/baseline corresponde a los artículos servidos
    assert m["classifier"]["predictionsInputSha256"]
    assert m["classifier"]["articlesSha256"] == m["files"]["articles.jsonl"]["sha256"]


CODE_T01 = r"""
import json, sys
from datetime import UTC, datetime, timedelta
from umbral_pipeline.validate import normalize_record
cut = datetime(2026, 10, 7, 12, tzinfo=UTC)
raws = json.load(sys.stdin)
ok, bad = [], []
for r in raws:
    a, rej = normalize_record(r, window_start=cut - timedelta(days=30), cutoff=cut, extracted_default="2026-10-07T11:00:00Z")
    (ok if a else bad).append(a or rej)
print(json.dumps({"ok": [{"title": a["title"], "publishedAt": a["publishedAt"], "detectedAt": a["detectedAt"]} for a in ok],
                  "bad": [b["reasonCodes"] for b in bad]}, ensure_ascii=False))
"""

DIRTY = [
    {"title": "Noticia válida con fecha correcta de prueba", "url": "https://tvn-2.com/a_1_1.html",
     "publishedRaw": "Tue, 06 Oct 2026 20:00:00 +0000", "origin": {"source": "fixture"}},
    {"title": "Noticia con fecha inválida de prueba", "url": "https://x.example/b",
     "publishedRaw": "31/02/2026", "origin": {"source": "fixture"}},
    {"title": "Noticia con fecha en el futuro lejano", "url": "https://x.example/c",
     "publishedRaw": "2031-01-01T00:00:00Z", "origin": {"source": "fixture"}},
    {"title": "", "url": "https://x.example/d", "publishedRaw": "2026-10-06T00:00:00Z", "origin": {"source": "fixture"}},
    {"title": "Noticia sin ninguna fecha utilizable", "url": "https://x.example/e", "origin": {"source": "fixture"}},
    {"title": None, "url": None, "origin": {"source": "fixture"}},
    {"title": "Solo detectada por GDELT, sin fecha de publicación", "url": "https://x.example/f",
     "detectedRaw": "20261006T120000Z", "origin": {"source": "fixture"}},
]


def test_t01_lote_sucio_separa_errores_conserva_nulos_y_no_bloquea():
    r = run_pipeline("-c", CODE_T01, stdin=json.dumps(DIRTY))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    titles = {a["title"] for a in out["ok"]}
    assert "Noticia válida con fecha correcta de prueba" in titles
    assert "Solo detectada por GDELT, sin fecha de publicación" in titles, "detección sin publicación es válida"
    gd = next(a for a in out["ok"] if a["title"].startswith("Solo detectada"))
    assert gd["publishedAt"] is None, "la fecha de publicación nula se conserva como null"
    assert gd["detectedAt"] and gd["detectedAt"].startswith("2026-10-06")
    codes = [c for cs in out["bad"] for c in cs]
    assert "invalid_date" in codes and "missing_title" in codes and "empty_row" in codes and "null_date" in codes
    assert len(out["ok"]) == 2 and len(out["bad"]) == 5, "5 rechazados con motivo; los válidos no se bloquean"


CODE_CLUSTER = r"""
import json
from datetime import UTC, datetime
from umbral_pipeline.cluster import build_clusters
cut = datetime(2026, 10, 7, 12, tzinfo=UTC)
def art(i, title, dom, pub, seen, key, kind):
    return {"articleId": i, "title": title, "domain": dom, "outlet": dom, "canonicalUrl": f"https://{dom}/{i}",
            "publishedAt": pub, "detectedAt": seen, "extractedAt": "2026-10-07T11:00:00Z", "publishedAtBasis": "rss_pubdate" if pub else "unknown",
            "effectiveDate": pub or seen, "isTvn": False,
            "provenance": {"key": key, "kind": kind, "agency": "efe" if kind == "agency" else None, "known": True},
            "dataOrigin": "fixture"}
arts = [
 art("fx_1", "Panamá registra aumento de llegadas de cruceristas en el último trimestre - EFE", "a.example", "2026-10-06T08:00:00Z", None, "agency:efe", "agency"),
 art("fx_2", "Panamá registra aumento de llegadas de cruceristas en el último trimestre (EFE)", "b.example", None, "2026-10-06T10:00:00Z", "agency:efe", "agency"),
 art("fx_3", "Aumentan las llegadas de cruceristas a Panamá en el último trimestre - EFE", "c.example", None, "2026-10-06T11:00:00Z", "agency:efe", "agency"),
 art("fx_4", "Inauguran nuevo tramo del metro de Panamá hoy", "d.example", "2026-03-12T15:00:00Z", "2026-10-06T09:00:00Z", "outlet:d.example", "outlet"),
]
preds = [{"articleId": a["articleId"], "category": "turismo", "probability": 0.9, "geoRelevance": "panama", "classifier": "baseline"} for a in arts]
clusters, stats = build_clusters(arts, preds, cut)
print(json.dumps([{"size": c["size"], "members": c["memberArticleIds"], "indep": c["independentProvenanceCount"],
                   "recirc": c["isRecirculation"], "orig": c["originalPublishedAt"]} for c in clusters]))
"""


def test_t02_t03_cluster_de_agencia_y_recirculacion():
    r = run_pipeline("-c", CODE_CLUSTER)
    assert r.returncode == 0, r.stderr
    clusters = json.loads(r.stdout.strip().splitlines()[-1])
    agency = next(c for c in clusters if set(c["members"]) >= {"fx_1", "fx_2"})
    assert agency["size"] >= 2
    assert agency["indep"] == 1, "una agencia replicada cuenta una sola procedencia"
    recirc = next(c for c in clusters if "fx_4" in c["members"])
    assert recirc["recirc"] is True
    assert recirc["orig"].startswith("2026-03-12")
