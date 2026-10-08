"""Verifica Hosting y API pública sin login, secretos ni llamadas Gemini reales."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def origin(value: str, allow_loopback: bool = False) -> str:
    parsed = urlsplit(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (allow_loopback and local and parsed.scheme == "http"):
        raise ValueError("Se requiere HTTPS; HTTP solo se admite en loopback explícito.")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("El origen no admite credenciales, rutas ni parámetros.")
    return value.rstrip("/")


def request(url: str, method: str = "GET", body: dict | None = None, web_origin: str | None = None) -> tuple[int, dict, bytes]:
    headers = {"Accept": "application/json", "User-Agent": "Umbral-hosted-verifier/1"}
    if web_origin:
        headers["Origin"] = web_origin
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = urlopen(Request(url, data=data, method=method, headers=headers), timeout=15)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Respuesta demasiado grande para verificación.")
        return response.status, {key.lower(): value for key, value in response.headers.items()}, raw


def json_response(url: str, method: str = "GET", body: dict | None = None, web_origin: str | None = None) -> tuple[int, dict, dict]:
    status, headers, raw = request(url, method, body, web_origin)
    if "application/json" not in headers.get("content-type", ""):
        raise ValueError("El servidor aún no entrega JSON (posible arranque en frío).")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("La respuesta JSON no cumple el contrato de objeto.")
    return status, headers, value


def verify_model_identity(snapshot_info: dict, model_version: str, profile_id: str,
                          profile_sha256: str) -> dict:
    """Require the API's active snapshot to expose the exact expected calibrated model."""
    manifest = snapshot_info.get("manifest") or {}
    classifier = manifest.get("classifier") or {}
    actual = {
        "modelVersion": classifier.get("modelVersion"),
        "calibrated": classifier.get("calibrated"),
        "calibrationProfileId": classifier.get("calibrationProfileId"),
        "calibrationProfileSha256": classifier.get("calibrationProfileSha256"),
    }
    expected = {
        "modelVersion": model_version,
        "calibrated": True,
        "calibrationProfileId": profile_id,
        "calibrationProfileSha256": profile_sha256,
    }
    if snapshot_info.get("snapshotId") != manifest.get("snapshotId") or actual != expected:
        raise ValueError(f"La identidad calibrada servida por la API no coincide: {actual}.")
    return actual


