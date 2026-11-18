"""Rotación asistida en dos fases (GitHub), con servidor falso.

Regla: si el valor nuevo no verifica, no se guarda nada y el viejo sigue.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.gate import material_for
from cofre.store import open_any
from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_usb_slot
from fake_github import FakeGitHub


class TestRotateManual(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-manual-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        master = secrets.token_bytes(32)
        self.serial = volume_serial(str(self.tmp.drive) + "\\")
        v2 = VaultV2(self.vault)
        datos = v2.create(master, new_usb_slot(master, self.llave.read_bytes(),
                                              self.serial, "t", ""))
        v2.put(datos, master, "GH_TOKEN", "ghp_bueno", ["prueba"], [], kind="api_token")
        v2.save(datos)
        register_stick(str(self.vault), self.serial, str(self.tmp.drive) + "\\")
        self.fake = FakeGitHub()
        base = self.fake.start()
        self.env = dict(os.environ, COFRE_GITHUB_API=base, COFRE_VAULT=str(self.vault))
        self.cmd = [sys.executable, "-m", "cofre.cli", "--gate", "usb",
                    "--stick", str(self.llave), "--vault", str(self.vault)]
        subprocess.run(self.cmd + ["meta", "GH_TOKEN", "--provider", "github"],
                       capture_output=True, env=self.env)

    def tearDown(self):
        self.fake.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _abrir(self):
        return open_any(self.vault, material=material_for("usb", str(self.vault),
                                                          stick=str(self.llave)))

    def test_valor_nuevo_invalido_no_guarda_nada(self):
        r = subprocess.run(self.cmd + ["rotate", "GH_TOKEN", "--manual", "--si"],
                           input="ghp_malo" + chr(10), capture_output=True, text=True, env=self.env)
        self.assertIn("NO es válido", r.stdout + r.stderr)
        self.assertEqual(self._abrir().get("GH_TOKEN"), "ghp_bueno")
        self.assertEqual(self.fake.revocados, [])

    def test_valor_nuevo_valido_se_guarda_y_revoca_el_viejo(self):
        r = subprocess.run(self.cmd + ["rotate", "GH_TOKEN", "--manual", "--si",
                                       "--revoke-old"],
                           input="ghp_bueno" + chr(10), capture_output=True, text=True, env=self.env)
        self.assertIn("revocado", (r.stdout + r.stderr).lower())
        self.assertIn("ghp_bueno", self.fake.revocados)

    def test_no_revoca_si_no_se_pide(self):
        subprocess.run(self.cmd + ["rotate", "GH_TOKEN", "--manual", "--si"],
                       input="ghp_bueno" + chr(10), capture_output=True, text=True, env=self.env)
        self.assertEqual(self.fake.revocados, [])
