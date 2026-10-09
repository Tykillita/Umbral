"""Configuración por variables de entorno (sin secretos en el repo; ver .env.example)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def repo_root() -> Path:
    # apps/api/src/umbral_api/config.py -> raíz del repo = parents[4]
    return Path(__file__).resolve().parents[4]


def load_dotenv_files() -> None:
    """Carga `.env` (apps/api y raíz del repo) sin pisar variables ya definidas. Sin dependencias extra."""
    for base in (Path(__file__).resolve().parents[2], repo_root()):
        env = base / ".env"
        if not env.is_file():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


def _preview_project() -> str | None:
    """Proyecto Firebase de los previews de PR. Solo un identificador DNS; nunca una expresión libre."""
    value = os.environ.get("UMBRAL_CORS_PREVIEW_PROJECT", "").strip().lower()
    if not value:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9-]{3,28}[a-z0-9]", value):
        raise RuntimeError("UMBRAL_CORS_PREVIEW_PROJECT debe ser un ID de proyecto Firebase válido.")
    return value


def _deploy_commit() -> str | None:
    """SHA del despliegue: UMBRAL_DEPLOY_COMMIT o, en Render, RENDER_GIT_COMMIT. Solo hexadecimal de 7 a 40."""
    value = (os.environ.get("UMBRAL_DEPLOY_COMMIT") or os.environ.get("RENDER_GIT_COMMIT") or "").strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{7,40}", value) else None


@dataclass(frozen=True)
class Settings:
    # --- datos
    snapshot_dir: Path | None = None  # carpeta del snapshot; None => último en data/snapshots o fixture
    snapshots_root: Path = field(default_factory=lambda: repo_root() / "data" / "snapshots")
    allow_fixture: bool = True  # si no hay snapshot real, servir fixture etiquetado
    strict_integrity: bool = False  # si True, un manifest/hash inválido impide arrancar
    semantic_enabled: bool = True  # artefactos íntegros opcionales; nunca carga modelos en la API
    semantic_root: Path = field(default_factory=lambda: repo_root() / "data" / "agrupacion")
    # --- modos
    offline: bool = False  # bloquea llamadas externas (Gemini, ChatGPT, red)
    local_mode: bool = True  # permite adaptadores ChatGPT/Claude solo desde loopback
    auth_mode: str = "local"  # local | dev-header | firebase | public
    desktop_token: str | None = None  # secreto efímero, suministrado por el proceso de escritorio
    trust_cloudflare_ip: bool = False  # solo público detrás de un edge que sobrescribe CF-Connecting-IP
    # --- persistencia
    persistence: str = "sqlite"  # sqlite | memory | firestore | none (solo público)
    sqlite_path: Path = field(default_factory=lambda: repo_root() / ".umbral-local" / "umbral.sqlite")
    firestore_project: str | None = None
    # --- generación
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"  # generación editorial real validada el 2026-10-07
    gemini_fallback_model: str | None = None  # habilitar explícitamente otro modelo del mismo Free Tier si hace falta
    gemini_calls_per_user_day: int = 20
    gemini_global_calls_per_day: int = 20
    gemini_timeout_s: int = 30
    gemini_thinking_budget: int | None = None  # 0 desactiva el «thinking» en modelos que lo admiten
    chatgpt_token_file: Path | None = None
    chatgpt_credentials_file: Path = field(default_factory=lambda: Path.home() / ".umbral-connections" / "chatgpt.dat")
    chatgpt_model: str = ""  # selección explícita del catálogo de la cuenta OAuth
    claude_cli: str = "claude"
    claude_model: str | None = None
    notion_api_key: str | None = None  # solo proceso local; nunca se devuelve a la UI
    notion_parent_page_id: str | None = None
    notion_oauth_client_id: str | None = None
    notion_oauth_client_secret: str | None = None
    notion_oauth_redirect_uri: str | None = None
    slack_oauth_client_id: str | None = None
    slack_oauth_client_secret: str | None = None
    slack_oauth_redirect_uri: str | None = None
    connector_encryption_key: str | None = None
    gemini_stub: str | None = None  # SOLO PRUEBAS: ok | quota | down | no_key (prohibido con auth firebase)
    # --- límites
    queries_per_minute: int = 30
    drafts_per_minute: int = 10
    snapshot_feed_url: str | None = None
    snapshot_refresh_s: int = 900
    snapshot_stale_hours: int = 36
    public_api_url: str | None = None  # escritorio: usa generación pública, sin clave en el instalador
    deploy_commit: str | None = None  # SHA del commit desplegado (trazabilidad); None si no se conoce
    # --- estáticos
    web_dist: Path = field(default_factory=lambda: repo_root() / "apps" / "web" / "dist")
    cors_origins: tuple[str, ...] = ("http://localhost:4321", "http://127.0.0.1:4321")
    # Proyecto Firebase cuyos canales de vista previa de PR (`<proyecto>--pr-<n>-<hash>.web.app`) pueden llamar a la API.
    cors_preview_project: str | None = None
    # --- reglas de scoring (permiten pruebas deterministas)
    now_override: str | None = None  # ISO UTC; por defecto el corte del snapshot

    def validate(self) -> None:
        """Rechaza configuraciones que publicarían sesiones compartidas o datos efímeros."""
        if self.auth_mode not in {"local", "dev-header", "firebase", "public"}:
            raise RuntimeError("UMBRAL_AUTH_MODE debe ser local, dev-header, firebase o public.")
        if self.persistence not in {"sqlite", "memory", "firestore", "none"}:
            raise RuntimeError("UMBRAL_PERSISTENCE debe ser sqlite, memory, firestore o none.")
        if self.trust_cloudflare_ip and (self.auth_mode != "public" or self.local_mode):
            raise RuntimeError("UMBRAL_TRUST_CLOUDFLARE_IP solo puede habilitarse en modo public con LOCAL_MODE=0.")
        if self.auth_mode == "public":
            if self.local_mode or self.persistence != "none" or self.gemini_stub:
                raise RuntimeError("Modo público requiere UMBRAL_LOCAL_MODE=0, UMBRAL_PERSISTENCE=none y no admite stubs.")
        elif self.persistence == "none":
            raise RuntimeError("UMBRAL_PERSISTENCE=none requiere UMBRAL_AUTH_MODE=public.")
        elif not self.local_mode or self.auth_mode == "firebase":
            if self.local_mode or self.auth_mode != "firebase" or self.persistence != "firestore":
                raise RuntimeError(
                    "Modo web requiere UMBRAL_LOCAL_MODE=0, UMBRAL_AUTH_MODE=firebase "
                    "y UMBRAL_PERSISTENCE=firestore; SQLite/dev-header son solo locales."
                )
            if not self.firestore_project:
                raise RuntimeError("Modo web requiere FIREBASE_PROJECT_ID explícito.")
        if self.queries_per_minute < 1 or self.drafts_per_minute < 1:
            raise RuntimeError("Los límites por minuto deben ser positivos.")
        if self.gemini_calls_per_user_day < 0 or self.gemini_timeout_s < 1:
            raise RuntimeError("La cuota Gemini debe ser >= 0 y su timeout positivo.")
        if not 0 <= self.gemini_global_calls_per_day <= 20:
            raise RuntimeError("La cuota pública global de Gemini debe estar entre 0 y 20 llamadas diarias.")
        if self.snapshot_refresh_s < 1 or self.snapshot_stale_hours < 1:
            raise RuntimeError("La actualización y antigüedad de snapshots deben ser positivas.")
        if self.snapshot_feed_url:
            from urllib.parse import urlparse

            url = urlparse(self.snapshot_feed_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise RuntimeError("UMBRAL_SNAPSHOT_FEED_URL debe ser HTTPS, sin credenciales, query ni fragmento.")
        if self.public_api_url:
            from urllib.parse import urlparse

            url = urlparse(self.public_api_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise RuntimeError("UMBRAL_PUBLIC_API_URL debe ser HTTPS sin credenciales, query ni fragmento.")
            if not self.local_mode:
                raise RuntimeError("El puente a la API pública solo está disponible en ejecución local.")

    @property
    def notion_configured(self) -> bool:
        """La exportación requiere ambas variables y no está disponible en modo sin conexión."""
        return bool(self.notion_api_key and self.notion_api_key.strip()
                    and self.notion_parent_page_id and self.notion_parent_page_id.strip() and not self.offline)

    @property
    def connector_storage_configured(self) -> bool:
        return bool(self.firestore_project and self.connector_encryption_key and not self.offline)

    @staticmethod
    def from_env() -> Settings:
        load_dotenv_files()
        snap = os.environ.get("UMBRAL_SNAPSHOT_DIR")
        root = os.environ.get("UMBRAL_SNAPSHOTS_ROOT")
        semantic_root = os.environ.get("UMBRAL_SEMANTIC_ROOT")
        sqlite = os.environ.get("UMBRAL_SQLITE_PATH")
        token = os.environ.get("CHATGPT_TOKEN_FILE")
        credentials = os.environ.get("CHATGPT_CREDENTIALS_FILE")
        web = os.environ.get("UMBRAL_WEB_DIST")
        origins = os.environ.get("UMBRAL_CORS_ORIGINS")
        d = Settings()
        return Settings(
            snapshot_dir=Path(snap) if snap else None,
            snapshots_root=Path(root) if root else d.snapshots_root,
            allow_fixture=_bool("UMBRAL_ALLOW_FIXTURE", True),
            strict_integrity=_bool("UMBRAL_STRICT_INTEGRITY", False),
            semantic_enabled=_bool("UMBRAL_SEMANTIC_ENABLED", True),
            semantic_root=Path(semantic_root) if semantic_root else d.semantic_root,
            offline=_bool("UMBRAL_OFFLINE", False),
            local_mode=_bool("UMBRAL_LOCAL_MODE", True),
            auth_mode=os.environ.get("UMBRAL_AUTH_MODE", "local"),
            desktop_token=os.environ.get("UMBRAL_DESKTOP_TOKEN") or None,
            trust_cloudflare_ip=_bool("UMBRAL_TRUST_CLOUDFLARE_IP", False),
            persistence=os.environ.get("UMBRAL_PERSISTENCE", "sqlite"),
            sqlite_path=Path(sqlite) if sqlite else d.sqlite_path,
            firestore_project=os.environ.get("FIREBASE_PROJECT_ID") or None,
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_model=os.environ.get("GEMINI_MODEL", d.gemini_model),
            gemini_fallback_model=os.environ.get("GEMINI_FALLBACK_MODEL", d.gemini_fallback_model or "") or None,
            gemini_calls_per_user_day=_int("GEMINI_CALLS_PER_USER_DAY", d.gemini_calls_per_user_day),
            gemini_global_calls_per_day=_int("GEMINI_GLOBAL_CALLS_PER_DAY", d.gemini_global_calls_per_day),
            gemini_timeout_s=_int("GEMINI_TIMEOUT_S", d.gemini_timeout_s),
            gemini_thinking_budget=(int(os.environ["GEMINI_THINKING_BUDGET"]) if os.environ.get("GEMINI_THINKING_BUDGET", "").lstrip("-").isdigit() else None),
            chatgpt_token_file=Path(token) if token else None,
            chatgpt_credentials_file=Path(credentials) if credentials else d.chatgpt_credentials_file,
            chatgpt_model=os.environ.get("CHATGPT_MODEL", d.chatgpt_model),
            claude_cli=os.environ.get("CLAUDE_CLI", d.claude_cli),
            claude_model=os.environ.get("CLAUDE_MODEL") or None,
            notion_api_key=os.environ.get("NOTION_API_KEY") or None,
            notion_parent_page_id=os.environ.get("NOTION_PARENT_PAGE_ID") or None,
            notion_oauth_client_id=os.environ.get("NOTION_OAUTH_CLIENT_ID") or None,
            notion_oauth_client_secret=os.environ.get("NOTION_OAUTH_CLIENT_SECRET") or None,
            notion_oauth_redirect_uri=os.environ.get("NOTION_OAUTH_REDIRECT_URI") or None,
            slack_oauth_client_id=os.environ.get("SLACK_OAUTH_CLIENT_ID") or None,
            slack_oauth_client_secret=os.environ.get("SLACK_OAUTH_CLIENT_SECRET") or None,
            slack_oauth_redirect_uri=os.environ.get("SLACK_OAUTH_REDIRECT_URI") or None,
            connector_encryption_key=os.environ.get("CONNECTOR_ENCRYPTION_KEY") or None,
            gemini_stub=os.environ.get("UMBRAL_GEMINI_STUB") or None,
            queries_per_minute=_int("UMBRAL_QUERIES_PER_MINUTE", d.queries_per_minute),
            drafts_per_minute=_int("UMBRAL_DRAFTS_PER_MINUTE", 2 if os.environ.get("UMBRAL_AUTH_MODE") == "public" else d.drafts_per_minute),
            snapshot_feed_url=os.environ.get("UMBRAL_SNAPSHOT_FEED_URL") or None,
            snapshot_refresh_s=_int("UMBRAL_SNAPSHOT_REFRESH_S", d.snapshot_refresh_s),
            snapshot_stale_hours=_int("UMBRAL_SNAPSHOT_STALE_HOURS", d.snapshot_stale_hours),
            public_api_url=os.environ.get("UMBRAL_PUBLIC_API_URL") or None,
            deploy_commit=_deploy_commit(),
            web_dist=Path(web) if web else d.web_dist,
            cors_origins=tuple(o.strip() for o in origins.split(",")) if origins else d.cors_origins,
            cors_preview_project=_preview_project(),
            now_override=os.environ.get("UMBRAL_NOW_OVERRIDE") or None,
        )
