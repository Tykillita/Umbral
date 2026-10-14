"""Empaquetado y descarga verificada del artefacto Laya calibrado (scripts/laya_artifact.py)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("laya_artifact", REPO / "scripts" / "laya_artifact.py")
art = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(art)  # type: ignore[union-attr]


def make_model(directory: Path, *, tamper: bool = False) -> Path:
    weights = b"pesos-de-prueba" * 100
    sha = hashlib.sha256(weights).hexdigest()
    directory.mkdir(parents=True)
    (directory / "model.safetensors").write_bytes(weights + (b"x" if tamper else b""))
    (directory / "umbral-model.json").write_text(json.dumps({"modelVersion": f"laya-ft-{sha[:16]}", "weightsSha256": sha}), encoding="utf-8")
    (directory / "umbral-calibration.json").write_text("{}", encoding="utf-8")
    (directory / "rl_agent_config.json").write_text("{}", encoding="utf-8")
    (directory / "tokenizer").mkdir()
    (directory / "tokenizer" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (directory / "encoder").mkdir()
    (directory / "encoder" / "config.json").write_text("{}", encoding="utf-8")
    (directory / "umbral-production-artifact.json").write_text("{}", encoding="utf-8")  # recibo local: no se empaqueta
    return directory


def test_el_descriptor_del_repo_es_valido_y_declara_la_identidad_del_modelo_publicado():
    descriptor = art.load_descriptor()
    assert descriptor["modelVersion"] == "laya-ft-" + descriptor["weightsSha256"][:16]
    if descriptor["status"] == "published":
        assert descriptor["asset"]["url"].startswith("https://github.com/") and len(descriptor["asset"]["sha256"]) == 64


def test_empaquetar_y_extraer_conserva_el_modelo_y_omite_el_recibo_local(tmp_path):
    model = make_model(tmp_path / "modelo")
    out = tmp_path / "salida" / "laya-calibrated.tar"
    descriptor_path = tmp_path / "descriptor.json"
    descriptor = art.package(model, out, descriptor_path, "laya-calibrated-v1", "Tykillita/Umbral")
    assert descriptor["status"] == "published" and descriptor["asset"]["sha256"] == art.sha256_file(out)
    assert descriptor["asset"]["url"] == "https://github.com/Tykillita/Umbral/releases/download/laya-calibrated-v1/laya-calibrated.tar"
    dest = tmp_path / "destino"
    identity = art.verify_and_extract(out, art.load_descriptor(descriptor_path), dest)
    assert identity["modelVersion"] == descriptor["modelVersion"]
    assert (dest / "model.safetensors").read_bytes() == (model / "model.safetensors").read_bytes()
    assert not (dest / "umbral-production-artifact.json").exists()


def test_el_empaquetado_es_reproducible(tmp_path):
    model = make_model(tmp_path / "modelo")
    first = art.package(model, tmp_path / "a.tar", tmp_path / "a.json", "t", "o/r")["asset"]["sha256"]
    second = art.package(model, tmp_path / "b.tar", tmp_path / "b.json", "t", "o/r")["asset"]["sha256"]
    assert first == second


def test_un_archivo_alterado_se_rechaza_por_sha256(tmp_path):
    model = make_model(tmp_path / "modelo")
    out = tmp_path / "a.tar"
    descriptor = art.package(model, out, tmp_path / "d.json", "t", "o/r")
    out.write_bytes(out.read_bytes() + b"\0")
    with pytest.raises(art.ArtifactError, match="SHA-256"):
        art.verify_and_extract(out, descriptor, tmp_path / "destino")


def test_pesos_que_no_coinciden_con_su_metadato_se_rechazan(tmp_path):
    with pytest.raises(art.ArtifactError, match="alterado|no coinciden"):
        art.inspect_model_dir(make_model(tmp_path / "modelo", tamper=True))


def test_un_modelo_distinto_al_del_descriptor_se_rechaza(tmp_path):
    model = make_model(tmp_path / "modelo")
    out = tmp_path / "a.tar"
    descriptor = art.package(model, out, tmp_path / "d.json", "t", "o/r")
    descriptor["weightsSha256"] = "0" * 64
    with pytest.raises(art.ArtifactError, match="no es el que declara"):
        art.verify_and_extract(out, descriptor, tmp_path / "destino")


@pytest.mark.parametrize("name,kind", [("../fuera.txt", "file"), ("/abs.txt", "file"), ("enlace", "symlink")])
def test_los_miembros_peligrosos_del_tar_se_rechazan(tmp_path, name, kind):
    out = tmp_path / "malo.tar"
    with tarfile.open(out, "w") as archive:
        info = tarfile.TarInfo(name)
        if kind == "symlink":
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        else:
            payload = b"x"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    descriptor = {"asset": {"sizeBytes": out.stat().st_size, "sha256": art.sha256_file(out)}, "modelVersion": "x", "weightsSha256": "y"}
    with pytest.raises(art.ArtifactError, match="Miembro no permitido"):
        art.verify_and_extract(out, descriptor, tmp_path / "destino")
    assert not (tmp_path / "fuera.txt").exists()


@pytest.mark.parametrize("url", [
    "http://github.com/x/y/releases/download/t/a.tar",
    "https://evil.example/a.tar",
    "https://user:pass@github.com/x/a.tar",
    "file:///etc/passwd",
])
def test_solo_se_descarga_por_https_desde_github(url):
    with pytest.raises(art.ArtifactError):
        art.check_url(url)


def test_fetch_con_el_artefacto_pendiente_falla_rapido_con_un_mensaje_claro(tmp_path, capsys):
    descriptor = tmp_path / "d.json"
    descriptor.write_text(json.dumps({"schemaVersion": 1, "status": "pending", "modelVersion": "m", "weightsSha256": "w", "asset": None}), encoding="utf-8")
    assert art.fetch(descriptor, tmp_path / "destino") == art.EXIT_PENDING
    assert "aún no está publicado" in capsys.readouterr().err


def test_fetch_no_vuelve_a_descargar_si_el_destino_ya_tiene_el_artefacto(tmp_path, monkeypatch):
    descriptor = tmp_path / "d.json"
    descriptor.write_text(json.dumps({"schemaVersion": 1, "status": "published", "modelVersion": "m", "weightsSha256": "w",
                                       "asset": {"name": "a", "url": "https://github.com/x/y/a", "sha256": "0" * 64, "sizeBytes": 1}}), encoding="utf-8")
    dest = tmp_path / "destino"
    dest.mkdir()
    (dest / "model.safetensors").write_bytes(b"x")
    monkeypatch.setattr(art, "download", lambda *a, **k: pytest.fail("no debe descargar"))
    assert art.fetch(descriptor, dest) == 0
