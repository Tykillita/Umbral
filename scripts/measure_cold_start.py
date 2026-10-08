"""Mide el arranque en frío de un servicio (p. ej. Render Free) y la latencia en caliente de /api/v1/health.

Render Free duerme el servicio tras ~15 min sin tráfico (según su documentación; verificar en el panel).
Uso:
  uv run --no-project python scripts/measure_cold_start.py https://<servicio>.onrender.com --samples 3 --idle-minutes 16
  uv run --no-project python scripts/measure_cold_start.py http://127.0.0.1:8000 --samples 1 --idle-minutes 0   # prueba local

Cada muestra: espera `idle-minutes`, mide el tiempo hasta la primera respuesta 200 (cold) y luego 5
peticiones seguidas (warm). Imprime JSON con fecha UTC, URL y tiempos; no inventa nada: solo lo medido.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from datetime import UTC, datetime


def fetch(url: str, timeout: float = 180.0) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (URL dada por el usuario)
            r.read()
            return r.status, time.perf_counter() - t0
    except Exception:
        return 0, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--idle-minutes", type=float, default=16.0)
    ap.add_argument("--path", default="/api/v1/health")
    ap.add_argument("--out", default=None, help="archivo JSON de salida")
    a = ap.parse_args()
    url = a.base_url.rstrip("/") + a.path
    samples = []
    for i in range(a.samples):
        if a.idle_minutes > 0:
            print(f"[{i + 1}/{a.samples}] esperando {a.idle_minutes} min para que el servicio duerma...", flush=True)
            time.sleep(a.idle_minutes * 60)
        status, cold = fetch(url)
        warm = [fetch(url)[1] for _ in range(5)] if status == 200 else []
        samples.append({"status": status, "coldSeconds": round(cold, 3),
                        "warmMedianSeconds": round(statistics.median(warm), 3) if warm else None})
        print(samples[-1], flush=True)
    ok = [s["coldSeconds"] for s in samples if s["status"] == 200]
    result = {"measuredAtUtc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "url": url,
              "idleMinutesBeforeEachSample": a.idle_minutes, "samples": samples,
              "coldMedianSeconds": round(statistics.median(ok), 3) if ok else None,
              "note": "Con idle-minutes=0 NO es un arranque en frío real: solo prueba el script."}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
