"""Conexión ChatGPT OSS local: OAuth PKCE/OIDC, perfiles separados, renovación y catálogo.

No realiza login personal automáticamente. Tokens nunca salen de esta capa ni se guardan en el repo.
En Windows se cifra con DPAPI del usuario; en Unix se exige modo 0600/0700. Escritura atómica y
bloqueo entre procesos protegen el refresh rotatorio. Contrato oficial consultado el 2026-10-07.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from pydantic import Field

from .config import Settings, repo_root
from .errors import Forbidden, NotFound, ServiceUnavailable, Unauthorized, Unprocessable
from .models import ApiModel

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT = "chatgpt.tokens.use.direct"
TERMINAL_REFRESH = {"invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}


class ConnectionStart(ApiModel):
    profile_id: str | None = None
    label: str = Field(default="Cuenta ChatGPT", min_length=1, max_length=120)


class AuthorizationResponse(ApiModel):
    authorization_url: str
    expires_in: int = 600


class ProfileChoice(ApiModel):
    profile_id: str


class ModelChoice(ApiModel):
    model: str = Field(min_length=1, max_length=150)


class ChatGPTProfile(ApiModel):
    profile_id: str
    label: str
    email: str | None = None
    connected: bool
    plan_usage_enabled: bool
    model: str | None = None
    active: bool


class ConnectionsResponse(ApiModel):
    available: bool
    reason: str | None = None
    profiles: list[ChatGPTProfile] = Field(default_factory=list)
    active_profile_id: str | None = None


class AccountModel(ApiModel):
    slug: str
    display_name: str


class ModelsResponse(ApiModel):
    profile_id: str
    models: list[AccountModel]
    selected_model: str | None = None


class DisconnectResponse(ApiModel):
    remote_revocation_confirmed: bool
    note: str


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    """DPAPI CurrentUser, sin UI. No crea una clave de cifrado exportable."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buf)
    target = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)  # type: ignore[attr-defined]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    fn = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("No se pudo proteger/abrir la credencial con DPAPI.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(target.pbData)


