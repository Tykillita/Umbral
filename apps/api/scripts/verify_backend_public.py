"""Recibo reproducible de la verificación completa del backend público/local."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    started = datetime.now(UTC)
    checks = []
    commands = [
        ("uv run --extra firebase pytest", [sys.executable, "-m", "pytest"]),
        ("uv run --extra firebase ruff check src tests scripts", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("uv run --extra firebase mypy src", [sys.executable, "-m", "mypy", "src"]),
        ("uv run --extra firebase python scripts/export_openapi.py --check", [sys.executable, "scripts/export_openapi.py", "--check"]),
    ]
    for command, argv in commands:
        tick = time.perf_counter()
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                                env=os.environ | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        checks.append({"command": command, "exitCode": result.returncode,
                       "durationSeconds": round(time.perf_counter() - tick, 3),
                       "output": (result.stdout + result.stderr).strip()[-4000:]})
        print(f"{command}: {'OK' if result.returncode == 0 else 'FALLO'}", flush=True)
    source_files = []
    paths = [path for folder in ("src", "tests", "scripts") for path in (ROOT / folder).rglob("*.py")]
    paths.extend(ROOT / name for name in ("openapi.json", "pyproject.toml", "uv.lock", ".env.example"))
    for path in sorted(paths):
        source_files.append({"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    from umbral_api.config import Settings
    from umbral_api.snapshot import load_corpus

    corpus = load_corpus(Settings(persistence="memory", allow_fixture=False, strict_integrity=True))
    receipt = {"startedAtUtc": started.isoformat(), "completedAtUtc": datetime.now(UTC).isoformat(),
               "command": "uv run --extra firebase python scripts/verify_backend_public.py", "checks": checks,
               "passed": all(check["exitCode"] == 0 for check in checks), "sourceFiles": source_files,
               "sourceFingerprintSha256": hashlib.sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest(),
               "snapshotId": corpus.snapshot_id, "counts": corpus.counts, "containsFixtures": corpus.contains_fixtures,
               "integrity": corpus.integrity.model_dump(mode="json", by_alias=True),
               "firestoreLocalReceipt": "diagnostics/public-counter-local.json",
               "scope": "API pública/local, aislamiento, cuotas/reintentos/cache, contratos, snapshots verificados, copia/restauración y evidencia archivada.",
               "notVerified": ["Hosting/Render públicos", "Credenciales/contador de Firestore de producción",
                               "Browser E2E", "Instalador e inferencia Laya empaquetada", "Actualización diaria alojada",
                               "Nuevas llamadas Gemini reales", "Revisión humana de calidad editorial"]}
    (ROOT / "diagnostics" / "backend-public-audit.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
