"""Refresco manual de noticias: pide al workflow de GitHub que clasifique un corte nuevo.

La web alojada no puede ejecutar Laya (el API de Render Free no lleva torch) y no hay forma de lanzar el workflow desde
el navegador sin exponer un token. Este módulo lo hace desde el servidor, con un token de GitHub que SOLO tiene permiso de
Actions sobre este repositorio y que vive únicamente como secreto de Render (`UMBRAL_GITHUB_DISPATCH_TOKEN`).

Salvaguardas: no hay token → no hace nada y lo dice; enfriamiento entre peticiones; si ya hay una ejecución en curso o en
cola no lanza otra; solo habla con api.github.com; el token nunca se registra ni se devuelve, y los errores de GitHub se
resumen sin detalles.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .config import Settings

GITHUB_API = "https://api.github.com"
USER_AGENT = "Umbral/0.4 (+https://github.com/Tykillita/Umbral; news refresh dispatcher)"
EXPECTED_MINUTES = "entre 15 y 25 minutos"


@dataclass(frozen=True)
class DispatchOutcome:
    status: str  # solicitada | en_curso | enfriamiento | no_disponible | error
    message: str
    next_allowed_at: datetime | None = None
    run_url: str | None = None


class NewsRefreshDispatcher:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._last_request: float | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.github_dispatch_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }

    def _active_run(self, client: httpx.Client) -> str | None:
        s = self.settings
        for state in ("in_progress", "queued"):
            response = client.get(
                f"{GITHUB_API}/repos/{s.github_repo}/actions/workflows/{s.github_news_workflow}/runs",
                params={"status": state, "per_page": 1},
            )
            response.raise_for_status()
            runs: list[dict[str, Any]] = response.json().get("workflow_runs") or []
            if runs:
                url = str(runs[0].get("html_url") or "")
                return url if url.startswith("https://github.com/") else "https://github.com/" + s.github_repo + "/actions"
        return None

    def request(self) -> DispatchOutcome:
        s = self.settings
        if s.offline or not s.github_dispatch_token:
            return DispatchOutcome(
                "no_disponible",
                "La clasificación automática no está configurada en este servicio. Las noticias recién consultadas se muestran "
                "sin clasificar; el próximo corte llega con la ingesta programada de cada 6 horas.",
            )
        with self._lock:
            now = self._clock()
            if self._last_request is not None and now - self._last_request < s.news_refresh_min_interval_s:
                remaining = s.news_refresh_min_interval_s - (now - self._last_request)
                ago = max(1, round((now - self._last_request) / 60))
                return DispatchOutcome(
                    "enfriamiento",
                    f"Ya se pidió una clasificación hace {ago} min; tarda {EXPECTED_MINUTES} y la agenda se actualiza sola al terminar.",
                    next_allowed_at=self._now() + timedelta(seconds=remaining),
                )
            try:
                with self._client_factory(timeout=8, headers=self._headers(), follow_redirects=False) as client:
                    running = self._active_run(client)
                    if running:
                        self._last_request = now
                        return DispatchOutcome(
                            "en_curso",
                            f"Ya hay una clasificación en curso; tarda {EXPECTED_MINUTES} y la agenda se actualiza sola al terminar.",
                            run_url=running,
                        )
                    response = client.post(
                        f"{GITHUB_API}/repos/{s.github_repo}/actions/workflows/{s.github_news_workflow}/dispatches",
                        json={"ref": s.github_news_ref},
                    )
                    if response.status_code == 204:
                        self._last_request = now
                        return DispatchOutcome(
                            "solicitada",
                            f"Clasificación solicitada. Puede tardar {EXPECTED_MINUTES}; mientras tanto se muestran las noticias "
                            "recién consultadas SIN clasificar. La agenda se actualiza sola cuando llegue el corte nuevo.",
                            next_allowed_at=self._now() + timedelta(seconds=s.news_refresh_min_interval_s),
                        )
                    return DispatchOutcome(
                        "error",
                        "GitHub no aceptó la solicitud de clasificación (revisa los permisos del token del servicio). "
                        "Las noticias recién consultadas siguen visibles sin clasificar.",
                    )
            except Exception:
                # Los detalles de red o de la respuesta pueden revelar configuración: no se registran ni se devuelven.
                return DispatchOutcome(
                    "error",
                    "No se pudo contactar con GitHub para pedir la clasificación; inténtalo de nuevo en unos minutos. "
                    "Las noticias recién consultadas siguen visibles sin clasificar.",
                )
