"""Calibración reproducible de las probabilidades de categoría de Laya."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..util import sha256_file

PROFILE_NAME = "umbral-calibration.json"
MODEL_METADATA_NAME = "umbral-model.json"


@dataclass(frozen=True)
class CalibrationProfile:
    profile_id: str
    model_version: str
    temperature: float
    threshold: float
    method: str = "temperature-scaling"
    sha256: str | None = None

    def apply_logits(self, logits: dict[str, float]) -> dict[str, float]:
        """Calibra logits pre-softmax y sin redondear."""
        values = {key: float(value) / self.temperature for key, value in logits.items()}
        if not values or any(not math.isfinite(value) for value in values.values()):
            raise ValueError("Logits inválidos para calibración")
        peak = max(values.values())
        weights = {key: math.exp(value - peak) for key, value in values.items()}
        total = sum(weights.values())
        return {key: value / total for key, value in weights.items()}

def profile_path(model_dir: Path | None = None, *, use_environment: bool = True) -> Path | None:
    candidates = []
    if use_environment:
        explicit = os.environ.get("UMBRAL_LAYA_CALIBRATION_PROFILE")
        if explicit:
            candidates.append(Path(explicit))
        configured_model = os.environ.get("UMBRAL_LAYA_MODEL_DIR")
        if configured_model:
            candidates.append(Path(configured_model) / PROFILE_NAME)
    if model_dir is not None:
        candidates.append(model_dir / PROFILE_NAME)
    candidates.append(Path(__file__).with_name(PROFILE_NAME))
    return next((path for path in candidates if path.is_file()), None)


def resolve_model_version(model_dir: Path | None, fallback: str) -> str:
    if model_dir is None:
        configured = os.environ.get("UMBRAL_LAYA_MODEL_DIR")
        model_dir = Path(configured) if configured else None
    metadata = model_dir / MODEL_METADATA_NAME if model_dir is not None else None
    if metadata is not None and metadata.is_file():
        raw = json.loads(metadata.read_text(encoding="utf-8"))
        value = str(raw.get("modelVersion") or "")
        if not value:
            raise ValueError(f"Falta modelVersion en {metadata}")
        expected_hash = raw.get("weightsSha256")
        weights = model_dir / "model.safetensors"
        if expected_hash and weights.is_file() and sha256_file(weights) != expected_hash:
            raise ValueError(f"Los pesos no coinciden con {metadata}")
        return value
    return fallback


def load_profile(
    model_version: str, model_dir: Path | None = None, *, use_environment: bool = True
) -> CalibrationProfile | None:
    path = profile_path(model_dir, use_environment=use_environment)
    if path is None:
        return None
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schemaVersion") != "1.0.0" or raw.get("method") != "temperature-scaling":
        raise ValueError(f"Perfil de calibración no compatible: {path}")
    fit = raw.get("fit") or {}
    if (raw.get("evaluationKind") != "agent_review" or fit.get("calibrationExamples", 0) < 150
            or fit.get("validationExamples", 0) < 100):
        raise ValueError("El perfil no tiene soporte mínimo de revisión del agente")
    if (fit.get("testGate") or {}).get("passed") is not True:
        raise ValueError("El perfil no superó la compuerta de la prueba intacta")
    profile = CalibrationProfile(
        profile_id=str(raw.get("profileId") or ""),
        model_version=str(raw.get("modelVersion") or ""),
        temperature=float(raw.get("temperature")),
        threshold=float(raw.get("threshold")),
        sha256=sha256_file(path),
    )
    if not profile.profile_id or profile.model_version != model_version:
        raise ValueError("El perfil de calibración no corresponde a esta versión de Laya")
    if not math.isfinite(profile.temperature) or not 0.05 <= profile.temperature <= 10:
        raise ValueError("Temperatura fuera del intervalo permitido")
    if not math.isfinite(profile.threshold) or not 0 <= profile.threshold <= 0.95:
        raise ValueError("Umbral fuera del intervalo permitido")
    return profile
