"""Exporta cinco fichas reales desde una API local; crea plantillas sin revisión humana.

Uso: tests/.venv/Scripts/python.exe scripts/export_editorial_cases.py --api http://127.0.0.1:8000
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if urlparse(args.api).hostname not in {"127.0.0.1", "localhost"}:
        parser.error("solo se exporta desde una API loopback local")
    base = args.api.rstrip("/") + "/api/v1"

    def api(path, body=None):
        request = Request(base + path, data=json.dumps(body).encode() if body else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    health = api("/health")
    assert not health["containsFixtures"], "las cinco fichas requieren un snapshot sin fixtures"
    assert health["localMode"] and health["authMode"] == "local", "solo sesión local"
    items = api("/topics?limit=100")["items"]  # scope=in_scope (defecto)
    # caso-03 puede estar fuera del alcance temático pero ser corroboración real entre medios panameños (se declara)
    extra = [t for t in api("/topics?limit=100&scope=all&band=medio")["items"] + api("/topics?limit=100&scope=all&band=alto")["items"]
             if t["id"] not in {i["id"] for i in items}]
    all_items = items + extra
    details = {item["id"]: api("/topics/" + item["id"]) for item in all_items}
    used = set()
    GDP = "NY.GDP.MKTP.KD.ZG"
    selectors = [  # criterios declarados (Notion, caso-0N); la API ya oculta temas fuera de alcance (scope=in_scope)
        ("Máxima prioridad EN ALCANCE", lambda item, detail: True),
        ("Contexto económico anual (Banco Mundial: país, año, unidad)",
         lambda item, detail: any(i["indicatorId"] == GDP for i in detail["officialContext"]["indicators"])
         and ("PIB" in item["title"] or "Producto Interno Bruto" in item["title"]) and not item["possibleSponsored"]),
        ("Corroboración real entre medios panameños: >= 2 procedencias independientes (puede estar fuera de las seis categorías)", lambda item, detail: item["independentProvenances"] >= 2 and item["geoRelevance"] == "panama"),
        ("Recirculación marcada por la regla (>14 d entre publicación y detección), en Panamá y NO patrocinada", lambda item, detail: item["isRecirculation"] and not item["possibleSponsored"] and item["geoRelevance"] == "panama"),
        ("Evidencia insuficiente con prioridad alta", lambda item, detail: item["evidenceStatus"] == "insuficiente" and item["band"] == "alto"),
    ]
    snapshot = ROOT / "data" / "snapshots" / health["snapshotId"]
    manifest_hash = hashlib.sha256((snapshot / "manifest.json").read_bytes()).hexdigest()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    cases = []
    out = ROOT / "docs" / "notion" / "fichas"
    out.mkdir(exist_ok=True)

    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    for number, (purpose, select) in enumerate(selectors, 1):
        pool = all_items if number == 3 else items
        item = next((item for item in pool if item["id"] not in used and select(item, details[item["id"]])), None)
        if item is None:
            raise RuntimeError("el corpus real no contiene un caso para: " + purpose)
        used.add(item["id"])
        detail = details[item["id"]]
        assert detail["case"]["status"] == "nuevo" and detail["case"]["reviewer"] is None, "usar SQLite limpio; el caso ya tiene revisión"
        generated = api("/topics/" + item["id"] + "/drafts", {"provider": "plantilla"})
        draft, case = generated["draft"], generated["case"]
        assert case["status"] == "nuevo" and case["reviewer"] is None, "no inventar revisión humana"
        sources = detail["articles"] + detail["officialContext"]["indicators"]
        known_ids = {source["id"] for source in sources}
        claims = draft["package"]["claims"]
        assert all(c["citations"] for c in claims if c["type"] in {"hecho", "declaracion"})
        assert all(cite["evidenceId"] in known_ids for claim in claims for cite in claim["citations"])
        limitations = list(detail["warnings"])
        if number == 1:
            limitations.append("Su «candidato a contradicción» es un falso positivo de la heurística: ambos titulares dicen 33 tránsitos; solo uno omite el calado de 49 pies. Sigue pendiente de revisión humana.")
        if number == 2:
            limitations.append("La serie del Banco Mundial se muestra como CONTEXTO oficial vinculado por palabra clave: no eleva E ni el estado de evidencia (E = 0,33 con una procedencia); solo una fuente primaria confirmada por un revisor la subiría. Es un dato anual de 2024, no la cifra trimestral del titular.")
        if number == 3:
            limitations.append("Corroboración entre medios distintos según el titular; no verifica la afirmación ni sustituye a una fuente primaria. En el snapshot cfa338b6 solo 2 clústeres con >=2 procedencias son de Panamá: el del caso-01 y este, que el clasificador deja fuera de las seis categorías (nota cultural), por lo que la agenda por defecto lo oculta.")
        if number == 4:
            limitations.append("Recirculación inferida por la regla del pipeline (publicación > 14 d antes de la detección); no demuestra una republicación real. No hay contradicciones confirmadas en el corpus real; T05 usa un fixture etiquetado en tests.")
        record = {
            "schemaVersion": "1.0.0", "id": case["caseId"], "topicId": item["id"],
            "caseNumber": number, "purpose": purpose, "modality": "editorial", "title": item["title"],
            "snapshotId": health["snapshotId"], "manifestSha256": manifest_hash,
            "provisional": health["provisional"], "containsFixtures": False,
            "classifier": manifest["classifier"],
            "rulesVersion": health["rulesVersion"], "sources": sources,
            "claims": claims, "citations": [cite for claim in claims for cite in claim["citations"]],
            "score": detail["score"], "components": detail["score"]["components"],
            "evidence": detail["evidence"], "draft": draft,
            "review": {"status": "nuevo", "humanReview": "PENDIENTE", "reviewer": None, "comment": None,
                       "version": case["version"], "history": case["history"]},
            "pendingVerifications": detail["pendingVerifications"], "limitations": limitations,
            "recommendedAction": detail["recommendedAction"],
            "exportedAtUtc": datetime.now(timezone.utc).isoformat(),
            "command": "python scripts/export_editorial_cases.py --api " + args.api,
        }
        cases.append(record)
        md = [f"# CASO-{number:02d} · {purpose}", "", f"**{item['title']}**", "",
              "> Datos reales provisionales, cero fixtures. Borrador por plantilla; revisión humana PENDIENTE. Solo titular/metadatos, sin aprobación ni publicación.", "",
              "| Campo | Valor |", "|---|---|",
              f"| ID de caso / tema | {case['caseId']} / {item['id']} |",
              f"| Snapshot / SHA-256 manifest | {health['snapshotId']} / `{manifest_hash}` |",
              f"| Clasificador / categoría propuesta | {health['classifier']} / {item['category']} |",
              f"| Probabilidad de categoría (sin calibrar) | {detail['articles'][0]['categoryProbability']} |",
              f"| Puntaje / banda / reglas | {item['score']} / {item['band']} / {health['rulesVersion']} |",
              f"| Evidencia / procedencias | {item['evidenceStatus']} / {item['independentProvenances']} |",
              "| Revisión / persona | nuevo / PENDIENTE (ninguna persona asignada) |", "",
              "## Qué se reporta", "", detail["whatIsReported"], "",
              "## Fuentes originales", "", "| ID | Medio / país | Publicación / año | Unidad | URL |", "|---|---|---|---|---|"]
        for article in detail["articles"]:
            md.append(f"| {article['id']} | {cell(article['outlet'])} | {article['publishedAt']} | — | [Fuente]({article['url']}) |")
        for indicator in detail["officialContext"]["indicators"]:
            md.append(f"| {indicator['id']} | {cell(indicator.get('country', indicator.get('countryIso3', '')))} | {indicator['year']} | {cell(indicator['unit'])} | [Dato oficial]({indicator.get('sourceUrl', '')}) |")
            md.append(f"\nIndicador anual: `{indicator.get('indicatorId', '')}`, valor **{indicator['value']}**, país {indicator.get('countryIso3', indicator.get('country', ''))}, año **{indicator['year']}**; contexto, no cifra de hoy.")
        md += ["", "## Componentes del puntaje", "", "| Componente | Valor 0–1 | Puntos | Regla y justificación |", "|---|---|---|---|"]
        for component in detail["score"]["components"]:
            md.append(f"| {component['key']} | {component['value']} | {component['points']} | {cell(component['rule']+' '+component['justification'])} |")
        md += ["", "## Afirmaciones y citas", "", "| Tipo | Afirmación | ID y campo/pasaje |", "|---|---|---|"]
        for claim in claims:
            cites = "; ".join(f"{cite['evidenceId']} · {cite['field']} · {cite.get('passage') or ''}" for cite in claim["citations"]) or "Sin cita: hipótesis pendiente, no hecho"
            md.append(f"| {claim['type']} | {cell(claim['text'])} | {cell(cites)} |")
        md += ["", "## Borrador de revisión", "", f"Origen: **{draft['generationLabel']}**. Validación estructural: {draft['validation']['ok']}; cobertura factual por cita: {draft['validation']['factualCitationCoverage']}. Sustento humano pendiente."]
        for field, label in [("proposedTitle", "Título"), ("brief", "Brief"), ("publicInterestAngle", "Enfoque"), ("script", "Guion"), ("socialCopy", "Copy")]:
            md += ["", f"### {label}", "", draft["package"][field]]
        for field, label in [("researchQuestions", "Preguntas de investigación"), ("pendingVerifications", "Verificaciones pendientes")]:
            md += ["", f"### {label}", ""] + ["- " + value for value in draft["package"][field]]
        md += ["", "## Límites y siguiente acción", ""] + ["- " + value for value in limitations]
        md += ["", detail["recommendedAction"], "", "Revisión humana: **PENDIENTE**. Persona y comentario: **PENDIENTES**. La extracción automática no se presenta como revisión editorial."]
        (out / f"caso-{number:02d}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"caso-{number:02d}: {item['id']} ({item['score']}; {item['evidenceStatus']})")
    (out / "fichas.jsonl").write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8")
    print("Exportadas 5 fichas Markdown y fichas.jsonl; no se registró revisión humana.")


if __name__ == "__main__":
    main()
