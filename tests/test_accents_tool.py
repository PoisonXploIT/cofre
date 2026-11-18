"""Pruebas de tools/fix_accents.py y tools/check_accents.py.

Lo importante: acentuar texto SI, tocar identificadores NO. Y en f-strings,
solo la parte de texto.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))


def _cargar(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


FA = _cargar("fix_accents", REPO / "tools" / "fix_accents.py")
SALTO = chr(10)


def _probar(texto: str) -> str:
    tmp = Path(tempfile.mkdtemp()) / "t.py"
    tmp.write_text(texto, encoding="utf-8")
    FA.procesar(tmp, comentarios=False, aplicar=True)
    return tmp.read_text(encoding="utf-8")


class TestFixAccents(unittest.TestCase):
    def test_acentua_solo_texto(self):
        salida = _probar('x = "lineas de codigo"' + SALTO + "y = lineas_de_codigo" + SALTO)  # no-tildes
        self.assertIn('"líneas de código"', salida)  # no-tildes
        self.assertIn("y = lineas_de_codigo", salida)  # no-tildes

    def test_no_toca_nombres_ni_claves(self):
        original = ("líneas = 1" + SALTO + "def rotacion_pendiente():" + SALTO
                    + '    return "rotacion"' + SALTO)  # no-tildes
        salida = _probar(original)
        self.assertIn("def rotacion_pendiente", salida)  # no-tildes
        self.assertIn("def rotacion_pendiente()", salida)  # no-tildes
        self.assertIn('"rotación"', salida)  # no-tildes

    def test_fstring_conserva_las_llaves(self):
        original = ("def f():" + SALTO
                    + '    return f"la rotacion {rotacion_pendiente} y lineas"' + SALTO)  # no-tildes
        salida = _probar(original)
        self.assertIn("{rotacion_pendiente}", salida)
        self.assertIn("la rotación", salida)  # no-tildes
        self.assertIn("y líneas", salida)  # no-tildes


class TestCheckAccents(unittest.TestCase):
    def test_detecta_identificador_acentuado(self):
        tmp = Path(tempfile.mkdtemp()) / "malo.py"
        tmp.write_text("def rotación():" + SALTO + "    pass" + SALTO, encoding="utf-8")
        codigo = (
            "import ast,sys;from pathlib import Path;"
            f"t=ast.parse(Path(r'{tmp}').read_text(encoding='utf-8'));"
            "malos=[n for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.Name))"
            " and any(c in getattr(n,'name',getattr(n,'id','')) for c in 'áéíóúñ')];"
            "sys.exit(1 if malos else 0)"
        )
        proc = subprocess.run([sys.executable, "-c", codigo], capture_output=True)
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
