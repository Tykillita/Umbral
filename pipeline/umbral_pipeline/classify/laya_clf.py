"""Clasificador Laya (checkpoint multilingue, Apache-2.0): https://huggingface.co/convaiinnovations/laya

Requiere el extra `laya` (torch + transformers + laya). Un solo forward por titular responde a la vez:
 - `category`: pregunta `choice` con las 6 categorias del reto + `otro` (-> `indeterminado`)
 - `geo`: pregunta `choice` panama / regional / none (relevancia geografica)
Las probabilidades NO estan calibradas (el propio README de Laya advierte que los checkpoints base salen
sobreconfiados): se miden contra etiquetas propias en eval/ antes de usarlas como senal de confianza.
"""

from __future__ import annotations

import importlib
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import CATEGORIES, INDETERMINATE
from ..util import iso_z, now_utc, sha256_hex
from . import input_hash, input_text_for
from .calibration import load_profile, resolve_model_version
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
        self.model_version = resolve_model_version(local, revision)
        self.calibration_profile = load_profile(self.model_version, local)
        if self.calibration_profile is not None:
            self.threshold = self.calibration_profile.threshold
        self._install_calibration_capture()
        self.laya_version = getattr(laya, "__version__", "unknown")
        self.run_at = iso_z(now_utc())
        self.log = log
        self.calls = 0

    def _install_calibration_capture(self) -> None:
        """Captura logits de categoría antes del redondeo de la API de Laya fijada."""
        module = importlib.import_module(self.agent.__class__.__module__)
        required = ("_option_logits", "temp_bucket", "QTYPES", "unpermute_probs", "np")
        if any(not hasattr(module, name) for name in required):
            raise RuntimeError("La versión fijada de Laya no permite capturar logits de calibración")
        decode = self.agent._decode_answers

        def decode_with_logits(*args, **kwargs):
            if len(args) < 6:
                return decode(*args, **kwargs)
            logits, _act, items, ids, internal, offset = args[:6]
            rows = module._option_logits(logits, items, offset)
            answers = decode(*args, **kwargs)
            for index, question_id in enumerate(ids):
                if question_id != "category" or question_id not in answers:
                    continue
                question = internal[question_id]
                question_type = module.QTYPES[question["t"]]
                option_count = len(items[index]["markers"])
                bucket = module.temp_bucket(question_type, option_count)
                base_temperature = self.agent.temperature_by_options.get(
                    bucket, self.agent.temperature[question_type])
                row = module.np.asarray(rows[index], dtype=module.np.float64) / float(base_temperature)
                probabilities = module.np.exp(row - row.max())
                probabilities /= probabilities.sum()
                probabilities = module.unpermute_probs(probabilities, question.get("option_order"))
                keys = list(question["crit"].keys())
                raw_logits = {key: math.log(max(float(value), 1e-300))
                              for key, value in zip(keys, probabilities, strict=True)}
                answers[question_id]["calibration_logits"] = raw_logits
                if self.calibration_profile is not None:
                    answers[question_id]["umbral_calibrated_probabilities"] = (
                        self.calibration_profile.apply_logits(raw_logits))
            return answers

        self.agent._decode_answers = decode_with_logits

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
            probs = {c: round(float(cat_probs.get(c, 0.0)), 6) for c in CATEGORIES}
            probs[INDETERMINATE] = round(float(cat_probs.get("otro", 0.0)), 6)
            raw_logits = ans["category"].get("calibration_logits")
            if raw_logits is None:
                raise RuntimeError("Laya no devolvió los logits necesarios para calibración")
            calibrated_choice_probs = ans["category"].get("umbral_calibrated_probabilities")
            calibrated_probs = None
            if calibrated_choice_probs is not None:
                calibrated_probs = {c: round(float(calibrated_choice_probs.get(c, 0.0)), 6)
                                    for c in CATEGORIES}
                calibrated_probs[INDETERMINATE] = round(
                    float(calibrated_choice_probs.get("otro", 0.0)), 6)
            decision_probs = calibrated_choice_probs or cat_probs
            category, p_best = decide_category(decision_probs, self.threshold)
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
                    "calibrationLogits": raw_logits,
                    **({"calibratedProbabilities": calibrated_probs}
                       if calibrated_probs is not None else {}),
                    "threshold": self.threshold,
                    "geoRelevance": geo,
                    "geoEvidence": geo_ev,
                    "geoMethod": GEO_METHOD,
                    "geoLayaRaw": geo_raw,
                    "classifier": "laya",
                    "modelId": self.model_id,
                    "modelVersion": self.model_version,
                    "predictedAt": ts,
                    "calibrated": self.calibration_profile is not None,
                    **({"calibrationProfileId": self.calibration_profile.profile_id}
                       if self.calibration_profile is not None else {}),
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
            "calibrated": self.calibration_profile is not None,
            "calibrationProfileId": self.calibration_profile.profile_id if self.calibration_profile else None,
            "calibrationProfileSha256": self.calibration_profile.sha256 if self.calibration_profile else None,
            "calibrationTemperature": self.calibration_profile.temperature if self.calibration_profile else None,
            "questions": {"category": f"choice 6+otro ({SCOPE_METHOD})", "geo": f"relevancia por contenido ({GEO_METHOD}); la pregunta geo de Laya se guarda en geoLayaRaw"},
            "scopeMethod": SCOPE_METHOD,
            "note": ("Temperature scaling validado; se conservan las probabilidades crudas."
                     if self.calibration_profile else "Perfil de calibración pendiente; calibrated=false."),
        }


def cache_size_bytes() -> int:
    root = Path.home() / ".cache" / "huggingface" / "hub" / "models--convaiinnovations--laya"
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


_ = re  # (reservado para normalizaciones futuras)
