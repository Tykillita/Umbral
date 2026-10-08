"""Clasificador Laya (checkpoint multilingue, Apache-2.0): https://huggingface.co/convaiinnovations/laya

Requiere el extra `laya` (torch + transformers + laya). Un solo forward por titular responde a la vez:
 - `category`: pregunta `choice` con las 6 categorias del reto + `otro` (-> `indeterminado`)
 - `geo`: pregunta `choice` panama / regional / none (relevancia geografica)
Las probabilidades NO estan calibradas (el propio README de Laya advierte que los checkpoints base salen
sobreconfiados): se miden contra etiquetas propias en eval/ antes de usarlas como senal de confianza.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import CATEGORIES, INDETERMINATE
from ..util import iso_z, now_utc, sha256_hex
from . import input_hash, input_text_for
from .geo import METHOD as GEO_METHOD
from .geo import geo_content_v2

os.environ.setdefault("USE_TF", "0")  # evita el bloqueo de transformers al sondear TensorFlow
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

REPO = "convaiinnovations/laya"
SUBFOLDER = "multilingual"
MODEL_ID = f"{REPO}/{SUBFOLDER}"
PINNED_REVISION = "7b928d828b7b0e022f929d9bd2e44165aa270148"

# Variante original (snapshot 20261007-37263360). Se conserva solo para reproducir/comparar.
CATEGORY_QUESTION_V0 = {
    "category": {
        "type": "choice",
        "instructions": "¿Qué tema principal trata este titular de noticias de Panamá y la región?",
        "criteria": {
            "economia": "economía, inflación, empleo, inversión, finanzas públicas y privadas, comercio, precios, impuestos, bancos",
            "logistica_canal": "Canal de Panamá, puertos, transporte de carga, buques, logística, cadena de suministro, zonas francas",
            "turismo": "turismo, hoteles, visitantes, aerolíneas, cruceros, destinos y festivales turísticos",
            "servicios_publicos": "agua, electricidad, salud, educación, transporte público, seguridad ciudadana e infraestructura y servicios del Estado",
            "eventos_naturales": "sismos, lluvias, inundaciones, huracanes, sequías, deslizamientos y otros fenómenos naturales o alertas",
            "regulacion": "leyes, decretos, normas, reformas, Asamblea, tribunales, sanciones, casos judiciales y regulación",
            "otro": "ninguna de las anteriores: deportes, espectáculos, política internacional, sucesos u otros temas",
        },
    },
    "geo": {
        "type": "choice",
        "instructions": "¿Con qué territorio se relaciona principalmente el hecho que reporta este titular?",
        "criteria": {
            "panama": "Panamá (país, ciudades, instituciones o el Canal de Panamá)",
            "regional": "Centroamérica, el Caribe o América Latina (otros países de la región, sin mencionar Panamá)",
            "none": "otro lugar del mundo, o no hay relación con Panamá ni con la región",
        },
    },
}

# --- Variantes del control de alcance (ver eval/exploratory/probe_scope.py y eval/README.md) ---
# Diseño de método, sin ajuste sobre etiquetas del corpus: `otro` pasa a ser una opción de primer orden con descripción
# explícita; el PDF define solo seis temas y lo demás (sucesos, deportes, farándula...) es ajeno al alcance.
# Se retiran de los criterios los términos que atraían ruido: «seguridad ciudadana», «casos judiciales», «alertas».
OTRO_CRITERION_V1 = (
    "ninguno de los seis temas: sucesos policiales, crímenes, homicidios, accidentes, deportes, "
    "espectáculos, farándula, política internacional, curiosidades, humor, religión u otros temas ajenos"
)
CATEGORY_QUESTION_V1 = {
    "category": {
        "type": "choice",
        "instructions": (
            "¿Cuál de estos temas de agenda editorial trata principalmente el titular? "
            "Si el titular es un suceso policial o crimen, deporte, espectáculo o farándula, política internacional, "
            "curiosidad u otro tema que no encaja claramente en los seis temas, elige «otro»."
        ),
        "criteria": {
            "economia": "economía, inflación, empleo, inversión, finanzas públicas y privadas, comercio, precios, impuestos, bancos",
            "logistica_canal": "Canal de Panamá, puertos, transporte de carga, buques, logística, cadena de suministro, zonas francas",
            "turismo": "turismo, hoteles, visitantes, aerolíneas, cruceros, destinos y ferias turísticas",
            "servicios_publicos": "servicio de agua, electricidad, salud pública, educación, transporte público e infraestructura estatal",
            "eventos_naturales": "sismos, lluvias, inundaciones, huracanes, sequías, deslizamientos y otros fenómenos naturales",
            "regulacion": "leyes, decretos, normas, reformas, resoluciones de entes reguladores y fallos sobre normas",
            "otro": OTRO_CRITERION_V1,
        },
    },
    "geo": CATEGORY_QUESTION_V0["geo"],
}
# V1B: mismos criterios ampliados con subtemas habituales y `otro` más corto (probada; peor retención en el sondeo).
CATEGORY_CRITERIA_V1B = {
    "economia": "economía, inflación, empleo, inversión, finanzas públicas y privadas, presupuesto, comercio, precios, impuestos, bancos",
    "logistica_canal": "Canal de Panamá, puertos, transporte de carga, buques, navieras, contenedores, logística, cadena de suministro, Zona Libre de Colón",
    "turismo": "turismo, hoteles, visitantes, aerolíneas, cruceros, destinos y ferias turísticas",
    "servicios_publicos": "servicios del Estado: agua potable, electricidad, salud pública y vacunación, hospitales, educación y escuelas, metro y transporte público, infraestructura",
    "eventos_naturales": "sismos, lluvias, inundaciones, huracanes, sequías, deslizamientos y otros fenómenos naturales",
    "regulacion": "leyes, proyectos de ley y debates de la Asamblea, decretos, normas, reformas, resoluciones de entes reguladores y fallos sobre normas",
}
CATEGORY_QUESTION_V1B = {
    "category": {
        "type": "choice",
        "instructions": "¿Cuál de estos temas de agenda editorial trata principalmente el titular? Si no encaja claramente en ninguno de los seis, elige «otro».",
        "criteria": {**CATEGORY_CRITERIA_V1B, "otro": "ninguno de los seis temas: sucesos policiales y crímenes, accidentes, deportes, espectáculos y farándula, política internacional, curiosidades u otros temas ajenos"},
    },
    "geo": CATEGORY_QUESTION_V0["geo"],
}
CATEGORY_QUESTION = CATEGORY_QUESTION_V1  # se fija tras el sondeo exploratorio (ver SCOPE_METHOD)
SCOPE_METHOD = "laya-category-v1"

# Puerta de alcance: pregunta binaria independiente (claves neutras A/B, ver advertencia de `noul` en el README de Laya).
SCOPE_QUESTION = {
    "scope": {
        "type": "choice",
        "instructions": "¿Este titular trata un tema de agenda editorial económica, logística, turística, de servicios públicos, de fenómenos naturales o de regulación?",
        "criteria": {
            "A": "sí: economía, Canal y logística, turismo, servicios públicos, fenómenos naturales o leyes y regulación",
            "B": "no: sucesos policiales, crímenes, deportes, espectáculos, farándula, política internacional, curiosidades u otros temas ajenos",
        },
    }
}

PAIR_QUESTION = {
    "same": {
        "type": "choice",
        "instructions": "¿Los dos titulares informan sobre el mismo hecho o evento concreto (no solo el mismo tema)?",
        "criteria": {"A": "sí, es el mismo hecho o evento", "B": "no, son hechos o eventos distintos"},
    }
}


def resolve_revision() -> str:
    """Hash de commit del repo HF usado (carpeta snapshots/<sha> de la cache local). 'unknown' si no se halla."""
    try:
        from huggingface_hub import scan_cache_dir

        for repo in scan_cache_dir().repos:
            if repo.repo_id == REPO and repo.repo_type == "model":
                revs = sorted(repo.revisions, key=lambda r: r.last_modified, reverse=True)
                if revs:
                    return revs[0].commit_hash
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def decide_category(cat_probs: dict[str, float], threshold: float) -> tuple[str, float]:
    """Mapea las probabilidades crudas de Laya a (categoria, prob. de la ganadora cruda).

    `otro` (fuera de alcance) o una ganadora por debajo del umbral -> `indeterminado`. Las probabilidades crudas
    se conservan aparte en `probabilities`; esta funcion solo decide la etiqueta.
    """
    best = max(cat_probs, key=lambda k: cat_probs[k])
    p_best = float(cat_probs[best])
    category = best if (best in CATEGORIES and p_best >= threshold) else INDETERMINATE
    return category, p_best


class LayaClassifier:
    name = "laya"
    model_id = MODEL_ID
    threshold = 0.5

    def __init__(self, *, log=print, model_dir: Path | None = None, revision: str = PINNED_REVISION) -> None:
        import laya  # type: ignore[import-not-found]
        import torch

        t0 = time.time()
        self._torch = torch
        local = model_dir or (Path(os.environ["UMBRAL_LAYA_MODEL_DIR"]) if os.environ.get("UMBRAL_LAYA_MODEL_DIR") else None)
        if local is not None:
            if not (local / "model.safetensors").is_file():
                raise RuntimeError("Faltan los pesos de Laya incluidos; no se sustituye por baseline.")
            self.agent = laya.load(str(local), device="cpu")
        else:
            self.agent = laya.load(REPO, subfolder=SUBFOLDER, revision=revision, device="cpu")
        self.load_seconds = round(time.time() - t0, 1)
        self.model_version = revision
        self.laya_version = getattr(laya, "__version__", "unknown")
        self.run_at = iso_z(now_utc())
        self.log = log
        self.calls = 0

    # ---- clasificacion ----
    def _answer(self, text: str, questions: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return self.agent.predict(text, questions)["answers"]

    def predict(self, articles: list[dict], *, predicted_at: datetime | None = None, progress=None) -> list[dict]:
        ts = iso_z(predicted_at or now_utc())
        out = []
        for n, a in enumerate(articles):
            ans = self._answer(input_text_for(a), CATEGORY_QUESTION)
            cat_probs: dict[str, float] = ans["category"]["probabilities"]
            geo_probs: dict[str, float] = ans["geo"]["probabilities"]
            category, p_best = decide_category(cat_probs, self.threshold)
            probs = {c: round(float(cat_probs.get(c, 0.0)), 6) for c in CATEGORIES}
            probs[INDETERMINATE] = round(float(cat_probs.get("otro", 0.0)), 6)
            # relevancia geográfica por CONTENIDO (regla léxica auditable); la respuesta cruda de Laya se conserva como diagnóstico
            geo, geo_ev = geo_content_v2(a)
            geo_raw = {k: round(float(v), 6) for k, v in geo_probs.items()}
            ih = input_hash(a)
            out.append(
                {
                    "predictionId": "pred_" + sha256_hex(a["articleId"] + ih + self.model_id)[:16],
                    "articleId": a["articleId"],
                    "inputHash": ih,
                    "task": "category",
                    "category": category,
                    "probability": round(p_best, 6),
                    "probabilities": probs,
                    "threshold": self.threshold,
                    "geoRelevance": geo,
                    "geoEvidence": geo_ev,
                    "geoMethod": GEO_METHOD,
                    "geoLayaRaw": geo_raw,
                    "classifier": "laya",
                    "modelId": self.model_id,
                    "modelVersion": self.model_version,
                    "predictedAt": ts,
                    "calibrated": False,
                    "provisional": True,
                }
            )
            if (n + 1) % 100 == 0:
                self.log(f"  [laya] {n + 1}/{len(articles)}")
            if progress is not None:
                progress(n + 1, len(articles))
        return out

    # ---- desempate de duplicados ambiguos ----
    def same_event(self, a: dict, b: dict) -> tuple[bool, float]:
        text = f"Titular A: {input_text_for(a)}\nTitular B: {input_text_for(b)}"
        ans = self._answer(text, PAIR_QUESTION)["same"]["probabilities"]
        p = float(ans.get("A", 0.0))
        return p >= 0.5, p

    def info(self) -> dict[str, Any]:
        return {
            "classifier": "laya", "modelId": self.model_id, "modelVersion": self.model_version,
            "layaPackageVersion": self.laya_version, "torchVersion": self._torch.__version__,
            "runAt": self.run_at, "device": "cpu",
            "loadSeconds": self.load_seconds, "forwardCalls": self.calls, "threshold": self.threshold,
            "questions": {"category": f"choice 6+otro ({SCOPE_METHOD})", "geo": f"relevancia por contenido ({GEO_METHOD}); la pregunta geo de Laya se guarda en geoLayaRaw"},
            "scopeMethod": SCOPE_METHOD,
            "note": "Probabilidades sin calibrar (calibrated=false).",
        }


def cache_size_bytes() -> int:
    root = Path.home() / ".cache" / "huggingface" / "hub" / "models--convaiinnovations--laya"
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


_ = re  # (reservado para normalizaciones futuras)
