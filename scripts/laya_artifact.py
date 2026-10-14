"""Empaqueta y descarga el artefacto Laya calibrado (el modelo que clasifica las noticias de producción).

Por qué existe: el job de datos reentrenaba Laya en cada ejecución (~2 h en CPU) y nunca terminó bien: o la compuerta de
calibración fallaba (los pesos salían distintos a los publicados) o el límite de tiempo cancelaba el job. Con el artefacto
exacto publicado como asset de una release de GitHub (gratis en repositorios públicos), el job lo descarga, comprueba su
SHA-256 y sus pesos, y `eval/prepare_laya_production_model.py` lo verifica en segundos en lugar de entrenar.

    python scripts/laya_artifact.py package --model-dir .production/laya-model --out .production/laya-calibrated.tar
    python scripts/laya_artifact.py fetch --dest .production/laya-model

Solo biblioteca estándar. `package` NO sube nada: imprime los comandos de `gh` para que la publicación sea una decisión tuya.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "eval" / "laya-calibrated-artifact.json"
REPO = "Tykillita/Umbral"
# Archivos de runtime que el job exige (igual que eval/prepare_laya_production_model.py).
REQUIRED = (
    "model.safetensors",
    "umbral-model.json",
    "umbral-calibration.json",
    "rl_agent_config.json",
    "tokenizer/tokenizer.json",
    "encoder/config.json",
)
MAX_BYTES = 2 * 1024 ** 3  # tope de una release de GitHub; también el de lo que se extrae
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
EXIT_PENDING = 2


class ArtifactError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_descriptor(path: Path = DESCRIPTOR) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1 or data.get("status") not in {"pending", "published"}:
        raise ArtifactError("El descriptor del artefacto Laya no es válido.")
    return data


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password:
        raise ArtifactError("El artefacto solo puede descargarse por HTTPS desde GitHub.")
    return url


def inspect_model_dir(model_dir: Path) -> dict:
    """Comprueba que la carpeta sea un artefacto completo y devuelve su identidad (versión del modelo y SHA de pesos)."""
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise ArtifactError("--model-dir debe ser una carpeta real.")
    missing = [name for name in REQUIRED if not (model_dir / name).is_file() or (model_dir / name).is_symlink()]
    if missing:
        raise ArtifactError("Faltan archivos del artefacto: " + ", ".join(missing))
    metadata = json.loads((model_dir / "umbral-model.json").read_text(encoding="utf-8"))
    weights_sha = sha256_file(model_dir / "model.safetensors")
    if metadata.get("weightsSha256") != weights_sha:
        raise ArtifactError("Los pesos no coinciden con umbral-model.json: el artefacto está alterado o incompleto.")
    model_version = metadata.get("modelVersion")
    if model_version != f"laya-ft-{weights_sha[:16]}":
        raise ArtifactError("La versión del modelo no corresponde al SHA-256 de sus pesos.")
    return {"modelVersion": model_version, "weightsSha256": weights_sha}


def package(model_dir: Path, out: Path, descriptor_path: Path, tag: str, repo: str) -> dict:
    identity = inspect_model_dir(model_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in model_dir.rglob("*") if p.is_file())
    for path in files:
        if path.is_symlink():
            raise ArtifactError(f"No se empaquetan enlaces simbólicos: {path.name}")
    with tarfile.open(out, "w") as archive:  # sin compresión: los pesos safetensors casi no comprimen
        for path in files:
            if path.name == "umbral-production-artifact.json":
                continue  # recibo local; lo vuelve a escribir la verificación
            info = archive.gettarinfo(path, arcname=path.relative_to(model_dir).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0  # empaquetado reproducible
            info.mode = 0o644
            with path.open("rb") as stream:
                archive.addfile(info, stream)
    size = out.stat().st_size
    if size > MAX_BYTES:
        raise ArtifactError("El artefacto supera el límite de 2 GiB de una release de GitHub.")
    name = out.name
    descriptor = {
        "schemaVersion": 1,
        "status": "published",
        **identity,
        "asset": {
            "name": name,
            "url": f"https://github.com/{repo}/releases/download/{tag}/{name}",
            "sha256": sha256_file(out),
            "sizeBytes": size,
        },
    }
    descriptor_path.write_text(json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return descriptor


def verify_and_extract(archive_path: Path, descriptor: dict, dest: Path) -> dict:
    """Verifica el SHA-256 y el tamaño del archivo, lo extrae sin salir de `dest` y comprueba la identidad de los pesos."""
    asset = descriptor.get("asset") or {}
    if archive_path.stat().st_size != asset.get("sizeBytes") or sha256_file(archive_path) != asset.get("sha256"):
        raise ArtifactError("El archivo descargado no coincide con el tamaño o el SHA-256 del descriptor.")
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    total = 0
    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
        for member in members:
            target = (root / member.name).resolve()
            if not member.isfile() or member.name.startswith(("/", "\\")) or root not in target.parents:
                raise ArtifactError(f"Miembro no permitido en el artefacto: {member.name!r}")
            total += member.size
            if total > MAX_BYTES:
                raise ArtifactError("El artefacto extraído supera el límite permitido.")
        for member in members:
            target = root / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ArtifactError(f"No se pudo leer {member.name!r}.")
            with source, target.open("wb") as output:
                while chunk := source.read(1 << 20):
                    output.write(chunk)
    identity = inspect_model_dir(root)
    if identity["modelVersion"] != descriptor.get("modelVersion") or identity["weightsSha256"] != descriptor.get("weightsSha256"):
        raise ArtifactError("El modelo extraído no es el que declara el descriptor.")
    return identity


def download(url: str, target: Path) -> None:
    class Strict(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            check_url(newurl)  # una redirección fuera de GitHub se rechaza
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(Strict)
    with opener.open(urllib.request.Request(check_url(url), headers={"User-Agent": "umbral-laya-artifact"}), timeout=120) as response, target.open("wb") as output:
        written = 0
        while chunk := response.read(1 << 20):
            written += len(chunk)
            if written > MAX_BYTES:
                raise ArtifactError("La descarga supera el límite permitido.")
            output.write(chunk)


def fetch(descriptor_path: Path, dest: Path) -> int:
    descriptor = load_descriptor(descriptor_path)
    if descriptor["status"] != "published":
        print(
            "El artefacto Laya calibrado aún no está publicado (eval/laya-calibrated-artifact.json está «pending»).\n"
            "Empaquétalo y publícalo una vez (ver docs/public/DEPLOYMENT.md, «Modelo Laya calibrado») o lanza el workflow con train=true.",
            file=sys.stderr,
        )
        return EXIT_PENDING
    if dest.exists() and any(dest.iterdir()):
        print(json.dumps({"fetched": False, "reason": "el destino ya tiene un artefacto (caché)"}))
        return 0
    with tempfile.TemporaryDirectory(prefix="laya-artifact-") as tmp:
        archive = Path(tmp) / "artifact.tar"
        download(descriptor["asset"]["url"], archive)
        identity = verify_and_extract(archive, descriptor, dest)
    print(json.dumps({"fetched": True, **identity}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("package", help="empaqueta una carpeta de modelo y actualiza el descriptor (no sube nada)")
    pack.add_argument("--model-dir", type=Path, required=True)
    pack.add_argument("--out", type=Path, required=True)
    pack.add_argument("--descriptor", type=Path, default=DESCRIPTOR)
    pack.add_argument("--tag", default="laya-calibrated-v1")
    pack.add_argument("--repo", default=REPO)
    get = sub.add_parser("fetch", help="descarga y verifica el artefacto publicado")
    get.add_argument("--descriptor", type=Path, default=DESCRIPTOR)
    get.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "package":
            descriptor = package(args.model_dir.resolve(), args.out.resolve(), args.descriptor, args.tag, args.repo)
            asset = descriptor["asset"]
            print(json.dumps(descriptor, ensure_ascii=False, indent=2))
            print(
                "\nPublicar (acción tuya; este script no sube nada):\n"
                f"  gh release create {args.tag} \"{args.out}\" --repo {args.repo} --title \"Laya calibrada ({descriptor['modelVersion']})\" "
                "--notes \"Artefacto del modelo Laya calibrado que usa el job de datos. Verifica su SHA-256 con eval/laya-calibrated-artifact.json.\"\n"
                f"y haz commit de {args.descriptor.name} (SHA-256 {asset['sha256'][:12]}…).",
                file=sys.stderr,
            )
            return 0
        return fetch(args.descriptor, args.dest)
    except ArtifactError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
