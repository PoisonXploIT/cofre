"""Pruebas del log encadenado (paso 3.1)."""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import audit
from cofre.paths import audit_path


class TestAuditChain(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-audit-test-"))
        self.vault = self.tmp / "cofre.json"
        audit.set_key(secrets.token_bytes(32))

    def tearDown(self):
        audit.clear_key()

    def _lineas(self) -> list[str]:
        return audit_path(self.vault).read_text(encoding="utf-8").splitlines()

    def test_cadena_valida(self):
        for i in range(4):
            audit.record(self.vault, "get", "usb", 111, name=f"S{i}")
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok, detalle)
        self.assertIn("cadena intacta", detalle)

    def test_borrar_una_linea_del_medio(self):
        for i in range(4):
            audit.record(self.vault, "get", "usb", 111, name=f"S{i}")
        lineas = self._lineas()
        del lineas[1]
        audit_path(self.vault).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("cadena no cuadra", detalle)

    def test_editar_un_nombre(self):
        audit.record(self.vault, "get", "usb", 111, name="ORIGINAL")
        audit.record(self.vault, "get", "usb", 111, name="OTRO")
        lineas = self._lineas()
        ev = json.loads(lineas[0])
        ev["name"] = "CAMBIADO"
        lineas[0] = json.dumps(ev, sort_keys=True, separators=(",", ":"))
        audit_path(self.vault).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("firma incorrecta", detalle)

    def test_truncar_el_final_sin_checkpoint_no_se_ve(self):
        # honestidad: sin checkpoint, borrar la ultima linea deja una cadena
        # valida mas corta. El checkpoint es lo que lo detecta.
        for i in range(3):
            audit.record(self.vault, "get", "usb", 111, name=f"S{i}")
        lineas = self._lineas()
        audit_path(self.vault).write_text("\n".join(lineas[:-1]) + "\n", encoding="utf-8")
        ok, _ = audit.verify(self.vault)
        self.assertTrue(ok, "sin checkpoint no hay forma de saberlo")

    def test_sin_clave_las_lineas_van_sin_firma(self):
        audit.clear_key()
        audit.record(self.vault, "gui-gate", "usb", ok=False)
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok)
        self.assertIn("sin firma", detalle)

    def test_tail_y_stats_no_revientan(self):
        audit.record(self.vault, "get", "usb", 111, name="X")
        self.assertTrue(audit.tail(self.vault, 5))
        self.assertTrue(audit.tail_human(self.vault, 5))
        self.assertEqual(audit.stats(self.vault)["entradas"], 1)

    def test_no_se_guarda_ningun_valor(self):
        audit.record(self.vault, "get", "usb", 111, name="API", detail="dominio=github.com")
        crudo = audit_path(self.vault).read_text(encoding="utf-8")
        self.assertNotIn("valor", crudo)
        self.assertIn("github.com", crudo)


class TestCheckpoint(unittest.TestCase):
    def test_checkpoint_detecta_lineas_borradas(self):
        from cofre.crypto import Vault
        from cofre.salt import get_salt
        from cofre.store import open_any
        from cofre.v2 import VaultV2, new_usb_slot

        tmp = Path(tempfile.mkdtemp(prefix="cofre-checkpoint-"))
        vp = tmp / "cofre.json"
        master = secrets.token_bytes(32)
        v2 = VaultV2(vp)
        data = v2.create(master, new_usb_slot(master, secrets.token_bytes(32), 111, "E", ""))

        audit.set_key(master)
        try:
            for i in range(3):
                audit.record(vp, "get", "usb", 111, name=f"S{i}")
            store = open_any(vp)
            store._data = data
            store.master = master
            audit.stamp(store, master)
            ok, detalle = audit.check_checkpoint(store, master)
            self.assertTrue(ok, detalle)

            lineas = audit_path(vp).read_text(encoding="utf-8").splitlines()
            audit_path(vp).write_text("\n".join(lineas[:-1]) + "\n", encoding="utf-8")
            ok, detalle = audit.check_checkpoint(store, master)
            self.assertFalse(ok)
            self.assertIn("faltan lineas", detalle)
        finally:
            audit.clear_key()


if __name__ == "__main__":
    unittest.main()
