"""Identidad del usuario.

- ``local``: sesión de usuario único (``local``).
- ``dev-header``: cabecera ``X-Umbral-User`` (solo pruebas/desarrollo; nunca en la web pública).
- ``firebase``: ``Authorization: Bearer <ID token>`` de Firebase Auth anónima, verificado con firebase-admin.
"""

from __future__ import annotations

import math
import re
import time
from ipaddress import IPv6Address, ip_address
from typing import Any

from fastapi import Request

from .errors import Unauthorized

_USER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
LOCAL_USER = "local"


class Authenticator:
    def __init__(self, mode: str, firebase_project: str | None = None, *, trust_cloudflare_ip: bool = False):
        if trust_cloudflare_ip and mode != "public":
            raise RuntimeError("La cabecera Cloudflare solo se admite en modo público configurado.")
        self.mode = mode
        self.firebase_project = firebase_project
        self.trust_cloudflare_ip = trust_cloudflare_ip
        self._firebase_ready = False
        self._firebase_app: Any = None

    def _init_firebase(self) -> Any:
        import firebase_admin  # type: ignore[import-not-found]  # extra opcional `firebase`

        if not self._firebase_ready:
            try:
                self._firebase_app = firebase_admin.get_app(name="umbral-auth")
            except ValueError:
                opts = {"projectId": self.firebase_project} if self.firebase_project else None
                self._firebase_app = firebase_admin.initialize_app(options=opts, name="umbral-auth")
            if self.firebase_project and self._firebase_app.project_id != self.firebase_project:
                raise RuntimeError("La aplicación Firebase inicializada pertenece a otro proyecto.")
            self._firebase_ready = True
        from firebase_admin import auth  # type: ignore[import-not-found]

        return auth

    def user_for(self, request: Request) -> str:
        if self.mode == "public":
            # Solo una topología configurada explícitamente permite confiar en este
            # header. El operador debe verificar que el edge lo sobrescriba y que no
            # haya acceso directo al origin. Nunca interpretar X-Forwarded-For.
            candidates = request.headers.getlist("cf-connecting-ip") if self.trust_cloudflare_ip else []
            if len(candidates) == 1:
                candidate = candidates[0].strip()
                try:
                    # Las zonas IPv6 identifican interfaces locales, no visitantes.
                    if "%" in candidate:
                        raise ValueError("Una dirección de visitante no admite zona de interfaz.")
                    address = ip_address(candidate)
                    if isinstance(address, IPv6Address) and address.ipv4_mapped:
                        address = address.ipv4_mapped
                    return "ip:" + str(address)
                except ValueError:
                    pass
            # Falta/malformed/duplicado: agrupar por socket conserva el límite de la
            # IP del proxy; no inventar una identidad desde cabeceras del visitante.
            return "ip:" + (request.client.host if request.client else "unknown")
        if self.mode == "local":
            if not is_loopback(request):
                raise Unauthorized("La sesión local solo admite peticiones desde localhost.")
            return LOCAL_USER
        if self.mode == "dev-header":
            if not is_loopback(request):
                raise Unauthorized("La cabecera de desarrollo solo admite peticiones desde localhost.")
            uid = request.headers.get("x-umbral-user", "").strip()
            if not uid or not _USER_RE.match(uid):
                raise Unauthorized("Falta la cabecera X-Umbral-User válida (modo dev-header).")
            return uid
        if self.mode == "firebase":
            header = request.headers.get("authorization", "")
            if not header.lower().startswith("bearer "):
                raise Unauthorized("Se requiere Authorization: Bearer <token de Firebase>.")
            token = header.split(" ", 1)[1].strip()
            try:
                auth = self._init_firebase()
                decoded = auth.verify_id_token(token, app=self._firebase_app, check_revoked=True)
            except Exception as exc:  # token inválido/expirado o firebase-admin ausente
                raise Unauthorized("Token de Firebase inválido o no verificable.") from exc
            # El SDK omite firma/fechas en el emulador. La vigencia debe mantener la misma
            # invariante en ambos entornos; esto no convierte un token emulado en firmado.
            exp, issued = decoded.get("exp"), decoded.get("iat")
            now = time.time()
            if (isinstance(exp, bool) or isinstance(issued, bool)
                or not isinstance(exp, (int, float)) or not isinstance(issued, (int, float))
                or not math.isfinite(exp) or not math.isfinite(issued)
                or exp <= now or issued > now or issued >= exp):
                raise Unauthorized("Token de Firebase expirado o con fechas de vigencia inválidas.")
            uid = str(decoded.get("uid") or decoded.get("sub") or "")
            if not uid or not _USER_RE.match(uid):
                raise Unauthorized("Token sin identificador de usuario válido.")
            return uid
        raise Unauthorized(f"Modo de autenticación desconocido: {self.mode}")


def is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def is_desktop_oauth_callback(request: Request) -> bool:
    """El navegador OAuth externo no posee el token IPC efímero de Electron.

    Solo se exime el GET exacto del callback local, sin Origin y con state; la
    conexión valida ese state aleatorio, su expiración y el código recibido.
    """
    return (
        request.method == "GET"
        and request.url.path in {
            "/api/v1/auth/callback",
            "/api/v1/connectors/notion/callback",
            "/api/v1/connectors/slack/callback",
        }
        and request.headers.get("origin") is None
        and bool(request.query_params.get("state"))
    )
