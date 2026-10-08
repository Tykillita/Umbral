"""Ajusta temperatura y umbral con conjuntos separados y etiquetas agent_review."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from umbral_pipeline.classify.calibration import PROFILE_NAME, resolve_model_version
from umbral_pipeline.config import CATEGORIES, INDETERMINATE
from umbral_pipeline.evalkit.metrics import (
    accuracy,
    macro_f1,
    prf_per_class,
    probability_quality,
)
from umbral_pipeline.snapshot import verify_snapshot
from umbral_pipeline.util import read_jsonl, sha256_file

LABELS = [*CATEGORIES, INDETERMINATE]


def load_labels(path: Path, expected_split: str) -> dict[str, dict]:
    source_rows = [row for row in read_jsonl(path) if row.get("label")]
    rows = {row["articleId"]: row for row in source_rows}
    if len(rows) != len(source_rows):
        raise ValueError(f"{path}: hay articleId duplicados")
    if not rows or any(row.get("labelMethod") != "agent_review" for row in rows.values()):
        raise ValueError(f"{path}: se requieren etiquetas con labelMethod=agent_review")
    if any(row["label"] not in LABELS for row in rows.values()):
        raise ValueError(f"{path}: etiqueta inválida")
    if any(row.get("split") != expected_split for row in rows.values()):
        raise ValueError(f"{path}: todas las etiquetas deben pertenecer a split={expected_split}")
    if any(not row.get("inputHash") or not row.get("eventGroup") for row in rows.values()):
        raise ValueError(f"{path}: cada etiqueta requiere inputHash y eventGroup")
    return rows


def validate_partition_groups(
    label_sets: dict[str, dict[str, dict]],
    reference_groups: dict[str, str],
    candidate_groups: dict[str, str],
) -> None:
    """Keep source event groups disjoint and reject candidate clusters crossing splits."""
    reference_owners: dict[str, str] = {}
    candidate_owners: dict[str, str] = {}
    for split_name, split_rows in label_sets.items():
        for article_id, label in split_rows.items():
            reference_group = reference_groups.get(article_id)
            if not reference_group or label.get("eventGroup") != reference_group:
                raise ValueError(f"{article_id}: eventGroup no coincide con el snapshot base")
            candidate_group = candidate_groups.get(article_id)
            if not candidate_group:
                raise ValueError(f"{article_id}: falta el clúster del snapshot candidato")
            previous_split = reference_owners.setdefault(reference_group, split_name)
            if previous_split != split_name:
                raise ValueError(f"El grupo de evento del snapshot base se comparte entre {previous_split} y {split_name}")
            previous_split = candidate_owners.setdefault(candidate_group, split_name)
            if previous_split != split_name:
                raise ValueError(f"Un clúster candidato cruza las particiones {previous_split} y {split_name}")


def softmax_temperature(logits: dict[str, float], temperature: float) -> dict[str, float]:
    scaled = {key: float(value) / temperature for key, value in logits.items()}
    peak = max(scaled.values())
    weights = {key: math.exp(value - peak) for key, value in scaled.items()}
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def nll(rows: list[tuple[dict[str, float], str]], temperature: float) -> float:
    return -sum(math.log(max(softmax_temperature(probs, temperature).get(label, 0.0), 1e-12))
                 for probs, label in rows) / len(rows)


def brier(rows: list[tuple[dict[str, float], str]], temperature: float) -> float:
    values = []
    for logits, gold in rows:
        probabilities = softmax_temperature(logits, temperature)
        values.append(sum((probabilities[label] - int(gold == label)) ** 2 for label in LABELS))
    return sum(values) / len(values)


def prediction_from_logits(logits: dict[str, float], temperature: float, threshold: float) -> dict:
    probabilities = softmax_temperature(logits, temperature)
    best = max(CATEGORIES, key=lambda category: probabilities[category])
    category = best if probabilities[best] >= threshold else INDETERMINATE
    return {"category": category, "probability": probabilities[best], "probabilities": probabilities}


def classification_report(
    labels: dict[str, dict], predictions: dict[str, dict], ids: list[str], *, calibrated: bool
) -> dict:
    truth = [labels[article_id]["label"] for article_id in ids]
    predicted = [predictions[article_id]["category"] for article_id in ids]
    per_class = prf_per_class(truth, predicted, LABELS)
    within_gold = [index for index, label in enumerate(truth) if label in CATEGORIES]
    outside_gold = [index for index, label in enumerate(truth) if label == INDETERMINATE]
    within_recall = (sum(predicted[index] in CATEGORIES for index in within_gold) / len(within_gold)
                     if within_gold else None)
    outside_recall = (sum(predicted[index] == INDETERMINATE for index in outside_gold) / len(outside_gold)
                      if outside_gold else None)
    return {
        "n": len(ids),
        "macroF1": macro_f1(truth, predicted, LABELS),
        "accuracy": accuracy(truth, predicted),
        "perClass": per_class,
        "scopeErrors": sum(gold == INDETERMINATE and guess != INDETERMINATE
                            for gold, guess in zip(truth, predicted, strict=True)),
        "inScopeRecall": within_recall,
        "outOfScopeRecall": outside_recall,
        "probabilityQuality": probability_quality(
            truth, [predictions[article_id] for article_id in ids], LABELS, calibrated=calibrated),
    }


def choose_threshold(
    rows: list[tuple[dict[str, float], str]], *,
    minimum_in_scope_recall: float | None = None,
    minimum_out_of_scope_recall: float | None = None,
) -> tuple[float, dict]:
    best = None
    best_any = None
    for step in range(96):
        threshold = step / 100
        truth, predicted = [], []
        scope_errors = 0
        covered = 0
        for probs, label in rows:
            winner = max(probs, key=probs.get)
            category = winner if winner in CATEGORIES and probs[winner] >= threshold else INDETERMINATE
            truth.append(label)
            predicted.append(category)
            covered += category != INDETERMINATE
            scope_errors += label == INDETERMINATE and category != INDETERMINATE
        in_scope = [index for index, label in enumerate(truth) if label in CATEGORIES]
        out_of_scope = [index for index, label in enumerate(truth) if label == INDETERMINATE]
        in_scope_recall = (sum(predicted[index] in CATEGORIES for index in in_scope) / len(in_scope)
                           if in_scope else None)
        out_of_scope_recall = (sum(predicted[index] == INDETERMINATE for index in out_of_scope) / len(out_of_scope)
                               if out_of_scope else None)
        score = macro_f1(truth, predicted, LABELS)
        candidate = (score, -scope_errors, covered / len(rows), -threshold)
        metrics = {"macroF1": score, "scopeErrors": scope_errors, "coverage": covered / len(rows),
                   "inScopeRecall": in_scope_recall, "outOfScopeRecall": out_of_scope_recall}
        entry = (candidate, threshold, metrics)
        if best_any is None or candidate > best_any[0]:
            best_any = entry
        meets_scope_gates = (
            (minimum_in_scope_recall is None or in_scope_recall is not None
             and in_scope_recall >= minimum_in_scope_recall - 1e-9)
            and (minimum_out_of_scope_recall is None or out_of_scope_recall is not None
                 and out_of_scope_recall >= minimum_out_of_scope_recall - 1e-9)
        )
        if meets_scope_gates and (best is None or candidate > best[0]):
            best = entry
    selected = best or best_any
    assert selected is not None
    selected[2]["scopeGatePassed"] = best is not None
    return selected[1], selected[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--baseline-snapshot", type=Path, required=True,
                        help="Snapshot del checkpoint base sobre los mismos titulares")
    parser.add_argument("--base-model-version", required=True,
                        help="Versión base registrada antes del afinado")
    parser.add_argument("--calibration-labels", type=Path, required=True)
    parser.add_argument("--validation-labels", type=Path, required=True)
    parser.add_argument("--test-labels", type=Path, required=True)
    parser.add_argument("--difficult-labels", type=Path, required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--model-dir", type=Path, required=True,
                        help="Directorio del checkpoint ajustado que se usará en web y escritorio")
    parser.add_argument("--out", type=Path, required=True,
                        help="Guarda el perfil junto al checkpoint local; no lo publiques automáticamente")
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"No se sobrescribe un perfil existente: {args.out}")
    if not (args.model_dir / "model.safetensors").is_file():
        raise ValueError("--model-dir no contiene model.safetensors")
    if resolve_model_version(args.model_dir, "") != args.model_version:
        raise ValueError("--model-version no corresponde al checkpoint local")
    if args.out.resolve() != (args.model_dir / PROFILE_NAME).resolve():
        raise ValueError(f"--out debe ser {args.model_dir / PROFILE_NAME}")

    calibration = load_labels(args.calibration_labels, "calibration")
    validation = load_labels(args.validation_labels, "validation")
    test = load_labels(args.test_labels, "test")
    difficult = load_labels(args.difficult_labels, "difficult")
    label_sets = {"calibration": calibration, "validation": validation, "test": test, "difficult": difficult}
    all_ids: set[str] = set()
    for split_name, split_rows in label_sets.items():
        if all_ids & set(split_rows):
            raise ValueError(f"Los conjuntos comparten titulares al incorporar {split_name}")
        all_ids.update(split_rows)
    valid, problems = verify_snapshot(args.snapshot)
    if not valid:
        raise ValueError("Snapshot inválido: " + "; ".join(problems))
    snapshot_manifest = json.loads((args.snapshot / "manifest.json").read_text(encoding="utf-8"))
    snapshot_id = snapshot_manifest["snapshotId"]
    if snapshot_manifest["classifier"].get("modelVersion") != args.model_version:
        raise ValueError("--model-version no coincide con el modelo del snapshot")
    if snapshot_manifest["classifier"].get("classifier") != "laya":
        raise ValueError("El snapshot ajustado debe usar Laya")
    article_groups = {article_id: cluster["clusterId"] for cluster in read_jsonl(args.snapshot / "clusters.jsonl")
                      for article_id in cluster["memberArticleIds"]}

    predictions = {row["articleId"]: row for row in read_jsonl(args.snapshot / "predictions.jsonl")}
    baseline_valid, baseline_problems = verify_snapshot(args.baseline_snapshot)
    if not baseline_valid:
        raise ValueError("Snapshot base inválido: " + "; ".join(baseline_problems))
    baseline_manifest = json.loads((args.baseline_snapshot / "manifest.json").read_text(encoding="utf-8"))
    if baseline_manifest["classifier"].get("classifier") != "laya":
        raise ValueError("El snapshot base debe usar Laya")
    if baseline_manifest["classifier"].get("modelVersion") != args.base_model_version:
        raise ValueError("--base-model-version no coincide con el snapshot base")
    baseline_groups = {article_id: cluster["clusterId"] for cluster in read_jsonl(args.baseline_snapshot / "clusters.jsonl")
                       for article_id in cluster["memberArticleIds"]}
    baseline_predictions = {row["articleId"]: row for row in read_jsonl(args.baseline_snapshot / "predictions.jsonl")}
    validate_partition_groups(label_sets, baseline_groups, article_groups)

    def aligned(labels: dict[str, dict]) -> list[tuple[dict[str, float], str, str]]:
        result = []
        for article_id, label in labels.items():
            prediction = predictions.get(article_id)
            if prediction is None:
                raise ValueError(f"{article_id}: no hay predicción en el snapshot")
            if label["inputHash"] != prediction.get("inputHash"):
                raise ValueError(f"{article_id}: inputHash no corresponde al snapshot")
            group = baseline_groups.get(article_id)
            if not group or label["eventGroup"] != group:
                raise ValueError(f"{article_id}: eventGroup no coincide con el snapshot base")
            if not article_groups.get(article_id):
                raise ValueError(f"{article_id}: falta el clúster del snapshot candidato")
            raw_logits = prediction.get("calibrationLogits")
            if not raw_logits:
                raise ValueError(f"{article_id}: el snapshot no contiene calibrationLogits; vuelve a clasificar")
            if set(raw_logits) != {*CATEGORIES, "otro"}:
                raise ValueError(f"{article_id}: calibrationLogits debe contener las seis categorías y otro")
            values = {key: float(raw_logits["otro" if key == INDETERMINATE else key]) for key in LABELS}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError(f"{article_id}: logits inválidos")
            result.append((values, label["label"], group))
        if not result:
            raise ValueError("No hay titulares etiquetados en el snapshot")
        return result

    calibration_rows = aligned(calibration)
    validation_rows = aligned(validation)
    aligned(test)
    aligned(difficult)
    if len(calibration_rows) < 150 or len(validation_rows) < 100:
        raise ValueError("Se requieren al menos 150 etiquetas de calibración y 100 de validación")
    calibration_groups = {group for _, _, group in calibration_rows}
    validation_groups = {group for _, _, group in validation_rows}
    if calibration_groups & validation_groups:
        raise ValueError("Los conjuntos de calibración y validación comparten grupos de evento")
    candidates = [step / 100 for step in range(5, 1001, 5)]
    temperature = min(candidates, key=lambda value: (nll([(p, y) for p, y, _ in calibration_rows], value),
                                                       abs(value - 1), value))
    validation_pairs = [(p, y) for p, y, _ in validation_rows]
    raw_validation_quality = {"nll": nll(validation_pairs, 1.0), "brier": brier(validation_pairs, 1.0)}
    calibrated_validation_quality = {"nll": nll(validation_pairs, temperature),
                                    "brier": brier(validation_pairs, temperature)}
    improves = any(calibrated_validation_quality[key] < raw_validation_quality[key] - 1e-9
                   for key in ("nll", "brier"))
    regresses = any(calibrated_validation_quality[key] > raw_validation_quality[key] + 1e-9
                    for key in ("nll", "brier"))
    if not improves or regresses:
        raise ValueError("El ajuste no mejora NLL/Brier sin regresión en validación; no se escribe perfil")
    calibrated_validation = [(softmax_temperature(probs, temperature), label)
                             for probs, label, _ in validation_rows]
    validation_baseline: dict[str, dict] = {}
    for article_id, label in validation.items():
        base_pred = baseline_predictions.get(article_id)
        if base_pred is None:
            raise ValueError(f"{article_id}: falta predicción base de validación")
        if label["inputHash"] != base_pred.get("inputHash"):
            raise ValueError(f"{article_id}: el snapshot base tiene otro inputHash")
        if baseline_groups.get(article_id) != label["eventGroup"]:
            raise ValueError(f"{article_id}: eventGroup no coincide con el snapshot base")
        probabilities = base_pred.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != set(LABELS):
            raise ValueError(f"{article_id}: la predicción base no contiene las siete probabilidades")
        validation_baseline[article_id] = {"category": base_pred["category"],
                                           "probability": base_pred["probability"],
                                           "probabilities": probabilities}
    baseline_validation_metrics = classification_report(validation, validation_baseline,
                                                        list(validation), calibrated=False)
    threshold, validation_metrics = choose_threshold(
        calibrated_validation,
        minimum_in_scope_recall=baseline_validation_metrics["inScopeRecall"],
        minimum_out_of_scope_recall=baseline_validation_metrics["outOfScopeRecall"],
    )
    validation_metrics["baselineInScopeRecall"] = baseline_validation_metrics["inScopeRecall"]
    validation_metrics["baselineOutOfScopeRecall"] = baseline_validation_metrics["outOfScopeRecall"]

    def compare_split(split_labels: dict[str, dict]) -> dict:
        ids = list(split_labels)
        tuned: dict[str, dict] = {}
        baseline: dict[str, dict] = {}
        for article_id in ids:
            tuned_pred = predictions[article_id]
            base_pred = baseline_predictions.get(article_id)
            if base_pred is None:
                raise ValueError(f"{article_id}: falta predicción base")
            if split_labels[article_id]["inputHash"] != base_pred.get("inputHash"):
                raise ValueError(f"{article_id}: el snapshot base tiene otro inputHash")
            base_group = baseline_groups.get(article_id)
            if base_group != split_labels[article_id]["eventGroup"]:
                raise ValueError(f"{article_id}: eventGroup no coincide con el snapshot base")
            logits = {key: float(tuned_pred["calibrationLogits"]["otro" if key == INDETERMINATE else key])
                      for key in LABELS}
            tuned[article_id] = prediction_from_logits(logits, temperature, threshold)
            probabilities = base_pred.get("probabilities")
            if not isinstance(probabilities, dict) or set(probabilities) != set(LABELS):
                raise ValueError(f"{article_id}: la predicción base no contiene las siete probabilidades")
            baseline[article_id] = {"category": base_pred["category"],
                                    "probability": base_pred["probability"],
                                    "probabilities": probabilities}
        return {"baseline": classification_report(split_labels, baseline, ids, calibrated=False),
                "tunedCalibrated": classification_report(split_labels, tuned, ids, calibrated=True)}

    test_comparison = compare_split(test)
    difficult_comparison = compare_split(difficult)
    base_quality = test_comparison["baseline"]["probabilityQuality"]
    tuned_quality = test_comparison["tunedCalibrated"]["probabilityQuality"]
    quality_improved = any(tuned_quality[key] < base_quality[key] - 1e-9 for key in ("nll", "brier"))
    quality_regressed = any(tuned_quality[key] > base_quality[key] + 1e-9 for key in ("nll", "brier"))
    scope_regressed = any(
        tuned is not None and base is not None and tuned < base - 1e-9
        for key in ("inScopeRecall", "outOfScopeRecall")
        for base, tuned in [(test_comparison["baseline"][key], test_comparison["tunedCalibrated"][key])]
    )
    test_gate = {"passed": validation_metrics["scopeGatePassed"] and quality_improved
                          and not quality_regressed and not scope_regressed,
                 "qualityImproved": quality_improved, "qualityRegressed": quality_regressed,
                 "scopeRecallRegressed": scope_regressed,
                 "validationScopeGatePassed": validation_metrics["scopeGatePassed"]}
    created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = {"modelVersion": args.model_version, "baseModelVersion": args.base_model_version,
                "temperature": temperature, "threshold": threshold,
                "calibrationLabelsSha256": sha256_file(args.calibration_labels),
                "validationLabelsSha256": sha256_file(args.validation_labels),
                "testLabelsSha256": sha256_file(args.test_labels),
                "difficultLabelsSha256": sha256_file(args.difficult_labels),
                "snapshotId": snapshot_id}
    profile_id = "laya-cal-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    report = {"schemaVersion": "1.0.0", "profileId": profile_id, "modelVersion": args.model_version,
              "method": "temperature-scaling", "temperature": temperature, "threshold": threshold,
              "createdAt": created_at, "evaluationKind": "agent_review", "fit": {
                  **identity, "calibrationExamples": len(calibration_rows), "validationExamples": len(validation_rows),
                  "calibrationNll": nll([(p, y) for p, y, _ in calibration_rows], temperature),
                  "validationQualityRaw": raw_validation_quality,
                  "validationQualityCalibrated": calibrated_validation_quality,
                  "validation": validation_metrics,
                  "baselineModelVersion": args.base_model_version,
                  "baselineSnapshotId": baseline_manifest["snapshotId"],
                  "testComparison": test_comparison,
                  "difficultComparison": difficult_comparison,
                  "testGate": test_gate}}
    temporary = args.out.with_name(args.out.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"No se sobrescribe un temporal existente: {temporary}")
    evaluation_path = args.out.with_name(f"{profile_id}-evaluation.json")
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    if evaluation_path.exists():
        raise FileExistsError(f"No se sobrescribe un informe existente: {evaluation_path}")
    evaluation_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not test_gate["passed"]:
        raise ValueError(f"La prueba intacta no habilita el perfil; informe: {evaluation_path}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({"profileId": profile_id, "temperature": temperature, "threshold": threshold,
                      "validation": validation_metrics, "testGate": test_gate,
                      "out": str(args.out), "evaluation": str(evaluation_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
