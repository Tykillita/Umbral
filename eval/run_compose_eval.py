"""Mide la redacción con IA (`POST /queries/compose`) contra Gemini REAL (Free Tier), sin inventar nada.

Qué hace
- Arranca una API local aislada con el snapshot indicado (no offline, sin stub). La clave se carga desde `apps/api/.env` dentro del
  proceso de la API; este script nunca la lee, la imprime ni la escribe.
- Ejecuta primero las consultas de desarrollo de forma determinista (sin modelo) y elige las que tienen respuesta con fuentes
  (`respondida`/`parcial`), repartidas por tipo de consulta.
- Redacta con Gemini solo esas, con un presupuesto duro de llamadas (`--max-calls`, por defecto 20 = el límite diario por usuario del
  proyecto) y una pausa entre casos para respetar los límites por minuto del Free Tier. Nunca cambia a un proveedor de pago.

Qué mide (numerador y denominador siempre)
- composed: casos en que el texto del modelo pasó la validación por código (ids, campos, pasajes literales, cifras, instrucciones, secretos).
- firstAttemptValid / rescuedByRetry: aceptado al primer intento / tras el único reintento con retroalimentación.
- validationRate: composed / (composed + validacion_fallida), solo entre los casos en que el modelo respondió.
- fallbackReasons: por qué se conservó la respuesta por reglas (cuota, servicio, validación…).
- newNumbersInComposedText: comprobación independiente del validador (cifras del texto redactado ausentes de la respuesta por reglas).
- Latencia (cliente) y tokens. El sustento de cada afirmación lo debe juzgar una persona: queda «pendiente».

Uso (desde la raíz):  apps/api/.venv/Scripts/python.exe eval/run_compose_eval.py --snapshot data/snapshots/<id> --out eval/results/<archivo>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import socket
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from run_benchmark import run
from umbral_pipeline.util import read_jsonl, sha256_file, write_json

MODEL_PROVIDER_ERRORS = {"cuota_agotada", "limite_por_usuario", "limite_global", "proveedor_no_disponible", "sin_credenciales",
                         "modo_sin_conexion", "contador_no_disponible"}
_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_MARKER = re.compile(r"\[\d{1,2}\]")


def wilson(k: int, n: int, z: float = 1.96) -> dict:
    """Intervalo de Wilson al 95 % para una proporción (n pequeño: úsalo para no sobreinterpretar)."""
    if n == 0:
        return {"numerator": k, "denominator": n, "value": None, "ci95": None}
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"numerator": k, "denominator": n, "value": round(p, 4), "ci95": [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]}


def numbers(text: str) -> set[str]:
    """Cifras de un texto, sin separadores ni ceros a la izquierda (así «2026-10-07» y «7 de octubre» coinciden)."""
    return {(t.replace(",", "").replace(".", "").lstrip("0") or "0") for t in _NUMBER.findall(_MARKER.sub("", text))}


def pick(items: list[dict], results: list[dict], limit: int) -> list[dict]:
    """Casos con respuesta con fuentes, repartidos por (intención, seguimiento) en orden de archivo."""
    by_id = {r["id"]: r for r in results}
    buckets: dict[tuple[str, bool], list[dict]] = {}
    for item in items:
        response = (by_id.get(item["id"]) or {}).get("response")
        if not response or item["type"] == "adversarial":
            continue
        if response["answerStatus"] in {"respondida", "parcial"} and response["citations"]:
            buckets.setdefault((response["intent"], bool(item.get("followUpOf"))), []).append(item)
    chosen: list[dict] = []
    while len(chosen) < limit and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(chosen) < limit:
                chosen.append(buckets[key].pop(0))
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--files", type=Path, nargs="+", default=[ROOT / "eval/dev/benchmark_dev.jsonl", ROOT / "eval/dev/benchmark_dev_ext.jsonl"])
    ap.add_argument("--max-cases", type=int, default=10)
    ap.add_argument("--max-calls", type=int, default=20, help="presupuesto duro de llamadas al modelo en esta ejecución")
    ap.add_argument("--pause", type=float, default=6.0, help="segundos entre casos (límites por minuto del Free Tier)")
    ap.add_argument("--dry-run", action="store_true", help="solo lista los casos elegidos; no llama al modelo")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    snapshot = a.snapshot.resolve()
    snapshot_id = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))["snapshotId"]
    items = [it for f in a.files for it in read_jsonl(f)]
    items = [it for it in items if it["snapshotId"] == snapshot_id]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    for blocked in ("GEMINI_API_KEY", "UMBRAL_GEMINI_STUB", "UMBRAL_OFFLINE"):
        env.pop(blocked, None)  # la clave llega desde apps/api/.env dentro del proceso de la API, no desde este script
    env.update({"PYTHONPATH": str(ROOT / "apps/api/src"), "UMBRAL_LOCAL_MODE": "1", "UMBRAL_AUTH_MODE": "local",
                "UMBRAL_PERSISTENCE": "memory", "UMBRAL_SNAPSHOT_DIR": str(snapshot), "UMBRAL_STRICT_INTEGRITY": "1",
                "UMBRAL_QUERIES_PER_MINUTE": "100", "UMBRAL_DRAFTS_PER_MINUTE": "10", "PYTHONUNBUFFERED": "1"})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    server_command = [sys.executable, "-m", "uvicorn", "umbral_api.main:app", "--host", "127.0.0.1", "--port", str(port)]
    log_path = a.out.with_suffix(".server.log")
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(server_command, env=env, stdout=log, stderr=log, cwd=ROOT)
        try:
            health = None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    health = httpx.get(base + "/api/v1/health", timeout=2).json()
                    break
                except httpx.HTTPError:
                    time.sleep(0.2)
            if health is None:
                raise SystemExit(f"La API local no arrancó; ver {log_path}")
            gemini = next((p for p in health["providers"] if p["name"] == "gemini"), None)
            if health["snapshotId"] != snapshot_id or health["offline"]:
                raise SystemExit("La API no cumple el snapshot o está en modo sin conexión; no se mide.")
            if not gemini or not gemini["available"]:
                raise SystemExit(f"Gemini no está disponible ({(gemini or {}).get('reason')}); no se mide ni se simula.")
            if "STUB" in (gemini.get("reason") or "") or gemini.get("model") == "gemini-stub":
                raise SystemExit("El proveedor es un stub; esta medición exige Gemini real.")

            deterministic = run(items, base, 30, {})
            chosen = pick(items, deterministic, a.max_cases)
            print(f"{len(chosen)} casos elegidos de {len(items)}: " + ", ".join(c["id"] for c in chosen))
            if a.dry_run:
                return
            responses = {r["id"]: r["response"] for r in deterministic if "response" in r}
            cases: list[dict] = []
            calls = 0
            with httpx.Client(base_url=base, timeout=150) as client:
                for index, item in enumerate(chosen):
                    if calls + 2 > a.max_calls:
                        print(f"Presupuesto de llamadas agotado ({calls}/{a.max_calls}); se detiene antes de {item['id']}.")
                        break
                    body: dict = {"question": item["question"], "limit": 5}
                    if item.get("followUpOf"):
                        body["followUp"] = responses[item["followUpOf"]]["followUpContext"]
                    started = time.perf_counter()
                    reply = client.post("/api/v1/queries/compose", json=body)
                    elapsed = round(time.perf_counter() - started, 3)
                    if reply.status_code != 200:
                        cases.append({"id": item["id"], "question": item["question"], "httpStatus": reply.status_code, "error": reply.text[:300],
                                      "elapsedSeconds": elapsed})
                        print(f"  {item['id']}: HTTP {reply.status_code}")
                        continue
                    data = reply.json()
                    calls += data["attempts"]
                    composed = data["response"]["answer"] if data["answerMode"] == "modelo" else None
                    usage = data.get("usage") or {}
                    cases.append({
                        "id": item["id"], "question": item["question"], "followUp": bool(item.get("followUpOf")),
                        "intent": data["response"]["intent"], "answerMode": data["answerMode"], "attempts": data["attempts"],
                        "fallbackReason": data["fallbackReason"], "fallbackDetail": (data["fallbackDetail"] or "")[:300] or None,
                        "model": data["model"], "elapsedSeconds": elapsed,
                        "usage": {k: usage.get(k) for k in ("promptTokens", "outputTokens", "totalTokens", "thinkingTokens", "latencyMs")} if usage else None,
                        "statements": composed.count("\n- ") + (1 if composed and "\n- " not in composed else 0) if composed else 0,
                        "newNumbersInComposedText": sorted(numbers(composed) - numbers(data["rulesAnswer"])) if composed else None,
                        "composedAnswer": composed, "rulesAnswer": data["rulesAnswer"],
                        "humanSupport": "pendiente",
                    })
                    print(f"  {item['id']}: {data['answerMode']} · intentos {data['attempts']} · {data['fallbackReason'] or 'ok'} · {elapsed}s")
                    if index < len(chosen) - 1:
                        time.sleep(a.pause)

            reached = [c for c in cases if "answerMode" in c]
            modelo = [c for c in reached if c["answerMode"] == "modelo"]
            invalid = [c for c in reached if c["fallbackReason"] == "validacion_fallida"]
            latencies = [c["elapsedSeconds"] for c in reached if c["attempts"]]
            tokens = [c["usage"]["totalTokens"] for c in modelo if c.get("usage") and c["usage"].get("totalTokens")]
            summary = {
                "casesAttempted": len(cases), "modelCallsUsed": calls, "callBudget": a.max_calls,
                "composed": wilson(len(modelo), len(reached)),
                "firstAttemptValid": wilson(sum(1 for c in modelo if c["attempts"] == 1), len(reached)),
                "rescuedByRetry": wilson(sum(1 for c in modelo if c["attempts"] == 2), len(reached)),
                "validationRate": wilson(len(modelo), len(modelo) + len(invalid)),
                "fallbackReasons": dict(Counter(c["fallbackReason"] for c in reached if c["fallbackReason"])),
                "newNumbersInComposedText": wilson(sum(1 for c in modelo if c["newNumbersInComposedText"]), len(modelo)),
                "latencySecondsClient": ({"median": statistics.median(latencies), "max": max(latencies), "n": len(latencies)} if latencies else None),
                "totalTokensComposed": ({"mean": round(statistics.mean(tokens)), "n": len(tokens)} if tokens else None),
                "humanSupport": {"status": "pendiente", "value": None, "reason": "Requiere que una persona juzgue cada afirmación contra su fuente."},
            }
            report = {
                "command": " ".join(sys.argv[:1] and ["eval/run_compose_eval.py", *sys.argv[1:]]),
                "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "environment": {"python": platform.python_version(), "os": platform.platform(), "snapshotId": snapshot_id,
                                "provider": "gemini (Free Tier, sin facturación; sin salto a pago)", "model": gemini.get("model"),
                                "geminiAvailableAtStart": True, "persistence": "memory"},
                "scriptSha256": sha256_file(Path(__file__)),
                "benchmarkFiles": {f.name: sha256_file(f) for f in a.files},
                "manifestSha256": sha256_file(snapshot / "manifest.json"),
                "apiSourceSha256": hashlib.sha256(json.dumps({
                    str(path.relative_to(ROOT)).replace("\\", "/"): sha256_file(path)
                    for path in sorted((ROOT / "apps/api/src/umbral_api").rglob("*.py"))
                }, sort_keys=True).encode("utf-8")).hexdigest(),
                "caveats": [
                    "Muestra pequeña de consultas escritas por el agente: los intervalos de Wilson son anchos; no es un benchmark final.",
                    "Un único modelo y un único día; el Free Tier puede dar 429/503 y eso se cuenta como respaldo por reglas, no como fallo de validación.",
                    "Que el texto pase la validación por código prueba estructura (ids, campos, pasajes literales, cifras), no sustento.",
                    "El sustento humano de cada afirmación está pendiente.",
                ],
                "summary": summary, "cases": cases,
            }
            write_json(a.out, report)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
