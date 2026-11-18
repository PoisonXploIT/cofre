"""Pruebas del catalogo de la paleta (paso 6.4), sin abrir ventanas."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.palette import catalogo, filtrar


class FakeQuery:
    def focus_set(self):
        return None


class FakeVault:
    def names(self):
        return ["CF_DNS", "GH_PAT", "NOTA"]

    def meta(self, nombre):
        return {
            "CF_DNS": {"provider": "cloudflare"},
            "GH_PAT": {"provider": "github"},
            "NOTA": {},
        }.get(nombre, {})


class FakeApp:
    def __init__(self, session=True):
        self.session = b"x" * 32 if session else None
        self.vault = FakeVault()
        self.selected = None
        self.query_entry = FakeQuery()
        self.llamadas = []

    def lock(self):
        self.llamadas.append("lock")

    def _focus_new(self):
        self.llamadas.append("nuevo")

    def open_settings(self):
        self.llamadas.append("ajustes")

    def open_keys(self):
        self.llamadas.append("llaves")

    def open_audit(self):
        self.llamadas.append("registro")

    def open_guide(self):
        self.llamadas.append("guia")

    def open_shortcuts(self):
        self.llamadas.append("atajos")

    def open_health(self):
        self.llamadas.append("salud")

    def _comprobar_salud(self):
        self.llamadas.append("comprobar")

    def select(self, nombre):
        self.selected = nombre
        self.llamadas.append("abrir:" + nombre)

    def copy_to_clipboard(self):
        self.llamadas.append("copiar:" + str(self.selected))

    def _rotar_para_paleta(self, nombre):
        self.llamadas.append("rotar:" + nombre)


class TestCatalogo(unittest.TestCase):
    def test_acciones_y_secretos(self):
        app = FakeApp()
        items = catalogo(app)
        textos = [texto for texto, _accion in items]
        self.assertIn("Bloquear el cofre", textos)
        self.assertIn("Comprobar salud de las credenciales", textos)
        self.assertIn("Abrir CF_DNS", textos)
        self.assertIn("Copiar CF_DNS", textos)
        self.assertIn("Rotar CF_DNS", textos)
        self.assertNotIn("Rotar GH_PAT", textos)
        self.assertIn("Abrir NOTA", textos)
        self.assertIn("Atajos de teclado", textos)

    def test_filtro_por_palabra(self):
        items = catalogo(FakeApp())
        self.assertEqual([t for t, _ in filtrar(items, "rotar")],
                         ["Rotar CF_DNS"])
        self.assertEqual([t for t, _ in filtrar(items, "copiar cf_dns")],
                         ["Copiar CF_DNS"])
        self.assertTrue(filtrar(items, "SALUD"))
        self.assertEqual(filtrar(items, "no existe"), [])

    def test_ejecutar_abrir(self):
        app = FakeApp()
        items = dict(catalogo(app))
        items["Abrir CF_DNS"]()
        self.assertEqual(app.selected, "CF_DNS")

    def test_ejecutar_copiar_y_rotar(self):
        app = FakeApp()
        items = dict(catalogo(app))
        items["Copiar CF_DNS"]()
        self.assertIn("copiar:CF_DNS", app.llamadas)
        items["Rotar CF_DNS"]()
        self.assertIn("rotar:CF_DNS", app.llamadas)

    def test_bloqueado_no_muestra_secretos(self):
        textos = [texto for texto, _ in catalogo(FakeApp(session=False))]
        self.assertFalse(any(texto.startswith("Abrir ") for texto in textos))
        self.assertIn("Bloquear el cofre", textos)


if __name__ == "__main__":
    unittest.main()
