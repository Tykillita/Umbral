"""Run development against an isolated local API, offline and without paid calls.

Use the existing API virtualenv. Starts its own server on a free loopback port,
stores command/environment/hash, and terminates only the process it started.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import httpx
from review_samples import write_claim_sample
from run_benchmark import run, score
from umbral_pipeline.util import (
    read_jsonl,
    sha256_file,
    write_json,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--file", type=Path, default=ROOT / "eval/dev/benchmark_dev.jsonl")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--claims-out", type=Path, default=ROOT / "eval/labels/claims_sample.jsonl",
                    help="nueva ruta explícita para otra muestra; archivos existentes siempre se conservan")
    a = ap.parse_args()
    snapshot = a.snapshot.resolve()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    snapshot_id = manifest["snapshotId"]
    items = list(read_jsonl(a.file))
    if {r.get("snapshotId") for r in items} != {snapshot_id}:
        raise SystemExit("Los casos de desarrollo pertenecen a otro snapshot")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(ROOT / "apps/api/src"), "UMBRAL_OFFLINE": "1",
                "UMBRAL_LOCAL_MODE": "1", "UMBRAL_AUTH_MODE": "local",
                "UMBRAL_PERSISTENCE": "memory", "UMBRAL_SNAPSHOT_DIR": str(snapshot),
                "UMBRAL_STRICT_INTEGRITY": "1", "UMBRAL_QUERIES_PER_MINUTE": "100",
                "UMBRAL_DRAFTS_PER_MINUTE": "50", "UMBRAL_GEMINI_STUB": "",
                "GEMINI_API_KEY": "", "PYTHONUNBUFFERED": "1"})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    server_command = [sys.executable, "-m", "uvicorn", "umbral_api.main:app",
                      "--host", "127.0.0.1", "--port", str(port)]
    log_path = a.out.with_suffix(".server.log")
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(server_command, env=env, stdout=log, stderr=log, cwd=ROOT)
        try:
            deadline = time.monotonic() + 45
            health = None
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    response = httpx.get(base + "/api/v1/health", timeout=2)
                    response.raise_for_status()
                    health = response.json()
                    break
                except httpx.HTTPError:
                    time.sleep(0.2)
            if health is None:
                raise RuntimeError(f"La API local no arrancó; ver {log_path}")
            if health["snapshotId"] != snapshot_id or not health["offline"]:
                raise RuntimeError("La API no cumple el snapshot/modo offline de la evaluación")
            results = run(items, base, 15, {})
            if any(r.get("response", {}).get("snapshotId") != snapshot_id for r in results if "response" in r):
                raise RuntimeError("La respuesta corresponde a otro snapshot")
            known_ids = {r["articleId"] for r in read_jsonl(snapshot / "articles.jsonl")} | {
                r["indicatorRowId"] for r in read_jsonl(snapshot / "indicators.jsonl")}
            summary = score(items, results, known_ids)
            report = {"command": " ".join(sys.argv), "serverCommand": server_command,
                      "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "environment": {"python": platform.python_version(), "os": platform.platform(),
                                      "api": base, "snapshotId": snapshot_id, "dataMode": health["dataMode"],
                                      "classifier": health["classifier"], "offline": True,
                                      "persistence": "memory", "queriesPerMinute": 100},
                      "benchmarkFile": a.file.name, "benchmarkSha256": sha256_file(a.file),
                      "manifestSha256": sha256_file(snapshot / "manifest.json"),
                      "evaluatorSha256": sha256_file(Path(__file__).with_name("run_benchmark.py")),
                      "apiSourceSha256": hashlib.sha256(json.dumps({
                          str(path.relative_to(ROOT)).replace("\\", "/"): sha256_file(path)
                          for path in sorted((ROOT / "apps/api/src/umbral_api").rglob("*.py"))
                      }, sort_keys=True).encode("utf-8")).hexdigest(),
                      "labelMethods": sorted({r["labelMethod"] for r in items}), "humanReviewed": False,
                      "caveats": ["40 pruebas públicas exploratorias escritas por el agente; no son el benchmark final60.",
                                  "Relevancia parcial programática; no mide utilidad de agenda.",
                                  "Citas presentes no prueban cobertura factual ni sustento humano.",
                                  "Latencia local caliente; no incluye arranque frío Render ni generación Gemini."],
                      "summary": summary, "results": results}
            write_json(a.out, report)

            # Collect genuine typed draft claims for a human reviewer without
            # inventing support labels or counting model validation as truth.
            review_rows = []
            with httpx.Client(base_url=base, timeout=15) as client:
                topics = client.get("/api/v1/topics", params={"limit": 32}).json()
                for topic in topics.get("items", []):
                    response = client.post(f"/api/v1/topics/{topic['id']}/drafts", json={"provider": "plantilla"})
                    response.raise_for_status()
                    draft = response.json()["draft"]
                    for claim in draft.get("package", {}).get("claims", []):
                        if claim.get("type") in {"hecho", "declaracion"}:
                            review_rows.append({"snapshotId": snapshot_id, "topicId": topic["id"],
                                                "claimId": claim["id"], "type": claim["type"], "text": claim["text"],
                                                "citations": claim.get("citations", []), "generationMode": draft.get("generationMode"),
                                                "supported": None, "citationCorrect": None,
                                                "labeler": None, "labelMethod": "human_pending", "notes": ""})
            review_path = a.claims_out
            created = write_claim_sample(review_path, review_rows)
            print(f"Muestra humana: {'creada' if created else 'existente conservada sin modificaciones'} -> {review_path}")
            print(f"snapshot={snapshot_id}; consultas={summary['n']}; HTTP errors={summary['httpErrors']}; "
                  f"afirmaciones para revisión humana={len(review_rows)}")
            print(json.dumps({k: v for k, v in summary.items() if k != "failures"}, ensure_ascii=False, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
