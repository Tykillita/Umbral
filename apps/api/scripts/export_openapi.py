"""Genera apps/api/openapi.json de forma reproducible (sin cargar datos ni servicios).

Uso: uv run python scripts/export_openapi.py [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from umbral_api.app import create_app
from umbral_api.config import Settings

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> int:
    app = create_app(Settings(), build_services=False)
    text = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("openapi.json desactualizado: ejecuta `uv run python scripts/export_openapi.py`")
            return 1
        print("openapi.json al día")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"escrito {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
