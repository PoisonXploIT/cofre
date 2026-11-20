"""D22 (2026-11-19): pasar el pendrive a llave + PIN.

El agente puede leer `COFRE.KEY` mientras el pendrive está puesto (tiene terminal con
el mismo usuario). Con PIN, la llave sola no sirve: hace falta la frase que solo sabe
el usuario.

Lo que se prueba aquí:
  1. con un cofre v2, la ranura pasa a pedir PIN;
  2. la llave sola ya no abre (y con PIN sí);
  3. la ranura vieja desaparece: no queda ninguna sin PIN para ese serial;
  4. si el PIN no vale, el cofre se queda **exactamente** como estaba;
  5. un PIN vacío o cortísimo se rechaza en la capa de `poner_pin`.
"""

from __future__ import annotations

import secrets
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import keys                                    # noqa: E402
from cofre.v2 import VaultV2, new_usb_slot                # noqa: E402
from cofre.v2.slots import SlotError, open_with_stick     # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-pin-"))
        self.vault_path = self.tmp / "cofre.json"
        self.llave = secrets.token_bytes(32)
        self.master = secrets.token_bytes(32)
        self.v2 = VaultV2(self.vault_path)
        datos = self.v2.create(self.master,
                               new_usb_slot(self.master, self.llave, 4242, "t", ""))
        self.v2.save(datos)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def abrir(self):
        return VaultV2(self.vault_path).load()


class TestPonerPin(Base):
    def test_la_ranura_pasa_a_pedir_pin(self):
        datos, detalle = keys.poner_pin(self.v2, self.abrir(), self.master, 4242,
                                        self.llave, "frase de seis palabras al azar")
        self.assertIn("pide PIN", detalle)
        releido = self.abrir()
        maestro, slot = open_with_stick(releido, self.llave, 4242,
                                        "frase de seis palabras al azar")
        self.assertEqual(maestro, self.master)
        self.assertTrue(slot.get("pin"))

    def test_la_llave_sola_ya_no_abre(self):
        keys.poner_pin(self.v2, self.abrir(), self.master, 4242, self.llave,
                       "frase de seis palabras al azar")
        with self.assertRaises(SlotError):
            open_with_stick(self.abrir(), self.llave, 4242, "")

    def test_no_queda_ninguna_ranura_sin_pin(self):
        keys.poner_pin(self.v2, self.abrir(), self.master, 4242, self.llave,
                       "frase de seis palabras al azar")
        ranuras = [s for s in self.abrir()["slots"]
                   if s.get("kind") == "usb" and int(s.get("serial", -1)) == 4242]
        self.assertEqual(len(ranuras), 1)
        self.assertTrue(ranuras[0].get("pin"))

    def test_pin_vacio_se_rechaza(self):
        with self.assertRaises(ValueError):
            keys.poner_pin(self.v2, self.abrir(), self.master, 4242, self.llave, "")

    def test_llave_que_no_abre_no_toca_nada(self):
        antes = self.vault_path.read_bytes()
        with self.assertRaises(ValueError):
            keys.poner_pin(self.v2, self.abrir(), self.master, 4242,
                           secrets.token_bytes(32), "frase de seis palabras")
        self.assertEqual(antes, self.vault_path.read_bytes())

    def test_dos_veces_no_rompe(self):
        keys.poner_pin(self.v2, self.abrir(), self.master, 4242, self.llave,
                       "frase de seis palabras al azar")
        # la segunda vez ya no hay ranura sin PIN: lo dice y no toca nada
        antes = self.vault_path.read_bytes()
        with self.assertRaises(ValueError) as ctx:
            keys.poner_pin(self.v2, self.abrir(), self.master, 4242, self.llave,
                           "otra frase distinta")
        self.assertIn("sin PIN", str(ctx.exception))
        self.assertEqual(antes, self.vault_path.read_bytes())


if __name__ == "__main__":
    unittest.main()


class TestLaVentanaConPin(unittest.TestCase):
    """2026-11-20: con `--gate usb-pin`, la ventana no abría aunque el PIN fuese
    bueno: `_bind_material` no le pasaba el PIN a `material_for`. Y si se abría sin
    `--gate usb-pin`, el aviso no decía que hacía falta el PIN.
    """

    def setUp(self):
        import secrets
        import shutil
        import tempfile
        import tkinter as tk
        from cofre.gui import CofreGUI
        from cofre.v2 import VaultV2, new_usb_slot
        from cofre.usb import register_stick, volume_serial
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-pin-gui-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        self.pin = "frase de seis palabras"
        master = secrets.token_bytes(32)
        serial = volume_serial(str(self.tmp.drive) + "\\")
        v2 = VaultV2(self.vault)
        v2.save(v2.create(master, new_usb_slot(master, self.llave.read_bytes(),
                                               serial, "t", self.pin)))
        register_stick(str(self.vault), serial, str(self.tmp.drive) + "\\")
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        import shutil
        try:
            for ident in self.root.tk.call("after", "info"):
                try:
                    self.root.after_cancel(ident)
                except Exception:
                    pass
        except Exception:
            pass
        self.root.destroy()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _app(self, gate="usb-pin"):
        from cofre.gui import CofreGUI
        app = CofreGUI(str(self.vault), gate, stick=str(self.llave), root=self.root)
        app.build()
        self.root.update()
        return app

    def test_con_el_pin_bueno_abre(self):
        app = self._app()
        self.assertIsNone(app.session)
        app.pin_var.set(self.pin)
        app.unlock()
        self.root.update()
        self.assertTrue(app.session, app.foot_var.get())

    def test_con_el_pin_malo_no_abre(self):
        app = self._app()
        app.pin_var.set("otra cosa")
        app.unlock()
        self.root.update()
        self.assertIsNone(app.session)

    def test_sin_gate_usb_pin_el_aviso_lo_dice(self):
        app = self._app(gate="usb")
        app.unlock()
        self.root.update()
        self.assertIsNone(app.session)
        self.assertIn("pide PIN", app.foot_var.get())
