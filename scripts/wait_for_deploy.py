"""Espera a que la API alojada atienda un commit concreto y cumpla el modo público.

Se ejecuta ANTES de publicar Firebase Hosting: si la API no responde con el SHA esperado,
con datos Laya íntegros y sin fixtures, el flujo falla y Hosting permanece como estaba.
No usa secretos ni llama a Gemini. Tolera el arranque en frío de Render Free.

Uso: python scripts/wait_for_deploy.py --api-url https://<servicio>.onrender.com --sha <40 hex>
     [--web-origin https://site-umbral.web.app] [--timeout 1200] [--out recibo.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SHA = re.compile(r"^[0-9a-f]{40}$")


def api_origin(value: str, allow_loopback: bool = False) -> str:
    parsed = urlsplit(value)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (allow_loopback and loopback and parsed.scheme == "http"):
        raise ValueError("La API debe usar HTTPS (HTTP solo en loopback explícito).")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("El origen de la API no admite credenciales, rutas ni parámetros.")
    return value.rstrip("/")


def fetch_health(api_url: str, web_origin: str | None) -> tuple[dict, dict]:
    headers = {"Accept": "application/json", "User-Agent": "Umbral-deploy-verifier/1"}
    if web_origin:
        headers["Origin"] = web_origin
    try:
        response = urlopen(Request(api_url + "/api/v1/health", headers=headers), timeout=20)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Respuesta demasiado grande.")
        if response.status != 200 or "application/json" not in response.headers.get("content-type", ""):
            raise ValueError(f"HTTP {response.status}: el servicio aún no entrega la salud en JSON.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("La salud no es un objeto JSON.")
        return value, {key.lower(): item for key, item in response.headers.items()}


def problems(health: dict, headers: dict, sha: str, web_origin: str | None) -> list[str]:
    """Condiciones que impiden publicar Hosting; lista vacía = la API está lista."""
    found = []
    deployed = health.get("deployCommit")
    if deployed != sha:
        found.append(f"deployCommit={deployed!r}, se esperaba {sha[:12]}…")
    if health.get("status") != "ok":
        found.append(f"status={health.get('status')!r}")
    if health.get("authMode") != "public" or health.get("localMode") is not False or health.get("persistence") != "none":
        found.append("la API no está en modo público sin persistencia")
    if health.get("containsFixtures") is not False or health.get("classifier") != "laya":
        found.append("los datos no son Laya reales sin fixtures")
    integrity = health.get("integrity") or {}
    if not integrity.get("manifestVerified") or integrity.get("predictionsHashVerified") is not True:
        found.append("integridad del snapshot no verificada")
    if web_origin and headers.get("access-control-allow-origin") != web_origin:
        found.append("CORS no permite el origen de Hosting")
    return found


def wait(api_url: str, sha: str, web_origin: str | None, timeout: float, interval: float) -> dict:
    started = time.monotonic()
    deadline = started + timeout
    last = "sin respuesta"
    attempts = 0
    while True:
        attempts += 1
        try:
            health, headers = fetch_health(api_url, web_origin)
            found = problems(health, headers, sha, web_origin)
            if not found:
                return {"status": "passed", "finishedAtUtc": datetime.now(UTC).isoformat(), "apiUrl": api_url,
                        "deployCommit": health["deployCommit"], "snapshotId": health.get("snapshotId"),
                        "apiVersion": health.get("apiVersion"), "counts": health.get("counts"),
                        "attempts": attempts, "waitedSeconds": round(time.monotonic() - started, 1)}
            last = "; ".join(found)
        except (OSError, URLError, ValueError) as error:
            last = f"{type(error).__name__}: {str(error)[:160]}"
        if time.monotonic() + interval > deadline:
            raise TimeoutError(f"La API no cumplió las condiciones en {timeout:.0f} s. Último estado: {last}")
        print(f"[{time.monotonic() - started:5.0f} s] esperando: {last}", flush=True)
        time.sleep(interval)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--sha", required=True, help="SHA completo (40 hex) del commit desplegado")
    parser.add_argument("--web-origin", help="origen de Hosting cuyo CORS debe aceptarse")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--allow-loopback", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    sha = args.sha.strip().lower()
    if not SHA.fullmatch(sha):
        print("El SHA debe tener 40 caracteres hexadecimales.", file=sys.stderr)
        return 2
    try:
        receipt = wait(api_origin(args.api_url, args.allow_loopback), sha, args.web_origin, args.timeout, args.interval)
    except (TimeoutError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
