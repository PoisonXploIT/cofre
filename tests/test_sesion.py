"""Pruebas de la sesion fisica (D18, 2026-11-19).

La sesion fisica es la parte que el usuario hace en 10 minutos. Aqui se prueba la
mitad de la maquina: que detecta los discos, que comprueba el registro, que sin
pendrive se para con un mensaje claro y que no ejecuta el panico.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import sesion_fisica


class TestDiscos(unittest.TestCase):
    def test_devuelve_las_tres_letras(self):
        estado = sesion_fisica.discos()
        self.assertEqual(sorted(estado), ["D:", "E:", "F:"])
        for letra, datos in estado.items():
            self.assertIsInstance(datos["key"], bool, letra)
            self.assertIsInstance(datos["mounted"], bool, letra)

    def test_las_llaves_salen_de_key_drives(self):
        with mock.patch.object(sesion_fisica, "key_drives", return_value=["E:\\"]):
            estado = sesion_fisica.discos()
        self.assertTrue(estado["E:"]["key"])
        self.assertFalse(estado["F:"]["key"])


class TestRegistro(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-sesión-"))
        self.vault = self.tmp / "cofre.json"
        self.registro = self.tmp / ".cofre-sticks.json"
        self.parches = [
            mock.patch.object(sesion_fisica, "default_vault", return_value=self.vault),
            mock.patch.object(sesion_fisica, "key_drives", return_value=["E:\\"]),
            mock.patch.object(sesion_fisica, "volume_serial",
                              return_value=1234567890),
        ]
        for parche in self.parches:
            parche.start()
        import contextlib
        import io
        self._silencio = contextlib.redirect_stdout(io.StringIO())
        self._silencio.__enter__()

    def tearDown(self):
        self._silencio.__exit__(None, None, None)
        for parche in self.parches:
            parche.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _registro(self, seriales):
        self.registro.write_text(json.dumps({
            "sticks": {str(s): {"serial": s, "drive": "E:\\", "role": "principal"}
                       for s in seriales}}), encoding="utf-8")

    def test_sin_registro_lo_dice(self):
        self.assertFalse(sesion_fisica.paso_registro())

    def test_con_registro_ok(self):
        self._registro([1234567890])
        self.assertTrue(sesion_fisica.paso_registro())

    def test_serial_no_registrado(self):
        self._registro([111])
        self.assertFalse(sesion_fisica.paso_registro())


class TestSinPendrive(unittest.TestCase):
    def test_se_para_con_un_mensaje_claro(self):
        vacio = {"E:": {"key": False, "mounted": False},
                 "F:": {"key": False, "mounted": False},
                 "D:": {"key": False, "mounted": False}}
        import contextlib
        import io
        with mock.patch.object(sesion_fisica, "discos", return_value=vacio),                 contextlib.redirect_stdout(io.StringIO()):
            codigo = sesion_fisica.main(["--comprobar"])
        self.assertEqual(codigo, 1)
        filas = {r[1]: r for r in sesion_fisica.RESULTADOS}
        self.assertEqual(filas["pendrive E: (principal)"][0], "FALTA")

    def test_no_ejecuta_el_panico(self):
        # el panico solo se lee: la funcion debe usar --dry-run siempre
        import inspect
        fuente = inspect.getsource(sesion_fisica.paso_panico)
        self.assertIn('"--dry-run"', fuente)


if __name__ == "__main__":
    unittest.main()
