"""Pruebas del ayudante de git (7.2) y del despacho por la tuberia."""

from __future__ import annotations

import contextlib
import io
import json
import os
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import audit, bridge_ops, git_helper
from cofre.crypto import Vault
from cofre.gate import material_for
from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_usb_slot


class Base(unittest.TestCase):
    def setUp(self):
        audit.set_key(b"k" * 32)      # D21: la GUI tiene la clave ligada
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-git-"))
        self.vault_path = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        self.master = secrets.token_bytes(32)
        self.serial = volume_serial(str(self.tmp.drive) + "\\")
        v2 = VaultV2(self.vault_path)
        datos = v2.create(self.master, new_usb_slot(
            self.master, self.llave.read_bytes(), self.serial, "t", ""))
        v2.put(datos, self.master, "GIT_TOKEN", "ghp_secret", [], ["github.com"],
               kind="api_token")
        contenido = v2.blob(datos, self.master, "GIT_TOKEN")
        contenido["fields"] = {"username": "sammi"}
        v2.set_blob(datos, self.master, "GIT_TOKEN", contenido)
        v2.save(datos)
        register_stick(str(self.vault_path), self.serial,
                       str(self.tmp.drive) + "\\")
        material = material_for("usb", str(self.vault_path), stick=str(self.llave))
        self.vault = Vault(self.vault_path).bind_material(material)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class FakeApp:
    def __init__(self, vault, vault_path, respuesta="once"):
        self.vault = vault
        self.vault_path = vault_path
        self.gate = "usb"
        self.serial = 1
        self.session = b"x"
        self.respuesta = respuesta
        self.llamadas = []

    def request_confirm(self, who, what, contexto=None, cachear=True):
        # D20: el canal git pasa cachear=False cuando quien pide es un agente
        self.llamadas.append((who, what, contexto))
        self.cachear = cachear
        return self.respuesta


class TestDespacho(Base):
    def test_entrega_y_log_sin_valor(self):
        app = FakeApp(self.vault, self.vault_path)
        respuesta = bridge_ops.dispatch(
            app, {"type": "git", "host": "github.com", "_client": {"pid": 7}})
        self.assertTrue(respuesta["ok"])
        self.assertEqual(respuesta["username"], "sammi")
        self.assertEqual(respuesta["password"], "ghp_secret")
        self.assertEqual(app.llamadas[0][2], "git:github.com")
        eventos = [e for e in audit._events(self.vault_path)
                   if e.get("ev") == "git-get"]
        self.assertEqual(len(eventos), 1)
        self.assertIn("git:github.com", eventos[0]["detail"])
        self.assertIn("pid=7", eventos[0]["detail"])
        self.assertNotIn("ghp_secret", json.dumps(eventos))

    def test_host_sin_coincidencia(self):
        app = FakeApp(self.vault, self.vault_path)
        respuesta = bridge_ops.dispatch(
            app, {"type": "git", "host": "ejemplo.com"})
        self.assertFalse(respuesta["ok"])
        self.assertEqual(app.llamadas, [])

    def test_confirmacion_denegada(self):
        app = FakeApp(self.vault, self.vault_path, respuesta="deny")
        respuesta = bridge_ops.dispatch(
            app, {"type": "git", "host": "github.com"})
        self.assertFalse(respuesta["ok"])
        self.assertNotIn("password", respuesta)


class TestAyudante(Base):
    def test_sin_gui_no_devuelve_nada(self):
        # pendrive puesto y cofre creado, pero sin tuberia (GUI cerrada)
        info = self.tmp / "pipe-name"
        entrada = "protocol=https\nhost=github.com\n\n"
        salida = io.StringIO()
        with mock.patch.dict(os.environ, {
                "COFRE_PIPE_INFO": str(info),
                "COFRE_VAULT": str(self.vault_path),
                "COFRE_STICK": str(self.llave)}, clear=False), \
                mock.patch("sys.stdin", io.StringIO(entrada)), \
                contextlib.redirect_stdout(salida):
            codigo = git_helper.main(["get"])
        self.assertEqual(codigo, 0)
        self.assertEqual(salida.getvalue(), "")

    def test_con_tuberia_entrega(self):
        entrada = "protocol=https\nhost=github.com\n\n"
        salida = io.StringIO()
        with mock.patch.object(git_helper, "forward",
                               return_value={"ok": True, "username": "sammi",
                                             "password": "ghp_secret"}), \
                mock.patch("sys.stdin", io.StringIO(entrada)), \
                contextlib.redirect_stdout(salida):
            codigo = git_helper.main(["get"])
        self.assertEqual(codigo, 0)
        self.assertEqual(salida.getvalue(),
                         "username=sammi\npassword=ghp_secret\n\n")


if __name__ == "__main__":
    unittest.main()
