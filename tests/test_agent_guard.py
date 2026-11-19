"""Pruebas del candado para agentes (D20, 2026-11-19).

La sesion del LLM va a una API en la nube: todo lo que lea o imprima sale del
equipo. Con `COFRE_AGENT=1` COFRE no debe mostrar valores nunca. Se prueba de dos
maneras:

  1. unidad: que `motivo()` bloquee lo que tiene que bloquear y deje pasar el resto;
  2. de verdad: con un cofre temporal y un secreto conocido, **ningún** subcomando
     imprime el valor; y los que lo muestran salen con codigo 3.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import agent_guard          # noqa: E402

VALOR = "valor-que-no-debe-salir-42"


class TestUnidad(unittest.TestCase):
    def _args(self, **kw):
        base = dict(command="list", recovery=False, minimal=False, value=None,
                    reanchor=False)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_sin_la_variable_nada_se_bloquea(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COFRE_AGENT", None)
            self.assertEqual(agent_guard.motivo(self._args(command="get")), "")

    def test_bloquea_lo_que_muestra_valores(self):
        with unittest.mock.patch.dict(os.environ, {"COFRE_AGENT": "1"}):
            self.assertTrue(agent_guard.motivo(self._args(command="get")))
            self.assertTrue(agent_guard.motivo(self._args(command="export")))
            self.assertTrue(agent_guard.motivo(self._args(command="list",
                                                         recovery=True)))
            self.assertTrue(agent_guard.motivo(self._args(command="describe")))
            self.assertTrue(agent_guard.motivo(self._args(command="add",
                                                          value="pegado")))
            self.assertTrue(agent_guard.motivo(self._args(command="log",
                                                          reanchor=True)))

    def test_bloquea_las_puertas_de_atras(self):
        # A2 de la revision (2026-11-19): shell lleva get dentro, serve es el
        # puente por puerto y gui no la maneja un agente.
        with unittest.mock.patch.dict(os.environ, {"COFRE_AGENT": "1"}):
            for comando in ("shell", "serve", "gui"):
                self.assertTrue(agent_guard.motivo(self._args(command=comando)),
                                comando)

    def test_deja_pasar_lo_permitido(self):
        with unittest.mock.patch.dict(os.environ, {"COFRE_AGENT": "1"}):
            for args in (self._args(command="exec"),
                         self._args(command="run"),
                         self._args(command="check"),
                         self._args(command="health"),
                         self._args(command="describe", minimal=True),
                         self._args(command="log"),
                         self._args(command="scan"),
                         self._args(command="list"),
                         self._args(command="add")):
                self.assertEqual(agent_guard.motivo(args), "", args.command)

    def test_la_variable_admite_varias_formas(self):
        for valor in ("1", "si", "sí", "true", "on", "YES"):
            with unittest.mock.patch.dict(os.environ, {"COFRE_AGENT": valor}):
                self.assertTrue(agent_guard.activo(), valor)
        for valor in ("", "0", "no", "false"):
            with unittest.mock.patch.dict(os.environ, {"COFRE_AGENT": valor}):
                self.assertFalse(agent_guard.activo(), valor)


class TestDeVerdad(unittest.TestCase):
    """Ningún subcomando imprime el valor con el candado puesto."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-agente-"))
        vault = self.tmp / "cofre.json"
        key = self.tmp / "COFRE.KEY"
        key.write_bytes(secrets.token_bytes(32))
        from cofre.salt import get_salt
        from cofre.usb import register_stick, usb_session_key, volume_serial
        from cofre.crypto import Vault
        salt = get_salt(str(vault), create=True)
        session = usb_session_key(str(key), salt)
        v = Vault(vault)
        v.init(session, salt=salt)
        v.add(session, "SECRETO", VALOR, ["prueba"])
        drive = str(self.tmp.drive) + "\\"
        register_stick(str(vault), volume_serial(drive), drive)
        self.base = [sys.executable, "-m", "cofre.cli", "--vault", str(vault),
                     "--stick", str(key)]
        self.entorno = dict(os.environ, COFRE_AGENT="1")
        self.vault = vault

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def correr(self, *args: str):
        return subprocess.run(self.base + list(args), capture_output=True, text=True,
                              cwd=str(REPO), env=self.entorno, timeout=180)

    def test_los_que_muestran_valores_salen_con_codigo_3(self):
        for args in (["get", "SECRETO"], ["get", "SECRETO", "--allow-pipe"],
                     ["export"], ["describe"]):
            with self.subTest(args=args):
                proc = self.correr(*args)
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
                self.assertNotIn(VALOR, proc.stdout + proc.stderr)
                self.assertIn("COFRE_AGENT=1", proc.stderr)

    def test_recorrido_de_subcomandos_sin_valores(self):
        # los que no necesitan datos del usuario: ninguno puede imprimir el valor
        ordenes = [["list"], ["check"], ["health"], ["describe", "--minimal"],
                   ["token-info", "SECRETO"], ["host-list"], ["meta", "SECRETO"],
                   ["stick-list"], ["stick-verify"], ["alerts"], ["due"],
                   ["versión"], ["salt"], ["scan", str(self.tmp)]]
        for args in ordenes:
            with self.subTest(args=args):
                proc = self.correr(*args)
                self.assertNotIn(VALOR, proc.stdout + proc.stderr,
                                 f"{args} imprime el valor")

    def test_recovery_y_reanchor_bloqueados(self):
        for args in (["--recovery", "list"], ["log", "verify", "--reanchor"]):
            with self.subTest(args=args):
                proc = self.correr(*args)
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
                self.assertIn("COFRE_AGENT=1", proc.stderr)

    def test_shell_serve_y_gui_bloqueados(self):
        # A2: las tres puertas de atras, de verdad y no solo en la unidad
        for args in (["shell"], ["serve"], ["gui"]):
            with self.subTest(args=args):
                proc = self.correr(*args)
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
                self.assertIn("COFRE_AGENT=1", proc.stderr)

    def test_serve_por_modulo_tambien(self):
        # `python -m cofre.serve` no pasa por cli.main: se comprueba aparte
        proc = subprocess.run([sys.executable, "-m", "cofre.serve", "--port", "0"],
                              capture_output=True, text=True, env=self.entorno,
                              cwd=str(REPO), timeout=60)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
