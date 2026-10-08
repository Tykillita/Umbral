"""Fine-tunea Laya con revisión agent_review y selecciona el prompt en validación."""

from __future__ import annotations

import argparse
import copy
import gc
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import laya
import torch
from label_provenance import verified_manifest
from laya.train import TrainConfig, finetune
from umbral_pipeline.classify import input_hash
from umbral_pipeline.classify.laya_clf import (
    CATEGORY_QUESTION_V1,
    CATEGORY_QUESTION_V1B,
)
from umbral_pipeline.config import CATEGORIES, INDETERMINATE
from umbral_pipeline.evalkit.metrics import macro_f1
from umbral_pipeline.util import read_jsonl, sha256_file

LABELS = [*CATEGORIES, INDETERMINATE]
LABEL_TO_OPTION = {**{key: key for key in CATEGORIES}, INDETERMINATE: "otro"}
VARIANTS = {"A": CATEGORY_QUESTION_V1, "B": CATEGORY_QUESTION_V1B}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True, help="Checkpoint multilingüe local, ya descargado")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--micro-batch", type=int, default=8)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--max-len", type=int)
    parser.add_argument("--gradient-checkpointing", action="store_true")
    parser.add_argument("--threads", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.micro_batch * args.grad_accum != 64:
        raise ValueError("micro-batch × grad-accum debe mantener el batch efectivo 64")
    if args.threads < 1:
        raise ValueError("--threads debe ser al menos 1")
    torch.set_num_threads(args.threads)

    manifest = verified_manifest(args.snapshot)
    articles = {row["articleId"]: row for row in read_jsonl(args.snapshot / "articles.jsonl")}
    source_labels = [row for row in read_jsonl(args.labels) if row.get("label")]
    labels = {row["articleId"]: row for row in source_labels}
    if len(labels) != len(source_labels):
        raise ValueError("El archivo de etiquetas contiene articleId duplicados")
    if not labels or any(row.get("labelMethod") != "agent_review" for row in labels.values()):
        raise ValueError("El entrenamiento exige etiquetas labelMethod=agent_review")
    if any(row.get("label") not in LABELS for row in labels.values()):
        raise ValueError("Hay etiquetas fuera del contrato de categorías")
    if not (args.base_model / "model.safetensors").is_file():
        raise ValueError("El checkpoint base local no contiene model.safetensors")

    group_by_article = {article_id: cluster["clusterId"]
                        for cluster in read_jsonl(args.snapshot / "clusters.jsonl")
                        for article_id in cluster["memberArticleIds"]}
    group_splits: dict[str, str] = {}
    for article_id, row in labels.items():
        split = row.get("split")
        if split not in {"train", "validation", "calibration", "test", "difficult"}:
            raise ValueError(f"{article_id}: partición inválida o ausente")
        group = group_by_article.get(article_id)
        if not group or row.get("eventGroup") != group:
            raise ValueError(f"{article_id}: eventGroup no coincide con clusters.jsonl")
        if group in group_splits and group_splits[group] != split:
            raise ValueError(f"El grupo de evento {group} aparece en más de una partición")
        group_splits[group] = split
        article = articles.get(article_id)
        if article is None or row.get("snapshotId") != manifest["snapshotId"]:
            raise ValueError(f"{article_id}: etiqueta fuera del snapshot")
        if not row.get("inputHash") or row["inputHash"] != input_hash(article):
            raise ValueError(f"{article_id}: hash de entrada no corresponde al titular")

    train_rows = [(articles[key]["title"], row["label"])
                  for key, row in labels.items() if row["split"] == "train"]
    validation_rows = [(articles[key]["title"], row["label"])
                       for key, row in labels.items() if row["split"] == "validation"]
    if len(train_rows) < 400 or len(validation_rows) < 100:
        raise ValueError("Se requieren al menos 400 titulares train y 100 validation; objetivo de train: 450")
    train_classes = {label for _, label in train_rows}
    missing_classes = set(LABELS) - train_classes
    if missing_classes:
        raise ValueError(f"Faltan categorías en train: {sorted(missing_classes)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if (args.output_dir / "selection.json").exists():
        raise FileExistsError("El directorio de salida ya contiene selection.json; usa una ruta nueva")
    if any((args.output_dir / f"variant-{name}").exists() for name in VARIANTS):
        raise FileExistsError("El directorio de salida ya contiene una variante; usa una ruta nueva")

    config = TrainConfig(epochs=4, micro_batch=args.micro_batch, grad_accum=args.grad_accum,
                         encoder_lr=2.5e-5, head_lr=1e-4,
                         min_lr=1e-6, weight_decay=0.01, grad_clip=1.0, loss="soft-ce", seed=0,
                         calib_max=0, calib_frac=0.0, text_column="text", label_column="label",
                         question_id="category", max_len=args.max_len,
                         gradient_checkpointing=args.gradient_checkpointing)
    runs = {}
    with tempfile.TemporaryDirectory(prefix="laya-train-", dir=args.output_dir) as temp_name:
        temp = Path(temp_name)
        for variant, question_set in VARIANTS.items():
            question = copy.deepcopy(question_set["category"])
            data_path = temp / f"train-{variant}.jsonl"
            with data_path.open("w", encoding="utf-8", newline="\n") as stream:
                for text, label in train_rows:
                    option = LABEL_TO_OPTION[label]
                    row = {"state": text, "questions": {"category": question},
                           "gold": {"category": {"probabilities": {option: 1.0}}}}
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            out = args.output_dir / f"variant-{variant}"
            result = finetune(str(data_path), str(args.base_model), str(out), config=config, device=args.device)
            model = laya.load(str(out), device=args.device)
            truth, predicted, losses = [], [], []
            for title, label in validation_rows:
                answer = model.predict(title, {"category": question})["answers"]["category"]
                raw = answer["probabilities"]
                winner = max(raw, key=raw.get)
                category = LABEL_TO_OPTION.get(label)
                predicted.append(winner if winner in CATEGORIES and raw[winner] >= 0.5 else INDETERMINATE)
                truth.append(label)
                losses.append(-math.log(max(float(raw.get(category, 0.0)), 1e-12)))
            score = {"macroF1": macro_f1(truth, predicted, LABELS),
                     "nll": sum(losses) / len(losses), "validationExamples": len(validation_rows),
                     "trainExamples": len(train_rows), "layaTraining": result}
            runs[variant] = score
            # `laya.load` keeps the full encoder alive after validation. Release it
            # before the next variant so CPU-only runs do not retain two checkpoints.
            del model, result
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    selected = min(VARIANTS, key=lambda variant: (-runs[variant]["macroF1"], runs[variant]["nll"], variant))
    selected_dir = args.output_dir / f"variant-{selected}"
    weights_hash = sha256_file(selected_dir / "model.safetensors")
    model_version = "laya-ft-" + weights_hash[:16]
    metadata = {"schemaVersion": "1.0.0", "modelVersion": model_version,
                "baseRevision": manifest["classifier"].get("modelVersion"),
                "weightsSha256": weights_hash, "promptVariant": selected, "selectedBy": "validation-macroF1-then-NLL",
                "evaluationKind": "agent_review", "snapshotId": manifest["snapshotId"],
                "labelsSha256": sha256_file(args.labels), "config": config.__dict__,
                "createdAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (selected_dir / "umbral-model.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    report = {"selected": selected, "selectedModelVersion": model_version,
              "evaluationKind": "agent_review", "runs": runs, "weightsSha256": weights_hash,
              "labelsSha256": sha256_file(args.labels), "createdAt": metadata["createdAt"]}
    (args.output_dir / "selection.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    print(json.dumps({"selected": selected, "modelVersion": model_version,
                      "validation": runs[selected], "outputDir": str(selected_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
