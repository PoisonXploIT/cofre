"""Pruebas del catalogo de mensajes (paso 6.3)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.messages import MSG, msg


class TestCatalogo(unittest.TestCase):
    def test_claves_y_textos(self):
        self.assertGreater(len(MSG), 40)
        for clave, texto in MSG.items():
            self.assertIsInstance(clave, str)
            self.assertTrue(clave)
            self.assertIsInstance(texto, str)
            self.assertTrue(texto.strip(), clave)

    def test_sin_emojis(self):
        for clave, texto in MSG.items():
            for caracter in texto:
                self.assertLess(ord(caracter), 0x1F000,
                                f"{clave} lleva un emoji")

    def test_formato_y_respaldo(self):
        self.assertEqual(msg("paleta.abrir", nombre="CF_DNS"),
                         "Abrir CF_DNS")
        self.assertEqual(msg("llaves.uso", fecha="2026-11-18"),
                         "último uso: 2026-11-18")
        self.assertEqual(msg("clave.que.no.existe"), "clave.que.no.existe")

    def test_las_pantallas_usan_el_catalogo(self):
        from cofre.palette import catalogo

        class App:
            session = None
            vault = type("V", (), {"names": lambda self: [],
                                   "meta": lambda self, n: {}})()

            def lock(self): pass
            def _focus_new(self): pass
            def open_settings(self): pass
            def open_keys(self): pass
            def open_audit(self): pass
            def open_guide(self): pass
            def open_shortcuts(self): pass
            def open_health(self): pass
            def _comprobar_salud(self): pass
            query_entry = type("Q", (), {"focus_set": lambda self: None})()

        textos = [t for t, _ in catalogo(App())]
        self.assertEqual(textos[0], MSG["paleta.bloquear"])
        self.assertIn(MSG["paleta.atajos"], textos)


if __name__ == "__main__":
    unittest.main()
