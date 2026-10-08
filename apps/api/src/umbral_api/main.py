"""Punto de entrada ASGI: `uvicorn umbral_api.main:app --port 8000`."""

from __future__ import annotations

from .app import create_app
from .config import Settings


def create() -> object:
    return create_app(Settings.from_env())


app = create_app(Settings.from_env())


def run() -> None:  # `umbral-api` (script de consola)
    import os

    import uvicorn

    uvicorn.run(
        "umbral_api.main:app",
        host=os.environ.get("UMBRAL_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", os.environ.get("UMBRAL_PORT", "8000"))),
        # La identidad pública maneja CF-Connecting-IP de forma explícita. Evitar
        # que otro middleware confíe indirectamente en X-Forwarded-For.
        proxy_headers=False,
    )
