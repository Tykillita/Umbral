"""Human support and structural factual citation coverage of reviewed claims."""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from label_provenance import evaluation_kind, verified_manifest
from umbral_pipeline.evalkit.metrics import ratio
from umbral_pipeline.util import read_jsonl, sha256_file, write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    manifest = verified_manifest(a.snapshot)
    rows = list(read_jsonl(a.labels))
    if any(row.get("snapshotId") != manifest["snapshotId"] for row in rows):
        raise ValueError("Las afirmaciones pertenecen a otro snapshot")
    facts = [r for r in rows if r.get("type") in {"hecho", "declaracion"}]
    reviewed = [r for r in facts if type(r.get("supported")) is bool]
    evidence = {r["articleId"]: r for r in read_jsonl(a.snapshot / "articles.jsonl")} | {
        r["indicatorRowId"]: r for r in read_jsonl(a.snapshot / "indicators.jsonl")}

    def valid_citations(row):
        citations = row.get("citations") or []
        return bool(citations) and all(c.get("evidenceId") in evidence
               and c.get("field") in evidence[c["evidenceId"]] for c in citations)

    write_json(a.out, {"command": " ".join(sys.argv), "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "snapshotId": manifest["snapshotId"], "evaluationKind": evaluation_kind(reviewed),
                       "facts": len(facts), "reviewedFacts": len(reviewed),
                       "factualCitationCoverageStructural": ratio(sum(valid_citations(r) for r in facts), len(facts)),
                       "humanSupport": ratio(sum(r["supported"] for r in reviewed), len(reviewed)),
                       "humanCitationCorrect": ratio(sum(r.get("citationCorrect") is True for r in reviewed), len(reviewed)),
                       "manifestSha256": manifest["manifestSha256"], "labelsSha256": sha256_file(a.labels),
                       "evaluatorSha256": sha256_file(Path(__file__)),
                       "note": "Validez de campos/IDs no prueba sustento; los juicios requieren revisión independiente."})
    print(f"afirmaciones={len(facts)}; juicios={len(reviewed)}; provenance={evaluation_kind(reviewed)} -> {a.out}")


if __name__ == "__main__":
    main()
