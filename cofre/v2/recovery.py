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


def revisar_palabras(palabras: list[str]) -> tuple[list[str], list[int], list[int], str]:
    """Valida 24 palabras propias. Devuelve (limpias, fuera_de_lista, repetidas, error).

    Las palabras NO tienen que estar en la lista: la lista es solo de donde sale la
    palabra de control y una pista de erratas. Ojo (2026-11-19): exigir que
    estuvieran hizo inutil el boton "Mis palabras", porque la lista es de palabras
    frecuentes y ninguna de las que uno elige a mano suele estar.
    """
    lista = set(_words())
    crudas = [str(p).strip() for p in (palabras or []) if str(p).strip()]
    if len(crudas) != WORDS:
        return [], [], [], f"hacen falta {WORDS} palabras y hay {len(crudas)}"
    limpias = [normalize(p) for p in crudas]
    for i, palabra in enumerate(limpias, 1):
        if not palabra.replace(" ", "").isalpha():
            return [], [], [], (f"la palabra {i} tiene algo que no es una letra; "
                                "escribe solo palabras")
        if len(palabra) < 2:
            return [], [], [], f"la palabra {i} es demasiado corta"
    fuera = [i for i, palabra in enumerate(limpias, 1) if palabra not in lista]
    vistas: set[str] = set()
    repetidas = []
    for i, palabra in enumerate(limpias, 1):
        if palabra in vistas:
            repetidas.append(i)
        vistas.add(palabra)
    return limpias, fuera, repetidas, ""


def code_from_words(palabras: list[str]) -> str:
    """Código a partir de 24 palabras elegidas por la persona + la de control.

    No cambia nada del formato del código: solo sustituye el azar por la elección.
    Aviso que la interfaz repite: 24 palabras elegidas por una persona tienen mucha
    menos entropía que 24 al azar; el cofre no lo impide, pero no es lo mismo.
    """
    limpias, _fuera, _repes, error = revisar_palabras(palabras)
    if error:
        raise ValueError(error)
    texto = " ".join(limpias)
    return f"{texto} {control_word(texto, _words())}"


def check_code(code: str) -> tuple[bool, str]:
    """Comprueba la palabra de control antes de intentar abrir nada."""
    palabras = _words()
    limpio = normalize(code)
    partes = limpio.split(" ")
    if len(partes) != WORDS + 1:
        return False, f"el código tiene {len(partes) - 1} palabras y deberian ser {WORDS} mas la de control"
    # 2026-11-19: decir DONDE falla sin repetir el codigo. Antes solo decia "hay un
    # error al copiar" y no habia forma de saber si sobraba una palabra, faltaba
    # otra o estaba mal la de control.
    # La lista es una pista, no un requisito: un codigo puede llevar palabras
    # elegidas a mano. Solo se avisa de las posiciones que no estan, por si es una
    # errata al copiar.
    fuera = [i for i, palabra in enumerate(partes[:-1], 1) if palabra not in palabras]
    texto = " ".join(partes[:-1])
    esperada = control_word(texto, palabras)
    if partes[-1] != normalize(esperada):
        pista = ""
        if fuera:
            posiciones = ", ".join(str(i) for i in fuera[:4])
            pista = f" (la palabra {posiciones} no está en la lista: revisa esas)"
        return False, ("la palabra de control no cuadra: revisa la última palabra o "
                       "el orden de las 24 primeras" + pista)
    return True, ""
