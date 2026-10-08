"""Precision@5 of agenda topics against independent reviewed topic IDs."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from label_provenance import evaluation_kind, verified_manifest
from umbral_pipeline.evalkit.metrics import precision_at_k
from umbral_pipeline.util import read_jsonl, sha256_file, write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--ranking", type=Path, required=True, help="JSON /topics: snapshotId,rulesVersion,items")
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    manifest = verified_manifest(a.snapshot)
    ranking = json.loads(a.ranking.read_text(encoding="utf-8"))
    if ranking["snapshotId"] != manifest["snapshotId"]:
        raise ValueError("Agenda y snapshot tienen IDs distintos")
    topic_ids = {r["clusterId"] for r in read_jsonl(a.snapshot / "clusters.jsonl")}
    ranked = [r["id"] for r in ranking["items"]][:5]
    if len(set(ranked)) != len(ranked) or not set(ranked) <= topic_ids:
        raise ValueError("Agenda con IDs desconocidos o duplicados")
    labels = [r for r in read_jsonl(a.labels) if r.get("relevantTopicIds") is not None]
    for row in labels:
        if row.get("snapshotId") != manifest["snapshotId"] or row.get("rulesVersion") != ranking["rulesVersion"]:
            raise ValueError("Juicio editorial de otro snapshot/rulesVersion")
        if not set(row["relevantTopicIds"]) <= topic_ids:
            raise ValueError("Juicio editorial cita tema inexistente")
    scores = [precision_at_k(ranked, set(row["relevantTopicIds"]), 5) for row in labels]
    write_json(a.out, {"command": " ".join(sys.argv), "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "snapshotId": manifest["snapshotId"], "rulesVersion": ranking["rulesVersion"],
                       "evaluationKind": evaluation_kind(labels), "judgments": len(labels),
                       "precisionAt5": sum(scores) / len(scores) if scores else None,
                       "manifestSha256": manifest["manifestSha256"], "rankingSha256": sha256_file(a.ranking),
                       "labelsSha256": sha256_file(a.labels), "evaluatorSha256": sha256_file(Path(__file__)),
                       "note": "Juicios independientes de agenda; no confundir con recuperación de noticias."})
    print(f"agenda juicios={len(labels)}; provenance={evaluation_kind(labels)} -> {a.out}")


if __name__ == "__main__":
    main()
