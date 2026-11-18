"""Pruebas del aviso del navegador (paso 4.6, 2026-11-18).

Lo que se comprueba: `match` dice que secretos valen para el host de la pestana
sin dar valores, y `assign` anade el host exacto **solo si la GUI lo confirma**
(una pagina no puede autorizarse sola). El registro no lleva valores.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import audit, bridge_ops


class FakeVault:
    def __init__(self):
        self.datos = {
            "CF_DNS": {"type": "api_token", "tags": ["cloudflare"],
                       "urls": ["dash.cloudflare.com"]},
            "BANCO": {"type": "password", "tags": [],
                      "urls": ["*.banco.example"]},
            "OTRO": {"type": "api_token", "tags": [], "urls": ["github.com"]},
        }

    def refresh(self):
        return None

    def names(self):
        return list(self.datos)

    def meta(self, nombre):
        return dict(self.datos.get(nombre) or {})

    def urls(self, nombre):
        return list((self.datos.get(nombre) or {}).get("urls") or [])

    def set_urls(self, nombre, urls):
        self.datos[nombre]["urls"] = list(urls)

    def is_v2(self):
        return True


class FakeApp:
    def __init__(self, respuesta="grant"):
        self.vault = FakeVault()
        self.vault_path = Path(tempfile.mkdtemp(prefix="cofre-popup-")) / "cofre.json"
        self.gate = "usb"
        self.serial = 1
        self.session = b"x"
        self.respuesta = respuesta
        self.llamadas = []

    def request_confirm(self, who, what, contexto=None):
        self.llamadas.append((who, what, contexto))
        return self.respuesta


class TestMatch(unittest.TestCase):
    def test_devuelve_solo_los_que_encajan(self):
        app = FakeApp()
        r = bridge_ops.dispatch(app, {"type": "match", "domain": "dash.cloudflare.com"})
        self.assertTrue(r["ok"])
        self.assertEqual([i["name"] for i in r["items"]], ["CF_DNS"])
        self.assertTrue(r["items"][0]["exact"])

    def test_comodin_cuenta_como_sitio_no_como_exacto(self):
        app = FakeApp()
        r = bridge_ops.dispatch(app, {"type": "match", "domain": "www.banco.example"})
        self.assertEqual([i["name"] for i in r["items"]], ["BANCO"])
        self.assertFalse(r["items"][0]["exact"])

    def test_ninguno_y_sin_valores(self):
        app = FakeApp()
        r = bridge_ops.dispatch(app, {"type": "match", "domain": "ejemplo.com"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["items"], [])
        self.assertNotIn("value", json.dumps(r))

    def test_sin_dominio_no_adivina(self):
        app = FakeApp()
        r = bridge_ops.dispatch(app, {"type": "match"})
        self.assertFalse(r["ok"])

    def test_sin_sesion_no_hay_nada(self):
        app = FakeApp()
        app.session = None
        self.assertFalse(bridge_ops.dispatch(app, {"type": "match",
                                                   "domain": "github.com"})["ok"])


class TestAssign(unittest.TestCase):
    def test_con_confirmacion_anade_el_host(self):
        app = FakeApp()
        r = bridge_ops.dispatch(app, {"type": "assign", "name": "CF_DNS",
                                      "domain": "api.cloudflare.com"})
        self.assertTrue(r["ok"] and r["changed"])
        self.assertEqual(app.vault.urls("CF_DNS"),
                         ["dash.cloudflare.com", "api.cloudflare.com"])
        self.assertEqual(app.llamadas[0][2], "assign:CF_DNS:api.cloudflare.com")
        eventos = [e for e in audit._events(app.vault_path)
                   if e.get("ev") == "host-assign"]
        self.assertTrue(eventos)
        self.assertIn("api.cloudflare.com", eventos[0]["detail"])

    def test_negado_no_toca_nada(self):
        app = FakeApp(respuesta="deny")
        r = bridge_ops.dispatch(app, {"type": "assign", "name": "CF_DNS",
                                      "domain": "api.cloudflare.com"})
        self.assertFalse(r["ok"])
        self.assertEqual(app.vault.urls("CF_DNS"), ["dash.cloudflare.com"])

    def test_ya_asignado_no_pregunta(self):
        app = FakeApp()
        r = bridge_ops.dispatch(app, {"type": "assign", "name": "CF_DNS",
                                      "domain": "dash.cloudflare.com"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["changed"])
        self.assertEqual(app.llamadas, [])

    def test_no_acepta_comodines_ni_rutas(self):
        for raro in ("*.ejemplo.com", "ejemplo.com/x", "http://ejemplo.com",
                     "ejemplo.com:8443", ""):
            with self.subTest(dominio=raro):
                app = FakeApp()
                r = bridge_ops.dispatch(app, {"type": "assign", "name": "CF_DNS",
                                              "domain": raro})
                self.assertFalse(r["ok"])
                self.assertEqual(app.vault.urls("CF_DNS"), ["dash.cloudflare.com"])

    def test_secreto_que_no_existe(self):
        app = FakeApp()
        r = bridge_ops.dispatch(app, {"type": "assign", "name": "NO_HAY",
                                      "domain": "ejemplo.com"})
        self.assertFalse(r["ok"])
        self.assertEqual(app.llamadas, [])


class TestSave(unittest.TestCase):
    """4.8: guardar el sitio desde el navegador abre la hoja de la GUI."""

    def test_abre_la_hoja_con_el_sitio_y_el_usuario(self):
        app = FakeApp()
        app.llamadas_ui = []
        app.ui_call = lambda fn, *a, **k: app.llamadas_ui.append((fn, a, k))
        abierto = []
        app.open_new_for_site = lambda sitio, usuario="": abierto.append((sitio, usuario))
        r = bridge_ops.dispatch(app, {"type": "save", "domain": "banco.example",
                                      "username": "sammi"})
        self.assertTrue(r["ok"] and r["opened"])
        self.assertEqual(len(app.llamadas_ui), 1)
        # la GUI lo hara en su hilo; aqui se ejecuta el paso encolado
        app.llamadas_ui[0][0](*app.llamadas_ui[0][1], **app.llamadas_ui[0][2])
        self.assertEqual(abierto, [("banco.example", "sammi")])

    def test_sin_ventana_que_abra_la_hoja(self):
        app = FakeApp()          # FakeApp no tiene open_new_for_site
        r = bridge_ops.dispatch(app, {"type": "save", "domain": "banco.example"})
        self.assertFalse(r["ok"])

    def test_host_raro_no_abre_nada(self):
        app = FakeApp()
        app.ui_call = lambda *a, **k: self.fail("no deberia abrir la hoja")
        app.open_new_for_site = lambda *a, **k: None
        for raro in ("", "a/b", "a?b", "a:b", "*.ejemplo.com"):
            with self.subTest(dominio=raro):
                r = bridge_ops.dispatch(app, {"type": "save", "domain": raro})
                self.assertFalse(r["ok"])

    def test_la_respuesta_no_lleva_valores(self):
        app = FakeApp()
        app.ui_call = lambda *a, **k: None
        app.open_new_for_site = lambda *a, **k: None
        r = bridge_ops.dispatch(app, {"type": "save", "domain": "banco.example"})
        self.assertNotIn("value", json.dumps(r))


if __name__ == "__main__":
    unittest.main()
