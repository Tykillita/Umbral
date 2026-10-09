"""Exportación directa de una ficha Markdown a una nueva página de Notion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .errors import ServiceUnavailable

NOTION_PAGES_URL = "https://api.notion.com/v1/pages"
# Versión vigente consultada en la documentación oficial de Notion el 2026-10-08.
NOTION_API_VERSION = "2026-03-11"
_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class CreatedNotionPage:
    page_id: str
    url: str
    title: str


class NotionExporter:
    """Cliente mínimo: no hace llamadas al construirlo; solo al pedir una exportación."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def create_page(self, markdown: str) -> CreatedNotionPage:
        api_key = self.settings.notion_api_key
        parent_page_id = self.settings.notion_parent_page_id
        if not api_key or not api_key.strip() or not parent_page_id or not parent_page_id.strip():
            raise ServiceUnavailable("Notion no está configurado. Define NOTION_API_KEY y NOTION_PARENT_PAGE_ID en apps/api/.env.")
        if self.settings.offline:
            raise ServiceUnavailable("La exportación a Notion no está disponible en modo sin conexión.")

        match = _TITLE.search(markdown)
        title = match.group(1).strip() if match else "Ficha de Umbral"
        try:
            response = httpx.post(
                NOTION_PAGES_URL,
                headers={
                    "Authorization": f"Bearer {api_key.strip()}",
                    "Notion-Version": NOTION_API_VERSION,
                    "Content-Type": "application/json",
                },
                json={"parent": {"page_id": parent_page_id.strip()}, "markdown": markdown},
                timeout=20.0,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ServiceUnavailable("No se pudo conectar con Notion. Comprueba la conexión e inténtalo de nuevo.") from exc

        if not response.is_success:
            message = _safe_notion_error(response.status_code)
            raise ServiceUnavailable(message, details={"provider": "notion", "httpStatus": response.status_code})

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise ServiceUnavailable("Notion respondió con un formato inesperado; no se pudo confirmar la exportación.") from exc
        if not isinstance(payload, dict):
            raise ServiceUnavailable("Notion respondió con un formato inesperado; no se pudo confirmar la exportación.")
        page_id = payload.get("id")
        page_url = payload.get("url")
        if not isinstance(page_id, str) or not page_id.strip() or not isinstance(page_url, str) or not page_url.startswith("https://"):
            raise ServiceUnavailable("Notion no devolvió los datos de la página; no se pudo confirmar la exportación.")
        return CreatedNotionPage(page_id=page_id, url=page_url, title=title)


def _safe_notion_error(status_code: int) -> str:
    """Traduce fallos comunes sin propagar el cuerpo remoto, que no es confiable."""
    if status_code == 401:
        return "Notion rechazó la credencial. Revisa NOTION_API_KEY."
    if status_code == 403:
        return "La integración no puede crear páginas en el destino. Compártelo con la integración de Notion."
    if status_code == 404:
        return "Notion no encontró la página destino. Revisa NOTION_PARENT_PAGE_ID y sus permisos."
    if status_code == 429:
        return "Notion limitó temporalmente las exportaciones. Inténtalo de nuevo más tarde."
    if status_code in {400, 413, 422}:
        return "Notion rechazó el contenido de la ficha. Revisa el tamaño o formato del Markdown."
    return "Notion no pudo completar la exportación. Inténtalo de nuevo más tarde."
