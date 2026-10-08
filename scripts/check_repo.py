"""Comprobaciones de higiene del repositorio (sin dependencias externas).

- Busca secretos accidentales (claves tipo Gemini/OpenAI/GitHub, bloques de clave privada,
  asignaciones no vacías de variables sensibles fuera de *.example).
- Verifica que no haya archivos prohibidos: .env reales, service-account*.json,
  benchmark reservado (eval/held-out, eval/reserved, *.reserved.*), pesos de modelos.

Uso:  uv run --no-project python scripts/check_repo.py [--strict]   (salida 0 = limpio)

Sin --strict, los archivos prohibidos por NOMBRE (.env locales, cuentas de servicio, bases de datos, etc.) solo
generan AVISO: en un equipo de desarrollo existen legítimamente y el .gitignore evita subirlos (lo que Git
subiría realmente lo examina scripts/preflight_publish.py). CI usa --strict (checkout limpio).
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", ".venv", "dist", ".astro", ".pytest_cache", ".ruff_cache",
             ".mypy_cache", "__pycache__", "playwright-report", "test-results", ".firebase", ".pytest-tmp", ".pytest_tmp", ".results", ".browsers", ".production", ".runtime", ".umbral-local"}
TEXT_EXT = {".log", ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".jsonl", ".md", ".yml", ".yaml", ".toml",
            ".env", ".example", ".txt", ".csv", ".astro", ".css", ".html", ".sh", ".ps1", ".cfg", ".ini"}

SECRET_PATTERNS = {
    "clave Google/Gemini": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "clave estilo OpenAI/Anthropic": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}"),
    "token de GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "bloque de clave privada": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "clave de AWS": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "cuenta de servicio de Google (JSON)": re.compile(r"\"type\"\s*:\s*\"service_account\""),
}
ASSIGN = re.compile(
    r"""(?:^|[\s`'"])(?:export\s+)?([A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)[A-Z0-9_]*)\s*=\s*(\S+)""",
    re.M,
)
ASSIGN_EXT = {".env", ".yml", ".yaml", ".sh", ".ps1", ".toml", ".md", ".cfg", ".ini"}
PLACEHOLDER = re.compile(
    r"^(?:|\"\"|''|\$.*|<.*|\.\.\..*|changeme|your[-_].*|xxx+|none|null|false|true|[\"'`]?<.*|`+)$", re.I
)

FORBIDDEN_NAME = [
    (re.compile(r"(^|/)\.env(\.(?!example$)[^/]*)?$"), ".env real (solo .env.example)"),
    (re.compile(r"(^|/)service-account[^/]*\.json$"), "credencial de cuenta de servicio"),
    (re.compile(r"-firebase-adminsdk-[^/]*\.json$|(^|/)firebase-service-account[^/]*\.json$"), "clave de cuenta de servicio de Firebase"),
    (re.compile(r"(^|/)eval/(held-out|reserved)(/|$)"), "benchmark reservado dentro del repo"),
    (re.compile(r"\.reserved\."), "archivo *.reserved.*"),
    (re.compile(r"\.(safetensors|gguf|pt|pth|ckpt)$"), "pesos de modelo"),
    (re.compile(r"\.(sqlite3?|db)$"), "base de datos local"),
]


def iter_files():
    for base, dirs, files in os.walk(ROOT):
        if Path(base) == ROOT / "apps" / "desktop":
            dirs[:] = [name for name in dirs if name not in {"staging", "build", "release", ".qa"}]
        # Los reservados son inaccesibles a los agentes, incluso al escáner.
        for name in tuple(dirs):
            if name in {"held-out", "reserved"}:
                p = Path(base) / name
                yield p, p.relative_to(ROOT).as_posix()
                dirs.remove(name)
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in files:
            p = Path(base) / name
            yield p, p.relative_to(ROOT).as_posix()


def main() -> int:
    strict = "--strict" in sys.argv
    problems: list[str] = []
    warnings: list[str] = []
    for path, rel in iter_files():
        if rel.startswith(("eval/held-out", "eval/reserved")) or ".reserved." in rel:
            problems.append(f"{rel}: benchmark reservado dentro del árbol; contenido no leído")
            continue
        for rx, why in FORBIDDEN_NAME:
            if rx.search(rel):
                (problems if strict else warnings).append(f"{rel}: {why}")
        if path.name.startswith(".env") and not path.name.endswith(".example"):
            continue  # Nunca abrir secretos locales; preflight_publish comprueba lo que Git incluiría.
        if path.suffix.lower() not in TEXT_EXT and path.name not in {".env.example", "LICENSE"}:
            continue
        if path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, rx in SECRET_PATTERNS.items():
            m = rx.search(text)
            if m:
                problems.append(f"{rel}: posible {label}")
        if (path.suffix.lower() in ASSIGN_EXT or path.name.startswith(".env")) and not rel.endswith(".example")                 and "tests/" not in rel:
            for m in ASSIGN.finditer(text):
                if not PLACEHOLDER.match(m.group(2).strip("\"'")):
                    problems.append(f"{rel}: asignación no vacía de {m.group(1)}")
    if warnings:
        print("AVISO (ignorados por .gitignore; no se suben, verifica con preflight_publish.py):")
        for w in sorted(set(warnings)):
            print(" -", w)
    if problems:
        print("PROBLEMAS DE HIGIENE:")
        for p in sorted(set(problems)):
            print(" -", p)
        return 1
    print("OK: sin secretos ni archivos prohibidos detectados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
