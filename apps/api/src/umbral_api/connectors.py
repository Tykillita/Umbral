"""Conectores OAuth de Notion y Slack con identidad Firebase anónima y secretos cifrados."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse

import httpx

from .config import Settings
from .errors import Forbidden, NotFound, ServiceUnavailable, Unauthorized, Unprocessable

_UID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_EVENT = re.compile(r"^[A-Za-z0-9_.:-]{1,180}$")
_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2026-03-11"
_SLACK_API = "https://slack.com/api"
_SLACK_STATUSES = {"en_revision", "requiere_evidencia", "aprobado_como_borrador", "descartado"}
_STATUS_LABELS = {
    "nuevo": "Nuevo",
    "en_revision": "En revisión",
    "requiere_evidencia": "Requiere evidencia",
    "aprobado_como_borrador": "Aprobado como borrador",
    "descartado": "Descartado",
}


class ConnectorStore(Protocol):
    def get_credential(self, uid: str, provider: str) -> str | None: ...
    def put_credential(self, uid: str, provider: str, value: str) -> None: ...
    def delete_credential(self, uid: str, provider: str) -> None: ...
    def get_preferences(self, uid: str) -> dict[str, Any]: ...
    def put_preferences(self, uid: str, value: dict[str, Any]) -> None: ...
    def save_oauth_state(self, state: str, value: dict[str, Any]) -> None: ...
    def consume_oauth_state(self, state: str) -> dict[str, Any] | None: ...
    def claim_event(self, uid: str, event_id: str) -> bool: ...
    def finish_event(self, uid: str, event_id: str, status: str) -> None: ...


def _key(value: str | None) -> bytes:
    if not value:
        raise ServiceUnavailable("El cifrado de conectores no está configurado en el servidor.")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        decoded = b""
    if len(decoded) != 32:
        raise ServiceUnavailable("La clave de cifrado de conectores debe ser AES-256 en Base64 URL-safe.")
    return decoded


def _doc_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


class FirestoreConnectorStore:
    """Documentos por usuario/proveedor; los valores secretos solo entran cifrados."""

    def __init__(self, project: str):
        self.project = project
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import firestore

                self._client = firestore.Client(project=self.project)
            except Exception as exc:
                raise ServiceUnavailable("El almacenamiento gratuito de conectores no está disponible. Reintenta más tarde.") from exc
        return self._client

    def get_credential(self, uid: str, provider: str) -> str | None:
        try:
            snapshot = self.client.collection("umbral_connector_credentials").document(_doc_id(uid, provider)).get()
            value = snapshot.to_dict() if snapshot.exists else None
            if not value or value.get("uid") != uid or value.get("provider") != provider:
                return None
            cipher = value.get("ciphertext")
            return cipher if isinstance(cipher, str) else None
        except ServiceUnavailable:
            raise
        except Exception as exc:
            raise ServiceUnavailable("No se pudo consultar la conexión guardada. Comprueba la cuota gratuita de Firestore.") from exc

    def put_credential(self, uid: str, provider: str, value: str) -> None:
        try:
            self.client.collection("umbral_connector_credentials").document(_doc_id(uid, provider)).set(
                {"uid": uid, "provider": provider, "ciphertext": value, "updated_at": int(time.time())}
            )
        except Exception as exc:
            raise ServiceUnavailable("No se pudo guardar la conexión. Comprueba la cuota gratuita de Firestore.") from exc

    def delete_credential(self, uid: str, provider: str) -> None:
        try:
            self.client.collection("umbral_connector_credentials").document(_doc_id(uid, provider)).delete()
        except Exception as exc:
            raise ServiceUnavailable("No se pudo cerrar la conexión en el almacenamiento gratuito.") from exc

    def get_preferences(self, uid: str) -> dict[str, Any]:
        try:
            snapshot = self.client.collection("umbral_connector_preferences").document(_doc_id(uid)).get()
            return snapshot.to_dict() or {} if snapshot.exists else {}
        except Exception as exc:
            raise ServiceUnavailable("No se pudieron consultar las preferencias de conectores. Comprueba la cuota gratuita de Firestore.") from exc

    def put_preferences(self, uid: str, value: dict[str, Any]) -> None:
        try:
            self.client.collection("umbral_connector_preferences").document(_doc_id(uid)).set(value)
        except Exception as exc:
            raise ServiceUnavailable("No se pudieron guardar las preferencias. Comprueba la cuota gratuita de Firestore.") from exc

    def save_oauth_state(self, state: str, value: dict[str, Any]) -> None:
        try:
            self.client.collection("umbral_connector_oauth_states").document(_doc_id(state)).set(value)
        except Exception as exc:
            raise ServiceUnavailable("No se pudo iniciar el flujo de conexión. Comprueba la cuota gratuita de Firestore.") from exc

    def consume_oauth_state(self, state: str) -> dict[str, Any] | None:
        try:
            from google.cloud import firestore

            reference = self.client.collection("umbral_connector_oauth_states").document(_doc_id(state))
            transaction = self.client.transaction()

            @firestore.transactional
            def consume(tx: Any) -> dict[str, Any] | None:
                snapshot = reference.get(transaction=tx)
                value = snapshot.to_dict() if snapshot.exists else None
                if snapshot.exists:
                    tx.delete(reference)
                return value

            return consume(transaction)
        except Exception as exc:
            raise ServiceUnavailable("No se pudo validar la respuesta de conexión. Reintenta el flujo.") from exc

    def claim_event(self, uid: str, event_id: str) -> bool:
        try:
            from google.cloud import firestore

            reference = self.client.collection("umbral_connector_events").document(_doc_id(uid, event_id))
            transaction = self.client.transaction()

            @firestore.transactional
            def claim(tx: Any) -> bool:
                snapshot = reference.get(transaction=tx)
                existing = snapshot.to_dict() if snapshot.exists else {}
                if existing.get("status") == "sent":
                    return False
                if existing.get("status") == "sending" and int(existing.get("updated_at", 0)) > int(time.time()) - 300:
                    return False
                tx.set(reference, {"uid": uid, "status": "sending", "updated_at": int(time.time())})
                return True

            return claim(transaction)
        except Exception as exc:
            raise ServiceUnavailable("No se pudo reservar el aviso para evitar duplicados.") from exc

    def finish_event(self, uid: str, event_id: str, status: str) -> None:
        try:
            self.client.collection("umbral_connector_events").document(_doc_id(uid, event_id)).set(
                {"uid": uid, "status": status, "updated_at": int(time.time())}
            )
        except Exception as exc:
            raise ServiceUnavailable("No se pudo guardar el resultado del aviso.") from exc


class MemoryConnectorStore:
    """Almacén determinista para pruebas de transporte OAuth, sin secretos en respuestas."""

    def __init__(self) -> None:
        self.credentials: dict[tuple[str, str], str] = {}
        self.preferences: dict[str, dict[str, Any]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.events: dict[tuple[str, str], str] = {}
        self.lock = threading.Lock()

    def get_credential(self, uid: str, provider: str) -> str | None:
        return self.credentials.get((uid, provider))

    def put_credential(self, uid: str, provider: str, value: str) -> None:
        self.credentials[(uid, provider)] = value

    def delete_credential(self, uid: str, provider: str) -> None:
        self.credentials.pop((uid, provider), None)

    def get_preferences(self, uid: str) -> dict[str, Any]:
        return dict(self.preferences.get(uid, {}))

    def put_preferences(self, uid: str, value: dict[str, Any]) -> None:
        self.preferences[uid] = dict(value)

    def save_oauth_state(self, state: str, value: dict[str, Any]) -> None:
        self.states[state] = dict(value)

    def consume_oauth_state(self, state: str) -> dict[str, Any] | None:
        with self.lock:
            return self.states.pop(state, None)

    def claim_event(self, uid: str, event_id: str) -> bool:
        with self.lock:
            status = self.events.get((uid, event_id))
            if status in {"sending", "sent"}:
                return False
            self.events[(uid, event_id)] = "sending"
            return True

    def finish_event(self, uid: str, event_id: str, status: str) -> None:
        with self.lock:
            self.events[(uid, event_id)] = status


class ConnectorManager:
    def __init__(self, settings: Settings, store: ConnectorStore | None = None):
        self.settings = settings
        self._store = store

    @property
    def store(self) -> ConnectorStore:
        if self._store is None:
            project = self.settings.firestore_project
            if not project:
                raise ServiceUnavailable("Firebase/Firestore no está configurado para guardar conectores.")
            self._store = FirestoreConnectorStore(project)
        return self._store

    def provider_available(self, provider: str) -> bool:
        if not self.settings.connector_storage_configured:
            return False
        if provider == "notion":
            return bool(self.settings.notion_oauth_client_id and self.settings.notion_oauth_client_secret and self.settings.notion_oauth_redirect_uri)
        if provider == "slack":
            return bool(self.settings.slack_oauth_client_id and self.settings.slack_oauth_client_secret and self.settings.slack_oauth_redirect_uri)
        return False

    def _require_provider(self, provider: str) -> None:
        if provider not in {"notion", "slack"}:
            raise NotFound("Ese conector no existe.")
        if self.settings.offline:
            raise ServiceUnavailable("Los conectores externos están desactivados en modo sin conexión.")
        if not self.provider_available(provider):
            raise ServiceUnavailable(f"{provider.title()} aún no está configurado en esta instalación.")
        _key(self.settings.connector_encryption_key)

    def _validate_uid(self, uid: str) -> None:
        if not _UID.fullmatch(uid):
            raise Unauthorized("La identidad anónima no es válida.")

    def _encrypt(self, uid: str, provider: str, value: dict[str, Any]) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = secrets.token_bytes(12)
        aad = f"umbral:{uid}:{provider}".encode()
        encrypted = AESGCM(_key(self.settings.connector_encryption_key)).encrypt(nonce, json.dumps(value, separators=(",", ":")).encode(), aad)
        return base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")

    def _decrypt(self, uid: str, provider: str, value: str | None) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            packed = base64.urlsafe_b64decode(value.encode("ascii"))
            nonce, encrypted = packed[:12], packed[12:]
            aad = f"umbral:{uid}:{provider}".encode()
            result = AESGCM(_key(self.settings.connector_encryption_key)).decrypt(nonce, encrypted, aad)
            decoded = json.loads(result)
            if not isinstance(decoded, dict):
                raise ValueError("payload")
            return decoded
        except Exception as exc:
            if isinstance(exc, ServiceUnavailable):
                raise
            raise ServiceUnavailable("No se pudo descifrar una conexión guardada. Vuelve a conectar el servicio.") from exc

    def _get_credential(self, uid: str, provider: str) -> dict[str, Any] | None:
        self._validate_uid(uid)
        return self._decrypt(uid, provider, self.store.get_credential(uid, provider))

    def _put_credential(self, uid: str, provider: str, value: dict[str, Any]) -> None:
        self._validate_uid(uid)
        self.store.put_credential(uid, provider, self._encrypt(uid, provider, value))

    def _preferences(self, uid: str) -> dict[str, Any]:
        value = self.store.get_preferences(uid)
        return {
            "notion_destination_id": value.get("notion_destination_id"),
            "notion_destination_title": value.get("notion_destination_title"),
            "slack_channel_id": value.get("slack_channel_id"),
            "slack_channel_name": value.get("slack_channel_name"),
            "slack_enabled": bool(value.get("slack_enabled", False)),
            "slack_statuses": [item for item in value.get("slack_statuses", []) if item in _SLACK_STATUSES],
        }

    def _save_preferences(self, uid: str, **changes: Any) -> dict[str, Any]:
        value = self._preferences(uid)
        value.update(changes)
        self.store.put_preferences(uid, value)
        return value

    def overview(self, uid: str) -> dict[str, Any]:
        self._validate_uid(uid)
        storage_ready = self.settings.connector_storage_configured
        available = {provider: self.provider_available(provider) for provider in ("notion", "slack")}
        credentials = {provider: self._get_credential(uid, provider) if available[provider] else None for provider in available}
        preferences = self._preferences(uid) if any(available.values()) else {}
        return {
            "configured": storage_ready,
            "providers": {
                "notion": {
                    "available": available["notion"],
                    "connected": credentials["notion"] is not None,
                    "workspace_name": (credentials["notion"] or {}).get("workspace_name"),
                    "destination_id": preferences.get("notion_destination_id"),
                    "destination_title": preferences.get("notion_destination_title"),
                },
                "slack": {
                    "available": available["slack"],
                    "connected": credentials["slack"] is not None,
                    "workspace_name": (credentials["slack"] or {}).get("workspace_name"),
                    "channel_id": preferences.get("slack_channel_id"),
                    "channel_name": preferences.get("slack_channel_name"),
                },
            },
            "slack_notifications": {
                "enabled": bool(preferences.get("slack_enabled", False)),
                "statuses": preferences.get("slack_statuses", []),
            },
        }

    def start(self, provider: str, uid: str) -> str:
        self._require_provider(provider)
        self._validate_uid(uid)
        state = secrets.token_urlsafe(32)
        self.store.save_oauth_state(state, {"uid": uid, "provider": provider, "expires_at": int(time.time()) + 600})
        if provider == "notion":
            redirect_uri = self._redirect_uri(self.settings.notion_oauth_redirect_uri)
            query = urlencode({"owner": "user", "client_id": self.settings.notion_oauth_client_id, "redirect_uri": redirect_uri, "response_type": "code", "state": state})
            return f"https://api.notion.com/v1/oauth/authorize?{query}"
        redirect_uri = self._redirect_uri(self.settings.slack_oauth_redirect_uri)
        query = urlencode({"client_id": self.settings.slack_oauth_client_id, "scope": "chat:write,channels:read,groups:read", "redirect_uri": redirect_uri, "state": state})
        return f"https://slack.com/oauth/v2/authorize?{query}"

    @staticmethod
    def _redirect_uri(value: str | None) -> str:
        parsed = urlparse(value or "")
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != ("http" if local else "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ServiceUnavailable("La URL de retorno OAuth del servidor no es válida.")
        return value or ""

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ServiceUnavailable("El proveedor respondió con un formato inesperado.") from exc
        if not isinstance(body, dict):
            raise ServiceUnavailable("El proveedor respondió con un formato inesperado.")
        return body

    @staticmethod
    def _safe_provider_error(status: int) -> str:
        if status == 401:
            return "El proveedor rechazó la conexión. Puede haberse revocado; vuelve a conectarlo."
        if status == 403:
            return "El proveedor no concedió permiso para esta operación. Revisa los permisos y el destino compartido."
        if status == 429:
            return "El proveedor limitó esta operación. Inténtalo más tarde."
        return "El proveedor no pudo completar la operación. Inténtalo más tarde."

    def callback(self, provider: str, state: str, code: str | None, error: str | None) -> bool:
        consumed = self.store.consume_oauth_state(state)
        if not consumed or consumed.get("provider") != provider or int(consumed.get("expires_at", 0)) < int(time.time()):
            raise Forbidden("La autorización caducó o su estado no es válido. Inicia la conexión otra vez.")
        uid = str(consumed.get("uid", ""))
        self._validate_uid(uid)
        if error or not code:
            return False
        self._require_provider(provider)
        if provider == "notion":
            payload = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri(self.settings.notion_oauth_redirect_uri),
            }
            client_id, client_secret = self.settings.notion_oauth_client_id, self.settings.notion_oauth_client_secret
            url = f"{_NOTION_API}/oauth/token"
            response = self._post_token(url, payload, auth=(client_id or "", client_secret or ""))
            body = self._json(response)
            access = body.get("access_token")
            refresh = body.get("refresh_token")
            if not response.is_success or not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ServiceUnavailable("Notion no pudo completar la autorización. Revisa la aplicación OAuth e inténtalo de nuevo.")
            owner = body.get("owner") if isinstance(body.get("owner"), dict) else {}
            self._put_credential(uid, provider, {
                "access_token": access,
                "refresh_token": refresh,
                "workspace_id": body.get("workspace_id"),
                "workspace_name": body.get("workspace_name"),
                "bot_id": body.get("bot_id"),
                "owner": owner,
                "expires_at": int(time.time()) + int(body["expires_in"]) if isinstance(body.get("expires_in"), (int, float)) else None,
            })
            return True
        payload = {
            "code": code,
            "client_id": self.settings.slack_oauth_client_id or "",
            "client_secret": self.settings.slack_oauth_client_secret or "",
            "redirect_uri": self._redirect_uri(self.settings.slack_oauth_redirect_uri),
        }
        response = self._post_token(f"{_SLACK_API}/oauth.v2.access", payload)
        body = self._json(response)
        access = body.get("access_token")
        team_value = body.get("team")
        team: dict[str, Any] = team_value if isinstance(team_value, dict) else {}
        if not response.is_success or body.get("ok") is not True or not isinstance(access, str) or not access or not team.get("id"):
            raise ServiceUnavailable("Slack no pudo completar la autorización. Revisa la aplicación OAuth e inténtalo de nuevo.")
        self._put_credential(uid, provider, {
            "access_token": access,
            "refresh_token": body.get("refresh_token"),
            "team_id": team.get("id"),
            "workspace_name": team.get("name"),
            "bot_user_id": body.get("bot_user_id"),
            "scope": body.get("scope", ""),
            "expires_at": int(time.time()) + int(body["expires_in"]) if isinstance(body.get("expires_in"), (int, float)) else None,
        })
        return True

    @staticmethod
    def _post_token(url: str, data: dict[str, Any], *, auth: tuple[str, str] | None = None) -> httpx.Response:
        try:
            if auth:
                return httpx.post(url, auth=auth, json=data, timeout=20.0, follow_redirects=False)
            return httpx.post(url, data=data, timeout=20.0, follow_redirects=False)
        except (httpx.HTTPError, OSError) as exc:
            raise ServiceUnavailable("No se pudo contactar con el proveedor OAuth. Revisa la conexión e inténtalo de nuevo.") from exc

    def _refresh(self, uid: str, provider: str, credential: dict[str, Any]) -> dict[str, Any]:
        refresh = credential.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            self.store.delete_credential(uid, provider)
            raise Unauthorized(f"La conexión con {provider.title()} fue revocada. Vuelve a conectarla.")
        if provider == "notion":
            payload = {"grant_type": "refresh_token", "refresh_token": refresh}
            response = self._post_token(
                f"{_NOTION_API}/oauth/token",
                payload,
                auth=(self.settings.notion_oauth_client_id or "", self.settings.notion_oauth_client_secret or ""),
            )
            body = self._json(response)
            if not response.is_success or not isinstance(body.get("access_token"), str) or not isinstance(body.get("refresh_token"), str):
                self.store.delete_credential(uid, provider)
                raise Unauthorized("Notion rechazó la renovación. Vuelve a conectar Notion.")
            credential.update({"access_token": body["access_token"], "refresh_token": body["refresh_token"]})
        else:
            response = self._post_token(f"{_SLACK_API}/oauth.v2.access", {
                "client_id": self.settings.slack_oauth_client_id,
                "client_secret": self.settings.slack_oauth_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            })
            body = self._json(response)
            if not response.is_success or body.get("ok") is not True or not isinstance(body.get("access_token"), str) or not isinstance(body.get("refresh_token"), str):
                self.store.delete_credential(uid, provider)
                raise Unauthorized("Slack rechazó la renovación. Vuelve a conectar Slack.")
            credential.update({"access_token": body["access_token"], "refresh_token": body["refresh_token"]})
        expires_in = body.get("expires_in")
        credential["expires_at"] = int(time.time()) + int(expires_in) if isinstance(expires_in, (int, float)) else None
        self._put_credential(uid, provider, credential)
        return credential

    def _token(self, uid: str, provider: str, *, force_refresh: bool = False) -> str:
        self._require_provider(provider)
        credential = self._get_credential(uid, provider)
        if not credential:
            raise ServiceUnavailable(f"Conecta {provider.title()} antes de usar esta función.")
        expiry = credential.get("expires_at")
        if force_refresh or (isinstance(expiry, (int, float)) and expiry <= time.time() + 60):
            credential = self._refresh(uid, provider, credential)
        token = credential.get("access_token")
        if not isinstance(token, str) or not token:
            raise Unauthorized(f"La conexión con {provider.title()} fue revocada. Vuelve a conectarla.")
        return token

    def _notion_request(self, uid: str, method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{_NOTION_API}{path}"
        for attempt in range(2):
            token = self._token(uid, "notion", force_refresh=attempt == 1)
            try:
                response = httpx.request(method, url, headers={"Authorization": f"Bearer {token}", "Notion-Version": _NOTION_VERSION, "Content-Type": "application/json"}, json=payload, timeout=20.0, follow_redirects=False)
            except (httpx.HTTPError, OSError) as exc:
                raise ServiceUnavailable("No se pudo conectar con Notion. Revisa la conexión e inténtalo de nuevo.") from exc
            if response.status_code == 401 and attempt == 0:
                continue
            if not response.is_success:
                if response.status_code == 401:
                    self.store.delete_credential(uid, "notion")
                    raise Unauthorized("La conexión con Notion fue revocada. Vuelve a conectarla.")
                raise ServiceUnavailable(self._safe_provider_error(response.status_code))
            return self._json(response)
        raise ServiceUnavailable("Notion no respondió después de renovar la conexión.")

    @staticmethod
    def _page_title(page: dict[str, Any]) -> str:
        properties_value = page.get("properties")
        properties: dict[str, Any] = properties_value if isinstance(properties_value, dict) else {}
        for prop in properties.values():
            if not isinstance(prop, dict):
                continue
            title = prop.get("title")
            if isinstance(title, list):
                value = "".join(item.get("plain_text", "") for item in title if isinstance(item, dict))
                if value.strip():
                    return value.strip()[:180]
        return "Página de Notion"

    def notion_pages(self, uid: str) -> list[dict[str, str]]:
        self._token(uid, "notion")
        items: list[dict[str, str]] = []
        cursor: str | None = None
        for _ in range(5):
            payload: dict[str, Any] = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            body = self._notion_request(uid, "POST", "/search", payload=payload)
            results = body.get("results")
            if isinstance(results, list):
                for page in results:
                    if not isinstance(page, dict) or not isinstance(page.get("id"), str):
                        continue
                    raw_url = page.get("url")
                    url = raw_url if isinstance(raw_url, str) and raw_url.startswith("https://") else ""
                    items.append({"id": page["id"], "title": self._page_title(page), "url": url})
            cursor = body.get("next_cursor") if body.get("has_more") and isinstance(body.get("next_cursor"), str) else None
            if not cursor:
                break
        return items

    def choose_notion_destination(self, uid: str, page_id: str) -> None:
        pages = self.notion_pages(uid)
        page = next((item for item in pages if item["id"] == page_id), None)
        if not page:
            raise Forbidden("La página no es accesible para esta conexión. Actualiza la lista y elige una página compartida.")
        self._save_preferences(uid, notion_destination_id=page["id"], notion_destination_title=page["title"])

    def export_notion(self, uid: str, markdown: str) -> dict[str, str]:
        if not markdown.strip() or len(markdown) > 100_000:
            raise Unprocessable("El contenido de la ficha debe tener entre 1 y 100 000 caracteres.")
        preferences = self._preferences(uid)
        page_id = preferences.get("notion_destination_id")
        if not isinstance(page_id, str) or not page_id:
            raise ServiceUnavailable("Elige una página accesible como destino de Notion desde Configuración.")
        match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
        title = match.group(1).strip()[:180] if match else "Ficha de Umbral"
        body = self._notion_request(uid, "POST", "/pages", payload={"parent": {"page_id": page_id}, "markdown": markdown})
        result_id, url = body.get("id"), body.get("url")
        if not isinstance(result_id, str) or not isinstance(url, str) or not url.startswith("https://"):
            raise ServiceUnavailable("Notion respondió sin confirmar la página creada.")
        return {"page_id": result_id, "url": url, "title": title}

    def _slack_request(self, uid: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(2):
            token = self._token(uid, "slack", force_refresh=attempt == 1)
            try:
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
                if method == "conversations.list":
                    response = httpx.get(f"{_SLACK_API}/{method}", headers=headers, params=payload, timeout=20.0, follow_redirects=False)
                else:
                    response = httpx.post(f"{_SLACK_API}/{method}", headers=headers, json=payload, timeout=20.0, follow_redirects=False)
            except (httpx.HTTPError, OSError) as exc:
                raise ServiceUnavailable("No se pudo conectar con Slack. Revisa la conexión e inténtalo de nuevo.") from exc
            body = self._json(response)
            if response.status_code == 401 and attempt == 0:
                continue
            if not response.is_success or body.get("ok") is not True:
                error = body.get("error")
                if response.status_code == 401 or error in {"invalid_auth", "token_revoked", "not_authed"}:
                    self.store.delete_credential(uid, "slack")
                    raise Unauthorized("La conexión con Slack fue revocada. Vuelve a conectarla.")
                status = response.status_code if not response.is_success else (429 if error in {"rate_limited", "ratelimited"} else 403)
                raise ServiceUnavailable(self._safe_provider_error(status))
            return body
        raise ServiceUnavailable("Slack no respondió después de renovar la conexión.")

    def slack_channels(self, uid: str) -> list[dict[str, Any]]:
        self._token(uid, "slack")
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(5):
            payload: dict[str, Any] = {"types": "public_channel,private_channel", "exclude_archived": True, "limit": 200}
            if cursor:
                payload["cursor"] = cursor
            body = self._slack_request(uid, "conversations.list", payload)
            channels = body.get("channels")
            if isinstance(channels, list):
                for channel in channels:
                    if not isinstance(channel, dict) or not isinstance(channel.get("id"), str) or not channel.get("is_member"):
                        continue
                    items.append({"id": channel["id"], "name": str(channel.get("name", "canal"))[:100], "is_private": bool(channel.get("is_private"))})
            metadata_value = body.get("response_metadata")
            metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
            cursor = metadata.get("next_cursor") if isinstance(metadata.get("next_cursor"), str) and metadata.get("next_cursor") else None
            if not cursor:
                break
        return items

    def choose_slack_channel(self, uid: str, channel_id: str) -> None:
        channels = self.slack_channels(uid)
        channel = next((item for item in channels if item["id"] == channel_id), None)
        if not channel:
            raise Forbidden("El canal no está accesible para Umbral. Añade la app al canal y actualiza la lista.")
        self._save_preferences(uid, slack_channel_id=channel["id"], slack_channel_name=channel["name"])

    def save_slack_preferences(self, uid: str, *, enabled: bool, statuses: list[str], channel_id: str | None = None) -> None:
        unique = list(dict.fromkeys(statuses))
        if any(status not in _SLACK_STATUSES for status in unique):
            raise Unprocessable("Selecciona estados de revisión válidos.")
        current = self._preferences(uid)
        selected = channel_id or current.get("slack_channel_id")
        if channel_id and channel_id != current.get("slack_channel_id"):
            raise Forbidden("Selecciona el canal con la lista de canales accesibles antes de guardar los avisos.")
        if enabled and (not selected or not unique):
            raise Unprocessable("Elige un canal y al menos un estado antes de activar los avisos.")
        if enabled and not self._get_credential(uid, "slack"):
            raise ServiceUnavailable("Conecta Slack antes de activar los avisos automáticos.")
        self._save_preferences(uid, slack_channel_id=selected, slack_enabled=enabled, slack_statuses=unique)

    def slack_preferences(self, uid: str) -> dict[str, Any]:
        value = self._preferences(uid)
        return {"enabled": value["slack_enabled"], "channel_id": value["slack_channel_id"], "statuses": value["slack_statuses"]}

    @staticmethod
    def _safe_text(value: str, limit: int) -> str:
        return " ".join("".join(char for char in value if char >= " " and char not in "\x7f").split())[:limit]

    def _post_slack_event(self, uid: str, value: dict[str, Any], *, automatic: bool) -> dict[str, Any]:
        self._validate_uid(uid)
        event_id = value.get("event_id")
        if not isinstance(event_id, str) or not _EVENT.fullmatch(event_id):
            raise Unprocessable("El identificador estable del aviso no es válido.")
        status = value.get("status")
        if automatic and not self.provider_available("slack"):
            return {"sent": False, "duplicate": False, "skipped_reason": "Slack aún no está configurado en esta instalación."}
        preferences = self._preferences(uid)
        if automatic and (not preferences.get("slack_enabled") or status not in preferences.get("slack_statuses", [])):
            return {"sent": False, "duplicate": False, "skipped_reason": "Avisos apagados o estado sin seleccionar."}
        if automatic and value.get("from_status") == status:
            return {"sent": False, "duplicate": False, "skipped_reason": "El estado de revisión no cambió."}
        self._require_provider("slack")
        channel = preferences.get("slack_channel_id")
        if not isinstance(channel, str) or not channel:
            raise ServiceUnavailable("Elige un canal de Slack desde Configuración antes de compartir.")
        if not self.store.claim_event(uid, event_id):
            return {"sent": False, "duplicate": True, "skipped_reason": "Este evento ya se envió o está en proceso."}
        title = self._safe_text(str(value.get("title", "")), 240) or "Ficha sin título"
        case_id = self._safe_text(str(value.get("case_id", "")), 100)
        snapshot = self._safe_text(str(value.get("snapshot_id", "")), 80)
        version = value.get("case_version")
        label = _STATUS_LABELS.get(str(status), "Estado actualizado")
        text = f"Umbral · {title}\nEstado de revisión: {label}\nCaso: {case_id} · versión {version} · snapshot {snapshot}"
        try:
            self._slack_request(uid, "chat.postMessage", {"channel": channel, "text": text, "mrkdwn": False, "unfurl_links": False, "unfurl_media": False, "parse": "none"})
        except Exception:
            self.store.finish_event(uid, event_id, "failed")
            raise
        self.store.finish_event(uid, event_id, "sent")
        return {"sent": True, "duplicate": False, "skipped_reason": None}

    def share_case_to_slack(self, uid: str, value: dict[str, Any]) -> dict[str, Any]:
        return self._post_slack_event(uid, value, automatic=False)

    def notify_slack_review(self, uid: str, value: dict[str, Any]) -> dict[str, Any]:
        return self._post_slack_event(uid, value, automatic=True)

    def disconnect(self, uid: str, provider: str) -> None:
        self._validate_uid(uid)
        if provider not in {"notion", "slack"}:
            raise NotFound("Ese conector no existe.")
        self.store.delete_credential(uid, provider)
        if provider == "notion":
            self._save_preferences(uid, notion_destination_id=None, notion_destination_title=None)
        else:
            self._save_preferences(uid, slack_channel_id=None, slack_channel_name=None, slack_enabled=False, slack_statuses=[])
