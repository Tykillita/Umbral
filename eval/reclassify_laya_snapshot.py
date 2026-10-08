"""Build a verified Laya candidate snapshot without activating CURRENT."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from umbral_pipeline.classify.calibration import load_profile, resolve_model_version
from umbral_pipeline.classify.laya_clf import PINNED_REVISION
from umbral_pipeline.refresh import load_verified, run_reclassify
from umbral_pipeline.snapshot import verify_snapshot
from umbral_pipeline.util import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="Snapshot de entrada con artículos reales")
    parser.add_argument("--model-dir", type=Path, required=True, help="Checkpoint seleccionado y perfil de calibración")
    parser.add_argument("--output-data-dir", type=Path, required=True, help="Raíz aislada para el snapshot candidato")
    parser.add_argument("--allow-raw-logits", action="store_true",
                        help="Permite crear un snapshot sin perfil para calibrarlo después")
    parser.add_argument("--out", type=Path, help="Recibo JSON opcional")
    args = parser.parse_args()

    source = args.snapshot.resolve()
    model_dir = args.model_dir.resolve()
    output = args.output_data_dir.resolve()
    if not source.is_dir() or not (source / "manifest.json").is_file():
        raise ValueError(f"El snapshot de entrada no existe o no es verificable: {source}")
    if not (model_dir / "model.safetensors").is_file():
        raise ValueError(f"Faltan los pesos de Laya seleccionados: {model_dir}")
    if output == source or output in source.parents or source in output.parents:
        raise ValueError("La raíz de salida debe estar aislada del snapshot de entrada")
    snapshots_root = output / "snapshots"
    if snapshots_root.exists() and any(snapshots_root.iterdir()):
        raise FileExistsError(f"La salida ya contiene snapshots; usa una raíz nueva: {snapshots_root}")

    model_version = resolve_model_version(model_dir, PINNED_REVISION)
    profile = load_profile(model_version, model_dir, use_environment=False)
    if profile is None and not args.allow_raw_logits:
        raise ValueError("El checkpoint no incluye un perfil de calibración aprobado")
    os.environ["UMBRAL_LAYA_MODEL_DIR"] = str(model_dir)

    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate = run_reclassify(output, source, set_current=False)
    ok, problems = verify_snapshot(candidate)
    if not ok:
        raise ValueError("Snapshot candidato inválido: " + "; ".join(problems))
    state = load_verified(candidate)
    manifest = state["manifest"]
    classifier = manifest["classifier"]
    predictions = state["predictions"]
    checks = {
        "snapshotVerified": ok,
        "allArticlesPredicted": len(predictions) == manifest["counts"]["articlesValid"],
        "modelVersionMatches": classifier.get("modelVersion") == model_version,
        "currentNotActivated": not (snapshots_root / "CURRENT").exists(),
        "noFixtures": manifest["containsFixtures"] is False,
    }
    if profile is not None:
        checks.update({
            "classifierCalibrated": classifier.get("calibrated") is True,
            "profileIdMatches": classifier.get("calibrationProfileId") == profile.profile_id,
            "profileSha256Matches": classifier.get("calibrationProfileSha256") == profile.sha256,
            "allPredictionsCalibrated": all(
                p.get("calibrated") is True and p.get("calibrationProfileId") == profile.profile_id
                and isinstance(p.get("calibratedProbabilities"), dict)
                and math.isclose(sum(p["calibratedProbabilities"].values()), 1.0, abs_tol=1e-5)
                and math.isclose(float(p.get("threshold", -1)), profile.threshold, abs_tol=1e-9)
                for p in predictions
            ),
        })
    else:
        checks.update({
            "classifierUncalibrated": classifier.get("calibrated") is False,
            "rawLogitsCaptured": all(isinstance(p.get("calibrationLogits"), dict) for p in predictions),
            "noCalibrationProfile": classifier.get("calibrationProfileId") is None,
        })
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Comprobaciones de snapshot fallidas: " + ", ".join(failed))

    receipt = {
        "schemaVersion": "1.0.0",
        "startedAtUtc": started,
        "finishedAtUtc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": " ".join(sys.argv),
        "sourceSnapshotId": load_verified(source)["manifest"]["snapshotId"],
        "snapshotId": manifest["snapshotId"],
        "snapshotPath": str(candidate),
        "modelVersion": model_version,
        "weightsSha256": sha256_file(model_dir / "model.safetensors"),
        "calibrated": profile is not None,
        "calibrationProfileId": profile.profile_id if profile else None,
        "calibrationProfileSha256": profile.sha256 if profile else None,
        "threshold": profile.threshold if profile else classifier.get("threshold"),
        "temperature": profile.temperature if profile else None,
        "counts": manifest["counts"],
        "classifier": classifier,
        "checks": checks,
        "result": "passed",
    }
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = args.out.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(encoded, encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
