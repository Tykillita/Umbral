"""Actualización HTTPS verificada; nunca activar un corpus parcialmente descargado."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import httpx

from .snapshot import sha256_file

if TYPE_CHECKING:
    from .services import Services

_SID = re.compile(r"^\d{8}-[0-9a-f]{8}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
_REQUIRED = {"articles.jsonl", "indicators.jsonl", "predictions.jsonl", "clusters.jsonl", "quality_report.json"}


class SnapshotFeed:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.last_error: str | None = None
        self.last_checked_at: datetime | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _fetch(client: httpx.Client, url: str, limit: int) -> bytes:
        data = bytearray()
        with client.stream("GET", url) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError("El archivo del feed excede el límite de tamaño.")
        return bytes(data)

    def refresh(self) -> bool:
        settings = self.services.settings
        if not settings.snapshot_feed_url or settings.offline:
            return False
        with self._lock:
            self.last_checked_at = datetime.now(UTC)
            staging: Path | None = None
            try:
                with httpx.Client(timeout=30, follow_redirects=False) as client:
                    descriptor = json.loads(self._fetch(client, settings.snapshot_feed_url, 128 * 1024))
                    sid = descriptor.get("snapshotId", "")
                    if descriptor.get("schemaVersion") != 1 or not _SID.fullmatch(sid):
                        raise ValueError("Descriptor de snapshot inválido.")
                    if sid == self.services.corpus.snapshot_id:
                        self.last_error = None
                        return False
                    published = descriptor.get("publishedAt")
                    if not isinstance(published, str) or not published.endswith(("Z", "+00:00")):
                        raise ValueError("El descriptor debe declarar publishedAt UTC.")
                    datetime.fromisoformat(published.replace("Z", "+00:00"))
                    files = descriptor.get("files")
                    if not isinstance(files, list) or not 5 <= len(files) <= 40:
                        raise ValueError("Inventario de archivos inválido.")
                    manifest_meta = descriptor.get("manifest") or {}
                    base_url = urljoin(settings.snapshot_feed_url, ".")

                    def file_url(meta: dict[str, Any], name: str) -> str:
                        relative = f"snapshots/{sid}/{name}"
                        if not _BASENAME.fullmatch(name) or ".." in name or meta.get("path") != relative:
                            raise ValueError("Ruta fuera del snapshot permitido.")
                        if not _HASH.fullmatch(str(meta.get("sha256", ""))):
                            raise ValueError("Hash inválido del feed.")
                        url = urljoin(base_url, relative)
                        if urlparse(url).netloc != urlparse(settings.snapshot_feed_url).netloc:
                            raise ValueError("El feed debe conservar el mismo origen.")
                        return url

                    manifest_bytes = self._fetch(client, file_url(manifest_meta, "manifest.json"), 1024 * 1024)
                    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_meta["sha256"]:
                        raise ValueError("Hash del manifest inválido.")
                    manifest = json.loads(manifest_bytes)
                    cutoff_text = manifest.get("cutoffUtc")
                    if not isinstance(cutoff_text, str):
                        raise ValueError("El manifest debe declarar un corte UTC.")
                    try:
                        incoming_cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise ValueError("El corte del manifest no es una fecha válida.") from exc
                    if incoming_cutoff.tzinfo is None:
                        raise ValueError("El corte del manifest debe incluir zona UTC.")
                    if incoming_cutoff.astimezone(UTC) < self.services.corpus.cutoff.astimezone(UTC):
                        # An older hosted snapshot must not undo newer data discovered
                        # locally by the packaged app.
                        self.last_error = None
                        return False
                    manifest_files = manifest.get("files") or {}
                    if manifest.get("snapshotId") != sid or manifest.get("containsFixtures") is not False:
                        raise ValueError("Manifest ajeno al descriptor o con fixtures.")
                    if not _REQUIRED.issubset(manifest_files):
                        raise ValueError("Faltan archivos obligatorios en el snapshot.")
                    indexed = {meta["path"].rsplit("/", 1)[-1]: meta for meta in files}
                    if len(indexed) != len(files) or set(indexed) != set(manifest_files):
                        raise ValueError("El inventario del feed y el manifest deben coincidir.")
                    root = settings.snapshots_root.resolve()
                    root.mkdir(parents=True, exist_ok=True)
                    staging = Path(tempfile.mkdtemp(prefix=".download-", dir=root))
                    (staging / "manifest.json").write_bytes(manifest_bytes)
                    total = 0
                    for name, meta in indexed.items():
                        size = meta.get("sizeBytes")
                        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 32 * 1024 * 1024:
                            raise ValueError("Tamaño de archivo inválido.")
                        total += size
                        if total > 128 * 1024 * 1024:
                            raise ValueError("El snapshot excede el límite total.")
                        if meta["sha256"] != manifest_files[name].get("sha256"):
                            raise ValueError("Los hashes del descriptor y manifest no coinciden.")
                        data = self._fetch(client, file_url(meta, name), size)
                        if len(data) != size or hashlib.sha256(data).hexdigest() != meta["sha256"]:
                            raise ValueError("Tamaño o hash descargado incorrecto.")
                        (staging / name).write_bytes(data)
                # Construir todo antes de modificar CURRENT o la referencia compartida.
                from dataclasses import replace

                from .services import build_snapshot_state
                from .snapshot import load_corpus

                corpus = load_corpus(replace(settings, snapshot_dir=staging, strict_integrity=True, allow_fixture=False))
                if corpus.contains_fixtures or not corpus.articles or not corpus.clusters:
                    raise ValueError("El snapshot remoto es vacío o contiene fixtures.")
                if corpus.classifier != "laya":
                    raise ValueError("El feed no puede sustituir Laya por otro clasificador.")
                state = build_snapshot_state(corpus)
                target = root / sid
                if target.exists():
                    if sha256_file(target / "manifest.json") != manifest_meta["sha256"]:
                        raise ValueError("Ya existe un snapshot distinto con ese identificador.")
                    for name, meta in indexed.items():
                        if sha256_file(target / name) != meta["sha256"]:
                            raise ValueError("El snapshot local con ese identificador está corrupto.")
                else:
                    staging.rename(target)
                    staging = None
                corpus.path = target
                pointer = root / ".CURRENT.new"
                pointer.write_text(sid + "\n", encoding="utf-8")
                pointer.replace(root / "CURRENT")
                self.services._state = state
                self.last_error = None
                return True
            except Exception:
                # Los detalles de red pueden contener configuración sensible: no se
                # registran. El snapshot previo permanece activo y el error es visible.
                self.last_error = "La actualización de datos falló; se conserva el último snapshot válido."
                return False
            finally:
                if staging is not None and staging.resolve().is_relative_to(settings.snapshots_root.resolve()):
                    shutil.rmtree(staging)
