"""Examina candidatos de Git sin modificar el checkout ni leer el benchmark reservado.

El índice temporal respeta los .gitignore reales. Solo se examinan nombres y contenido
de los archivos publicables. Las consultas externas reservadas nunca se abren.
Uso: python scripts/preflight_publish.py [carpeta-del-proyecto]
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_repo import (  # noqa: E402
    ASSIGN,
    ASSIGN_EXT,
    FORBIDDEN_NAME,
    PLACEHOLDER,
    SECRET_PATTERNS,
    TEXT_EXT,
)

MAX_BYTES = 5_000_000


def publication_files(root: Path, git_dir: Path) -> list[str]:
    subprocess.run(["git", "init", "-q", str(git_dir.parent)], check=True, capture_output=True)
    args = ["git", "-c", "core.autocrlf=false", f"--git-dir={git_dir}", f"--work-tree={root}"]
    subprocess.run([*args, "add", "-A"], check=True, capture_output=True)
    result = subprocess.run([*args, "ls-files", "-z"], check=True, capture_output=True)
    return [name for name in result.stdout.decode("utf-8").split("\0") if name]


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
    reserved = [root / "eval" / name for name in ("held-out", "reserved")]
    if any(folder.exists() for folder in reserved):
        print("PROBLEMA: benchmark reservado dentro del proyecto; contenido no leído.")
        return 1
    with tempfile.TemporaryDirectory(prefix="umbral-preflight-") as directory:
        temporary = Path(directory).resolve()
        temporary.relative_to(Path(tempfile.gettempdir()).resolve())
        files = publication_files(root, temporary / "repo" / ".git")
        problems: list[str] = []
        big: list[str] = []
        for rel in files:
            path = root / rel
            forbidden = [why for pattern, why in FORBIDDEN_NAME if pattern.search(rel)]
            problems.extend(f"{rel}: {why}" for why in forbidden)
            if rel.startswith("data/raw/"):
                problems.append(f"{rel}: dato crudo no redistribuible")
            # Rechazar por nombre antes de abrir secretos o consultas.
            if forbidden or not path.is_file():
                continue
            if path.is_symlink():
                if not path.resolve().is_relative_to(root):
                    problems.append(f"{rel}: enlace fuera del proyecto")
                continue
            size = path.stat().st_size
            if size > MAX_BYTES:
                big.append(f"{rel} ({size / 1e6:.1f} MB)")
            if path.suffix.lower() not in TEXT_EXT and path.name not in {".env.example", "LICENSE", ".gitignore"}:
                continue
            if size > 20_000_000:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(content):
                    problems.append(f"{rel}: posible {label}")
            if path.suffix.lower() in ASSIGN_EXT and not rel.endswith(".example") and not rel.startswith("tests/"):
                for assignment in ASSIGN.finditer(content):
                    if not PLACEHOLDER.match(assignment.group(2).strip("\"'")):
                        problems.append(f"{rel}: asignación no vacía de {assignment.group(1)}")
        print(f"Archivos que Git subiría: {len(files)}")
        print("Benchmark reservado: excluido de lectura; su contenido no se compara.")
        if big:
            print("AVISO archivos grandes:", *big, sep="\n  ")
        if problems:
            print("PROBLEMAS (no publicar):", *sorted(set(problems)), sep="\n - ")
            return 1
        print("OK: candidatos de publicación sin secretos ni archivos prohibidos detectados.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

