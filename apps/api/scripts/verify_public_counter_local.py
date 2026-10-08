"""Prueba SDK/Firestore real local de la cuota global, sin claves ni nube.

Iniciar antes el emulador Firestore en 127.0.0.1:8088 con proyecto
demo-umbral-public-audit. Este script solo toca ese proyecto de laboratorio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1:8088"
PROJECT = "demo-umbral-public-audit"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    os.environ["FIRESTORE_EMULATOR_HOST"] = HOST
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    from umbral_api.storage import PublicGeminiCounter

    first = PublicGeminiCounter(PROJECT)
    if args.probe_only:
        allowed, used = first.reserve(20)
        assert not allowed and used == 20
        print(json.dumps({"allowed": allowed, "used": used}))
        first._db.close()
        return
    started = datetime.now(UTC)
    reference = first._db.collection("publicCounters").document(f"gemini-{started:%Y%m%d}")
    reference.delete()  # proyecto demo en loopback, dato de este laboratorio únicamente
    second = PublicGeminiCounter(PROJECT)

    def reserve(index: int) -> bool:
        # Igual que el proceso API: una instancia serializa las reservas de sus
        # threads; Firestore es la autoridad compartida con el siguiente cliente.
        return first.reserve(20)[0]

    with ThreadPoolExecutor(max_workers=4) as pool:
        accepted = list(pool.map(reserve, range(40)))
    stored = reference.get().to_dict()
    assert sum(accepted) == stored["value"] == 20
    assert second.reserve(20) == (False, 20)
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe-only"],
                           capture_output=True, text=True, check=True, timeout=30)
    probe = json.loads(child.stdout)
    assert probe == {"allowed": False, "used": 20}
    files = []
    for name in ("storage.py", "services.py", "public.py", "config.py"):
        path = ROOT / "src" / "umbral_api" / name
        files.append({"path": "src/umbral_api/" + name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    receipt = {"startedAtUtc": started.isoformat(), "completedAtUtc": datetime.now(UTC).isoformat(),
               "command": "uv run --extra firebase python scripts/verify_public_counter_local.py",
               "scope": "Firestore SDK real en emulador loopback; 40 reservas concurrentes en una instancia API, segundo cliente y proceso nuevo tras agotar 20.",
               "project": PROJECT, "host": HOST, "accepted": sum(accepted), "rejected": len(accepted) - sum(accepted),
               "storedValue": stored["value"], "newProcessProbe": probe, "passed": True, "sourceFiles": files,
               "priorAttempt": {"scope": "Dos clientes concurrentes con escrituras en un mismo documento del emulador",
                                "result": "Falló por contención después de agotar reintentos SDK; no se llamó Gemini.",
                                "classification": "ServiceUnavailable, conserva contador Firestore y fallback por plantilla"},
               "notVerified": ["Credenciales y contador en Firestore de producción", "Escrituras simultáneas exitosas entre instancias distintas", "Llamadas reales a Gemini"]}
    output = ROOT / "diagnostics" / "public-counter-local.json"
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    first._db.close()
    second._db.close()
    print("Contador Firestore local: 20 aceptadas, 20 rechazadas; proceso nuevo conserva cuota agotada.")


if __name__ == "__main__":
    main()
