#!/usr/bin/env python3
"""Guardián de la regla «nada nativo» del proyecto (ver docs/public/ARCHITECTURE.md, «Seguridad e interfaz»).

Recorre el código de apps/web/src (y las páginas .astro) y falla si encuentra controles o ayudas con apariencia
nativa del navegador o del sistema: <select>, <details>/<summary>, <dialog>, <datalist>, <progress>, <meter>,
<input type=checkbox|radio|number|range|date|time|file|color|search>, el atributo `title` en elementos HTML
(tooltip nativo) y los diálogos alert/confirm/prompt. Los componentes propios están en components/ui/controls.tsx.

Uso: python scripts/check_no_native_ui.py   (sale con código 1 si hay incumplimientos)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "web" / "src"

FORBIDDEN_TAGS = {
    "select": "menú <select> nativo: usa <Select> de components/ui/controls.tsx",
    "details": "<details> nativo: usa <Disclosure>",
    "summary": "<summary> nativo: usa <Disclosure>",
    "dialog": "<dialog> nativo: usa un panel propio",
    "datalist": "<datalist> nativo: usa <Select> o una lista propia",
    "progress": "<progress> nativo: dibuja la barra con CSS propio",
    "meter": "<meter> nativo: dibuja la barra con CSS propio",
}
FORBIDDEN_INPUT_TYPES = {"checkbox", "radio", "number", "range", "date", "datetime-local", "time", "month", "week", "file", "color", "search"}
# Elementos HTML en minúscula: `title=` en ellos genera un tooltip nativo. (Los componentes en MayúsculaInicial, como
# <Notice title=…> o <Base title=…>, usan `title` como propiedad y están permitidos.)
HTML_TAG = re.compile(r"<([a-z][a-z0-9-]*)\b")
DIALOGS = re.compile(r"(?<![\w.])(?:window\.)?(?:alert|confirm|prompt)\s*\(")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"(?m)^(\s*)//.*$", lambda m: m.group(1), text)


def opening_tag_end(text: str, start: int) -> int:
    """Índice del `>` que cierra la etiqueta de apertura que empieza en `start`, respetando comillas y llaves JSX."""
    depth = 0
    quote = ""
    i = start
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth == 0:
            return i
        i += 1
    return len(text) - 1


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def scan(path: Path) -> list[str]:
    return scan_text(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())


def scan_text(raw: str, rel: str) -> list[str]:
    text = strip_comments(raw)
    problems: list[str] = []
    for m in HTML_TAG.finditer(text):
        tag = m.group(1)
        end = opening_tag_end(text, m.end())
        attrs = text[m.end():end]
        where = f"{rel}:{line_of(text, m.start())}"
        if tag in FORBIDDEN_TAGS:
            problems.append(f"{where}: {FORBIDDEN_TAGS[tag]}")
        if tag == "input":
            t = re.search(r"""\btype\s*=\s*["']([\w-]+)["']""", attrs)
            if t and t.group(1) in FORBIDDEN_INPUT_TYPES:
                problems.append(f"{where}: <input type=\"{t.group(1)}\"> nativo: usa el componente propio de controls.tsx")
        if re.search(r"(?<![\w-])title\s*=", attrs) and tag not in {"title", "meta", "link", "svg"}:
            problems.append(f"{where}: atributo `title` en <{tag}> (tooltip nativo): usa <Tooltip>")
    for m in DIALOGS.finditer(text):
        problems.append(f"{rel}:{line_of(text, m.start())}: diálogo nativo `{m.group(0).strip()}`: usa un panel propio")
    return problems


def main() -> int:
    files = [p for p in SRC.rglob("*") if p.suffix in {".tsx", ".astro"} and not p.name.endswith(".test.tsx") and "node_modules" not in p.parts]
    problems = [x for f in sorted(files) for x in scan(f)]
    if problems:
        print("REGLA «NADA NATIVO» INCUMPLIDA (ver docs/public/ARCHITECTURE.md):", *problems, sep="\n  - ")
        return 1
    print(f"OK: {len(files)} archivos de la interfaz sin controles ni ayudas nativas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
