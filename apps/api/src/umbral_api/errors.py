"""Errores de dominio mapeados a respuestas ErrorResponse {code, message, details}."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers or {}


class NotFound(ApiError):
    status_code = 404
    code = "no_encontrado"


class Unauthorized(ApiError):
    status_code = 401
    code = "no_autenticado"


class Forbidden(ApiError):
    status_code = 403
    code = "prohibido"


class VersionConflict(ApiError):
    """Control de concurrencia optimista: la versión esperada no coincide (409)."""

    status_code = 409
    code = "conflicto_de_version"


class InvalidTransition(ApiError):
    status_code = 422
    code = "transicion_invalida"


class Unprocessable(ApiError):
    status_code = 422
    code = "no_procesable"


class RateLimited(ApiError):
    status_code = 429
    code = "limite_excedido"


class ServiceUnavailable(ApiError):
    status_code = 503
    code = "no_disponible"
