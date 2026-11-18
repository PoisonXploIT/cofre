"""Falla si aparece un identificador con tilde.

El reemplazo de tildes rompio el codigo dos veces porque toco nombres. Esto lo
detecta siempre, y `run_all_probes.py` lo ejecuta en cada pasada.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LETRAS = "áéíóúÁÉÍÓÚñÑüÜ"


def main() -> int:
    malos = []
    for carpeta in ("cofre", "tools", "tests"):
        base = RAIZ / carpeta
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                arbol = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                print(f"SINTAXIS: {path}:{exc.lineno}: {exc.msg}")
                malos.append((str(path), "sintaxis", exc.lineno or 0))
                continue
            for nodo in ast.walk(arbol):
                nombre = None
                if isinstance(nodo, ast.Name):
                    nombre = nodo.id
                elif isinstance(nodo, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                    nombre = nodo.name
                elif isinstance(nodo, ast.arg):
                    nombre = nodo.arg
                elif isinstance(nodo, ast.Attribute):
                    nombre = nodo.attr
                if nombre and any(c in LETRAS for c in nombre):
                    malos.append((str(path), nombre, getattr(nodo, "lineno", 0)))
    if malos:
        for path, nombre, linea in malos:
            print(f"identificador con tilde: {path}:{linea}: {nombre}")
        return 1
    print("identificadores sin tildes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
