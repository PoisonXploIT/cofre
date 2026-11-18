"""Codigo de recuperacion: 24 palabras + una palabra de control.

Se deriva de la lista en espanol que ya usa el generador (2000 palabras). No es
un secreto guardado en ningun sitio: si se pierde, se pierde la llave.
"""

from __future__ import annotations

import hashlib
import secrets
import unicodedata
from pathlib import Path

WORDS = 24
LISTA = Path(__file__).resolve().parent.parent / "data" / "wordlist_es.txt"


def _words() -> list[str]:
    if not LISTA.exists():
        raise RuntimeError(f"falta la lista de palabras: {LISTA}")
    return [w.strip() for w in LISTA.read_text(encoding="utf-8").splitlines() if w.strip()]


def normalize(text: str) -> str:
    """minusculas, sin tildes, un espacio entre palabras."""
    sin = unicodedata.normalize("NFKD", str(text))
    sin = "".join(c for c in sin if not unicodedata.category(c).startswith("Mn"))
    return " ".join(sin.lower().split())


def control_word(texto_normalizado: str, palabras: list[str]) -> str:
    indice = int(hashlib.sha256(texto_normalizado.encode("utf-8")).hexdigest(), 16) % len(palabras)
    return palabras[indice]


def new_code() -> str:
    """Devuelve 'palabra palabra ... palabra_control' (25 palabras)."""
    palabras = _words()
    elegidas = [secrets.choice(palabras) for _ in range(WORDS)]
    texto = " ".join(elegidas)
    return f"{texto} {control_word(texto, palabras)}"


def check_code(code: str) -> tuple[bool, str]:
    """Comprueba la palabra de control antes de intentar abrir nada."""
    palabras = _words()
    limpio = normalize(code)
    partes = limpio.split(" ")
    if len(partes) != WORDS + 1:
        return False, f"el código tiene {len(partes) - 1} palabras y deberian ser {WORDS} mas la de control"
    texto = " ".join(partes[:-1])
    esperada = control_word(texto, palabras)
    if partes[-1] != normalize(esperada):
        return False, "la palabra de control no cuadra: hay un error al copiar el código"
    return True, ""
