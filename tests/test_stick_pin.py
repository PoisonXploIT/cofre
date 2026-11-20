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
from unittest import mock
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

    # --- 2026-11-20 (tarde): el PIN se teclea en la pantalla de bloqueo, pero
    # nadie lo leia de ahi. Se rellenaba `pin_var` solo desde el panel de la
    # derecha, tapado por la capa de bloqueo, asi que Abrir y Reconectar usaban
    # un PIN vacio y el cofre contestaba siempre lo mismo: "escribe el PIN".

    def test_reconectar_lee_el_pin_del_campo(self):
        app = self._app()
        app.lock_screen.pin_field.set(self.pin)
        app.lock_screen.b_reconectar.invoke()
        self.root.update()
        self.assertTrue(app.session, app.foot_var.get())

    def test_abrir_lee_el_pin_del_campo(self):
        app = self._app()
        app.lock_screen.pin_field.set(self.pin)
        app.lock_screen.b_abrir.invoke()
        self.root.update()
        self.assertTrue(app.session, app.foot_var.get())

    def test_enter_en_el_campo_pin_abre(self):
        # No se puede simular la tecla: en Windows el evento de teclado va a la
        # ventana con el foco y este proceso no lo tiene (se comprobo: el
        # `event_generate` de Return acaba en el root, no en el Entry). Se
        # comprueba el cableado y que el mismo camino abre con el PIN puesto.
        app = self._app()
        app.lock_screen.pin_field.set(self.pin)
        self.assertTrue(app.lock_screen.pin_field.entry.bind("<Return>"),
                        "Enter en el campo PIN no hace nada")
        app.lock_screen._abrir()
        self.root.update()
        self.assertTrue(app.session, app.foot_var.get())

    def test_sin_pin_el_aviso_habla_del_pin_y_no_del_pendrive(self):
        app = self._app()
        app.unlock()
        self.root.update()
        self.assertIsNone(app.session)
        aviso = app.foot_var.get()
        self.assertIn("PIN", aviso)
        self.assertNotIn("conecta un pendrive", aviso)

    def test_pin_malo_el_aviso_no_culpa_al_pendrive(self):
        app = self._app()
        app.lock_screen.pin_field.set("otra cosa")
        app.lock_screen.b_abrir.invoke()
        self.root.update()
        self.assertIsNone(app.session)
        aviso = app.foot_var.get()
        self.assertIn("PIN", aviso)
        self.assertNotIn("Quita y vuelve a conectar", aviso)


class TestMaterialForTomaLaFrase(unittest.TestCase):
    """2026-11-21: `log verify`, `stick-verify` y `panic` se quedaban sin la frase.

    La sesion se la pasaba al hijo en COFRE_PIN, pero esos comandos llamaban a
    `material_for` sin frase y el material salia sin PIN: la ranura no abria y
    el aviso culpaba a la llave.
    """

    def _material(self, modo, **kw):
        from cofre import gate
        with mock.patch.dict("os.environ", {"COFRE_PIN": "frase del entorno"}), \
                mock.patch.object(gate, "read_pin",
                                  return_value="frase del entorno") as lector, \
                mock.patch("cofre.usb.find_stick",
                           return_value=("X:/COFRE.KEY", 4242)), \
                mock.patch("cofre.usb.read_key", return_value=b"k" * 32):
            material = gate.material_for(modo, "c:/tmp/cofre.json", **kw)
        return material, lector

    def test_sin_frase_pasa_por_read_pin(self):
        material, lector = self._material("usb-pin")
        self.assertEqual(material["pin"], "frase del entorno")
        lector.assert_called_once()

    def test_si_le_pasan_frase_no_pregunta(self):
        material, lector = self._material("usb-pin", pin="la que me dan")
        self.assertEqual(material["pin"], "la que me dan")
        lector.assert_not_called()

    def test_gate_usb_no_pregunta_nada(self):
        material, lector = self._material("usb")
        self.assertEqual(material["pin"], "")
        lector.assert_not_called()


class TestStickVerifyConPin(Base):
    """`stick-verify --gate usb-pin` prueba llave + frase, no la llave sola."""

    PIN = "frase de seis palabras"

    def setUp(self):
        super().setUp()
        from cofre.usb import register_stick
        keys.poner_pin(self.v2, self.abrir(), self.master, 4242, self.llave,
                       self.PIN)
        self.fichero = self.tmp / "COFRE.KEY"
        self.fichero.write_bytes(self.llave)
        register_stick(str(self.vault_path), 4242, "X:\\")

    def _verificar(self, frase):
        import contextlib
        import io
        from cofre import cli
        salida = io.StringIO()
        with mock.patch.object(cli, "keys_to_try",
                               return_value=[str(self.fichero)]), \
                mock.patch.object(cli, "volume_serial", return_value=4242), \
                mock.patch.object(cli, "_drive_of", return_value="X:\\"), \
                mock.patch.object(cli, "read_pin", return_value=frase), \
                contextlib.redirect_stdout(salida):
            codigo = cli.cmd_stick_verify(str(self.vault_path), "usb-pin")
        return codigo, salida.getvalue()

    def test_con_la_frase_buena_la_llave_sirve(self):
        codigo, texto = self._verificar(self.PIN)
        self.assertEqual(codigo, 0, texto)
        self.assertIn("abre el cofre", texto)

    def test_con_la_frase_mala_la_llave_no_sirve(self):
        codigo, texto = self._verificar("otra cosa")
        self.assertEqual(codigo, 1, texto)
        self.assertIn("NO abre el cofre", texto)
