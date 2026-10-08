"""Sesión de Claude: reconoce la sesión abierta en el equipo y lanza el inicio de sesión del CLI oficial.

Umbral NO implementa su propio OAuth de Claude ni lee sus ficheros de credenciales: las credenciales de la suscripción
pertenecen al CLI oficial (``claude auth login``). Aquí solo se (a) pregunta ``claude auth status`` y (b) se lanza
``claude auth login --claudeai`` para que el CLI abra el navegador. Nunca se ofrece ``--console`` (facturación por API,
fuera de la ruta gratuita) y el entorno del hijo no hereda ``ANTHROPIC_API_KEY`` ni ``ANTHROPIC_AUTH_TOKEN``.
Solo localhost (el guardia está en las rutas).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any

from .config import Settings
from .errors import ServiceUnavailable, Unprocessable
from .models import ApiModel

STATUS_TIMEOUT_S = 10
LOGOUT_TIMEOUT_S = 20
CACHE_TTL_S = 15.0
LOGIN_WINDOW_S = 600.0
LOGIN_COMMAND = "claude auth login"
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def clean_env() -> dict[str, str]:
    """Entorno del CLI sin credenciales de API: solo puede usar la sesión de suscripción del propio CLI."""
    return {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}


class ClaudeConnection(ApiModel):
    available: bool
    installed: bool = False
    logged_in: bool = False
    auth_method: str | None = None
    account: str | None = None
    login_pending: bool = False
    reason: str | None = None
    login_command: str = LOGIN_COMMAND


def _billing_by_api(method: str | None) -> bool:
    """Una sesión de Consola/clave de API factura por uso: queda fuera de la ruta gratuita."""
    value = (method or "").lower()
    return "console" in value or "api" in value


class ClaudeSession:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._cached: tuple[float, ClaudeConnection] | None = None
        self._login: subprocess.Popen[bytes] | None = None
        self._login_started = 0.0

    def _exe(self) -> str | None:
        return shutil.which(self.settings.claude_cli)

    def _invalidate(self) -> None:
        self._cached = None

    def _pending(self) -> bool:
        proc = self._login
        if proc is None:
            return False
        if proc.poll() is not None:
            self._login = None
            return False
        if time.monotonic() - self._login_started > LOGIN_WINDOW_S:
            proc.kill()
            self._login = None
            return False
        return True

    def status(self, *, fresh: bool = False) -> ClaudeConnection:
        if self.settings.offline:
            return ClaudeConnection(available=False, reason="Modo sin conexión: el inicio de sesión está bloqueado.")
        exe = self._exe()
        if not exe:
            return ClaudeConnection(available=False, reason=f"CLI «{self.settings.claude_cli}» no encontrado en PATH.")
        with self._lock:
            pending = self._pending()
            now = time.monotonic()
            if not fresh and not pending and self._cached and now - self._cached[0] < CACHE_TTL_S:
                return self._cached[1]
            conn = self._query(exe)
            conn.login_pending = pending and not conn.logged_in
            if conn.logged_in and self._login is not None:
                self._login = None  # el CLI terminó su flujo
            self._cached = (now, conn)
            return conn

    def _query(self, exe: str) -> ClaudeConnection:
        try:
            proc = subprocess.run(  # noqa: S603 - binario del usuario, sin shell, sin credenciales de API en el entorno
                [exe, "auth", "status", "--json"], capture_output=True, text=True, encoding="utf-8",
                timeout=STATUS_TIMEOUT_S, env=clean_env(), stdin=subprocess.DEVNULL,
            )
            data: Any = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return ClaudeConnection(available=True, installed=True, reason="No se pudo leer el estado de la sesión de Claude.")
        if not isinstance(data, dict):
            return ClaudeConnection(available=True, installed=True, reason="Estado de sesión de Claude no reconocido.")
        method = data.get("authMethod") if isinstance(data.get("authMethod"), str) else None
        logged_in = data.get("loggedIn") is True
        email = data.get("email")
        account = email if isinstance(email, str) and email else None
        if logged_in and _billing_by_api(method):
            return ClaudeConnection(
                available=True, installed=True, logged_in=False, auth_method=method, account=account,
                reason="La sesión abierta factura por API (Consola); Umbral solo usa la suscripción de Claude.")
        reason = None if logged_in else "Sin sesión: inicia sesión con tu cuenta de Claude."
        return ClaudeConnection(available=True, installed=True, logged_in=logged_in, auth_method=method, account=account, reason=reason)

    def login(self) -> ClaudeConnection:
        current = self.status(fresh=True)
        exe = self._exe()
        if not current.installed or not exe:
            raise Unprocessable(current.reason or "CLI de Claude no disponible.", details={"command": LOGIN_COMMAND})
        if current.logged_in or current.login_pending:
            return current
        flags = 0
        if os.name == "nt":  # sin ventana de consola propia y en su propio grupo de procesos
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        try:
            proc = subprocess.Popen(  # noqa: S603 - CLI oficial; sin --console (API de pago); sin shell
                [exe, "auth", "login", "--claudeai"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=clean_env(), creationflags=flags,
            )
        except OSError as exc:
            raise ServiceUnavailable("No se pudo lanzar el inicio de sesión del CLI de Claude.", details={"command": LOGIN_COMMAND}) from exc
        with self._lock:
            self._login = proc
            self._login_started = time.monotonic()
            self._invalidate()
        return self.status(fresh=True)

    def logout(self) -> ClaudeConnection:
        exe = self._exe()
        if not exe:
            raise Unprocessable("CLI de Claude no disponible.")
        try:
            subprocess.run(  # noqa: S603
                [exe, "auth", "logout"], capture_output=True, text=True, encoding="utf-8", timeout=LOGOUT_TIMEOUT_S,
                env=clean_env(), stdin=subprocess.DEVNULL, check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ServiceUnavailable("No se pudo cerrar la sesión de Claude.") from exc
        with self._lock:
            self._invalidate()
        return self.status(fresh=True)