def verify(web_url: str, api_url: str, expected_snapshot: str | None = None, wait_seconds: float = 90,
           expected_model_version: str | None = None, expected_profile_id: str | None = None,
           expected_profile_sha256: str | None = None) -> dict:
    expected_model = (expected_model_version, expected_profile_id, expected_profile_sha256)
    if any(expected_model) and not all(expected_model):
        raise ValueError("La verificación del modelo requiere versión, perfil y SHA-256.")
    started = time.monotonic()
    checks: list[str] = []
    for route, label in (("/", "Portada"), ("/app", "Aplicación")):
        status, _, html = request(web_url + route)
        if status != 200 or b"Umbral" not in html or b"Site Not Found" in html:
            raise ValueError(label + " alojada no disponible.")
        checks.append(label + " alojada HTTP 200")
    status, _, config = json_response(web_url + "/public-config.json")
    if status != 200 or config != {"schemaVersion": 1, "apiUrl": api_url}:
        raise ValueError("Configuración pública de escritorio no coincide con la API publicada.")
    checks.append("Descubrimiento público de API coherente")
    status, _, descriptor = json_response(web_url + "/data/current.json")
    if status != 200 or descriptor.get("schemaVersion") != 1:
        raise ValueError("Descriptor de datos no válido.")
    expected_snapshot = expected_snapshot or descriptor.get("snapshotId")
    if descriptor.get("snapshotId") != expected_snapshot:
        raise ValueError("Snapshot alojado distinto del candidato verificado.")
    checks.append("Descriptor de datos corresponde al candidato")
    deadline = time.monotonic() + wait_seconds
    health = None
    while time.monotonic() <= deadline:
        try:
            status, headers, candidate = json_response(api_url + "/api/v1/health", web_origin=web_url)
            if status == 200 and candidate.get("snapshotId") == expected_snapshot:
                health = candidate
                break
        except (OSError, URLError, TypeError, ValueError):
            pass
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    if health is None:
        raise ValueError("La API no se recuperó o no adoptó el snapshot durante el plazo.")
    if headers.get("access-control-allow-origin") != web_url:
        raise ValueError("CORS no permite el origen de Hosting.")
    integrity = health.get("integrity", {})
    if (health.get("authMode") != "public" or health.get("containsFixtures") is not False
        or health.get("classifier") != "laya" or not integrity.get("manifestVerified")
        or integrity.get("predictionsHashVerified") is not True):
        raise ValueError("La API no cumple el modo público con datos Laya reales e íntegros.")
    checks.extend(["API pública sin Authorization", "CORS del origen alojado", "Snapshot Laya sin fixtures e íntegro"])
    model_identity = None
    if expected_model_version:
        status, _, snapshot_info = json_response(api_url + "/api/v1/snapshot", web_origin=web_url)
        if status != 200 or snapshot_info.get("snapshotId") != expected_snapshot:
            raise ValueError("La ficha de snapshot de la API no coincide con el candidato verificado.")
        model_identity = verify_model_identity(snapshot_info, expected_model_version,
                                               expected_profile_id or "", expected_profile_sha256 or "")
        checks.append("Versión y perfil calibrados de Laya coinciden exactamente")
    context = {"snapshotId": expected_snapshot}
    prefix = api_url + "/api/v1/public"
    status, _, agenda = json_response(prefix + "/agenda", "POST", {"context": context}, web_url)
    if status != 200 or not agenda.get("items") or agenda.get("snapshotId") != expected_snapshot:
        raise ValueError("La agenda pública no devuelve temas del snapshot esperado.")
    topic_id = agenda["items"][0]["id"]
    status, _, detail = json_response(prefix + f"/topics/{topic_id}", "POST", {"context": context}, web_url)
    if status != 200 or not detail.get("articles"):
        raise ValueError("La ficha pública no trae evidencia.")
    checks.extend(["Agenda pública", "Ficha pública con evidencia"])
    status, _, query = json_response(prefix + "/queries", "POST", {"context": context, "question": "¿Qué cinco temas debo revisar para la agenda de Panamá?"}, web_url)
    if status != 200 or query.get("snapshotId") != expected_snapshot or not query.get("answer"):
        raise ValueError("La consulta pública no cumple el contrato.")
    checks.append("Consulta pública en español")
    status, _, generated = json_response(prefix + "/drafts", "POST", {"context": context, "topicId": topic_id, "provider": "plantilla"}, web_url)
    draft = generated.get("draft", {})
    if status != 200 or draft.get("generationMode") != "plantilla" or not draft.get("validation", {}).get("ok"):
        raise ValueError("La plantilla pública no supera su validación estructural.")
    checks.append("Plantilla con citas, sin Gemini real ni persistencia personal")
    status, _, _ = json_response(api_url + "/api/v1/rules", "PUT", {}, web_url)
    if status != 403:
        raise ValueError("El servidor público no bloquea la escritura privada de reglas.")
    checks.append("Escritura privada rechazada HTTP 403")
    return {"status": "passed", "finishedAtUtc": datetime.now(UTC).isoformat(), "webUrl": web_url, "apiUrl": api_url,
            "snapshotId": expected_snapshot, "counts": health.get("counts"), "checks": checks,
            "model": model_identity,
            "durationSeconds": round(time.monotonic() - started, 3),
            "limitations": ["Gemini real no se llama en este verificador", "No acredita sustento humano ni instalación limpia de Windows"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-url", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--expected-snapshot-file", type=Path)
    parser.add_argument("--expected-model-version")
    parser.add_argument("--expected-calibration-profile-id")
    parser.add_argument("--expected-calibration-profile-sha256")
    parser.add_argument("--wait-seconds", type=float, default=90)
    parser.add_argument("--allow-loopback", action="store_true")
    parser.add_argument("--out", type=Path, default=Path(".production/hosted-receipt.json"))
    args = parser.parse_args()
    expected = args.expected_snapshot_file.read_text(encoding="utf-8").strip() if args.expected_snapshot_file else None
    try:
        result = verify(origin(args.web_url, args.allow_loopback), origin(args.api_url, args.allow_loopback),
                        expected, args.wait_seconds, args.expected_model_version,
                        args.expected_calibration_profile_id, args.expected_calibration_profile_sha256)
    except (OSError, TypeError, ValueError) as error:
        result = {"status": "failed", "finishedAtUtc": datetime.now(UTC).isoformat(), "error": str(error)}
    result["command"] = "python scripts/verify_hosted.py --web-url <web verificada> --api-url <api verificada>"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.out)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
