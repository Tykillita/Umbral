"""Lista candidatos REALES para las 5 fichas de Notion a partir del snapshot servido por un backend local.

Arranca la API en un puerto libre contra data/snapshots/<id> (o CURRENT), lee /topics y /topics/{id} y aplica los
criterios declarados. No inventa nada: solo clasifica lo que devuelve la API. Salida: JSON en stdout.

  uv run --no-project --with httpx python scripts/ficha_candidates.py [snapshotId [evt_id ...]] > candidatos.json
Criterios:
  caso-01  máxima prioridad EN ALCANCE (categoría != indeterminado y relevancia geográfica != none)
  caso-02  tema económico con indicador anual del Banco Mundial en el contexto oficial
  caso-03  cluster con >= 2 procedencias independientes (corroboración real)
  caso-04  recirculación o contradicción (si no existe en el corpus real, se informa)
  caso-05  evidencia insuficiente con prioridad alta (needsInvestigation)
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    snaps = ROOT / "data" / "snapshots"
    sid = sys.argv[1] if len(sys.argv) > 1 else (snaps / "CURRENT").read_text(encoding="utf-8").strip()
    port = free_port()
    work = Path(tempfile.mkdtemp(prefix="umbral-fichas-"))
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env.update(UMBRAL_SNAPSHOT_DIR=str(snaps / sid), UMBRAL_AUTH_MODE="local", UMBRAL_PERSISTENCE="memory",
               UMBRAL_ALLOW_FIXTURE="0", GEMINI_API_KEY="", UMBRAL_OFFLINE="1", PYTHONUTF8="1",
               UMBRAL_WEB_DIST=str(work / "w"), UMBRAL_QUERIES_PER_MINUTE="1000")
    proc = subprocess.Popen(["uv", "run", "uvicorn", "umbral_api.main:app", "--port", str(port)],
                            cwd=ROOT / "apps" / "api", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        for _ in range(300):
            try:
                if httpx.get(base + "/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            print("el backend no arrancó", file=sys.stderr)
            return 1
        c = httpx.Client(base_url=base, timeout=60)
        health = c.get("/health").json()
        items: list[dict] = []
        for band in ("alto", "medio", "bajo"):  # limit máx. 100 por petición: se pagina por banda
            items += c.get("/topics", params={"limit": 100, "band": band}).json()["items"]
        items.sort(key=lambda t: (-t["score"], -t["urgency"], t["id"]))
        details = {t["id"]: c.get(f"/topics/{t['id']}").json() for t in items}

        def brief(t: dict) -> dict:
            d = details[t["id"]]
            return {"topicId": t["id"], "rank": t["rank"], "title": t["title"], "category": t["category"],
                    "score": t["score"], "band": t["band"], "evidenceStatus": t["evidenceStatus"],
                    "independentProvenances": t["independentProvenances"], "articleCount": t["articleCount"],
                    "geoRelevance": t["geoRelevance"], "isRecirculation": t["isRecirculation"],
                    "hasContradictions": t["hasContradictions"], "needsInvestigation": t["needsInvestigation"],
                    "indicators": [i["id"] for i in d["officialContext"]["indicators"] if not i["isMissing"]][:6],
                    "articleIds": [a["id"] for a in d["articles"]][:6]}

        in_scope = [t for t in items if t["category"] != "indeterminado" and t["geoRelevance"] != "none"]
        out = {
            "snapshotId": health["snapshotId"], "dataMode": health["dataMode"], "provisional": health["provisional"],
            "containsFixtures": health["containsFixtures"], "classifier": health["classifier"],
            "totalTopics": len(items), "inScopeTopics": len(in_scope),
            "caso01_max_prioridad_en_alcance": [brief(t) for t in in_scope[:3]],
            "caso02_economico_con_indicador": [brief(t) for t in items
                                               if details[t["id"]]["officialContext"]["indicators"]
                                               and t["category"] == "economia"][:3],
            "caso03_multiprocedencia": [brief(t) for t in sorted(items, key=lambda x: -x["independentProvenances"])
                                        if t["independentProvenances"] >= 2][:20],
            "caso04_recirculacion": [brief(t) for t in items if t["isRecirculation"]][:3],
            "caso04_contradiccion": [brief(t) for t in items if t["hasContradictions"]][:3],
            "caso05_insuficiente_prioridad_alta": [brief(t) for t in items if t["needsInvestigation"]][:3],
            "caso05_alternativa_insuficiente_en_alcance": [brief(t) for t in in_scope
                                                           if t["evidenceStatus"] == "insuficiente"][:3],
        }
        want = [a for a in sys.argv[2:] if a.startswith("evt_")]
        if want:  # detalle completo (TopicDetail) de los temas pedidos, para redactar fichas sin transcribir a mano
            out["detalle"] = {i: c.get(f"/topics/{i}").json() for i in want}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
