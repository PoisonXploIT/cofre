"""Pruebas de los botones de la GUI (2026-11-19).

Un fallo real: `_btn` envuelve el comando como `lambda: command(None)`, asi que
toda funcion o metodo que se le pase tiene que aceptar **un** argumento. Habia
doce botones que pasaban funciones sin argumentos: entre ellos **Probar código**
(cerraba la ventana), **Botón de pánico**, **Comprobar ahora** (Salud) y
**Sellar** el registro. Al pulsarlos saltaba `TypeError`; y con `pythonw` el
manejador de errores escribia a `sys.stderr`, que es None, se escapaba del bucle
de Tk y la ventana se cerraba "sola".

Aqui se comprueba, sin abrir ventanas:

  1. que ninguna llamada a `_btn` / `_text_btn` / `_icon_btn` recibe una funcion
     local ni un metodo que no acepte argumentos;
  2. que `_on_tk_error` no revienta cuando no hay stderr (pythonw) y avisa en el
     pie de la ventana.
"""

from __future__ import annotations

import ast
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

BOTONES = {"_btn", "_text_btn", "_icon_btn"}
FICHEROS = ["gui.py", "gui_puente.py"]
SIN_ARGUMENTOS = "botones que revientan al pulsarlos:"


def _defs_locales(arbol: ast.AST) -> dict[str, list[ast.FunctionDef]]:
    defs: dict[str, list[ast.FunctionDef]] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef):
            for hijo in nodo.body:
                if isinstance(hijo, ast.FunctionDef):
                    defs.setdefault(hijo.name, []).append(hijo)
    return defs


def _metodos(arbol: ast.AST) -> dict[str, ast.FunctionDef]:
    salida: dict[str, ast.FunctionDef] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef):
            for hijo in nodo.body:
                if isinstance(hijo, ast.FunctionDef):
                    salida[hijo.name] = hijo
    return salida


def _admiten_argumentos(func: ast.FunctionDef, sin_self: bool) -> bool:
    args = func.args
    posicionales = args.args[1:] if sin_self else args.args
    return bool(posicionales or args.vararg or args.kwarg)


def _arboles():
    for nombre in FICHEROS:
        ruta = REPO / "cofre" / nombre
        if ruta.exists():
            yield nombre, ast.parse(ruta.read_text(encoding="utf-8"))


class TestBotones(unittest.TestCase):
    def test_las_funciones_locales_admiten_el_argumento(self):
        malos = []
        for nombre, arbol in _arboles():
            locales = _defs_locales(arbol)
            for nodo in ast.walk(arbol):
                if not (isinstance(nodo, ast.Call)
                        and isinstance(nodo.func, ast.Attribute)
                        and nodo.func.attr in BOTONES):
                    continue
                for arg in nodo.args:
                    if not (isinstance(arg, ast.Name) and arg.id in locales):
                        continue
                    for definicion in locales[arg.id]:
                        if not _admiten_argumentos(definicion, sin_self=False):
                            malos.append(
                                f"{nombre}:{nodo.lineno} {nodo.func.attr}"
                                f"(... {arg.id} ...) y {arg.id} esta en la "
                                f"línea {definicion.lineno} sin argumentos")
        self.assertEqual(malos, [], SIN_ARGUMENTOS + "\n" + "\n".join(malos))

    def test_los_metodos_de_la_ventana_admiten_el_argumento(self):
        malos = []
        for nombre, arbol in _arboles():
            metodos = _metodos(arbol)
            for nodo in ast.walk(arbol):
                if not (isinstance(nodo, ast.Call)
                        and isinstance(nodo.func, ast.Attribute)
                        and nodo.func.attr in BOTONES):
                    continue
                for arg in nodo.args:
                    if not (isinstance(arg, ast.Attribute)
                            and isinstance(arg.value, ast.Name)
                            and arg.value.id == "self"):
                        continue
                    definicion = metodos.get(arg.attr)
                    if definicion is None:
                        continue
                    if not _admiten_argumentos(definicion, sin_self=True):
                        malos.append(
                            f"{nombre}:{nodo.lineno} {nodo.func.attr}"
                            f"(... self.{arg.attr} ...) y {arg.attr} esta en la "
                            f"línea {definicion.lineno} sin argumentos")
        self.assertEqual(malos, [], SIN_ARGUMENTOS + "\n" + "\n".join(malos))

    def test_los_botones_clave_siguen_aceptando_evento(self):
        # los metodos pueden vivir en gui.py o en un mixin: se miran todos
        texto = ""
        for nombre in ("gui.py", "gui_puente.py", "gui_hojas.py", "gui_llaves.py"):
            ruta = REPO / "cofre" / nombre
            if ruta.exists():
                texto += ruta.read_text(encoding="utf-8")
        for metodo in ("probar(event=None)", "open_panic(self, event=None)",
                       "_comprobar_salud(self, event=None)",
                       "_sellar_registro(self, event=None)",
                       "dismiss_alerts(self, event=None)"):
            self.assertIn(metodo, texto, f"falta {metodo}")


class TestErroresDeTk(unittest.TestCase):
    class Falso:
        def __init__(self):
            self.texto = ""
            self.vault_path = (Path(tempfile.mkdtemp(prefix="cofre-tkerr-"))
                               / "cofre.json")
            self.gate = "usb"
            self.serial = 1

        def set_foot(self, texto, ttl=8000):
            self.texto = texto

    def test_no_revienta_sin_stderr(self):
        from cofre.gui import CofreGUI
        falso = self.Falso()
        with mock.patch.object(sys, "stderr", None):
            CofreGUI._on_tk_error(falso, ValueError, ValueError("prueba"), None)
        self.assertIn("ValueError", falso.texto)

    def test_avisa_en_el_pie(self):
        from cofre.gui import CofreGUI
        falso = self.Falso()
        with contextlib.redirect_stderr(io.StringIO()):
            CofreGUI._on_tk_error(falso, RuntimeError, RuntimeError("vaya"), None)
        self.assertIn("error interno", falso.texto)
        self.assertIn("vaya", falso.texto)


if __name__ == "__main__":
    unittest.main()
