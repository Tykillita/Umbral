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
    r"developer\s+mode|modo\s+desarrollador|jailbreak|\bDAN\b",
    r"(cambia|modifica|sobrescribe)\s+(las\s+)?(reglas|el\s+puntaje|la\s+puntuaci[oó]n|los\s+pesos)",
    r"asigna\w*\s+(prioridad|puntaje|impacto)\s+(alta|m[aá]xim\w+|100)",
    r"<\s*/?\s*(system|assistant|instruction)\s*>",
    r"\[\s*(system|inst)\s*\]",
    r"nuevas?\s+instrucciones\s*:",
    r"(api[_\s-]?key|gemini_api_key|firebase|bearer\s+[a-z0-9._-]{12,})",
]
_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def looks_like_instruction(text: str | None) -> bool:
    """True si el texto parece dirigirse a un agente (inyección de prompt)."""
    if not text:
        return False
    return bool(_RE.search(_fold(text)))


_SECRET_RE = re.compile(r"(AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|GEMINI_API_KEY|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


def leaks_secret(text: str) -> bool:
    return bool(_SECRET_RE.search(text))


def sanitize_for_prompt(text: str, max_len: int = 400) -> str:
    """Limpia texto no confiable antes de incluirlo como dato en un prompt (sin ejecutar nada)."""
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", _fold(text))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]
