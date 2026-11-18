"""COFRE - hilos y Tkinter (2026-11-18).

Lo que se comprueba:

  1. `assert_main` deja pasar el hilo principal y para a los demas;
  2. la ConfirmQueue **no** se puede usar desde el hilo de Tk (ahi se abre el
     dialogo directamente) y si desde otro hilo;
  3. el texto de un permiso temporal es el que se ve ("git: github.com");
  4. el evento `grant-revoke` se firma como los demas.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import audit                                     # noqa: E402
from cofre.gui_confirm import ConfirmQueue                  # noqa: E402
from cofre.threads import WrongThread, assert_main, is_main  # noqa: E402


class TestHilos(unittest.TestCase):
    def test_el_principal_pasa(self):
        self.assertTrue(is_main())
        self.assertIsNone(assert_main("prueba"))

    def test_otro_hilo_salta(self):
        caja = {}

        def trabajo():
            try:
                assert_main("prueba")
                caja["r"] = "no salto"
            except WrongThread as exc:
                caja["r"] = "salto"
                caja["texto"] = str(exc)

        hilo = threading.Thread(target=trabajo, name="otro")
        hilo.start()
        hilo.join()
        self.assertEqual(caja["r"], "salto")
        self.assertIn("Tkinter", caja["texto"])

    def test_la_cola_no_se_usa_desde_tk(self):
        cola = ConfirmQueue(None)
        with self.assertRaises(AssertionError):
            cola.ask("Navegador - ejemplo.com", "SECRETO")

    def test_ask_desde_otro_hilo_encola(self):
        cola = ConfirmQueue(None)
        caja = {}

        def trabajo():
            caja["r"] = cola.ask("git - github.com", "TOKEN", timeout=0.2)

        hilo = threading.Thread(target=trabajo)
        hilo.start()
        hilo.join(timeout=3)
        # nadie contesta: se deniega por defecto y no se queda colgada
        self.assertEqual(caja.get("r"), "deny")
        self.assertFalse(cola.ocupada)


class TestPermisosATiempo(unittest.TestCase):
    def test_texto_del_permiso(self):
        from cofre.gui import CofreGUI
        self.assertEqual(CofreGUI._grant_texto(("git:github.com", "git")),
                         "git: github.com")
        self.assertEqual(CofreGUI._grant_texto(("BANCO_PASS", "Navegador")),
                         "navegador: BANCO_PASS")

    def test_evento_de_retirada_se_firma(self):
        tmp = Path(tempfile.mkdtemp(prefix="cofre-hilos-"))
        try:
            cofre = tmp / "cofre.json"
            master = b"k" * 32
            audit.set_key(master)
            try:
                audit.record(cofre, "grant-revoke", "usb", 1, name="github.com",
                             detail="permiso retirado a mano: git: github.com")
                eventos = [e for e in audit._events(cofre)
                           if e.get("ev") == "grant-revoke"]
                self.assertEqual(len(eventos), 1)
                self.assertTrue(eventos[0].get("mac"), "el evento va sin firma")
                self.assertIn("grant-revoke", audit.PRIVILEGED)
            finally:
                audit.clear_key()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
