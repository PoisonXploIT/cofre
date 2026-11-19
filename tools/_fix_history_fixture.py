"""Reescribe el fixture de tests/test_v2.py en los commits viejos.

Lo llamaba `git filter-branch --tree-filter` (2026-11-19, ya aplicado) para quitar del historial las
24 palabras del codigo de recuperacion que se colaron en una prueba. Se ejecuta en
un checkout temporal de cada commit: si el fichero no existe o ya esta limpio, no
toca nada.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(".")


def limpio(texto: str) -> bool:
    """True si no hay 24 palabras seguidas de la lista (usa el detector de COFRE)."""
    try:
        # el modulo vive en el repo real (el checkout temporal puede no tenerlo)
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from cofre.leak import codigos_de_recuperacion  # type: ignore
    except Exception:
        return True          # sin el modulo no se toca nada (no romper commits)
    return not codigos_de_recuperacion(texto)


def main() -> int:
    ruta = REPO / "tests" / "test_v2.py"
    if not ruta.is_file():
        return 0
    texto = ruta.read_text(encoding="utf-8")
    if limpio(texto):
        return 0
    lineas = texto.splitlines(keepends=True)
    salida, i = [], 0
    while i < len(lineas):
        if lineas[i].strip().startswith("propias = ["):
            indent = lineas[i][:len(lineas[i]) - len(lineas[i].lstrip())]
            salida.append(indent + 'propias = [f"palabra{letra}" for letra in '
                                  '"abcdefghijklmnopqrstuvwx"]\n')
            # saltar hasta la linea que cierra la lista
            while i < len(lineas) and "]" not in lineas[i]:
                i += 1
            i += 1
            continue
        salida.append(lineas[i])
        i += 1
    ruta.write_text("".join(salida), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
