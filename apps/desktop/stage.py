"""Copia únicamente el corte real, los pesos fijados y la web a recursos de entrega."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
from pathlib import Path

from umbral_pipeline.classify.calibration import (
    PROFILE_NAME,
    load_profile,
    require_calibrated_classifier_binding,
    resolve_model_version,
)
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
    (licenses / "LAYA-MODEL-CARD.md").write_text(
        "# Laya multilingual model\n\n"
        "Umbral bundles the `convaiinnovations/laya` multilingual checkpoint at the pinned revision "
        f"`{PINNED_REVISION}`. The checkpoint and runtime are distributed under Apache License 2.0.\n\n"
        "This file identifies the bundled model; consult the upstream model card for its architecture, "
        "intended use, evaluation, and limitations:\n\n"
        f"https://huggingface.co/convaiinnovations/laya/blob/{PINNED_REVISION}/README.md\n",
        encoding="utf-8",
    )
    (licenses / "NOTICE.md").write_text(
        "# Licencias incluidas\n\nUmbral: MIT (UMBRAL-MIT.txt).\n\n"
        "Laya y checkpoint multilingüe: Apache 2.0 (LAYA-APACHE-2.0.txt). "
        f"Checkpoint fijado: {PINNED_REVISION}.\n"
        "Origen del modelo y su declaración de licencia: "
        f"https://huggingface.co/convaiinnovations/laya/blob/{PINNED_REVISION}/README.md\n\n"
        "LAYA-MODEL-CARD.md identifica el modelo incluido y enlaza su ficha original; "
        "sus resultados no constituyen una medición de Umbral.\n\n"
        "Electron/Chromium: LICENSE.electron.txt y LICENSES.chromium.html en la carpeta de la aplicación. "
        "Las licencias de las dependencias Python se conservan en sus carpetas dist-info del motor incluido.\n",
        encoding="utf-8")
    snapshot_dir = snapshot_dir or ROOT / "data/snapshots" / (ROOT / "data/snapshots/CURRENT").read_text().strip()
    state = load_verified(snapshot_dir)
    if state["manifest"]["classifier"]["classifier"] != "laya":
        raise ValueError("La entrega exige snapshot de Laya real, sin sustitución baseline.")
    if model_dir is None:
        configured = os.environ.get("UMBRAL_LAYA_MODEL_DIR")
        if not configured:
            raise ValueError("El empaquetado requiere el artefacto Laya calibrado exacto con --model o UMBRAL_LAYA_MODEL_DIR.")
        model_dir = Path(configured)
    model_dir = model_dir.resolve()
    required = ("model.safetensors", "rl_agent_config.json", "encoder/config.json", "tokenizer/tokenizer.json",
                "tokenizer/tokenizer_config.json", "umbral-model.json", PROFILE_NAME)
    for name in required:
        if not (model_dir / name).is_file():
            raise ValueError(f"Falta un recurso del modelo fijado: {name}")
    model_version = resolve_model_version(model_dir, "")
    active_profile = load_profile(model_version, model_dir, use_environment=False)
    if active_profile is None or not active_profile.sha256:
        raise ValueError("El empaquetado exige un perfil Laya calibrado y ligado a los pesos incluidos.")
    classifier = state["manifest"].get("classifier", {})
    require_calibrated_classifier_binding(classifier, model_version, active_profile)
    predictions = state["predictions"]
    expected_count = state["manifest"].get("counts", {}).get("articlesValid")
    if (len(predictions) != expected_count or any(
            row.get("calibrated") is not True
            or row.get("modelVersion") != model_version
            or row.get("calibrationProfileId") != active_profile.profile_id
            for row in predictions)):
        raise ValueError("Las predicciones del snapshot no usan el perfil Laya calibrado incluido.")
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
    shutil.copyfile(model_metadata, staged_metadata)
    calibration_profile = model_dir / PROFILE_NAME
    staged_profile = destination / PROFILE_NAME
    shutil.copyfile(calibration_profile, staged_profile)
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
    if active_profile is None or active_model_version != model_version:
        raise ValueError("El modelo calibrado cambió durante la preparación del paquete.")
    manifest = {"version": 1, "createdAt": iso_z(now_utc()), "snapshotId": snapshot_dir.name,
                "layaRevision": PINNED_REVISION, "modelWeightsSha256": sha256_file(destination / "model.safetensors"),
                "modelVersion": active_model_version,
                "calibrated": True,
                "calibrationProfileId": active_profile.profile_id,
                "calibrationProfileSha256": sha256_file(staged_profile),
                "calibrationTemperature": active_profile.temperature,
                "calibrationThreshold": active_profile.threshold,
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
    firebase_values = {}
    firebase_file = ROOT / "apps/web/.env.firebase"
    if firebase_file.is_file():
        for line in firebase_file.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"\s*(PUBLIC_FIREBASE_(?:API_KEY|AUTH_DOMAIN|PROJECT_ID|APP_ID))\s*=\s*(.*?)\s*$", line)
            if match:
                value = match.group(2).strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                elif " #" in value:
                    value = value.split(" #", 1)[0].rstrip()
                firebase_values[match.group(1)] = value
    for name in ("PUBLIC_FIREBASE_API_KEY", "PUBLIC_FIREBASE_AUTH_DOMAIN", "PUBLIC_FIREBASE_PROJECT_ID", "PUBLIC_FIREBASE_APP_ID"):
        firebase_values[name] = os.environ.get(name, firebase_values.get(name, "")).strip()
    required_firebase = ("PUBLIC_FIREBASE_API_KEY", "PUBLIC_FIREBASE_AUTH_DOMAIN", "PUBLIC_FIREBASE_PROJECT_ID", "PUBLIC_FIREBASE_APP_ID")
    if any(firebase_values.values()):
        if not all(firebase_values.get(name) for name in required_firebase):
            raise ValueError("La configuración pública de Firebase Auth está incompleta; completa las cuatro variables PUBLIC_FIREBASE_*.")
        manifest["firebaseConfig"] = {
            "apiKey": firebase_values["PUBLIC_FIREBASE_API_KEY"],
            "authDomain": firebase_values["PUBLIC_FIREBASE_AUTH_DOMAIN"],
            "projectId": firebase_values["PUBLIC_FIREBASE_PROJECT_ID"],
            "appId": firebase_values["PUBLIC_FIREBASE_APP_ID"],
        }
    (staging / "bundle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"snapshotId": snapshot_dir.name, "modelBytes": sum((destination / name).stat().st_size for name in required),
                      "bundleManifestSha256": sha256_file(staging / "bundle-manifest.json")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    stage(args.snapshot, args.model)
