"""Fronteras de publicación: hashes, snapshot inmutable y reservados inaccesibles."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("stage_hosting_data", REPO / "scripts/stage_hosting_data.py")
assert spec and spec.loader
hosting_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hosting_data)


@pytest.fixture
def prepared(tmp_path):
    source_root = REPO / "data/snapshots"
    sid = (source_root / "CURRENT").read_text(encoding="utf-8").strip()
    source = source_root / sid
    snapshots = tmp_path / "snapshots"
    shutil.copytree(source, snapshots / sid)
    (snapshots / "CURRENT").write_text(sid + "\n", encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><html lang=es></html>", encoding="utf-8")
    return snapshots, web, sid


def test_feed_publicado_y_descargado_conserva_el_snapshot_verificado(prepared, tmp_path, monkeypatch):
    snapshots, web, sid = prepared
    receipt = hosting_data.stage(snapshots, web)
    assert receipt["snapshotId"] == sid and receipt["snapshots"] == 1
    descriptor = json.loads((web / "data/current.json").read_text(encoding="utf-8"))
    assert descriptor["manifest"]["sha256"] == hosting_data.digest(snapshots / sid / "manifest.json")
    assert all(item["path"].startswith(f"snapshots/{sid}/") for item in descriptor["files"])

    def local_fetch(url, limit):
        assert url.startswith("https://feed.example/data/")
        data = (web / "data" / url.removeprefix("https://feed.example/data/")).read_bytes()
        assert len(data) <= limit
        return data

    monkeypatch.setattr(hosting_data, "fetch_bytes", local_fetch)
    downloaded = tmp_path / "downloaded"
    result = hosting_data.download("https://feed.example/data/", downloaded)
    assert result["snapshotId"] == sid
    assert (downloaded / "CURRENT").read_text().strip() == sid
    hosting_data.read_manifest(downloaded / sid)


def test_corrupto_no_sustituye_el_build_ya_preparado(prepared):
    snapshots, web, sid = prepared
    hosting_data.stage(snapshots, web)
    before = (web / "data/current.json").read_bytes()
    with (snapshots / sid / "articles.jsonl").open("ab") as file:
        file.write(b"\n{}\n")
    with pytest.raises(ValueError, match="Integridad"):
        hosting_data.stage(snapshots, web)
    assert (web / "data/current.json").read_bytes() == before


def test_fixtures_y_baseline_no_se_promueven(prepared):
    snapshots, web, sid = prepared
    manifest_file = snapshots / sid / "manifest.json"
    original = json.loads(manifest_file.read_text(encoding="utf-8"))
    for field in ("fixtures", "baseline"):
        manifest = json.loads(json.dumps(original))
        if field == "fixtures":
            manifest["containsFixtures"] = True
        else:
            manifest["classifier"]["classifier"] = "baseline"
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            hosting_data.stage(snapshots, web)
    assert not (web / "data").exists()


def test_descriptor_con_ruta_externa_no_se_descarga(prepared, tmp_path, monkeypatch):
    snapshots, web, _sid = prepared
    hosting_data.stage(snapshots, web)
    descriptor = json.loads((web / "data/current.json").read_text(encoding="utf-8"))
    descriptor["manifest"]["path"] = "https://otra.example/manifest.json"
    requests = []

    def malicious_feed(url, limit):
        requests.append(url)
        if url.endswith("current.json"):
            return json.dumps(descriptor).encode()
        return json.dumps({"schemaVersion": 1, "snapshots": [descriptor]}).encode()

    monkeypatch.setattr(hosting_data, "fetch_bytes", malicious_feed)
    with pytest.raises(ValueError, match="Referencia"):
        hosting_data.download("https://feed.example/data/", tmp_path / "downloaded")
    assert len(requests) == 2
    assert not (tmp_path / "downloaded/CURRENT").exists()


def test_preflight_respeta_gitignore_y_no_toca_el_git_original(tmp_path):
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Proyecto de control", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRETO_LOCAL_DE_CONTROL=sentinela", encoding="utf-8")
    result = subprocess.run([sys.executable, str(REPO / "scripts/preflight_publish.py"), str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Archivos que Git" in result.stdout
    assert "sentinela" not in result.stdout
    assert not (tmp_path / ".git").exists()


def test_preflight_rechaza_nombre_reservado_sin_abrir_contenido(tmp_path):
    # Carpeta sintética vacía: ninguna consulta real se crea ni se lee.
    (tmp_path / "eval/held-out").mkdir(parents=True)
    result = subprocess.run([sys.executable, str(REPO / "scripts/preflight_publish.py"), str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "contenido no leído" in result.stdout
    assert not (tmp_path / ".git").exists()
