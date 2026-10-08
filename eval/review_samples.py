"""Preserve reviewer-owned label files when rerunning development probes."""
from __future__ import annotations

import json
from pathlib import Path


def write_claim_sample(path: Path, rows: list[dict]) -> bool:
    """Create a sample once; never replace existing labels, including null labels.

    Exclusive creation also protects a file created between the existence check
    and opening it. A new snapshot/review can use a distinct filename explicitly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        return False
    with handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True
