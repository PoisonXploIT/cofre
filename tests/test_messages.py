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


class TestTrinqueteDeTextos(unittest.TestCase):
    """2026-11-18: el tope tambien para el CLI y sin subidas silenciosas."""

    def setUp(self):
        sys.path.insert(0, str(REPO / "tools"))
        import messages_probe
        self.probe = messages_probe
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-tope-"))
        self.ruta = self.tmp / "messages_top.txt"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lee_el_formato_viejo(self):
        self.ruta.write_text("266\n", encoding="utf-8")
        topes, notas = self.probe.leer_topes(self.ruta)
        self.assertEqual(topes, {"gui": 266})
        self.assertEqual(notas, [])

    def test_lee_las_dos_caras_y_las_notas(self):
        self.ruta.write_text("gui 265\ncli 279\n# motivo\n", encoding="utf-8")
        topes, notas = self.probe.leer_topes(self.ruta)
        self.assertEqual(topes, {"gui": 265, "cli": 279})
        self.assertEqual(notas, ["# motivo"])

    def test_ida_y_vuelta(self):
        self.probe.guardar_topes({"gui": 1, "cli": 2}, ["# x"], self.ruta)
        topes, notas = self.probe.leer_topes(self.ruta)
        self.assertEqual(topes, {"gui": 1, "cli": 2})
        self.assertEqual(notas, ["# x"])

    def test_baja_sola(self):
        self.assertEqual(self.probe.resolver("gui", 10, 12, ""), (10, "bajado"))
        self.assertEqual(self.probe.resolver("cli", 10, 10, ""), (10, "igual"))

    def test_sube_solo_con_motivo(self):
        self.assertEqual(self.probe.resolver("cli", 12, 10, ""), (10, "fallo"))
        self.assertEqual(self.probe.resolver("cli", 12, 10, "  "), (10, "fallo"))
        self.assertEqual(self.probe.resolver("cli", 12, 10, "nuevo comando"),
                         (12, "subido"))

    def test_ningun_modulo_de_tk_se_queda_fuera(self):
        # 2026-11-19: al partir gui.py, gui_puente.py no estaba en la lista y sus
        # textos dejaron de contar: el trinquete bajaba solo. Esto lo impide.
        self.assertEqual(self.probe._modulos_sin_vigilar(), [])

    def test_el_fichero_real_tiene_las_dos_caras(self):
        topes, _notas = self.probe.leer_topes(REPO / "tools" / "messages_top.txt")
        self.assertIn("gui", topes)
        self.assertIn("cli", topes)
