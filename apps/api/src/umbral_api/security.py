"""Tratamiento de contenido no confiable (T07): el texto de una fuente es dato, nunca instrucción."""

from __future__ import annotations

import re
import unicodedata

_PATTERNS = [
    r"ignor[ae]\w*\s+(todas?\s+)?(las\s+|tus\s+|sus\s+|los\s+)?(instrucciones|reglas|indicaciones|restricciones)",
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier|your)\s+(instructions|rules|prompts?)",
    r"olvida\w*\s+(todo\s+)?(lo\s+anterior|tus\s+instrucciones|las\s+reglas)",
    r"disregard\s+(all\s+)?(previous|prior|the)\s+",
    r"revela\w*\s+(tu|el|la|los|las|tus)\s+(clave|claves|api|secret|secreto|secretos|prompt|contrase\w+|token|tokens|credenciales)",
    r"reveal\s+(your|the)\s+(system\s+prompt|prompt|secret|secrets|api\s*key|password|token)",
    r"(muestra|imprime|dime|env[ií]a)\s+(tu|el)\s+(system\s*prompt|prompt\s+del\s+sistema|clave|api\s*key)",
    r"system\s*prompt",
    r"(act[uú]a|comp[oó]rtate|responde)\s+como\s+(si\s+fueras\s+)?(un|una|el|la)?\s*\w*\s*(sin\s+restricciones|administrador|root|dios)",
    r"you\s+are\s+now\s+(an?\s+)?\w+",
    r"developer\s+mode|modo\s+desarrollador|jailbreak|(?-i:\bDAN\b)",
    r"ignor[ae]\w*\s+(todo\s+)?(lo\s+)?anterior\b",
    r"\beres\s+ahora\s+(un|una|el|la)\s+\w+",
    r"(asistente|modelo|bot|ia)\s+sin\s+(reglas|restricciones|filtros)",
    r"mensaje\s+del\s+sistema\s*:",
    r"(mostrar|muestra\w*|revelar|revela\w*|imprimir|imprime\w*|lista\w*|dime)\s+(todas?\s+)?(las\s+)?variables\s+de\s+entorno",
    r"/etc/(passwd|shadow)",
    r"(cambia|modifica|sobrescribe)\s+(las\s+)?(reglas|el\s+puntaje|la\s+puntuaci[oó]n|los\s+pesos)",
    r"asigna\w*\s+(prioridad|puntaje|impacto)\s+(alta|m[aá]xim\w+|100)",
    r"<\s*/?\s*(system|assistant|instruction)\s*>",
    r"\[\s*(system|inst)\s*\]",
    r"\b(system|developer|assistant)\s*:",
    r"nuevas?\s+instrucciones\s*:",
    r"(api[_\s-]?key|gemini_api_key|firebase|bearer\s+[a-z0-9._-]{12,})",
]
_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


# Letras de otros alfabetos que se confunden a simple vista con las latinas (p. ej. la «о» cirílica en «Ignоra»).
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "к": "k", "м": "m", "т": "t", "н": "h", "в": "b",
    "і": "i", "ѕ": "s", "ј": "j", "ο": "o", "α": "a", "ε": "e", "ι": "i", "ν": "v", "ρ": "p", "τ": "t", "υ": "u",
})
_SPACED_LETTERS = re.compile(r"(?<=\b\w) (?=\w\b)")


def _fold(text: str) -> str:
    """NFKC + homoglifos a latino + letras separadas por un espacio («i g n o r a»), para que no eludan los patrones."""
    folded = unicodedata.normalize("NFKC", text).translate(_CONFUSABLES)
    return _SPACED_LETTERS.sub("", folded) if re.search(r"(?:\b\w ){4,}\w\b", folded) else folded


def looks_like_instruction(text: str | None) -> bool:
    """True si el texto parece dirigirse a un agente (inyección de prompt)."""
    if not text:
        return False
    return bool(_RE.search(_fold(text)))


def split_instruction(text: str) -> tuple[str, bool]:
    """Retira desde el primer fragmento de inyección; nunca devuelve ese fragmento para buscarlo."""
    folded = _fold(text)
    match = _RE.search(folded)
    if match is None:
        return text.strip(), False
    # NFKC y los homoglifos conservan el largo en los casos corrientes; ante texto alterado se falla cerrado.
    prefix = text[: match.start()].strip(" \t\r\n,;:-")
    return prefix, True


_PROFILE_RE = re.compile(
    r"\b(quien(?:es)?|qu[eé]\s+(?:diputad\w*|funcionari\w*|personas?|politic\w*)|lista|identifica|perfila|describe|clasifica|rankea)\b.{0,100}\b"
    r"(sospechos[oa]s?|culpables?|criminales?|delincuentes?|corrupt[oa]s?|peligros[oa]s?)\b",
    re.IGNORECASE,
)
_GUILT_RE = re.compile(
    r"\b(es verdad que|es cierto que|crees que|consideras que|es|son)\b.{0,120}\b"
    r"(culpable|culpables|criminal|criminales|corrupto|corrupta|responsable penalmente)\b",
    re.IGNORECASE,
)


def looks_like_profiling(text: str | None) -> bool:
    return bool(text and _PROFILE_RE.search(_fold(text)))


def looks_like_guilt_question(text: str | None) -> bool:
    return bool(text and _GUILT_RE.search(_fold(text)))


_SECRET_RE = re.compile(r"(AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|GEMINI_API_KEY|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


def leaks_secret(text: str) -> bool:
    return bool(_SECRET_RE.search(text))


def sanitize_for_prompt(text: str, max_len: int = 400) -> str:
    """Limpia texto no confiable antes de incluirlo como dato en un prompt (sin ejecutar nada)."""
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", _fold(text))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]
