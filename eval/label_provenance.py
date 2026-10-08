"""Shared provenance and integrity checks for reviewed and synthetic labels."""
from __future__ import annotations

import json
from pathlib import Path

from umbral_pipeline.snapshot import verify_snapshot
from umbral_pipeline.util import sha256_file


def evaluation_kind(rows: list[dict]) -> str:
    if not rows:
        return "pending"
    if any(r.get("synthetic") or str(r.get("labelMethod", "")).startswith("synthetic") for r in rows):
        return "synthetic_control"
    if all(r.get("labelMethod") == "human" and str(r.get("labeler") or "").strip() for r in rows):
        return "human"
    return "unverified_labels"


def verified_manifest(snapshot: Path) -> dict:
    ok, problems = verify_snapshot(snapshot)
    if not ok:
        raise ValueError(f"Snapshot inválido: {'; '.join(problems)}")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    return {**manifest, "manifestSha256": sha256_file(snapshot / "manifest.json")}
