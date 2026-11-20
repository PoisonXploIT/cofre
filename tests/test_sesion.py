"""Pruebas de la sesion fisica (D18, 2026-11-19).

La sesion fisica es la parte que el usuario hace en 10 minutos. Aqui se prueba la
mitad de la maquina: que detecta los discos, que comprueba el registro, que sin
pendrive se para con un mensaje claro y que no ejecuta el panico.
"""

from __future__ import annotations

import json
import os
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


class TestLaFrase(unittest.TestCase):
    """2026-11-20 (cierre 1.0.0): la frase se pide UNA vez, en el padre, y viaja
    solo en el entorno de cada hijo.

    Antes habia que ponerla a mano (`set` en cmd, `$env:` en PowerShell): quedaba
    en la ventana, la heredaba todo y cada hijo que la necesitaba se colgaba en
    `getpass`.
    """

    DISCOS = {"E:": {"key": True, "mounted": True},
              "F:": {"key": True, "mounted": True},
              "D:": {"key": False, "mounted": True}}
    FRASE = "frase de prueba"

    class _Falso:
        returncode = 0
        stdout = ""
        stderr = ""

    def _correr(self, argv, stdin=None, entorno=None, discos=None):
        """Ejecuta `main` con subprocess.run de mentira y la entrada simulada."""
        import contextlib
        import io
        entornos = []

        def falso_run(cmd, **kw):
            entornos.append(kw.get("env"))
            return self._Falso()

        with (
            mock.patch.object(sesion_fisica, "discos",
                              return_value=discos or self.DISCOS),
            mock.patch.object(sesion_fisica, "paso_registro", return_value=True),
            mock.patch.object(sesion_fisica, "paso_recordatorio",
                              return_value=True),
            mock.patch.object(sesion_fisica.subprocess, "run",
                              side_effect=falso_run),
            mock.patch.dict(os.environ, entorno or {}),
            mock.patch.object(sys, "stdin",
                              io.StringIO(self.FRASE + chr(10) if stdin is None
                                          else stdin)),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            codigo = sesion_fisica.main(argv)
        return codigo, entornos

    def test_la_frase_va_a_los_hijos_y_no_al_padre(self):
        codigo, entornos = self._correr(["--gate", "usb-pin", "--comprobar"])
        self.assertEqual(codigo, 0)
        con_frase = [e for e in entornos if e and e.get("COFRE_PIN") == self.FRASE]
        self.assertGreaterEqual(len(con_frase), 2,
                                "la frase no llego a los pasos hijos")
        self.assertNotIn("COFRE_PIN", os.environ,
                         "la frase se quedo en el entorno del padre")

    def test_con_cofre_agent_no_se_pide(self):
        with mock.patch.object(sesion_fisica, "leer_frase",
                               side_effect=AssertionError("no debe preguntar")):
            codigo, entornos = self._correr(["--gate", "usb-pin", "--comprobar"],
                                            entorno={"COFRE_AGENT": "1"})
        self.assertEqual(codigo, 3)
        self.assertEqual(entornos, [])

    def test_sin_frase_no_sigue(self):
        codigo, entornos = self._correr(["--gate", "usb-pin", "--comprobar"],
                                        stdin=chr(10))
        self.assertEqual(codigo, 3)
        self.assertEqual(entornos, [])

    def test_sin_gate_usb_pin_no_pregunta(self):
        with mock.patch.object(sesion_fisica, "leer_frase",
                               side_effect=AssertionError("no debe preguntar")):
            # sin E: se para en el primer paso, pero antes no debe pedir nada
            vacio = {"E:": {"key": False, "mounted": False},
                     "F:": {"key": False, "mounted": False},
                     "D:": {"key": True, "mounted": True}}
            codigo, _entornos = self._correr(["--comprobar"], discos=vacio,
                                             entorno={"COFRE_AGENT": "0"})
        self.assertEqual(codigo, 1)


if __name__ == "__main__":
    unittest.main()
