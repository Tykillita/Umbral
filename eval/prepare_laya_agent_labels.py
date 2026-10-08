"""Valida etiquetas agent_review y separa eventos sin cruzar grupos entre conjuntos."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from umbral_pipeline.classify import input_hash
from umbral_pipeline.config import CATEGORIES, INDETERMINATE
from umbral_pipeline.util import read_jsonl, sha256_file

LABELS = {*CATEGORIES, INDETERMINATE}
TARGETS = {"train": 450, "validation": 100, "calibration": 150, "test": 200, "difficult": 91}
SPLIT_ORDER = ("train", "validation", "calibration", "test")
SEED = "umbral-laya-agent-review-split-v1"


def stable_key(value: str) -> str:
    return hashlib.sha256(f"{SEED}:{value}".encode()).hexdigest()


def choose_difficult_groups(group_members: dict[str, list[str]], labels: dict[str, dict]) -> set[str]:
    candidates = [group for group, members in group_members.items()
                  if any(labels[article_id].get("difficulty") == "difficult" for article_id in members)]
    candidates.sort(key=lambda group: (
        -sum(labels[article_id].get("difficulty") == "difficult" for article_id in group_members[group])
        / len(group_members[group]),
        -sum(labels[article_id].get("difficulty") == "difficult" for article_id in group_members[group]),
        stable_key(group),
    ))
    cap = TARGETS["difficult"] + max((len(group_members[group]) for group in candidates), default=0)
    reachable: dict[int, tuple[str, ...]] = {0: ()}
    for group in candidates:
        size = len(group_members[group])
        for total, selected in list(reachable.items())[::-1]:
            new_total = total + size
            if new_total <= cap and new_total not in reachable:
                reachable[new_total] = (*selected, group)
    selected_total = min(reachable, key=lambda total: (abs(total - TARGETS["difficult"]), total > TARGETS["difficult"], total))
    selected = set(reachable[selected_total])
    if selected_total == 0:
        raise ValueError("No hay suficientes grupos ambiguos para el conjunto difícil")
    return selected


def assign_remaining_groups(
    group_members: dict[str, list[str]], labels: dict[str, dict], groups: set[str]
) -> dict[str, str]:
    counts = Counter(labels[article_id]["label"] for group in groups for article_id in group_members[group])
    size_total = sum(len(group_members[group]) for group in groups)
    requested = sum(TARGETS[split] for split in SPLIT_ORDER)
    size_targets = {split: size_total * TARGETS[split] / requested for split in SPLIT_ORDER}
    label_targets = {
        split: {label: counts[label] * TARGETS[split] / requested for label in LABELS}
        for split in SPLIT_ORDER
    }
    current_size = Counter()
    current_labels = {split: Counter() for split in SPLIT_ORDER}
    class_totals = Counter(counts)

    def group_priority(group: str) -> tuple[float, int, str]:
        group_counts = Counter(labels[article_id]["label"] for article_id in group_members[group])
        rarity = sum(group_counts[label] / max(1, class_totals[label]) for label in group_counts)
        return (-rarity, -len(group_members[group]), stable_key(group))

    result = {}
    for group in sorted(groups, key=group_priority):
        members = group_members[group]
        group_counts = Counter(labels[article_id]["label"] for article_id in members)

        def placement_cost(split: str, group_size: int = len(members), category_counts=group_counts) -> float:
            before = current_size[split] - size_targets[split]
            after = current_size[split] + group_size - size_targets[split]
            cost = (after * after - before * before) / max(1.0, size_targets[split])
            for label in LABELS:
                before_label = current_labels[split][label] - label_targets[split][label]
                after_label = current_labels[split][label] + category_counts[label] - label_targets[split][label]
                cost += (after_label * after_label - before_label * before_label) / max(
                    1.0, label_targets[split][label]
                )
            return cost

        split = min(SPLIT_ORDER, key=lambda value: (placement_cost(value), SPLIT_ORDER.index(value)))
        result[group] = split
        current_size[split] += len(members)
        current_labels[split].update(group_counts)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True, help="Etiquetas agent_review sin particiones")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("snapshotId") != args.snapshot.name:
        raise ValueError("El nombre de carpeta no coincide con el snapshotId")
    if sha256_file(args.snapshot / "articles.jsonl") != manifest["files"]["articles.jsonl"]["sha256"]:
        raise ValueError("articles.jsonl no coincide con el manifiesto")
    if sha256_file(args.snapshot / "clusters.jsonl") != manifest["files"]["clusters.jsonl"]["sha256"]:
        raise ValueError("clusters.jsonl no coincide con el manifiesto")
    articles = list(read_jsonl(args.snapshot / "articles.jsonl"))
    article_by_id = {article["articleId"]: article for article in articles}
    source_rows = list(read_jsonl(args.labels))
    labels = {row["articleId"]: row for row in source_rows}
    if len(labels) != len(source_rows):
        raise ValueError("El archivo de revisión contiene articleId duplicados")
    if set(labels) != set(article_by_id):
        raise ValueError(
            f"Las etiquetas deben cubrir exactamente el snapshot: faltan {len(set(article_by_id) - set(labels))}, "
            f"sobran {len(set(labels) - set(article_by_id))}"
        )
    if any(row.get("labelMethod") != "agent_review" or row.get("labeler") != "codex-agent" for row in labels.values()):
        raise ValueError("Cada etiqueta debe registrar labelMethod=agent_review y labeler=codex-agent")
    if any(row.get("label") not in LABELS for row in labels.values()):
        raise ValueError("Hay etiquetas fuera del contrato de categorías")

    group_members: dict[str, list[str]] = defaultdict(list)
    for cluster in read_jsonl(args.snapshot / "clusters.jsonl"):
        for article_id in cluster["memberArticleIds"]:
            group_members[cluster["clusterId"]].append(article_id)
    if {article_id for members in group_members.values() for article_id in members} != set(article_by_id):
        raise ValueError("clusters.jsonl no particiona exactamente los artículos")
    group_of = {article_id: group for group, members in group_members.items() for article_id in members}

    difficult_groups = choose_difficult_groups(group_members, labels)
    regular_groups = set(group_members) - difficult_groups
    regular_splits = assign_remaining_groups(group_members, labels, regular_groups)
    split_by_group = {**regular_splits, **{group: "difficult" for group in difficult_groups}}

    output_rows = []
    for article in articles:
        article_id = article["articleId"]
        source = labels[article_id]
        group = group_of[article_id]
        row = {
            "articleId": article_id,
            "label": source["label"],
            "labelMethod": "agent_review",
            "labeler": "codex-agent",
            "reviewBasis": "headline_only",
            "snapshotId": manifest["snapshotId"],
            "articlesSha256": manifest["files"]["articles.jsonl"]["sha256"],
            "inputHash": input_hash(article),
            "eventGroup": group,
            "split": split_by_group[group],
        }
        if source.get("difficulty") == "difficult":
            row["difficulty"] = "difficult"
            row["reviewNote"] = "El titular por sí solo deja ambigua la frontera entre categorías cercanas."
        output_rows.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report_path = args.out.with_suffix(".manifest.json")
    if args.out.exists() or report_path.exists():
        raise FileExistsError(f"No se sobrescribe un archivo existente: {args.out} o {report_path}")
    args.out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output_rows), encoding="utf-8")
    split_counts = Counter(row["split"] for row in output_rows)
    support = {
        split: dict(Counter(row["label"] for row in output_rows if row["split"] == split))
        for split in (*SPLIT_ORDER, "difficult")
    }
    report = {
        "schemaVersion": "1.0.0",
        "snapshotId": manifest["snapshotId"],
        "sourceArticlesSha256": manifest["files"]["articles.jsonl"]["sha256"],
        "sourceReviewLabelsSha256": sha256_file(args.labels),
        "outputLabelsSha256": sha256_file(args.out),
        "labelMethod": "agent_review",
        "labeler": "codex-agent",
        "reviewBasis": "headline_only",
        "groupSplitSeed": SEED,
        "createdAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(output_rows),
        "eventGroups": len(group_members),
        "groupsBySplit": {split: len({row["eventGroup"] for row in output_rows if row["split"] == split})
                          for split in (*SPLIT_ORDER, "difficult")},
        "countsBySplit": dict(split_counts),
        "supportByClassAndSplit": support,
        "interpretation": "Acuerdo con revisión de IA sobre titulares; no equivale a validación humana/editorial.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"labels": str(args.out), "manifest": str(report_path),
                      "countsBySplit": dict(split_counts), "eventGroups": len(group_members)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
