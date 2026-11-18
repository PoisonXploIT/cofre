"""Pruebas del ayudante de credenciales de git (paso 7.2)."""

from __future__ import annotations

import contextlib
import io
import os
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import audit, git_helper
from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_usb_slot


class TestGitHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-git-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        master = secrets.token_bytes(32)
        self.serial = volume_serial(str(self.tmp.drive) + "\\")
        v2 = VaultV2(self.vault)
        datos = v2.create(master, new_usb_slot(
            master, self.llave.read_bytes(), self.serial, "t", ""))
        v2.put(datos, master, "GIT_TOKEN", "ghp_secret", [], ["github.com"],
               kind="api_token")
        contenido = v2.blob(datos, master, "GIT_TOKEN")
        contenido["fields"] = {"username": "sammi"}
        v2.set_blob(datos, master, "GIT_TOKEN", contenido)
        v2.save(datos)
        register_stick(str(self.vault), self.serial,
                       str(self.tmp.drive) + "\\")
        self.env = {"COFRE_VAULT": str(self.vault),
                    "COFRE_STICK": str(self.llave)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, host="github.com", operacion="get") -> str:
        entrada = f"protocol=https\nhost={host}\n\n"
        salida = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=False), \
                mock.patch("sys.stdin", io.StringIO(entrada)), \
                contextlib.redirect_stdout(salida):
            git_helper.main([operacion])
        return salida.getvalue()

    def test_entrega_usuario_y_valor_del_host(self):
        salida = self._get()
        self.assertEqual(salida, "username=sammi\npassword=ghp_secret\n\n")
        eventos = [e for e in audit._events(self.vault) if e.get("ev") == "git-get"]
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0].get("name"), "GIT_TOKEN")
        self.assertNotIn("ghp_secret", str(eventos[0]))

    def test_host_que_no_coincide_no_responde(self):
        self.assertEqual(self._get(host="ejemplo.com"), "")

    def test_store_y_erase_no_hacen_nada(self):
        self.assertEqual(self._get(operacion="store"), "")
        self.assertEqual(self._get(operacion="erase"), "")


if __name__ == "__main__":
    unittest.main()
