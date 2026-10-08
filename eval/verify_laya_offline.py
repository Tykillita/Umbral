"""One real cached Laya inference with the quality team's socket/DNS block active."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

from umbral_pipeline.classify.laya_clf import LayaClassifier
from umbral_pipeline.util import read_jsonl, sha256_file, write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    # Fail closed if the netblock isn't loaded: flags alone do not demonstrate
    # that this process was unable to reach the network.
    if socket.getaddrinfo.__module__ != "sitecustomize":
        raise SystemExit("Falta tests/support/netblock en PYTHONPATH antes de arrancar Python")
    try:
        socket.getaddrinfo("huggingface.co", 443)
    except OSError:
        probe_blocked = True
    else:
        raise SystemExit("La prueba de bloqueo de red no bloqueó DNS externo")
    if os.environ.get("HF_HUB_OFFLINE") != "1" or os.environ.get("TRANSFORMERS_OFFLINE") != "1":
        raise SystemExit("Se requieren HF_HUB_OFFLINE=1 y TRANSFORMERS_OFFLINE=1")
    netlog = Path(os.environ["UMBRAL_NETBLOCK_LOG"])
    before = len(netlog.read_text(encoding="utf-8").splitlines())
    article = next(read_jsonl(a.snapshot / "articles.jsonl"))
    manifest = json.loads((a.snapshot / "manifest.json").read_text(encoding="utf-8"))
    classifier = LayaClassifier()
    prediction = classifier.predict([article])[0]
    after = len(netlog.read_text(encoding="utf-8").splitlines())
    write_json(a.out, {"status": "ejecutado", "test": "T10_Laya_cached_no_network",
                       "command": " ".join(sys.argv), "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "snapshotId": manifest["snapshotId"], "manifestSha256": sha256_file(a.snapshot / "manifest.json"),
                       "classifier": classifier.info(), "prediction": prediction,
                       "dnsProbeBlocked": probe_blocked, "modelExternalAttemptsBlocked": after - before,
                       "offlineFlags": {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
                       "netblockLog": str(netlog),
                       "caveat": "Inferencia real sin red; no evaluación de exactitud ni macro-F1."})
    print(f"T10 Laya local: inferencia real OK; DNS externo bloqueado; intentos externos modelo={after-before}; {a.out}")


if __name__ == "__main__":
    main()
