"""Prepara o verifica el artefacto Laya que consumen los refrescos de producción."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from umbral_pipeline.classify.calibration import (
    PROFILE_NAME,
    load_profile,
    resolve_model_version,
)
from umbral_pipeline.classify.laya_clf import PINNED_REVISION, REPO, SUBFOLDER
from umbral_pipeline.snapshot import verify_snapshot
from umbral_pipeline.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]
BASE_SNAPSHOT_ID = "20261007-cfa338b6"
LABEL_SPLITS = ("train", "validation", "calibration", "test", "difficult")
EXPECTED_COUNTS = {"train": 448, "validation": 101, "calibration": 151, "test": 200, "difficult": 91}
ARTIFACT_RECEIPT = "umbral-production-artifact.json"


def _inside_production(path: Path) -> Path:
    resolved = path.resolve()
    production_root = (ROOT / ".production").resolve()
    if resolved == production_root or not resolved.is_relative_to(production_root):
        raise ValueError("Los artefactos temporales deben quedar debajo de .production/.")
    if path.is_symlink():
        raise ValueError("No se aceptan enlaces para el artefacto del modelo.")
    return resolved


def _split_bytes(lines: list[str]) -> bytes:
    """Serialize label splits with the CRLF format used by the audited fit."""
    text = "".join(lines).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\r\n").encode("utf-8")


def _load_inputs(snapshot: Path, labels: Path) -> tuple[dict, dict[str, list[str]], dict[str, str], str]:
    if snapshot.name != BASE_SNAPSHOT_ID or labels.name != "laya-agent-review-20261007-split.jsonl":
        raise ValueError("El entrenamiento de producción requiere el snapshot y las particiones fijadas de Laya.")
    valid, problems = verify_snapshot(snapshot)
    if not valid:
        raise ValueError("Snapshot base inválido: " + "; ".join(problems))
    base_manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if base_manifest["classifier"].get("modelVersion") != PINNED_REVISION:
        raise ValueError("El snapshot base no corresponde al checkpoint Laya fijado.")

    labels_sha = sha256_file(labels)
    labels_manifest_path = labels.with_suffix(".manifest.json")
    if not labels_manifest_path.is_file():
        raise ValueError("Falta el manifest de procedencia de las etiquetas particionadas.")
    labels_manifest = json.loads(labels_manifest_path.read_text(encoding="utf-8"))
    if (labels_manifest.get("snapshotId") != BASE_SNAPSHOT_ID
            or labels_manifest.get("outputLabelsSha256") != labels_sha
            or labels_manifest.get("labelMethod") != "agent_review"
            or labels_manifest.get("labeler") != "codex-agent"):
        raise ValueError("La procedencia de las particiones no coincide con el snapshot o sus etiquetas.")

    split_lines = {name: [] for name in LABEL_SPLITS}
    article_ids: set[str] = set()
    group_owners: dict[str, str] = {}
    for line in labels.read_text(encoding="utf-8").splitlines(keepends=True):
        if not line.strip():
            continue
        row = json.loads(line)
        article_id, group, split = row.get("articleId"), row.get("eventGroup"), row.get("split")
        if row.get("labelMethod") != "agent_review" or row.get("labeler") != "codex-agent":
            raise ValueError("Todas las particiones deben conservar la revisión de agente y su autoría.")
        if split not in split_lines or not article_id or not group:
            raise ValueError("Hay una etiqueta sin ID, grupo o partición válida.")
        if article_id in article_ids:
            raise ValueError("El archivo de particiones contiene articleId duplicados.")
        article_ids.add(article_id)
        owner = group_owners.setdefault(group, split)
        if owner != split:
            raise ValueError(f"El grupo de evento {group} cruza las particiones {owner} y {split}.")
        split_lines[split].append(line)

    counts = {name: len(rows) for name, rows in split_lines.items()}
    if counts != EXPECTED_COUNTS or labels_manifest.get("countsBySplit") != counts:
        raise ValueError(f"Tamaños de partición distintos al conjunto auditado: {counts}.")
    if len(article_ids) != base_manifest["counts"]["articlesValid"]:
        raise ValueError("Las etiquetas no cubren exactamente los titulares válidos del snapshot base.")
    split_hashes = {
        name: hashlib.sha256(_split_bytes(rows)).hexdigest()
        for name, rows in split_lines.items()
    }
    return base_manifest, split_lines, split_hashes, labels_sha


def _artifact_state(model_dir: Path, base_manifest: dict, split_hashes: dict[str, str],
                    labels_sha: str) -> dict:
    metadata_path = model_dir / "umbral-model.json"
    weights = model_dir / "model.safetensors"
    profile_path = model_dir / PROFILE_NAME
    if model_dir.is_symlink() or not all(p.is_file() and not p.is_symlink() for p in
                                         (metadata_path, weights, profile_path)):
        raise ValueError("El artefacto Laya debe incluir metadatos, pesos y perfil de calibración locales.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    model_version = resolve_model_version(model_dir, "")
    weights_sha = sha256_file(weights)
    if (metadata.get("baseRevision") != base_manifest["classifier"].get("modelVersion")
            or metadata.get("snapshotId") != BASE_SNAPSHOT_ID
            or metadata.get("labelsSha256") != labels_sha
            or metadata.get("weightsSha256") != weights_sha):
        raise ValueError("Los metadatos del artefacto no corresponden al conjunto fijado o a sus pesos.")
    profile = load_profile(model_version, model_dir, use_environment=False)
    if profile is None:
        raise ValueError("El artefacto no tiene un perfil calibrado para su versión exacta.")
    report = json.loads(profile_path.read_text(encoding="utf-8"))
    fit = report.get("fit", {})
    expected_fit_hashes = {
        "calibrationLabelsSha256": split_hashes["calibration"],
        "validationLabelsSha256": split_hashes["validation"],
        "testLabelsSha256": split_hashes["test"],
        "difficultLabelsSha256": split_hashes["difficult"],
    }
    if (fit.get("baselineSnapshotId") != BASE_SNAPSHOT_ID
            or fit.get("baseModelVersion") != base_manifest["classifier"].get("modelVersion")
            or fit.get("calibrationExamples") != EXPECTED_COUNTS["calibration"]
            or fit.get("validationExamples") != EXPECTED_COUNTS["validation"]
            or any(fit.get(key) != digest for key, digest in expected_fit_hashes.items())
            or (fit.get("testGate") or {}).get("passed") is not True):
        raise ValueError("El perfil no corresponde a las particiones de evaluación o no superó testGate.")
    return {
        "schemaVersion": "1.0.0",
        "baseSnapshotId": BASE_SNAPSHOT_ID,
        "baseModelVersion": base_manifest["classifier"]["modelVersion"],
        "labelsSha256": labels_sha,
        "splitCounts": EXPECTED_COUNTS,
        "modelVersion": model_version,
        "weightsSha256": weights_sha,
        "profileId": profile.profile_id,
        "profileSha256": profile.sha256,
        "temperature": profile.temperature,
        "threshold": profile.threshold,
        "calibrated": True,
        "testGatePassed": True,
    }


def _write_receipt(model_dir: Path, expected: dict) -> None:
    path = model_dir / ARTIFACT_RECEIPT
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != expected:
            raise ValueError("El recibo cacheado no coincide con el modelo verificado.")
        return
    temporary = model_dir / (ARTIFACT_RECEIPT + ".tmp")
    temporary.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_split_files(directory: Path, split_lines: dict[str, list[str]]) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for split, lines in split_lines.items():
        path = directory / f"{split}.jsonl"
        path.write_bytes(_split_bytes(lines))
        outputs[split] = path
    return outputs


def _run(command: list[str], *, log_path: Path | None = None) -> None:
    if log_path is None:
        subprocess.run(command, cwd=ROOT, check=True)
        return
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(command, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)


def _train(snapshot: Path, labels: Path, model_dir: Path, work_dir: Path,
           base_manifest: dict, split_lines: dict[str, list[str]], split_hashes: dict[str, str],
           labels_sha: str, threads: int) -> dict:
    if any(model_dir.iterdir()):
        raise ValueError("El directorio del modelo tiene contenido parcial; no se sobrescribe.")
    if work_dir.exists() and any(work_dir.iterdir()):
        raise ValueError("El directorio de trabajo ya contiene archivos; usa un checkout limpio.")
    work_dir.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import snapshot_download

    base_repo = Path(snapshot_download(repo_id=REPO, revision=PINNED_REVISION,
                                       allow_patterns=[f"{SUBFOLDER}/*"]))
    base_model = base_repo / SUBFOLDER
    if not (base_model / "model.safetensors").is_file():
        raise ValueError("No se pudo recuperar el checkpoint base fijado de Hugging Face.")

    training_dir = work_dir / "training"
    _run([sys.executable, str(ROOT / "eval/finetune_laya.py"),
          "--snapshot", str(snapshot), "--labels", str(labels), "--base-model", str(base_model),
          "--output-dir", str(training_dir), "--device", "cpu", "--micro-batch", "8",
          "--grad-accum", "8", "--max-len", "512", "--gradient-checkpointing", "--threads", str(threads)])
    selection = json.loads((training_dir / "selection.json").read_text(encoding="utf-8"))
    selected = selection.get("selected")
    if selected not in {"A", "B"} or selection.get("weightsSha256") is None:
        raise ValueError("El afinador no produjo una selección A/B verificable.")
    shutil.copytree(training_dir / f"variant-{selected}", model_dir, dirs_exist_ok=True)

    raw_root = work_dir / "calibration-snapshot"
    raw_receipt_path = work_dir / "raw-reclassify-receipt.json"
    _run([sys.executable, str(ROOT / "eval/reclassify_laya_snapshot.py"),
          "--snapshot", str(snapshot), "--model-dir", str(model_dir),
          "--output-data-dir", str(raw_root), "--allow-raw-logits", "--out", str(raw_receipt_path)],
         log_path=work_dir / "raw-reclassification.log")
    raw_receipt = json.loads(raw_receipt_path.read_text(encoding="utf-8"))
    raw_snapshot = Path(raw_receipt["snapshotPath"])
    if not raw_snapshot.resolve().is_relative_to(raw_root.resolve()):
        raise ValueError("El snapshot de evaluación salió del área temporal.")
    split_files = _write_split_files(work_dir / "label-splits", split_lines)
    _run([sys.executable, str(ROOT / "eval/fit_calibration.py"),
          "--snapshot", str(raw_snapshot), "--baseline-snapshot", str(snapshot),
          "--base-model-version", base_manifest["classifier"]["modelVersion"],
          "--calibration-labels", str(split_files["calibration"]),
          "--validation-labels", str(split_files["validation"]),
          "--test-labels", str(split_files["test"]), "--difficult-labels", str(split_files["difficult"]),
          "--model-version", selection["selectedModelVersion"], "--model-dir", str(model_dir),
          "--out", str(model_dir / PROFILE_NAME)])
    return _artifact_state(model_dir, base_manifest, split_hashes, labels_sha)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/snapshots" / BASE_SNAPSHOT_ID)
    parser.add_argument("--labels", type=Path,
                        default=ROOT / "eval/labels/laya-agent-review-20261007-split.jsonl")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.threads < 1:
        raise ValueError("--threads debe ser al menos 1.")
    snapshot = args.snapshot.resolve()
    labels = args.labels.resolve()
    model_dir = _inside_production(args.model_dir)
    work_dir = _inside_production(args.work_dir)
    if not snapshot.is_dir() or not labels.is_file():
        raise FileNotFoundError("Falta el snapshot base o el archivo particionado de etiquetas.")
    base_manifest, split_lines, split_hashes, labels_sha = _load_inputs(snapshot, labels)
    model_dir.mkdir(parents=True, exist_ok=True)
    if any(model_dir.iterdir()):
        state = _artifact_state(model_dir, base_manifest, split_hashes, labels_sha)
        _write_receipt(model_dir, state)
        print(json.dumps({**state, "cacheHit": True}, ensure_ascii=False))
        return 0
    state = _train(snapshot, labels, model_dir, work_dir, base_manifest,
                   split_lines, split_hashes, labels_sha, args.threads)
    _write_receipt(model_dir, state)
    print(json.dumps({**state, "cacheHit": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