class CredentialStore:
    def __init__(self, path: Path):
        self.path = path
        self._thread_lock = threading.RLock()

    def _check_path(self) -> None:
        if self.path.resolve().is_relative_to(repo_root().resolve()):
            raise Unprocessable("CHATGPT_CREDENTIALS_FILE debe estar fuera del workspace.")

    def read(self) -> dict[str, Any]:
        self._check_path()
        if not self.path.exists():
            return {"profiles": {}, "active": None}
        try:
            raw = self.path.read_bytes()
            if os.name == "nt":
                if not raw.startswith(b"UMBRAL-DPAPI\n"):
                    raise ValueError("Formato no protegido.")
                raw = _dpapi(raw.split(b"\n", 1)[1], decrypt=True)
            elif self.path.stat().st_mode & 0o077:
                raise ValueError("Permisos de archivo demasiado abiertos.")
            saved = json.loads(raw)
            if not isinstance(saved, dict) or not isinstance(saved.get("profiles"), dict):
                raise ValueError("Registro inválido.")
            return saved
        except (OSError, ValueError) as exc:
            raise ServiceUnavailable("No se pudo abrir el almacén protegido de ChatGPT; no se reemplazó.") from exc

    def write(self, saved: dict[str, Any]) -> None:
        self._check_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        raw = json.dumps(saved, ensure_ascii=False).encode()
        if os.name == "nt":
            raw = b"UMBRAL-DPAPI\n" + _dpapi(raw)
        tmp = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()

    @contextmanager
    def locked(self):  # noqa: ANN201
        self._check_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._thread_lock, open(self.path.with_suffix(".lock"), "a+b") as lock:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                # Windows permite bloquear más allá del EOF; no leer el byte antes de adquirir el lock.
                # Otra instancia puede tenerlo bloqueado y esa lectura produciría PermissionError.
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class ChatGPTConnections:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = CredentialStore(settings.chatgpt_credentials_file)
        self.pending: dict[str, dict[str, Any]] = {}
        self._pending_lock = threading.Lock()

    def _online(self) -> None:
        if not self.settings.local_mode or self.settings.auth_mode == "firebase":
            raise Forbidden("Las conexiones personales solo están disponibles en localhost.")
        if self.settings.offline:
            raise ServiceUnavailable("Modo sin conexión: OAuth, catálogo y renovación bloqueados.")

    def _http(self) -> httpx.Client:
        return httpx.Client(timeout=self.settings.gemini_timeout_s, follow_redirects=False)

    def status(self) -> ConnectionsResponse:
        if not self.settings.local_mode or self.settings.auth_mode == "firebase":
            return ConnectionsResponse(available=False, reason="Solo disponible en localhost.")
        saved = self.store.read()
        active = saved.get("active")
        profiles = [ChatGPTProfile(
            profile_id=pid, label=p["label"], email=p.get("email"),
            connected=bool(p.get("access_token")), plan_usage_enabled=DIRECT in p.get("scope", "").split(),
            model=p.get("model"), active=pid == active,
        ) for pid, p in saved["profiles"].items()]
        return ConnectionsResponse(available=not self.settings.offline,
            reason="Modo sin conexión: solicitudes externas bloqueadas." if self.settings.offline else None,
            profiles=profiles, active_profile_id=active)

    def start(self, request: ConnectionStart, redirect_uri: str) -> AuthorizationResponse:
        self._online()
        if not redirect_uri.startswith("http://127.0.0.1:") or not redirect_uri.endswith("/api/v1/auth/callback"):
            raise Unprocessable("El callback debe ser HTTP en 127.0.0.1 con el puerto de esta API.")
        with self.store.locked():
            saved = self.store.read()
            host = saved.setdefault("host", "urn:uuid:" + str(uuid.uuid4()))
            profile = saved["profiles"].get(request.profile_id) if request.profile_id else None
            if request.profile_id and not profile:
                raise NotFound("Perfil ChatGPT no encontrado.")
            self.store.write(saved)
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        client_id = profile["client_id"] if profile else "dynamic_agent_client"
        params = {
            "client_id": client_id, "ext_agent_host_id": host, "response_type": "code", "redirect_uri": redirect_uri,
            "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce, "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="),
        }
        if profile:
            if profile.get("id_token"):
                params["id_token_hint"] = profile["id_token"]
            if profile.get("email"):
                params["login_hint"] = profile["email"]
        else:
            params["agent_name_hint"] = "Umbral"
        with self._pending_lock:
            self.pending = {k: v for k, v in self.pending.items() if v["until"] > time.time()}
            self.pending[state] = {"nonce": nonce, "verifier": verifier, "redirect": redirect_uri,
                "client_id": client_id, "profile_id": request.profile_id, "subject": profile.get("subject") if profile else None,
                "label": profile["label"] if profile else request.label.strip(), "until": time.time() + 600}
        return AuthorizationResponse(authorization_url=AUTHORIZE + "?" + urlencode(params))

    def _identity(self, id_token: str, client_id: str, nonce: str | None) -> dict[str, Any]:
        try:
            with self._http() as client:
                response = client.get(ISSUER + "/.well-known/jwks.json")
                response.raise_for_status()
                keys = response.json()["keys"]
            header = jwt.get_unverified_header(id_token)
            key = next(k for k in keys if k.get("kid") == header.get("kid"))
            required = ["sub", "exp", "iat"] + (["nonce"] if nonce is not None else [])
            identity = jwt.decode(id_token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"],
                audience=client_id, issuer=ISSUER, leeway=15, options={"require": required})
            if not isinstance(identity.get("sub"), str) or not identity["sub"] or (nonce is not None and not secrets.compare_digest(str(identity["nonce"]), nonce)):
                raise ValueError("Identidad/nonce incorrecto.")
            return identity
        except Exception as exc:
            raise Unauthorized("El ID token de ChatGPT no pasó firma, identidad o nonce; no se guardaron credenciales.") from exc

    def _exchange(self, payload: dict[str, str]) -> dict[str, Any]:
        try:
            with self._http() as client:
                response = client.post(TOKEN, data=payload)
            data = response.json()
            if response.status_code >= 400:
                code = data.get("error", "") if isinstance(data, dict) else ""
                if code in TERMINAL_REFRESH:
                    raise Unauthorized("La sesión ChatGPT fue revocada o expiró.", details={"code": code})
                raise ServiceUnavailable("OAuth de ChatGPT no disponible; se conservaron las credenciales.")
            if not isinstance(data, dict) or not isinstance(data.get("access_token"), str) or data.get("token_type", "").lower() != "bearer":
                raise ValueError("Respuesta de tokens inválida.")
            expiry = float(data["expires_in"])
            if expiry <= 0:
                raise ValueError("Expiración inválida.")
            data["expires_at"] = time.time() + expiry
            return data
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ServiceUnavailable("No se completó OAuth de ChatGPT; se conservaron las credenciales.") from exc

    def callback(self, *, state: str, code: str | None, client_id: str | None, error: str | None = None) -> ConnectionsResponse:
        self._online()
        with self._pending_lock:
            pending = self.pending.pop(state, None)
        if not pending or pending["until"] <= time.time():
            raise Unauthorized("Intento OAuth inexistente o expirado; inicia de nuevo.")
        if error:
            raise Unauthorized("La autorización ChatGPT se canceló; la conexión anterior se conserva.")
        issued = client_id or pending["client_id"]
        if not code or issued == "dynamic_agent_client" or (pending["client_id"] != "dynamic_agent_client" and issued != pending["client_id"]):
            raise Unauthorized("El callback no coincide con el registro solicitado.")
        tokens = self._exchange({"grant_type": "authorization_code", "client_id": issued, "code": code,
            "code_verifier": pending["verifier"], "redirect_uri": pending["redirect"], "resource": RESOURCE})
        identity = self._identity(tokens.get("id_token", ""), issued, pending["nonce"])
        if pending["subject"] and identity["sub"] != pending["subject"]:
            raise Unauthorized("La cuenta recibida no es el perfil seleccionado; no se reemplazó.")
        profile_id = hashlib.sha256((issued + "\0" + identity["sub"]).encode()).hexdigest()[:24]
        with self.store.locked():
            saved = self.store.read()
            old = saved["profiles"].get(profile_id, {})
            saved["profiles"][profile_id] = dict(tokens, client_id=issued, subject=identity["sub"],
                email=identity.get("email"), label=pending["label"], model=old.get("model"))
            saved["active"] = profile_id
            self.store.write(saved)
        return self.status()

    def select(self, profile_id: str) -> ConnectionsResponse:
        self._online()
        with self.store.locked():
            saved = self.store.read()
            if profile_id not in saved["profiles"]:
                raise NotFound("Perfil ChatGPT no encontrado.")
            saved["active"] = profile_id
            self.store.write(saved)
        return self.status()

    def credentials(self) -> dict[str, Any]:
        self._online()
        with self.store.locked():
            saved = self.store.read()
            profile = saved["profiles"].get(saved.get("active"))
            if not profile or not profile.get("access_token"):
                raise Unauthorized("Inicia sesión con ChatGPT.")
            if float(profile.get("expires_at", 0)) <= time.time() + 60:
                if not profile.get("refresh_token"):
                    raise Unauthorized("La sesión expiró; vuelve a iniciar sesión.")
                earliest = profile.get("earliest_refresh_at")
                if earliest is not None and float(earliest) > time.time():
                    raise ServiceUnavailable("La renovación aún no está permitida por el proveedor.")
                try:
                    new = self._exchange({"grant_type": "refresh_token", "client_id": profile["client_id"],
                        "refresh_token": profile["refresh_token"], "resource": RESOURCE})
                except Unauthorized:
                    for field in ("access_token", "refresh_token", "id_token"):
                        profile.pop(field, None)
                    self.store.write(saved)
                    raise
                if not isinstance(new.get("refresh_token"), str) or not new["refresh_token"]:
                    raise ServiceUnavailable("El proveedor no devolvió la renovación rotatoria; no se reemplazó la sesión.")
                if new.get("id_token"):
                    identity = self._identity(new["id_token"], profile["client_id"], None)
                    if identity["sub"] != profile["subject"]:
                        raise Unauthorized("La identidad de la renovación no corresponde a la cuenta activa.")
                profile.update(new)
                self.store.write(saved)
            if DIRECT not in profile.get("scope", "").split():
                raise Unauthorized("La cuenta no autorizó el uso del plan ChatGPT.")
            return dict(profile, profile_id=saved["active"])

    def models(self) -> ModelsResponse:
        profile = self.credentials()
        try:
            with self._http() as client:
                response = client.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + profile["access_token"]})
            response.raise_for_status()
            raw = response.json()["models"]
            models = [AccountModel(slug=m["slug"], display_name=m["display_name"]) for m in raw if m.get("visibility") == "list"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ServiceUnavailable("No se pudo obtener el catálogo de esta cuenta ChatGPT.") from exc
        return ModelsResponse(profile_id=profile["profile_id"], models=models, selected_model=profile.get("model"))

    def choose_model(self, model: str) -> ModelsResponse:
        catalog = self.models()
        if model not in {m.slug for m in catalog.models}:
            raise Unprocessable("El modelo no está disponible en el catálogo de esta cuenta.")
        with self.store.locked():
            saved = self.store.read()
            if saved.get("active") != catalog.profile_id:
                raise Unprocessable("La cuenta activa cambió; recarga su catálogo.")
            saved["profiles"][catalog.profile_id]["model"] = model
            self.store.write(saved)
        catalog.selected_model = model
        return catalog

    def disconnect(self, profile_id: str) -> DisconnectResponse:
        self._online()
        confirmed = False
        with self.store.locked():
            saved = self.store.read()
            profile = saved["profiles"].get(profile_id)
            if not profile:
                raise NotFound("Perfil ChatGPT no encontrado.")
            if profile.get("refresh_token"):
                try:
                    with self._http() as client:
                        discovery = client.get(ISSUER + "/.well-known/openid-configuration")
                        discovery.raise_for_status()
                        endpoint = discovery.json()["revocation_endpoint"]
                        if not endpoint.startswith(ISSUER + "/"):
                            raise ValueError("Revocación fuera del emisor.")
                        response = client.post(endpoint, data={"token": profile["refresh_token"],
                            "token_type_hint": "refresh_token", "client_id": profile["client_id"]})
                        confirmed = response.status_code == 200
                except (httpx.HTTPError, ValueError, KeyError):
                    pass
            for field in ("access_token", "refresh_token", "id_token", "model"):
                profile.pop(field, None)
            if saved.get("active") == profile_id:
                saved["active"] = None
            self.store.write(saved)
        return DisconnectResponse(remote_revocation_confirmed=confirmed,
            note="Sesión desconectada." if confirmed else "Sesión local desconectada. Revocación remota sin confirmar; revisa ChatGPT Settings → Apps.")
