"""Clasificacion de categorias (Laya o baseline lexico)."""

from __future__ import annotations

from typing import Protocol

from ..util import normalize_text, sha256_hex


def input_text_for(article: dict) -> str:
    """Texto de entrada normalizado (hoy: solo titular). Su SHA-256 es el `inputHash` del contrato."""
    return normalize_text(article["title"])


def input_hash(article: dict) -> str:
    return sha256_hex(input_text_for(article))


class Classifier(Protocol):
    name: str
    model_id: str
    model_version: str
    threshold: float

    def predict(self, articles: list[dict]) -> list[dict]: ...
