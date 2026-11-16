"""Pruebas del formato v2 (paso 1.1 a 1.4 y 1.8)."""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.crypto import Vault
from cofre.salt import get_salt
from cofre.usb import usb_session_key
from cofre.v2 import VaultV2, new_usb_slot, open_with_recovery, open_with_stick
from cofre.v2.recovery import check_code, new_code
from cofre.v2.slots import SlotError, new_recovery_slot
from cofre.v2.vault import Vault2Error


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="cofre-v2-test-"))


class TestSlots(unittest.TestCase):
    def setUp(self):
        self.master = secrets.token_bytes(32)
        self.k1 = secrets.token_bytes(32)
        self.k2 = secrets.token_bytes(32)
        self.s1 = new_usb_slot(self.master, self.k1, 111, "E", "")
        self.s2 = new_usb_slot(self.master, self.k2, 222, "F", "")
        self.code = new_code()
        self.s3 = new_recovery_slot(self.master, self.code, "papel")
        self.vault = {"slots": [self.s1, self.s2, self.s3]}

    def test_cada_pendrive_abre_su_ranura(self):
        self.assertEqual(open_with_stick(self.vault, self.k1, 111)[0], self.master)
        self.assertEqual(open_with_stick(self.vault, self.k2, 222)[0], self.master)

    def test_llave_ajena_no_abre(self):
        with self.assertRaises(SlotError):
            open_with_stick({"slots": [self.s2]}, self.k1, 222)

    def test_serial_manipulado_rompe_el_aad(self):
        manipulado = dict(self.s1, serial=999)
        with self.assertRaises(SlotError):
            open_with_stick({"slots": [manipulado]}, self.k1, 999)

    def test_revocar_borra_la_ranura(self):
        sin_f = {"slots": [self.s1, self.s3]}
        with self.assertRaises(SlotError):
            open_with_stick(sin_f, self.k2, 222)
        self.assertEqual(open_with_stick(sin_f, self.k1, 111)[0], self.master)

    def test_codigo_de_recuperacion(self):
        self.assertEqual(open_with_recovery(self.vault, self.code)[0], self.master)
        with self.assertRaises(SlotError):
            open_with_recovery(self.vault, new_code())

    def test_palabra_de_control(self):
        self.assertTrue(check_code(self.code)[0])
        partes = self.code.split()
        roto = " ".join(partes[:-1] + ["zzzz"])
        self.assertFalse(check_code(roto)[0])


class TestIndiceCifrado(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir()
        self.path = self.tmp / "cofre.json"
        self.master = secrets.token_bytes(32)
        self.key = secrets.token_bytes(32)
        self.v = VaultV2(self.path)
        self.data = self.v.create(self.master, new_usb_slot(self.master, self.key, 111, "E", ""))
        self.v.put(self.data, self.master, "GITHUB_TOKEN", "ghp_x", ["git"], ["github.com"])
        self.v.save(self.data)

    def test_ida_y_vuelta(self):
        data = VaultV2(self.path).load()
        m, _ = open_with_stick(data, self.key, 111)
        self.assertEqual(VaultV2(self.path).get(data, m, "GITHUB_TOKEN"), "ghp_x")
        self.assertEqual(VaultV2(self.path).urls(data, m, "GITHUB_TOKEN"), ["github.com"])

    def test_los_dominios_no_se_ven_en_claro(self):
        crudo = self.path.read_text(encoding="utf-8")
        self.assertNotIn("github.com", crudo)
        self.assertNotIn("GITHUB_TOKEN", crudo)

    def test_editar_el_indice_se_detecta(self):
        data = VaultV2(self.path).load()
        data["index"]["c"] = data["index"]["c"][:-4] + "0000"
        with self.assertRaises(Vault2Error):
            VaultV2(self.path).index(data, self.master)

    def test_mover_una_entrada_a_otro_id_falla(self):
        data = VaultV2(self.path).load()
        idx = VaultV2(self.path).index(data, self.master)
        entry_id = idx["entries"]["GITHUB_TOKEN"]["id"]
        blob = data["entries"][entry_id]
        data["entries"]["otro-id"] = blob
        idx["entries"]["GITHUB_TOKEN"]["id"] = "otro-id"
        # el indice manipulado se vuelve a cifrar: asi el ataque es creible y lo
        # que tiene que fallar es el AAD de la entrada, no el indice
        VaultV2(self.path)._write_index(data, self.master, idx)
        with self.assertRaises(Vault2Error):
            VaultV2(self.path).get(data, self.master, "GITHUB_TOKEN")


class TestMigracion(unittest.TestCase):
    def test_v1_a_v2_conserva_valores_y_dominios(self):
        from cofre.v2.migrate import migrate

        tmp = tmpdir()
        vault_path = tmp / "cofre.json"
        key = tmp / "COFRE.KEY"
        key.write_bytes(secrets.token_bytes(32))
        salt = get_salt(str(vault_path), create=True)
        session = usb_session_key(str(key), salt)
        v1 = Vault(vault_path)
        v1.init(session, salt=salt)
        v1.add(session, "UNO", "valor-uno", ["a"])
        v1.add(session, "DOS", "valor-dos", ["b"])

        # dry-run no escribe nada
        antes = vault_path.read_bytes()
        from cofre.v2.migrate import migrate as migrar
        plan = migrar(vault_path, key.read_bytes(), 111, dry_run=True,
                      hosts_map={"UNO": ["ejemplo.com"]})
        self.assertEqual(vault_path.read_bytes(), antes)
        self.assertEqual(plan["entradas"], ["DOS", "UNO"])

        res = migrar(vault_path, key.read_bytes(), 111, hosts_map={"UNO": ["ejemplo.com"]})
        self.assertTrue(res["backup"])
        self.assertTrue((tmp / "cofre.v1.json").exists())
        self.assertEqual(check_code(res["codigo"])[0], True)

        data = VaultV2(vault_path).load()
        self.assertTrue(VaultV2.is_v2(data))
        m, _ = open_with_stick(data, key.read_bytes(), 111)
        v2 = VaultV2(vault_path)
        self.assertEqual(v2.get(data, m, "UNO"), "valor-uno")
        self.assertEqual(v2.get(data, m, "DOS"), "valor-dos")
        self.assertEqual(v2.urls(data, m, "UNO"), ["ejemplo.com"])
        self.assertEqual(v2.names(data, m), ["DOS", "UNO"])

        # y con el codigo de recuperacion
        m3, _ = open_with_recovery(data, res["codigo"])
        self.assertEqual(v2.get(data, m3, "UNO"), "valor-uno")


if __name__ == "__main__":
    unittest.main()
