"""Publica archivos de datos en un build local; descarga el feed previo sin modificar fuentes.

No despliega nada. Cada archivo se verifica contra su manifest antes de copiarlo.
El descriptor es relativo a /data/ y el historial conserva siete snapshots Laya.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from umbral_pipeline.snapshot import verify_snapshot  # noqa: E402

SNAPSHOT_ID = re.compile(r"^\d{8}-[a-f0-9]{8}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def read_manifest(snapshot: Path) -> dict:
    if snapshot.is_symlink() or not SNAPSHOT_ID.fullmatch(snapshot.name):
        raise ValueError("Carpeta de snapshot no válida.")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("snapshotId") != snapshot.name or manifest.get("containsFixtures") is not False:
        raise ValueError("El snapshot público debe coincidir con su carpeta y no contener fixtures.")
    classifier = manifest.get("classifier", {})
    if classifier.get("classifier") != "laya":
        raise ValueError("La publicación diaria requiere predicciones Laya, sin sustitución por baseline.")
    files = manifest.get("files", {})
    if not isinstance(files, dict) or not 1 <= len(files) <= 32:
        raise ValueError("Lista de archivos del manifest no válida.")
    for name, record in files.items():
        if not FILENAME.fullmatch(name) or ".." in name or name == "manifest.json":
            raise ValueError("Nombre de archivo no permitido en manifest.")
        if not isinstance(record, dict) or not SHA256.fullmatch(record.get("sha256", "")):
            raise ValueError("SHA-256 no válido en manifest.")
        file = snapshot / name
        if file.is_symlink() or not file.resolve().is_relative_to(snapshot.resolve()):
            raise ValueError("Un snapshot público no admite enlaces ni rutas externas.")
        if not file.is_file() or file.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Archivo ausente o demasiado grande.")
        if digest(file) != record["sha256"]:
            raise ValueError(f"Integridad del snapshot: SHA-256 distinto en {name}.")
    if sum((snapshot / name).stat().st_size for name in files) > 128 * 1024 * 1024:
        raise ValueError("El snapshot excede el límite total del feed (128 MB).")
    ok, problems = verify_snapshot(snapshot)
    if not ok:
        raise ValueError("Integridad del snapshot: " + "; ".join(problems))
    return manifest


def descriptor(snapshot: Path, published_at: str) -> dict:
    manifest = read_manifest(snapshot)
    prefix = f"snapshots/{snapshot.name}/"
    return {
        "schemaVersion": 1,
        "snapshotId": snapshot.name,
        "publishedAt": published_at,
        "manifest": {"path": prefix + "manifest.json", "sha256": digest(snapshot / "manifest.json")},
        "files": [
            {"path": prefix + name, "sha256": record["sha256"], "sizeBytes": (snapshot / name).stat().st_size}
            for name, record in sorted(manifest["files"].items())
        ],
    }


def _remove_generated(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    if path.is_symlink() or resolved.parent != parent.resolve() or not path.name.startswith(".umbral-data-"):
        raise ValueError("No se elimina una ruta fuera del área temporal de datos.")
    if path.exists():
        shutil.rmtree(path)


def stage(snapshots_root: Path, web_dist: Path, active_id: str | None = None, retain: int = 7, api_url: str | None = None) -> dict:
    snapshots_root, web_dist = snapshots_root.resolve(), web_dist.resolve()
    if not 1 <= retain <= 7 or not (web_dist / "index.html").is_file():
        raise ValueError("Se requiere un build de la web y retención entre uno y siete.")
    active_id = active_id or (snapshots_root / "CURRENT").read_text(encoding="utf-8").strip()
    if not SNAPSHOT_ID.fullmatch(active_id):
        raise ValueError("CURRENT no contiene un identificador válido.")
    active = snapshots_root / active_id
    read_manifest(active)  # jamás saltar la validación del activo
    if api_url:
        api = urlsplit(api_url)
        if (api.scheme != "https" or not api.hostname or not api.hostname.endswith(".onrender.com")
            or api.username or api.password or api.query or api.fragment or api.path not in {"", "/"}):
            raise ValueError("API pública debe ser un origen HTTPS de Render sin credenciales.")
    valid: list[tuple[str, Path]] = []
    for candidate in snapshots_root.iterdir():
        if not candidate.is_dir() or candidate == active or not SNAPSHOT_ID.fullmatch(candidate.name):
            continue
        try:
            manifest = read_manifest(candidate)
            valid.append((manifest.get("createdAt", manifest.get("cutoffUtc", "")), candidate))
        except (ValueError, OSError, KeyError, json.JSONDecodeError):
            continue  # candidato antiguo inválido nunca sustituye al activo
    selected = [active, *(item[1] for item in sorted(valid, reverse=True)[: retain - 1])]
    published_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    records = [descriptor(snapshot, published_at) for snapshot in selected]
    web_dist.mkdir(parents=True, exist_ok=True)
    destination = web_dist / "data"
    if destination.is_symlink() or not destination.resolve().is_relative_to(web_dist):
        raise ValueError("El destino de datos debe estar dentro del build.")
    temporary = Path(tempfile.mkdtemp(prefix=".umbral-data-stage-", dir=web_dist)).resolve()
    temporary.relative_to(web_dist)
    backup = web_dist / (".umbral-data-backup-" + temporary.name.rsplit("-", 1)[-1])
    try:
        for snapshot, record in zip(selected, records, strict=True):
            out = temporary / "snapshots" / snapshot.name
            out.mkdir(parents=True)
            names = [Path(item["path"]).name for item in record["files"]] + ["manifest.json"]
            for name in names:
                shutil.copyfile(snapshot / name, out / name)
            read_manifest(out)
        (temporary / "current.json").write_text(json.dumps(records[0], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temporary / "history.json").write_text(json.dumps({"schemaVersion": 1, "snapshots": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if destination.exists():
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except BaseException:
            if backup.exists():
                os.replace(backup, destination)
            raise
        _remove_generated(backup, web_dist)
        if api_url:
            config = {"schemaVersion": 1, "apiUrl": api_url.rstrip("/")}
            config_file = web_dist / ".umbral-public-config.json"
            config_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            os.replace(config_file, web_dist / "public-config.json")
        return {"snapshotId": active_id, "snapshots": len(records), "descriptorSha256": digest(destination / "current.json")}
    finally:
        _remove_generated(temporary, web_dist)


def fetch_bytes(url: str, limit: int) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "Umbral-data-release/1"}), timeout=60) as response:
        # urllib sigue redirects: la publicación solo admite el origen configurado.
        if urlsplit(response.url).netloc != urlsplit(url).netloc or urlsplit(response.url).scheme != "https":
            raise ValueError("El feed redirige fuera del origen HTTPS configurado.")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Descarga supera el tamaño permitido.")
        return data


def download(base_url: str, snapshots_root: Path) -> dict:
    base = urlsplit(base_url)
    if base.scheme != "https" or not base.netloc or base.username or base.password or base.query or base.fragment:
        raise ValueError("El feed debe ser una URL HTTPS sin credenciales ni parámetros.")
    base_url = base_url.rstrip("/") + "/"
    current = json.loads(fetch_bytes(urljoin(base_url, "current.json"), MAX_METADATA_BYTES))
    history = json.loads(fetch_bytes(urljoin(base_url, "history.json"), MAX_METADATA_BYTES))
    records = history.get("snapshots", [])
    if history.get("schemaVersion") != 1 or not isinstance(records, list) or not 1 <= len(records) <= 7:
        raise ValueError("Historial de snapshots no válido.")
    records = [current, *(record for record in records if record.get("snapshotId") != current.get("snapshotId"))][:7]
    snapshots_root = snapshots_root.resolve()
    snapshots_root.mkdir(parents=True, exist_ok=True)
    for record in records:
        sid = record.get("snapshotId", "")
        if record.get("schemaVersion") != 1 or not SNAPSHOT_ID.fullmatch(sid):
            raise ValueError("Identificador del descriptor no válido.")
        prefix = f"snapshots/{sid}/"
        manifest_ref = record.get("manifest", {})
        if manifest_ref.get("path") != prefix + "manifest.json" or not SHA256.fullmatch(manifest_ref.get("sha256", "")):
            raise ValueError("Referencia a manifest no válida.")
        manifest_data = fetch_bytes(urljoin(base_url, manifest_ref["path"]), MAX_METADATA_BYTES)
        if hashlib.sha256(manifest_data).hexdigest() != manifest_ref["sha256"]:
            raise ValueError("SHA-256 del manifest descargado no coincide.")
        manifest = json.loads(manifest_data)
        files = record.get("files", [])
        if not isinstance(files, list) or not 1 <= len(files) <= 32:
            raise ValueError("Descriptor sin archivos válidos.")
        expected = manifest.get("files", {})
        names = [item.get("path", "").removeprefix(prefix) for item in files]
        if set(names) != set(expected) or len(set(names)) != len(names):
            raise ValueError("Descriptor y manifest no declaran los mismos archivos.")
        temporary = Path(tempfile.mkdtemp(prefix=".umbral-data-download-", dir=snapshots_root)).resolve()
        temporary.relative_to(snapshots_root)
        prepared = temporary / sid
        prepared.mkdir()
        try:
            (prepared / "manifest.json").write_bytes(manifest_data)
            for item, name in zip(files, names, strict=True):
                size = item.get("sizeBytes")
                if (not FILENAME.fullmatch(name) or ".." in name or item.get("path") != prefix + name
                    or isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE_BYTES
                    or item.get("sha256") != expected[name].get("sha256")):
                    raise ValueError("Ruta, tamaño o hash no válido en descriptor.")
                data = fetch_bytes(urljoin(base_url, item["path"]), size)
                if len(data) != size or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError("Un archivo descargado no coincide con su descriptor.")
                (prepared / name).write_bytes(data)
            read_manifest(prepared)
            destination = snapshots_root / sid
            if destination.exists():
                old = read_manifest(destination)
                if old != manifest:
                    raise ValueError("Un snapshot inmutable ya existe con un manifest distinto.")
            else:
                os.replace(prepared, destination)
        finally:
            _remove_generated(temporary, snapshots_root)
    descriptor_fd, pointer_name = tempfile.mkstemp(prefix=".umbral-data-current-", dir=snapshots_root)
    pointer = Path(pointer_name)
    try:
        with os.fdopen(descriptor_fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(current["snapshotId"] + "\n")
        os.replace(pointer, snapshots_root / "CURRENT")
    finally:
        if pointer.exists():
            pointer.unlink()
    return {"snapshotId": current["snapshotId"], "snapshots": len(records)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("stage")
    build.add_argument("--snapshots-root", type=Path, default=ROOT / "data/snapshots")
    build.add_argument("--web-dist", type=Path, default=ROOT / "apps/web/dist")
    build.add_argument("--snapshot-id")
    build.add_argument("--api-url", help="origen HTTPS de Render publicado; descubrimiento desde escritorio")
    fetch = sub.add_parser("download")
    fetch.add_argument("--base-url", required=True, help="origen HTTPS y prefijo /data/")
    fetch.add_argument("--snapshots-root", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.snapshots_root, args.web_dist, args.snapshot_id, api_url=args.api_url) if args.command == "stage" else download(args.base_url, args.snapshots_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
