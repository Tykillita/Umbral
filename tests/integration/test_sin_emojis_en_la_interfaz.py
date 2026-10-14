"""La interfaz no usa emojis ni caracteres con presentación de emoji: los iconos son SVG (lucide-react o SVG propio).

iOS y Android pintan algunos caracteres de flecha (↗ ↘ ↖ ↙ ↔ ↕) y los pictogramas como emoji de color, fuera del estilo de Umbral.
Se permiten las flechas de texto ← → ↑ ↓ en datos y textos, no como decoración de botones y enlaces.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps" / "web" / "src"

EMOJI = re.compile(
    "["
    "↔-↙"  # ↔ ↕ ↖ ↗ ↘ ↙
    "↩↪"  # ↩ ↪
    "⌚⌛⌨⏏⏩-⏳⏸-⏺"  # relojes y controles multimedia
    "▪▫▶◀◻-◾"  # formas con presentación de emoji
    "☀-➿"  # símbolos varios y dingbats (✓ ✔ ✖ ⚠ ★ ☀ …)
    "⤴⤵⬅-⬇⬛⬜⭐⭕"
    "\U0001f000-\U0001faff"  # emojis propiamente dichos
    "️"  # selector de variación de emoji
    "]"
)


def _files():
    for path in sorted(SRC.rglob("*")):
        if path.suffix in {".tsx", ".ts", ".astro", ".css"} and ".test." not in path.name:
            yield path


def test_el_codigo_de_la_interfaz_no_contiene_emojis():
    found = []
    for path in _files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = EMOJI.search(line)
            if match:
                found.append(f"{path.relative_to(REPO).as_posix()}:{number} U+{ord(match.group()):04X}")
    assert not found, "usa un icono SVG en lugar de estos caracteres:\n" + "\n".join(found)


def test_el_detector_reconoce_flechas_y_pictogramas_de_emoji():
    for sample in ("↗", "↘", "↔", "✓", "⚠", "★", "🙂", "➡️"):
        assert EMOJI.search(sample), sample
    for sample in ("←", "→", "↑", "↓", "·", "—", "…", "«»"):
        assert not EMOJI.search(sample), sample
