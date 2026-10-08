"""Cliente HTTP con reintentos y limitacion de ritmo (respeta condiciones de uso)."""

from __future__ import annotations

import time

import httpx

from ..config import USER_AGENT


class Throttle:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


def make_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)


def get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    *,
    throttle: Throttle | None = None,
    retries: int = 4,
    backoff: float = 8.0,
    log=print,
) -> httpx.Response:
    """GET con reintentos ante 429/5xx/errores de red. Lanza la ultima excepcion si se agotan."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        if throttle:
            throttle.wait()
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
                log(f"  [http] {resp.status_code} en {url} (intento {attempt + 1}/{retries + 1})")
            else:
                resp.raise_for_status()
                return resp
        except httpx.TransportError as exc:
            last_exc = exc
            log(f"  [http] error de red {type(exc).__name__} (intento {attempt + 1}/{retries + 1})")
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc
