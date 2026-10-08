"""Verifica que el repositorio solo contenga lo publicable.

Examina los archivos versionados (índice de Git), de modo que un `git add -f` no
evita la comprobación. Con `--candidates` examina además los archivos sin versionar
que `.gitignore` no excluye (lo que entraría con un `git add -A`). Con `--commits
<rango>` revisa también los mensajes de commit.

Reglas:
  1. Instrucciones privadas, coordinación, tableros, prompts y registros internos
     no se publican.
  2. Solo los Markdown de la lista explícita se versionan.
  3. Ningún archivo de texto contiene rutas personales de un equipo.
  4. Ningún archivo ni commit incluye líneas de coautoría ni créditos de generación
     asociados a herramientas de IA.
  5. Los enlaces relativos de los Markdown publicados apuntan a archivos versionados.

Uso: python scripts/check_public_files.py [--candidates] [--commits RANGO]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fuente de verdad de los Markdown publicables; debe coincidir con el .gitignore.
PUBLIC_MARKDOWN = (
    "README.md",
    "README.es.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "apps/web/README.md",
    "docs/public/*.md",
    "docs/contracts/api-draft.md",
    "docs/contracts/api-public.md",
    "docs/contracts/snapshot-schema.md",
    "eval/README.md",
    "eval/labels/LEEME.md",
    "tests/e2e/TESTIDS.md",
    "data/snapshots/*/DATA_DICTIONARY.md",
    "data/snapshots/*/TERMS_OF_USE.md",
)

# Nombres o carpetas que nunca se publican, sea cual sea su extensión.
PRIVATE_PATHS = (
    (re.compile(r"(^|/)(CLAUDE|AGENTS|GEMINI)\.md$", re.I), "instrucciones privadas para agentes"),
    (re.compile(r"(^|/)\.claude(/|$)"), "configuración local de agentes"),
    (re.compile(r"^docs/(board|notion)(/|$)"), "coordinación y material interno"),
    (re.compile(r"(^|/)(COORDINATION|CONTINUIDAD|ROSTER|CODEX-GOAL[^/]*)\.md$", re.I), "traspaso o coordinación interna"),
    (re.compile(r"(^|/)prompts[^/]*\.md$", re.I), "prompts internos"),
    (re.compile(r"(^|/)(events|coordination)\.log$", re.I), "registro interno"),
    (re.compile(r"^docs/reto-tvn-media\.pdf$"), "documento de terceros sin permiso de redistribución"),
)

TEXT_SUFFIXES = {
    ".md", ".json", ".jsonl", ".py", ".ts", ".tsx", ".js", ".cjs", ".mjs", ".astro", ".css", ".html",
    ".yml", ".yaml", ".toml", ".txt", ".csv", ".ps1", ".sh", ".xml", ".cfg", ".ini", ".rules", ".env",
    ".geojson", ".lock",
}
MAX_TEXT_BYTES = 8_000_000
# Este verificador y sus pruebas contienen a propósito ejemplos de lo que rechazan.
SELF_TESTING = {"scripts/check_public_files.py", "tests/integration/test_publicacion.py"}

# Rutas personales genéricas (cualquier equipo), sin nombres propios en este archivo.
PERSONAL_PATH = re.compile(
    r"(?i:[A-Z]:\\{1,4}Users\\{1,4}[^\\\"'\s]+|[A-Z]:/Users/[^/\"'\s]+"
    r"|Obsidian\\{1,4}MyVault|AppData\\{1,4}(?:Local|Roaming)\\{1,4}Temp)"
    r"|/Users/[^/\"'\s{<$]+|/home/[a-z][^/\"'\s{<$]*/"
)
# Prefijos aceptables: ejemplos genéricos de documentación.
PERSONAL_ALLOWED = re.compile(r"(?i)(Users[\\/]+(?:<[^>]+>|%[^%]+%|(?:usuario|user|you|tu)\b)|/home/(?:runner|user)/)")

AI_CREDIT = re.compile(
    r"(?im)^\s*co-authored-by:.*(?:claude|anthropic|openai|codex|copilot|gemini|chatgpt|noreply@anthropic)"
    r"|generated\s+with\s+\[?claude\s+code"
    r"|🤖\s*generated\s+with"
)

LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def git(*args: str) -> str:
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def listed_files(candidates: bool) -> list[str]:
    names = set(git("ls-files", "-z").split("\0"))
    if candidates:
        names |= set(git("ls-files", "-z", "--others", "--exclude-standard").split("\0"))
    return sorted(name for name in names if name and (ROOT / name).exists())


def _glob(pattern: str) -> re.Pattern[str]:
    """Como el .gitignore anclado: `*` no cruza directorios."""
    return re.compile("".join("[^/]*" if part == "*" else re.escape(part) for part in re.split(r"(\*)", pattern)) + r"\Z")


PUBLIC_MARKDOWN_RE = tuple(_glob(pattern) for pattern in PUBLIC_MARKDOWN)


def is_public_markdown(name: str) -> bool:
    return any(pattern.match(name) for pattern in PUBLIC_MARKDOWN_RE)


def check_files(files: list[str]) -> list[str]:
    problems: list[str] = []
    tracked = set(files)
    for name in files:
        for pattern, why in PRIVATE_PATHS:
            if pattern.search(name):
                problems.append(f"{name}: {why}")
        if name.lower().endswith(".md") and not is_public_markdown(name):
            problems.append(f"{name}: Markdown fuera de la lista publicable")
        path = ROOT / name
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"LICENSE", "CURRENT", ".gitignore", ".firebaserc"}:
            continue
        if not path.is_file() or path.stat().st_size > MAX_TEXT_BYTES:
            continue
        if name in SELF_TESTING:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in PERSONAL_PATH.finditer(text):
            if PERSONAL_ALLOWED.search(text[max(0, match.start() - 4):match.end() + 12]):
                continue
            problems.append(f"{name}: ruta personal ({match.group(0)[:48]!r})")
            break
        if name in SELF_TESTING:
            continue
        if AI_CREDIT.search(text):
            problems.append(f"{name}: línea de coautoría o crédito de generación de una herramienta de IA")
        if name.lower().endswith(".md"):
            problems.extend(broken_links(name, text, tracked))
    return problems


def broken_links(name: str, text: str, tracked: set[str]) -> list[str]:
    problems = []
    base = Path(name).parent
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        for target in LINK.findall(line):
            if re.match(r"^(?:[a-z][a-z0-9+.-]*:|#|mailto:)", target, re.I):
                continue
            relative = target.split("#", 1)[0].split("?", 1)[0]
            if not relative:
                continue
            resolved = (base / relative).as_posix()
            parts: list[str] = []
            for part in resolved.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                elif part not in ("", "."):
                    parts.append(part)
            final = "/".join(parts)
            exists = final in tracked or any(item.startswith(final + "/") for item in tracked)
            if not exists:
                problems.append(f"{name}: enlace roto o a archivo no publicado → {target}")
    return problems


def check_commits(revision_range: str) -> list[str]:
    problems = []
    log = git("log", "--format=%H%x1f%an%x1f%ae%x1f%B%x1e", revision_range)
    for record in filter(None, log.split("\x1e")):
        sha, author, email, body = (record.strip("\n").split("\x1f") + ["", "", "", ""])[:4]
        if AI_CREDIT.search(body):
            problems.append(f"commit {sha[:10]}: mensaje con coautoría o crédito de una herramienta de IA")
        if re.search(r"(?i)claude|anthropic|codex|openai|copilot", f"{author} {email}"):
            problems.append(f"commit {sha[:10]}: autor asociado a una herramienta de IA ({author})")
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", action="store_true", help="incluye archivos sin versionar no ignorados")
    parser.add_argument("--commits", metavar="RANGO", help="revisa también los commits de este rango, p. ej. origin/main..HEAD")
    args = parser.parse_args()
    files = listed_files(args.candidates)
    problems = check_files(files)
    if args.commits:
        problems.extend(check_commits(args.commits))
    if problems:
        print(f"check_public_files: {len(problems)} problema(s) en {len(files)} archivos")
        for problem in problems:
            print("  -", problem)
        return 1
    print(f"check_public_files: OK ({len(files)} archivos examinados)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
