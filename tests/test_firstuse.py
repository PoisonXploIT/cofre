"""Pruebas del primer uso (6.8) con un cofre temporal y vacio."""

from __future__ import annotations

import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import firstuse
from cofre.store import open_any
from cofre.usb import load_registry
from cofre.v2 import VaultV2
from cofre.v2.slots import open_with_recovery, open_with_stick


class TestCrear(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-first-"))
        self.vault = self.tmp / "cofre.json"
        self.clave = self.tmp / "COFRE.KEY"
        self.drive = str(self.tmp.drive) + "\\"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_crea_llave_cofre_y_codigo_vacios(self):
        with mock.patch("cofre.firstuse.volume_serial", return_value=111):
            estado = firstuse.crear_cofre(self.vault, self.drive,
                                          clave=self.clave)
        self.assertTrue(self.clave.exists())
        self.assertEqual(len(self.clave.read_bytes()), 32)
        datos = VaultV2(self.vault).load()
        self.assertEqual(open_with_stick(datos, self.clave.read_bytes(), 111)[0],
                         estado["master"])
        self.assertEqual(open_with_recovery(datos, estado["código"])[0],
                         estado["master"])
        self.assertEqual(VaultV2(self.vault).names(datos, estado["master"]), [])
        reg = load_registry(self.vault)
        self.assertIn("111", reg["sticks"])
        # el cofre vacio se abre con el pendrive
        store = open_any(self.vault, material={
            "stick_key": self.clave.read_bytes(), "serial": 111, "pin": ""})
        self.assertEqual(store.names(), [])

    def test_no_pisa_un_cofre_ni_una_llave(self):
        self.vault.write_text("{}", encoding="utf-8")
        with mock.patch("cofre.firstuse.volume_serial", return_value=111):
            with self.assertRaises(FileExistsError):
                firstuse.crear_cofre(self.vault, self.drive, clave=self.clave)
        self.vault.unlink()
        self.clave.write_bytes(secrets.token_bytes(32))
        with mock.patch("cofre.firstuse.volume_serial", return_value=111):
            with self.assertRaises(FileExistsError):
                firstuse.crear_cofre(self.vault, self.drive, clave=self.clave)

    def test_agrega_reserva_y_confirma_palabras(self):
        with mock.patch("cofre.firstuse.volume_serial", return_value=111):
            estado = firstuse.crear_cofre(self.vault, self.drive,
                                          clave=self.clave)
        reserva = self.tmp / "RESERVA.KEY"
        with mock.patch("cofre.firstuse.volume_serial", return_value=222):
            datos = firstuse.agregar_reserva(
                self.vault, estado["data"], estado["master"], self.drive,
                clave=reserva)
        self.assertIn("222", load_registry(self.vault)["sticks"])
        self.assertEqual(open_with_stick(estado["data"], reserva.read_bytes(),
                                         222)[0], estado["master"])
        partes = estado["código"].split()
        self.assertTrue(firstuse.confirmar_palabras(
            estado["código"], {1: partes[0], 7: partes[6]}))
        self.assertFalse(firstuse.confirmar_palabras(
            estado["código"], {1: "no", 7: partes[6]}))


if __name__ == "__main__":
    unittest.main()
