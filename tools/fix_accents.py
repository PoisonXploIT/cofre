"""Acentuar textos en castellano sin tocar identificadores.

El repaso de tildes ya rompio el codigo dos veces: un reemplazo de "lineas" por
"líneas" alcanzo al nombre de una variable. Esta herramienta lo hace bien:

  - usa `tokenize`, asi que solo ve cadenas de texto (STRING) y comentarios si se
    pide con --comentarios;
  - nunca toca NOMBRE, OP, NUMBER ni palabras clave;
  - reescribe el fichero conservando el resto tal cual.

Uso:
  python tools/fix_accents.py --check          # 1 si hay algo que cambiar
  python tools/fix_accents.py                 # aplica en cofre/ y tools/
  python tools/fix_accents.py --comentarios    # incluye comentarios
"""

from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETAS = [RAIZ / "cofre", RAIZ / "tools", RAIZ / "tests"]

# palabra sin tilde -> con tilde. Solo palabras sueltas y en minuscula, para no
# romper identificadores ni nombres propios.
PALABRAS = {
    "lineas": "líneas", "linea": "línea",
    "rotacion": "rotación", "sesion": "sesión", "confirmacion": "confirmación",
    "revocacion": "revocación", "explicacion": "explicación",
    "informacion": "información", "proposito": "propósito",
    "codigo": "código", "numero": "número", "ultima": "última", "ultimo": "último",
    "encontro": "encontró", "ningun": "ningún", "ninguna": "ninguna",
    "boveda": "bóveda", "contrasena": "contraseña", "contrasenas": "contraseñas",
    "seleccion": "selección", "busqueda": "búsqueda", "todavia": "todavía",
    "aqui": "aquí", "asi": "así", "version": "versión", "dia": "día", "dias": "días",
    "valido": "válido", "invalido": "inválido", "automatico": "automático",
}

import re

PATRON = re.compile(r"\b(" + "|".join(sorted(PALABRAS)) + r")\b")


def acentuar(texto: str) -> str:
    return PATRON.sub(lambda m: PALABRAS[m.group(1)], texto)


def procesar(path: Path, comentarios: bool, aplicar: bool) -> bool:
    """Devuelve True si cambiaria (o cambio) algo."""
    original = path.read_text(encoding="utf-8")
    cambios = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(original).readline):
            if tok.type == tokenize.STRING:
                # las cadenas multilinea se dejan: mover indices ahi es fragil
                if tok.start[0] != tok.end[0]:
                    continue
                nuevo = acentuar(tok.string)
                if nuevo != tok.string:
                    cambios.append((tok.start, tok.end, nuevo))
            elif comentarios and tok.type == tokenize.COMMENT:
                nuevo = "#" + acentuar(tok.string.lstrip("#"))
                if nuevo != tok.string:
                    cambios.append((tok.start, tok.end, nuevo))
    except tokenize.TokenError:
        return False
    if not cambios:
        return False
    if not aplicar:
        for (sr, sc), _e, nuevo in cambios[:5]:
            print(f"{path}:{sr}:{sc}: {nuevo.strip()[:60]}")
        return True
    lineas = original.splitlines(keepends=True)
    # se aplican de atras hacia delante para no mover las posiciones
    for (sr, sc), (er, ec), nuevo in sorted(cambios, reverse=True):
        if sr != er:
            continue                  # cadenas multilinea: se dejan
        linea = lineas[sr - 1]
        lineas[sr - 1] = linea[:sc] + nuevo + linea[ec:]
    path.write_text("".join(lineas), encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    aplicar = "--check" not in argv
    comentarios = "--comentarios" in argv
    tocados = 0
    for carpeta in CARPETAS:
        if not carpeta.exists():
            continue
        for path in sorted(carpeta.rglob("*.py")):
            if "fix_accents" in path.name:
                continue
            if procesar(path, comentarios, aplicar):
                tocados += 1
    if aplicar:
        print(f"ficheros cambiados: {tocados}")
        return 0
    if tocados:
        print(f"{tocados} ficheros con tildes pendientes (ejecuta sin --check)")
        return 1
    print("sin tildes pendientes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
