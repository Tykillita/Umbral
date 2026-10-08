"""Apply an approved Laya profile to saved logits and export a candidate snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from umbral_pipeline.classify.calibration import load_profile, resolve_model_version
from umbral_pipeline.classify.laya_clf import PINNED_REVISION, decide_category
from umbral_pipeline.config import CATEGORIES, INDETERMINATE
from umbral_pipeline.refresh import load_verified, rules_hash
from umbral_pipeline.snapshot import export_snapshot, verify_snapshot
from umbral_pipeline.util import iso_z, now_utc, parse_dt, sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-snapshot", type=Path, required=True,
                        help="Snapshot del modelo seleccionado con calibrationLogits y sin perfil aplicado")
    parser.add_argument("--model-dir", type=Path, required=True,
                        help="Checkpoint seleccionado con umbral-calibration.json aprobado")
    parser.add_argument("--output-data-dir", type=Path, required=True,
                        help="Raíz aislada para el nuevo snapshot candidato")
    parser.add_argument("--out", type=Path, help="Recibo JSON opcional")
    args = parser.parse_args()

    raw_snapshot = args.raw_snapshot.resolve()
    model_dir = args.model_dir.resolve()
    output = args.output_data_dir.resolve()
    if not raw_snapshot.is_dir() or not (raw_snapshot / "manifest.json").is_file():
        raise ValueError(f"No existe el snapshot de logits: {raw_snapshot}")
    if not (model_dir / "model.safetensors").is_file():
        raise ValueError(f"Faltan los pesos Laya seleccionados: {model_dir}")
    if output == raw_snapshot or output in raw_snapshot.parents or raw_snapshot in output.parents:
        raise ValueError("La raíz de salida debe estar aislada del snapshot de entrada")
    snapshots_root = output / "snapshots"
    if snapshots_root.exists() and any(snapshots_root.iterdir()):
        raise FileExistsError(f"La salida ya contiene snapshots; usa una raíz nueva: {snapshots_root}")

    model_version = resolve_model_version(model_dir, PINNED_REVISION)
    profile = load_profile(model_version, model_dir, use_environment=False)
    if profile is None:
        raise ValueError("El checkpoint no tiene un perfil que haya superado el test gate")
    os.environ["UMBRAL_LAYA_MODEL_DIR"] = str(model_dir)
    state = load_verified(raw_snapshot)
    source_manifest = state["manifest"]
    source_classifier = source_manifest["classifier"]
    if source_classifier.get("modelVersion") != model_version:
        raise ValueError("Los logits pertenecen a otra versión del modelo")
    if source_classifier.get("calibrated") is not False:
        raise ValueError("El snapshot de entrada ya está calibrado o no declara su estado crudo")

    expected_keys = set(CATEGORIES) | {"otro"}
    predictions = []
    for source in state["predictions"]:
        logits = source.get("calibrationLogits")
        if not isinstance(logits, dict) or set(logits) != expected_keys:
            raise ValueError(f"{source.get('articleId')}: faltan logits crudos completos")
        if source.get("calibrated") is not False or source.get("calibratedProbabilities") is not None:
            raise ValueError(f"{source.get('articleId')}: se rechaza aplicar temperatura dos veces")
        calibrated_choice = profile.apply_logits(logits)
        calibrated = {category: round(float(calibrated_choice[category]), 6) for category in CATEGORIES}
        calibrated[INDETERMINATE] = round(float(calibrated_choice["otro"]), 6)
        category, probability = decide_category(calibrated_choice, profile.threshold)
        predictions.append({
            **source,
            "category": category,
            "probability": round(probability, 6),
            "calibratedProbabilities": calibrated,
            "threshold": profile.threshold,
            "calibrated": True,
            "calibrationProfileId": profile.profile_id,
        })

    classifier_info = {
        **source_classifier,
        "threshold": profile.threshold,
        "calibrated": True,
        "calibrationProfileId": profile.profile_id,
        "calibrationProfileSha256": profile.sha256,
        "calibrationTemperature": profile.temperature,
        "rulesHash": rules_hash(),
        "note": "Temperature scaling validado; las probabilidades crudas se conservan para auditoría.",
    }
    quality = dict(state["quality"])
    quality["generatedAt"] = iso_z(now_utc())
    quality["classification"] = {
        **quality.get("classification", {}),
        "byCategory": dict(Counter(row["category"] for row in predictions)),
        "indeterminate": sum(row["category"] == INDETERMINATE for row in predictions),
    }
    candidate = export_snapshot(
        output,
        cutoff=parse_dt(source_manifest["cutoffUtc"]),
        window=source_manifest["window"],
        queries=source_manifest["queries"],
        articles=state["articles"],
        indicators=state["indicators"],
        predictions=predictions,
        clusters=state["clusters"],
        invalid=state["invalid"],
        quality=quality,
        classifier_info=classifier_info,
        events_geojson=state["events"],
        contains_fixtures=source_manifest["containsFixtures"],
        provisional_reasons=source_manifest["provisionalReasons"],
        sources_extracted={row["id"]: row.get("extractedAt") for row in source_manifest["sources"]},
        transformations=[*source_manifest["transformations"], "laya_temperature_scaling"],
        version=source_manifest["version"],
        set_current=False,
    )
    ok, problems = verify_snapshot(candidate)
    if not ok:
        raise ValueError("Snapshot calibrado inválido: " + "; ".join(problems))
    result = load_verified(candidate)
    manifest = result["manifest"]
    calibrated_rows = result["predictions"]
    checks = {
        "snapshotVerified": ok,
        "allArticlesPredicted": len(calibrated_rows) == manifest["counts"]["articlesValid"],
        "classifierCalibrated": manifest["classifier"].get("calibrated") is True,
        "modelVersionMatches": manifest["classifier"].get("modelVersion") == model_version,
        "profileIdMatches": manifest["classifier"].get("calibrationProfileId") == profile.profile_id,
        "profileSha256Matches": manifest["classifier"].get("calibrationProfileSha256") == profile.sha256,
        "allPredictionsCalibrated": all(
            row.get("calibrated") is True
            and row.get("calibrationProfileId") == profile.profile_id
            and isinstance(row.get("calibratedProbabilities"), dict)
            and math.isclose(sum(row["calibratedProbabilities"].values()), 1.0, abs_tol=1e-5)
            and math.isclose(float(row.get("threshold", -1)), profile.threshold, abs_tol=1e-9)
            for row in calibrated_rows
        ),
        "rawProbabilitiesPreserved": all(isinstance(row.get("probabilities"), dict) for row in calibrated_rows),
        "currentNotActivated": not (snapshots_root / "CURRENT").exists(),
        "noFixtures": manifest["containsFixtures"] is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Comprobaciones del snapshot calibrado fallidas: " + ", ".join(failed))

    receipt = {
        "schemaVersion": "1.0.0",
        "createdAtUtc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": " ".join(sys.argv),
        "rawSnapshotId": source_manifest["snapshotId"],
        "snapshotId": manifest["snapshotId"],
        "snapshotPath": str(candidate),
        "modelVersion": model_version,
        "weightsSha256": sha256_file(model_dir / "model.safetensors"),
        "calibrationProfileId": profile.profile_id,
        "calibrationProfileSha256": profile.sha256,
        "temperature": profile.temperature,
        "threshold": profile.threshold,
        "counts": manifest["counts"],
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
