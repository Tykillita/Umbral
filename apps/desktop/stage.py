"""Copia únicamente el corte real, los pesos fijados y la web a recursos de entrega."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import re
import shutil
from pathlib import Path

from umbral_pipeline.classify.calibration import load_profile, resolve_model_version
from umbral_pipeline.classify.laya_clf import PINNED_REVISION
from umbral_pipeline.refresh import load_verified
from umbral_pipeline.util import iso_z, now_utc, sha256_file

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = Path(__file__).resolve().parent


def stage(snapshot_dir: Path | None = None, model_dir: Path | None = None):
    staging = DESKTOP / "staging"
    staging.mkdir(exist_ok=True)
    licenses = staging / "licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "LICENSE", licenses / "UMBRAL-MIT.txt")
    laya_distribution = importlib.metadata.distribution("laya")
    laya_license = laya_distribution.locate_file("laya-0.3.28.dist-info/licenses/LICENSE")
    if not laya_license.is_file() or "Apache License" not in laya_license.read_text(encoding="utf-8"):
        raise ValueError("Falta la licencia Apache 2.0 verificada del paquete Laya.")
    shutil.copyfile(laya_license, licenses / "LAYA-APACHE-2.0.txt")
    shutil.copyfile(DESKTOP / "licenses/laya-model-card.md", licenses / "LAYA-MODEL-CARD.md")
    (licenses / "NOTICE.md").write_text(
        "# Licencias incluidas\n\nUmbral: MIT (UMBRAL-MIT.txt).\n\n"
        "Laya y checkpoint multilingüe: Apache 2.0 (LAYA-APACHE-2.0.txt). "
        f"Checkpoint fijado: {PINNED_REVISION}.\n"
        "Origen del modelo y su declaración de licencia: "
        f"https://huggingface.co/convaiinnovations/laya/blob/{PINNED_REVISION}/README.md\n\n"
        "La ficha original del modelo se conserva en LAYA-MODEL-CARD.md; "
        "sus resultados no constituyen una medición de Umbral.\n\n"
        "Electron/Chromium: LICENSE.electron.txt y LICENSES.chromium.html en la carpeta de la aplicación. "
        "Las licencias de las dependencias Python se conservan en sus carpetas dist-info del motor incluido.\n",
        encoding="utf-8")
    snapshot_dir = snapshot_dir or ROOT / "data/snapshots" / (ROOT / "data/snapshots/CURRENT").read_text().strip()
    state = load_verified(snapshot_dir)
    if state["manifest"]["classifier"]["classifier"] != "laya":
        raise ValueError("La entrega exige snapshot de Laya real, sin sustitución baseline.")
    model_dir = model_dir or (Path.home() / ".cache/huggingface/hub/models--convaiinnovations--laya/snapshots"
                              / PINNED_REVISION / "multilingual")
    required = ("model.safetensors", "rl_agent_config.json", "encoder/config.json", "tokenizer/tokenizer.json",
                "tokenizer/tokenizer_config.json")
    for name in required:
        if not (model_dir / name).is_file():
            raise ValueError(f"Falta un recurso del modelo fijado: {name}")
    # Copy links as bytes, never include HF credentials, cache metadata or sibling checkpoints.
    destination = staging / "laya"
    destination.mkdir(exist_ok=True)
    for name in required:
        target = destination / name
        target.parent.mkdir(exist_ok=True)
        if not target.exists() or sha256_file(target) != sha256_file(model_dir / name):
            shutil.copyfile(model_dir / name, target)
    model_metadata = model_dir / "umbral-model.json"
    staged_metadata = destination / "umbral-model.json"
    if model_metadata.is_file():
        shutil.copyfile(model_metadata, staged_metadata)
    elif staged_metadata.exists():
        staged_metadata.unlink()
    calibration_profile = model_dir / "umbral-calibration.json"
    if not calibration_profile.is_file():
        calibration_profile = ROOT / "pipeline/umbral_pipeline/classify/umbral-calibration.json"
    staged_profile = destination / "umbral-calibration.json"
    if calibration_profile.is_file():
        shutil.copyfile(calibration_profile, staged_profile)
    elif staged_profile.exists():
        staged_profile.unlink()
    # Pre-normalize tokenizer metadata at build time: resources stay read-only at runtime.
    cfg_path = destination / "tokenizer/tokenizer_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("tokenizer_class") in {None, "TokenizersBackend"}:
        cfg["tokenizer_class"] = "PreTrainedTokenizerFast"
        cfg.pop("backend", None)
        cfg.pop("is_local", None)
    if isinstance(cfg.get("extra_special_tokens"), list):
        cfg["extra_special_tokens"] = {f"extra_{i}": value for i, value in enumerate(cfg["extra_special_tokens"])}
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    snapshots = staging / "snapshots"
    snapshots.mkdir(exist_ok=True)
    target = snapshots / snapshot_dir.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(snapshot_dir, target)
    (snapshots / "CURRENT").write_text(snapshot_dir.name + "\n", encoding="utf-8")
    if not (staging / "web/index.html").exists():
        raise ValueError("Primero construye Astro en staging/web con modo local para escritorio.")
    files = {}
    for directory in (destination, snapshots, staging / "web", licenses):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                files[path.relative_to(staging).as_posix()] = {"sha256": sha256_file(path), "sizeBytes": path.stat().st_size}
    active_model_version = resolve_model_version(destination, PINNED_REVISION)
    active_profile = load_profile(active_model_version, destination, use_environment=False)
    manifest = {"version": 1, "createdAt": iso_z(now_utc()), "snapshotId": snapshot_dir.name,
                "layaRevision": PINNED_REVISION, "modelWeightsSha256": sha256_file(destination / "model.safetensors"),
                "modelVersion": active_model_version,
                "calibrationProfileId": active_profile.profile_id if active_profile else None,
                "calibrationProfileSha256": sha256_file(staged_profile) if active_profile else None,
                "files": files, "runtime": {name: importlib.metadata.version(name)
                for name in ("torch", "laya", "transformers", "PyInstaller", "umbral-api", "umbral-pipeline")}}
    inline_hashes = set()
    for html in (staging / "web").rglob("*.html"):
        for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script>", html.read_text(encoding="utf-8"), re.S | re.I):
            if not re.search(r"\bsrc\s*=", attrs, re.I):
                inline_hashes.add("'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'")
    manifest["inlineScriptHashes"] = sorted(inline_hashes)
    manifest["feedUrl"] = "https://site-umbral.web.app/data/current.json"
    manifest["publicConfigUrl"] = "https://site-umbral.web.app/public-config.json"
    manifest["publicApiUrl"] = ""  # se fija al preparar la publicación del servicio público
    (staging / "bundle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"snapshotId": snapshot_dir.name, "modelBytes": sum((destination / name).stat().st_size for name in required),
                      "bundleManifestSha256": sha256_file(staging / "bundle-manifest.json")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    stage(args.snapshot, args.model)
