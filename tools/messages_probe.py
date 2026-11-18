"""COFRE - sonda de textos visibles fuera del catalogo (6.3).

  python tools/messages_probe.py [--max N]

Cuenta, con ast, los literales que ve el usuario y no salen de `msg()`:

  - GUI: `text=`, pies (`set_foot`, `set_status`), titulos, hojas, botones,
    chips, confirmaciones y los textos de las alertas.
  - CLI: `print` y `help` tecnicos. Se aceptan como lista blanca de contexto:
    la salida de consola no es interfaz grafica y el plan lo permite.

Objetivo de la GUI: 0. El CLI se cuenta aparte y queda en la lista blanca.
Sale 1 si la GUI tiene pendientes (o si se pasa de --max, para medir).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
COFRE = RAIZ / "cofre"
GUI = ["gui.py", "firstuse.py", "palette.py", "lock_screen.py",
       "entry_sheet.py", "gui_confirm.py", "alerts.py", "health.py"]
CLI = ["cli.py"]

# nombres de funcion cuyo argumento de texto es visible
POR_NOMBRE = {
    "set_foot": [0], "set_status": [0], "_texto": [0], "_titulo": [0],
    "_indicador": [1], "_sheet": [0], "_mostrar_salida": [0],
    "_confirmar_accion": [0, 1, 2], "read_secret": [0],
}
BOTONES = {"_btn", "_text_btn", "_icon_btn", "Button", "Chip"}
ALERTAS = {"Alert"}


def _letras(texto: str) -> bool:
    return any(c.isalpha() for c in texto)


def _textos(expr) -> list[str]:
    """Literales de un argumento, incluidas las partes fijas de una f-string."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.JoinedStr):
        trozos = [v.value for v in expr.values
                  if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        return ["".join(trozos)] if trozos else []
    if isinstance(expr, (ast.List, ast.Tuple)):
        salida = []
        for elemento in expr.elts:
            salida.extend(_textos(elemento))
        return salida
    return []


class Visitante(ast.NodeVisitor):
    def __init__(self, fichero: str, cli: bool, hallados: list):
        self.fichero = fichero
        self.cli = cli
        self.hallados = hallados

    def _apuntar(self, nodo, texto: str, contexto: str) -> None:
        texto = " ".join(str(texto).split())
        if not texto or not _letras(texto):
            return
        self.hallados.append((self.fichero, nodo.lineno, texto, contexto))

    def visit_Call(self, nodo: ast.Call) -> None:
        nombre = (nodo.func.attr if isinstance(nodo.func, ast.Attribute)
                  else nodo.func.id if isinstance(nodo.func, ast.Name) else "")
        if nombre == "msg":
            # el texto real esta en el catalogo; no se cuenta la clave
            return
        # text=, help=, description=
        for kw in nodo.keywords:
            if kw.arg in ("text", "help", "description"):
                for texto in _textos(kw.value):
                    self._apuntar(kw.value, texto, f"{nombre or 'llamada'}.{kw.arg}")
        # argumentos por nombre de funcion
        if nombre in POR_NOMBRE:
            for indice in POR_NOMBRE[nombre]:
                if indice < len(nodo.args):
                    for texto in _textos(nodo.args[indice]):
                        self._apuntar(nodo.args[indice], texto, nombre)
        # botones y chips: el segundo argumento es la etiqueta
        if nombre in BOTONES and len(nodo.args) >= 2:
            for texto in _textos(nodo.args[1]):
                self._apuntar(nodo.args[1], texto, nombre)
        if nombre in ALERTAS and len(nodo.args) >= 3:
            for texto in _textos(nodo.args[2]):
                self._apuntar(nodo.args[2], texto, nombre)
        # print del CLI: todo lo que se escribe en consola
        if self.cli and nombre == "print":
            for argumento in nodo.args:
                for texto in _textos(argumento):
                    self._apuntar(argumento, texto, "print")
        self.generic_visit(nodo)


def main(argv: list[str]) -> int:
    tope = None
    if "--max" in argv:
        tope = int(argv[argv.index("--max") + 1])
    gui, cli = [], []
    for nombre in GUI:
        ruta = COFRE / nombre
        if not ruta.exists():
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
        Visitante(nombre, False, gui).visit(arbol)
    for nombre in CLI:
        ruta = COFRE / nombre
        if not ruta.exists():
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
        Visitante(nombre, True, cli).visit(arbol)

    print("Textos visibles fuera de msg():")
    print(f"  GUI pendientes: {len(gui)}")
    print(f"  CLI tecnicos (lista blanca de contexto): {len(cli)}")
    por_fichero: dict[str, int] = {}
    for fichero, _linea, _texto, _contexto in gui:
        por_fichero[fichero] = por_fichero.get(fichero, 0) + 1
    for fichero in sorted(por_fichero):
        print(f"    {fichero:20} {por_fichero[fichero]:4}")
    if gui:
        print("")
        print("Pendientes (primeros 200):")
        for fichero, linea, texto, contexto in gui[:200]:
            print(f"  {fichero}:{linea} [{contexto}] {texto[:90]}")
    if tope is not None and len(gui) > tope:
        print(f"\nFALLO: {len(gui)} pendientes > tope {tope}")
        return 1
    print(f"GUI pendientes: {len(gui)}"
          + (f" (tope {tope})" if tope is not None else "")
          + f"; CLI tecnicos en lista blanca: {len(cli)}")
    if tope is not None:
        return 0
    return 1 if gui else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
