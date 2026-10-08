"""Capture the actual local agenda and create an empty independent review form."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from fastapi.testclient import TestClient
from label_provenance import verified_manifest
from umbral_api.app import create_app
from umbral_api.config import Settings
from umbral_pipeline.util import write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--ranking-out", type=Path, required=True)
    ap.add_argument("--labels-out", type=Path, required=True)
    a = ap.parse_args()
    if a.ranking_out.exists() or a.labels_out.exists():
        raise SystemExit("Los archivos existentes se conservan; elige rutas nuevas explícitas")
    manifest = verified_manifest(a.snapshot)
    settings = Settings(snapshot_dir=a.snapshot.resolve(), offline=True, strict_integrity=True,
                        persistence="memory", auth_mode="dev-header", local_mode=True, gemini_api_key=None)
    with TestClient(create_app(settings), headers={"X-Umbral-User": "agenda-eval-preparation"}) as client:
        response = client.get("/api/v1/topics", params={"limit": 5})
        response.raise_for_status()
        ranking = response.json()
    if ranking["snapshotId"] != manifest["snapshotId"]:
        raise ValueError("La API no devolvió el snapshot solicitado")
    ranking["capturedAt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ranking["command"] = " ".join(sys.argv)
    ranking["manifestSha256"] = manifest["manifestSha256"]
    write_json(a.ranking_out, ranking)
    a.labels_out.parent.mkdir(parents=True, exist_ok=True)
    with a.labels_out.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps({"snapshotId": manifest["snapshotId"], "rulesVersion": ranking["rulesVersion"],
                                 "relevantTopicIds": None, "labelMethod": "human_pending", "labeler": None,
                                 "instructions": "Revise evidencia en las fichas y elija IDs de temas pertinentes. No copie automáticamente la agenda propuesta ni use sus puntajes como juicio.",
                                 "notes": ""}, ensure_ascii=False) + "\n")
    print(f"Agenda real de cinco temas capturada; juicio editorial VACÍO -> {a.labels_out}")


if __name__ == "__main__":
    main()
