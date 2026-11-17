"""Prueba de humo del CLI (R8 y el aviso de los UnboundLocalError).

Dos veces seguidas aparecio un `UnboundLocalError` que solo salta al pasar por
una rama concreta: un import local dentro de main() convierte el nombre en
variable local de toda la funcion, y cualquier otra rama que lo use revienta.
Una regla no lo evita; esto si: se ejecuta CADA subcomando al menos una vez
contra un cofre temporal.

  python -m unittest tests.test_cli_smoke
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.crypto import Vault
from cofre.salt import get_salt
from cofre.usb import register_stick, usb_session_key, volume_serial


class TestCliSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-cli-smoke-"))
        self.vault_path = self.tmp / "cofre.json"
        self.key = self.tmp / "COFRE.KEY"
        self.key.write_bytes(secrets.token_bytes(32))
        salt = get_salt(str(self.vault_path), create=True)
        self.session = usb_session_key(str(self.key), salt)
        vault = Vault(self.vault_path)
        vault.init(self.session, salt=salt)
        vault.add(self.session, "UNO", "valor-uno", ["a"])
        # sin registro el gate falla cerrado (H13) y el CLI no llega a actuar:
        # se autoriza el volumen del temporal para poder probar los comandos
        drive = str(self.tmp.drive) + "\\"
        register_stick(str(self.vault_path), volume_serial(drive), drive)
        self.base = [sys.executable, "-m", "cofre.cli", "--vault", str(self.vault_path),
                     "--stick", str(self.key)]

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(self.base + list(args), capture_output=True, text=True,
                              cwd=str(REPO), timeout=180)

    def _sin_unbound(self, proc: subprocess.CompletedProcess, etiqueta: str) -> None:
        salida = proc.stdout + proc.stderr
        self.assertNotIn("UnboundLocalError", salida,
                         f"{etiqueta} revienta con UnboundLocalError:\n{salida}")
        self.assertNotIn("NameError", salida, f"{etiqueta} revienta con NameError:\n{salida}")

    def test_comandos_de_datos(self):
        for args in (["list"], ["check"], ["log", "--lines", "3"],
                     ["get", "UNO", "--allow-pipe"], ["host-list"],
                     ["salt"], ["stick-list"], ["stick-verify"]):
            with self.subTest(args=args):
                self._sin_unbound(self.run_cli(*args), " ".join(args))

    def test_altas_y_bajas(self):
        self._sin_unbound(self.run_cli("add", "DOS", "valor-dos"), "add")
        self._sin_unbound(self.run_cli("host-assign", "DOS", "ejemplo.com"), "host-assign")
        proc = self.run_cli("rename", "DOS", "DOS2")
        self._sin_unbound(proc, "rename")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        proc = self.run_cli("list")
        self.assertIn("DOS2", proc.stdout)
        self._sin_unbound(self.run_cli("del", "DOS"), "del")
        # el secreto esta en el cofre
        proc = self.run_cli("list")
        self.assertIn("UNO", proc.stdout)

    def test_comandos_de_pendrive(self):
        for args in (["stick-list"], ["stick-verify"],
                     ["stick-register", str(self.key)],
                     ["stick-role", "0", "reserva"]):
            with self.subTest(args=args):
                self._sin_unbound(self.run_cli(*args), " ".join(args))

    def test_meta_y_rotate(self):
        # los metadatos y la rotacion en seco: aqui aparecio un UnboundLocalError
        proc = self.run_cli("meta", "UNO")
        self._sin_unbound(proc, "meta")
        proc = self.run_cli("meta", "UNO", "--provider", "cloudflare",
                            "--token-id", "tok-1", "--rotate-every", "90")
        self._sin_unbound(proc, "meta --provider")
        proc = self.run_cli("rotate", "UNO", "--dry-run")
        self._sin_unbound(proc, "rotate --dry-run")

    def test_migrate_dry_run(self):
        proc = self.run_cli("migrate", "--dry-run")
        self._sin_unbound(proc, "migrate --dry-run")
        self.assertIn("dry-run", proc.stdout)

    def test_stick_add_v2_sin_v2(self):
        proc = self.run_cli("stick-add-v2", str(self.tmp / "X.KEY.nuevo"))
        self._sin_unbound(proc, "stick-add-v2")
        self.assertIn("v2", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
