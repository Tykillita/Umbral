"""Diagnóstico REAL opt-in, un intento por llamada; solo guarda metadatos sin claves/respuestas crudas."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from umbral_api.config import Settings
from umbral_api.drafts import build_pack
from umbral_api.models import DraftRequest
from umbral_api.providers import ModelOutput, build_user_content
from umbral_api.services import Services


class ProbeOutput(BaseModel):
    ok: bool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true", help="Requiere autorización del usuario; consume Free Tier")
    parser.add_argument("--model")
    parser.add_argument("--stage", choices=("probe", "editorial"), default="probe")
    parser.add_argument("--probe", choices=("plain", "small_schema", "both"), default="both")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--topic-id", help="Tema explícito del snapshot para una comprobación editorial pública")
    parser.add_argument("--expected-snapshot", help="Aborta antes de enviar si cambió el snapshot esperado")
    parser.add_argument("--max-editorial-calls", type=int, choices=(1, 2), default=1,
                        help="Presupuesto de llamadas SDK de la ejecución editorial (default: una)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.allow_live:
        parser.error("Las llamadas reales están deshabilitadas sin --allow-live.")
    settings = Settings.from_env()
    if settings.offline or not settings.gemini_api_key:
        parser.error("No hay credencial disponible o está activo el modo offline (sin exponer la clave).")
    model = args.model or settings.gemini_model
    report = {"startedAtUtc": datetime.now(UTC).isoformat(), "model": model, "stage": args.stage,
              "realNetwork": True, "retryAttempts": 1, "calls": [], "result": "pending"}
    if args.stage == "probe":
        with genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(
            timeout=args.timeout * 1000, retry_options=types.HttpRetryOptions(attempts=1),
        )) as client:
            for name, schema in (("plain", None), ("small_schema", ProbeOutput)):
                if args.probe != "both" and args.probe != name:
                    continue
                start = time.monotonic()
                call = {"name": name, "schemaBytes": len(json.dumps(schema.model_json_schema())) if schema else 0}
                try:
                    response = client.models.generate_content(model=model, contents="Devuelve ok=true.", config=types.GenerateContentConfig(
                        response_mime_type="application/json" if schema else "text/plain", response_schema=schema, max_output_tokens=256,
                    ))
                    call.update(status="success", parsed=bool(response.parsed) if schema else bool(response.text))
                except errors.APIError as error:
                    call.update(status="api_error", code=error.code)
                except Exception as error:
                    call.update(status="transport_error", errorType=type(error).__name__)
                call["latencySeconds"] = round(time.monotonic() - start, 3)
                report["calls"].append(call)
                print(json.dumps(call), flush=True)
                if call.get("code") == 429:
                    report["result"] = "quota_stop"
                    break
    else:
        safe_settings = replace(settings, persistence="memory", auth_mode="local", local_mode=True, strict_integrity=True,
                                gemini_model=model, gemini_fallback_model=None, gemini_timeout_s=args.timeout, gemini_stub=None,
                                gemini_calls_per_user_day=args.max_editorial_calls)
        service = Services(safe_settings)
        if args.expected_snapshot and service.corpus.snapshot_id != args.expected_snapshot:
            parser.error("El snapshot actual cambió; no se enviará ninguna solicitud.")
        # Tema con evidencia citable y prompt pequeño para aislar problemas del formato editorial.
        candidates = [(len(build_user_content(base.display_title, build_pack(base), {})), base)
                      for base in service.bases.values() if build_pack(base).items and not base.suspicious_ids]
        if args.topic_id:
            base = service.bases.get(args.topic_id)
            if base is None or not build_pack(base).items or base.suspicious_ids:
                parser.error("El tema explícito no tiene evidencia pública utilizable en este snapshot.")
        else:
            _, base = min(candidates, key=lambda row: row[0])
        content = build_user_content(base.display_title, build_pack(base), {"snapshotId": service.corpus.snapshot_id, "rulesVersion": "scoring-v1", "scope": "titular/metadatos"})
        report.update(snapshotId=service.corpus.snapshot_id, classifier=service.corpus.classifier, containsFixtures=service.corpus.contains_fixtures,
                      topicId=base.id, category=base.category.value, geoRelevance=base.geo.value,
                      rulesVersion=service.rules().rules_version, humanReview=False,
                      maxEditorialCalls=args.max_editorial_calls, articleCount=len(service.corpus.articles),
                      publicSourceUrls=[article.url for article in base.usable_articles],
                      promptBytes=len(content.encode()), promptSha256=hashlib.sha256(content.encode()).hexdigest(),
                      schemaBytes=len(json.dumps(ModelOutput.model_json_schema()).encode()),
                      schemaSha256=hashlib.sha256(json.dumps(ModelOutput.model_json_schema(), sort_keys=True).encode()).hexdigest())
        start = time.monotonic()
        response = service.create_draft("diagnostic", base.id, DraftRequest(provider="gemini"), client_is_local=True)
        draft = response.draft
        report["calls"].append({"name": "full_editorial", "latencySeconds": round(time.monotonic() - start, 3),
                                "generationMode": draft.generation_mode.value, "fallbackReason": draft.fallback_reason.value if draft.fallback_reason else None,
                                "fallbackDetail": draft.fallback_detail, "validationOk": draft.validation.ok,
                                "factualCitationCoverage": draft.validation.factual_citation_coverage,
                                "claimCount": len(draft.package.claims), "wordCounts": draft.validation.word_counts,
                                "scriptSecondsEstimate": draft.validation.script_seconds_estimate,
                                "citationFields": sorted({citation.field for claim in draft.package.claims for citation in claim.citations}),
                                "modelUsed": draft.model})
        report["calls"][-1]["usage"] = draft.usage.model_dump(mode="json", by_alias=True) if draft.usage else None
        report["result"] = "success" if draft.generation_mode.value == "modelo" else "fallback"
        if draft.fallback_reason and draft.fallback_reason.value == "cuota_agotada":
            report["result"] = "quota_stop"
        print(json.dumps(report["calls"][-1]), flush=True)
    if report["result"] == "pending":
        report["result"] = "success" if all(c["status"] == "success" for c in report["calls"]) else "failed"
    report["completedAtUtc"] = datetime.now(UTC).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["result"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
