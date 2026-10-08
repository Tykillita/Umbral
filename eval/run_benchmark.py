"""Ejecuta el benchmark contra la API de Umbral y calcula metricas REALES (nada se inventa).

Uso (API en marcha en localhost:8000):
  uv run --project pipeline python eval/run_benchmark.py --file eval/dev/benchmark_dev.jsonl --out eval/results/dev-<fecha>.json
  uv run --project pipeline python eval/run_benchmark.py --file %USERPROFILE%/umbral-held-out/benchmark_reserved.jsonl --out %USERPROFILE%/umbral-held-out/results.json

Formato de cada linea del benchmark (JSONL):
  id, type (sustentada|ambigua|sin_respuesta|adversarial), question, expectedStatus,
  relevantEvidenceIds (ids de articulos/indicadores que deben aparecer entre los 5 primeros hits),
  mustAbstain (bool), forbiddenSubstrings (lista; la respuesta NO puede contenerlas), synthetic (bool),
  snapshotId (snapshot sobre el que se etiqueto), labeler, labelMethod, notes.

Metricas (numerador y denominador siempre; fallos listados):
  - Precision@5: sobre consultas con relevantEvidenceIds, fraccion de los 5 primeros hits que son relevantes.
  - Cobertura de citas: respuestas con afirmacion factual (answerStatus != abstencion) que traen >=1 cita con evidenceId
    existente en los hits/evidencia / respuestas no abstenidas.  Que la cita exista NO prueba sustento (eso lo revisa una persona).
  - Abstencion correcta: mustAbstain=true y answerStatus=abstencion. Abstencion incorrecta: abstiene en consulta con
    relevantEvidenceIds (respondible).
  - Adversariales: pasan si no contienen forbiddenSubstrings y (si mustAbstain) abstienen.
  - Latencia: mediana y p95 de extremo a extremo (cliente), en el entorno declarado.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from umbral_pipeline.evalkit.metrics import latency_summary, precision_at_k, ratio
from umbral_pipeline.util import read_jsonl, sha256_file


def run(items: list[dict], base: str, timeout: float, headers: dict[str, str]) -> list[dict]:
    results = []
    with httpx.Client(base_url=base, timeout=timeout, headers=headers) as c:
        for it in items:
            t0 = time.perf_counter()
            rec: dict = {"id": it["id"], "type": it["type"], "question": it["question"]}
            try:
                r = c.post("/api/v1/queries", json={"question": it["question"], "limit": 5})
                rec["latencySeconds"] = time.perf_counter() - t0
                rec["httpStatus"] = r.status_code
                if r.status_code == 200:
                    rec["response"] = r.json()
                else:
                    rec["error"] = r.text[:300]
            except Exception as exc:  # noqa: BLE001
                rec["latencySeconds"] = time.perf_counter() - t0
                rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
            results.append(rec)
    return results


def score(items: list[dict], results: list[dict], known_evidence_ids: set[str] | None = None) -> dict:
    by_id = {r["id"]: r for r in results}
    failures: list[dict] = []
    p5_vals: list[float] = []
    cite_num = cite_den = 0
    abst_ok_num = abst_ok_den = 0
    abst_bad_num = abst_bad_den = 0
    adv_num = adv_den = 0
    status_ok = 0
    lat: list[float] = []
    errors = 0
    for it in items:
        r = by_id[it["id"]]
        lat.append(r["latencySeconds"])
        resp = r.get("response")
        if resp is None:
            errors += 1
            failures.append({"id": it["id"], "why": "sin respuesta HTTP 200", "detail": r.get("error")})
            if it.get("mustAbstain"):
                abst_ok_den += 1
            if it["type"] == "adversarial":
                adv_den += 1
            continue
        status = resp.get("answerStatus")
        abstained = status == "abstencion"
        hit_ids = [h["evidenceId"] for h in resp.get("hits", [])]
        relevant = set(it.get("relevantEvidenceIds") or [])
        if relevant:
            p = precision_at_k(hit_ids, relevant, 5)
            p5_vals.append(p)
            if p == 0:
                failures.append({"id": it["id"], "why": "P@5 = 0", "hits": hit_ids[:5], "relevant": sorted(relevant)})
        if not abstained:
            cite_den += 1
            cited = [c["evidenceId"] for c in resp.get("citations", [])]
            known = known_evidence_ids if known_evidence_ids is not None else set(hit_ids)
            if cited and all(cid and cid in known for cid in cited):
                cite_num += 1
            else:
                failures.append({"id": it["id"], "why": "respuesta no abstenida sin cita verificable", "citations": cited})
        if it.get("mustAbstain"):
            abst_ok_den += 1
            if abstained:
                abst_ok_num += 1
            else:
                failures.append({"id": it["id"], "why": "debía abstenerse y no lo hizo", "status": status})
        elif relevant:
            abst_bad_den += 1
            if abstained:
                abst_bad_num += 1
                failures.append({"id": it["id"], "why": "abstención incorrecta en pregunta respondible"})
        if it["type"] == "adversarial":
            adv_den += 1
            # QueryResponse echoes the input question and retrieved data. Those
            # fields are not generated obedience; inspect only the answer.
            text = str(resp.get("answer", "")).lower()
            leaked = [s for s in it.get("forbiddenSubstrings", []) if s.lower() in text]
            ok = not leaked and (abstained or not it.get("mustAbstain"))
            if ok:
                adv_num += 1
            else:
                failures.append({"id": it["id"], "why": "adversarial no superado", "leaked": leaked, "status": status})
        if it.get("expectedStatus") and status == it["expectedStatus"]:
            status_ok += 1
    return {
        "n": len(items),
        "byType": dict(Counter(i["type"] for i in items)),
        "httpErrors": errors,
        "retrievalPrecisionAt5": {
            "mean": (sum(p5_vals) / len(p5_vals)) if p5_vals else None,
            "queriesEvaluated": len(p5_vals),
            "perQuery": p5_vals,
        },
        "responseCitationPresence": ratio(cite_num, cite_den),
        "factualCitationCoverage": {"status": "pendiente", "value": None,
                                    "reason": "QueryResponse no expone afirmaciones tipadas; requiere revisión por afirmación."},
        "agendaPrecisionAt5": {"status": "pendiente", "value": None,
                               "reason": "Falta juicio editorial independiente sobre cinco temas de agenda."},
        "humanSupport": {"status": "pendiente", "value": None},
        "correctAbstention": ratio(abst_ok_num, abst_ok_den),
        "incorrectAbstentionOnAnswerable": ratio(abst_bad_num, abst_bad_den),
        "adversarialPassed": ratio(adv_num, adv_den),
        "expectedStatusMatch": ratio(status_ok, sum(1 for i in items if i.get("expectedStatus"))),
        "latencySeconds": latency_summary(lat),
        "failures": failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--snapshot", type=Path, required=True, help="snapshot exacto para validar IDs de citas contra el corpus")
    ap.add_argument("--user", default="eval-runner", help="X-Umbral-User (solo UMBRAL_AUTH_MODE=dev-header)")
    a = ap.parse_args()
    items = list(read_jsonl(a.file))
    manifest = json.loads((a.snapshot / "manifest.json").read_text(encoding="utf-8"))
    health = httpx.get(a.api + "/api/v1/health", timeout=15).json()
    expected_ids = {r.get("snapshotId") for r in items}
    if expected_ids != {health.get("snapshotId")} or manifest["snapshotId"] != health.get("snapshotId"):
        raise SystemExit("Benchmark y API no usan el mismo snapshotId; no se ejecuta una evaluación mezclada.")
    results = run(items, a.api, a.timeout, {"X-Umbral-User": a.user})
    if any(r.get("response", {}).get("snapshotId") != health["snapshotId"]
           for r in results if "response" in r):
        raise SystemExit("La API cambió snapshotId durante la ejecución; no se publican métricas mezcladas.")
    known_ids = {r["articleId"] for r in read_jsonl(a.snapshot / "articles.jsonl")} | {
        r["indicatorRowId"] for r in read_jsonl(a.snapshot / "indicators.jsonl")}
    summary = score(items, results, known_ids)
    report = {
        "command": " ".join(sys.argv),
        "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": {"python": platform.python_version(), "os": platform.platform(), "api": a.api,
                        "snapshotId": health.get("snapshotId"), "dataMode": health.get("dataMode"),
                        "classifier": health.get("classifier")},
        "benchmarkFile": a.file.name, "benchmarkSha256": sha256_file(a.file),
        "manifestSha256": sha256_file(a.snapshot / "manifest.json"),
        "evaluatorSha256": sha256_file(Path(__file__)),
        "labelMethods": sorted({r.get("labelMethod", "unspecified") for r in items}),
        "humanReviewed": all(r.get("humanReviewed", False) for r in items),
        "caveats": ["Desarrollo exploratorio; no benchmark final ni etiquetas humanas.",
                    "P@5 mide recuperación de IDs programáticos parciales; no utilidad editorial de agenda.",
                    "Presencia de citas por respuesta no prueba cobertura factual ni sustento."],
        "summary": summary, "results": results,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    s = {k: v for k, v in summary.items() if k not in ("failures",)}
    s["retrievalPrecisionAt5"] = {k: v for k, v in s["retrievalPrecisionAt5"].items() if k != "perQuery"}
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print(f"fallos: {len(summary['failures'])} (detalle en {a.out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
