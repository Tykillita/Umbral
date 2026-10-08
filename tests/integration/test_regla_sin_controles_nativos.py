"""Regla del proyecto «nada nativo» (CLAUDE.md / AGENTS.md): el guardián estático debe detectar lo nativo y el código debe cumplirla."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_no_native_ui", REPO / "scripts" / "check_no_native_ui.py")
guard = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(guard)  # type: ignore[union-attr]

NATIVE_SAMPLES = {
    "select": "<select id='x'><option>a</option></select>",
    "details": "<details><summary>Más</summary>x</details>",
    "dialog": "<dialog open>hola</dialog>",
    "checkbox": '<input type="checkbox" checked />',
    "radio": "<input type='radio' />",
    "number": '<input type="number" min="0" />',
    "search": '<input type="search" />',
    "date": '<input type="date" />',
    "file": '<input type="file" />',
    "title nativo en span": '<span className="x" title="ayuda">hola</span>',
    "title nativo con flecha en el mismo tag": "<button onClick={() => go('a')} title={why}>Ir</button>",
    "alert": "function f() { window.alert('hola'); }",
    "confirm": "if (confirm('seguro')) {}",
}

CLEAN_SAMPLES = {
    "componente con title como propiedad": '<Notice tone="warn" title="Aviso">x</Notice>',
    "campo de texto": '<input type="text" className="x" />',
    "textarea con estilo": '<textarea rows={3} className="x" />',
    "comentario que menciona select": "// no uses <select> nativo\nconst a = 1;",
    "tooltip propio": '<Tooltip content="ayuda"><span>hola</span></Tooltip>',
}


@pytest.mark.parametrize("name", sorted(NATIVE_SAMPLES))
def test_el_guardian_detecta_lo_nativo(name):
    assert guard.scan_text(NATIVE_SAMPLES[name], "muestra.tsx"), f"no detectó: {name}"


@pytest.mark.parametrize("name", sorted(CLEAN_SAMPLES))
def test_el_guardian_no_da_falsos_positivos(name):
    assert guard.scan_text(CLEAN_SAMPLES[name], "muestra.tsx") == [], f"falso positivo: {name}"


def test_la_interfaz_real_no_usa_controles_nativos():
    files = [f for f in guard.SRC.rglob("*") if f.suffix in {".tsx", ".astro"} and not f.name.endswith(".test.tsx")]
    problems = [p for f in files for p in guard.scan(f)]
    assert files, "no se encontraron archivos de la interfaz"
    assert not problems, "Regla «nada nativo» incumplida:\n  - " + "\n  - ".join(problems)


def test_la_regla_esta_escrita_para_los_agentes():
    """Las guías para agentes son privadas (no se publican): se comprueban solo cuando existen en el equipo local."""
    present = [name for name in ("CLAUDE.md", "AGENTS.md") if (REPO / name).is_file()]
    if not present:
        pytest.skip("CLAUDE.md y AGENTS.md no están en este checkout (son locales).")
    for name in present:
        text = (REPO / name).read_text(encoding="utf-8").lower()
        assert "nada nativo" in text, f"{name} no documenta la regla"
        assert "controls.tsx" in text, f"{name} no indica dónde están los componentes propios"
