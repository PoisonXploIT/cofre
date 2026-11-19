"""Prueba de humo de los botones de verdad (D19, 2026-11-19).

Tres fallos de la misma familia en un dia, y ninguno lo cazó una prueba por AST:

  - callbacks sin argumento (`def probar():` pasado a `_btn`, que llama con None);
  - `_on_tk_error` escribiendo a `sys.stderr` (None con pythonw);
  - `_btn` sustituyendo `set_enabled` por un envoltorio que se llamaba a si mismo.

La tercera solo revienta **al deshabilitar un boton**, y eso no se ve leyendo el
codigo. Aqui se construye la ventana real con un cofre temporal, se abren sus hojas y
se **activan y desactivan todos** los botones con un limite de recursion bajo
(`sys.setrecursionlimit(150)`), para que una recursion infinita falle en el sitio en
vez de colgar.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

VALOR = "valor-de-prueba-para-botones"


def _botones(widget) -> list:
    """Todos los objetos con `set_enabled` (botones propios) del arbol."""
    salida = []
    pila = [widget]
    while pila:
        actual = pila.pop()
        if hasattr(actual, "set_enabled"):
            salida.append(actual)
        try:
            pila.extend(actual.winfo_children())
        except Exception:
            continue
    return salida


import tkinter as tk  # noqa: E402


class TestBotonesDeVerdad(unittest.TestCase):
    def setUp(self):
        try:
            tk.Tk()
        except Exception as exc:                     # noqa: BLE001
            self.skipTest(f"sin Tk: {exc}")
        import tmpvault
        from cofre.gui import CofreGUI
        self.vault, self.llave, self.tmp = tmpvault.cofre_temporal()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = CofreGUI(str(self.vault), "usb", stick=str(self.llave),
                            root=self.root)
        self.app.build()
        self.root.update()

    def _cerrar_hojas(self) -> None:
        # solo las hojas (Toplevel): los hijos de la raiz son la propia ventana
        for ventana in list(self.root.winfo_children()):
            if isinstance(ventana, tk.Toplevel) and ventana.winfo_exists():
                try:
                    ventana.destroy()
                except Exception:
                    pass

    def tearDown(self):
        # cancelar los `after` pendientes antes de destruir: si no, Tk avisa
        # "invalid command name _pump_confirm" al cerrar el interprete y ensucia
        # la salida de la bateria.
        try:
            for ident in self.root.tk.call("after", "info"):
                try:
                    self.root.after_cancel(ident)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.quit()        # salir del bucle antes de destruir
            self.root.update()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        import gc
        gc.collect()                # sin Tk colgando en el recolector
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _probar(self, titulo: str) -> int:
        botones = _botones(self.root)
        self.assertGreaterEqual(len(botones), 1, f"{titulo}: sin botones")
        limite = sys.getrecursionlimit()
        sys.setrecursionlimit(150)
        try:
            for boton in botones:
                try:
                    boton.set_enabled(False)
                    boton.set_enabled(True)
                    self.app.root.update()
                except tk.TclError:
                    # el widget ya no existe (hoja cerrada): no es un fallo
                    continue
        finally:
            sys.setrecursionlimit(limite)
        return len(botones)

    def test_la_ventana_principal_no_revienta_al_activar_y_desactivar(self):
        self.assertGreater(self._probar("ventana"), 0)

    def test_las_hojas_no_revientan_al_activar_y_desactivar(self):
        for nombre in ("open_keys", "open_health", "open_audit", "open_guide",
                       "open_shortcuts", "open_panic", "open_settings",
                       "_probar_codigo"):
            with self.subTest(hoja=nombre):
                getattr(self.app, nombre)()
                self.root.update()
                self._probar(nombre)
                self._cerrar_hojas()
                try:
                    self.app._mostrar_vista("detalle")   # quita el panel de salud
                except Exception:
                    pass
                self.root.update()

    def test_la_paleta_y_el_primer_uso(self):
        self.app.open_palette()
        self.root.update()
        self._probar("paleta")
        self._cerrar_hojas()
        self.root.update()

    def test_el_detalle_con_un_secreto_elegido(self):
        # con seleccion, el detalle pinta chips, sitios y botones
        self.app.selected = self.app.vault.names()[0]
        self.app.refresh_detail()
        self.app._update_detail_visible()
        self.root.update()
        self._probar("detalle")


if __name__ == "__main__":
    unittest.main()


class TestPendriveQueRespondeAMedias(unittest.TestCase):
    """2026-11-19: el volumen contestaba a resolve_session_key pero no a
    material_for. La ventana decia "abierto" con el cofre sin clave: 0 secretos y
    "cofre v2 abierto sin sesión" al guardar. Ahora se cierra y avisa.
    """

    def setUp(self):
        import tmpvault
        from cofre.gui import CofreGUI
        self.vault, self.llave, self.tmp = tmpvault.cofre_temporal()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = CofreGUI(str(self.vault), "usb", stick=str(self.llave),
                            root=self.root)
        self.app.build()
        self.root.update()

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

    def test_sin_llave_util_el_cofre_se_cierra_y_avisa(self):
        from unittest import mock
        self.app.lock()
        self.app.vault.reset_store()      # como al arrancar: sin tienda en memoria
        with mock.patch("cofre.gui.material_for", return_value=None):
            resultado = self.app.unlock()
        self.root.update()
        self.assertFalse(resultado)
        self.assertIsNone(self.app.session)
        self.assertEqual(self.app.status_var.get(), "Cerrado")
        self.assertIn("no se abre con su llave", self.app.foot_var.get())

    def test_con_llave_buena_abre_y_tiene_secretos(self):
        self.assertTrue(self.app.session)
        self.assertTrue(self.app.vault.names())
        self.assertIsNotNone(self.app.vault._v2store().master)
