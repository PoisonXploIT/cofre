"""Cofre - generador de credenciales.

Dos perfiles, no uno:
  machine : 48 bytes aleatorios (64 caracteres). Para API keys y tokens que
            nadie teclea.
  human   : passphrase de palabras frecuentes, tecleable en un navegador.

Las listas estan en cofre/data/wordlist_en.txt y wordlist_es.txt (2000
palabras de alta frecuencia, generadas con tools/build_wordlist.py).
2000 palabras = 10.97 bits por palabra:

  4 palabras  = 44 bits   (no recomendado)
  6 palabras  = 66 bits   (bien)
  8 palabras  = 88 bits   (muy bien)

Sin lista, se usa el fallback silabico (~36 bits): vale para una prueba, no
para un secreto serio. entropy() te dice exactamente lo que tienes.
"""

from __future__ import annotations

import math
import os
import secrets
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

SYLLABLES = [
    "ba", "be", "bi", "bo", "bu", "ca", "ce", "ci", "co", "cu",
    "da", "de", "di", "do", "du", "fa", "fe", "fi", "fo", "fu",
    "ga", "ge", "gi", "go", "gu", "ha", "he", "hi", "ho", "hu",
    "ja", "je", "ji", "jo", "ju", "ka", "ke", "ki", "ko", "ku",
    "la", "le", "li", "lo", "lu", "ma", "me", "mi", "mo", "mu",
    "na", "ne", "ni", "no", "nu", "pa", "pe", "pi", "po", "pu",
    "ra", "re", "ri", "ro", "ru", "sa", "se", "si", "so", "su",
    "ta", "te", "ti", "to", "tu", "va", "ve", "vi", "vo", "vu",
    "ya", "ye", "yo", "yu", "za", "ze", "zo", "zu",
]


def load_words(lang: str = "en") -> list[str]:
    env = os.environ.get("COFRE_WORDLIST")
    if env and Path(env).exists():
        words = [w.strip().lower() for w in Path(env).read_text(encoding="utf-8").split() if w.strip()]
        if len(words) >= 200:
            return words
    p = DATA / f"wordlist_{lang}.txt"
    if p.exists():
        words = [w.strip().lower() for w in p.read_text(encoding="utf-8").split() if w.strip()]
        if len(words) >= 200:
            return words
    return []


def entropy(words: int = 5, lang: str = "en") -> dict:
    wl = load_words(lang)
    if not wl:
        # Ojo: esta rama tiene que devolver las MISMAS claves que la otra.
        # En 2026-11-13 la GUI petaba con KeyError 'bits_por_palabra' cuando la
        # wordlist no estaba disponible.
        bits = 6 * math.log2(len(SYLLABLES)) + math.log2(10)
        return {"palabras": words, "lista": 0, "bits_por_palabra": 0.0,
                "bits": round(bits, 1),
                "aviso": "sin wordlist: fallback silabico (~36 bits). "
                         "Genera una con tools/build_wordlist.py"}
    per = math.log2(len(wl))
    return {"palabras": words, "lista": len(wl), "bits_por_palabra": round(per, 2),
           "bits": round(words * per + 1, 1), "aviso": ""}


def machine_password(length: int = 48) -> str:
    return secrets.token_urlsafe(length)


def human_password(words: int = 5, lang: str = "en") -> str:
    """Passphrase de palabras + un digito. Ej: correctotreehorsebanana4

    Palabras pegadas (sin guiones) porque muchos formularios los rechazan.
    """
    wl = load_words(lang)
    if not wl:
        base = "".join(secrets.choice(SYLLABLES) for _ in range(6))
        return base.capitalize() + secrets.choice("0123456789")
    picked = [secrets.choice(wl) for _ in range(max(2, words))]
    return "".join(picked).capitalize() + secrets.choice("0123456789")


def classify(value: str) -> str:
    """Devuelve 'human' si la credencial se va a teclear, 'machine' si no."""
    return "machine" if len(value) > 24 and not any(c in value for c in " -") else "human"
