"""Pruebas del proveedor generico (paso 5.5, 2026-11-18).

Lo que importa: que Salud sepa comprobar Tavily, OpenAI, Hugging Face y cualquier
API configurada a mano, sin guardar ni mostrar el valor, y que un 401 sea
"invalida" de verdad.
"""

from __future__ import annotations

import secrets
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import health
from cofre.providers import REGISTRY, get
from cofre.providers.generic import CATALOGO, GENERICO, Generic, conocido
from cofre.store import open_any
from cofre.v2 import VaultV2, new_usb_slot


class TestCatalogo(unittest.TestCase):
    def test_los_conocidos_estan_registrados(self):
        for nombre in CATALOGO:
            self.assertTrue(conocido(nombre), nombre)
            self.assertIn(nombre, REGISTRY)
            self.assertIsInstance(get(nombre), Generic)
            self.assertFalse(get(nombre).can_auto_rotate)

    def test_generico_sin_configurar_lo_dice(self):
        resultado = GENERICO.verify("valor", {})
        self.assertFalse(resultado.ok)
        self.assertIn("url", resultado.detail)

    def test_manual_url_del_catalogo(self):
        self.assertTrue(GENERICO.manual_url({"provider": "tavily"}) is not None)
        self.assertTrue(get("tavily").manual_url({}).startswith("https://"))

    def test_no_rota_solo(self):
        from cofre.providers import ProviderError
        with self.assertRaises(ProviderError):
            get("tavily").create_replacement({}, "admin")
        with self.assertRaises(ProviderError):
            get("tavily").roll_value("id", "admin", {})


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.cfg = {"url": "http://servidor-falso/quien", "header": "Authorization",
                    "prefix": "Bearer ", "ok": [200]}

    def _con(self, status, cuerpo, cfg=None):
        with mock.patch("cofre.providers.generic.request",
                        return_value=(status, {}, cuerpo)):
            return GENERICO.verify("token-de-prueba", {"verify": cfg or self.cfg})

    def test_200_es_valido(self):
        resultado = self._con(200, {"ok": True})
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.status, "active")

    def test_401_es_invalida(self):
        resultado = self._con(401, {"error": "no"})
        self.assertFalse(resultado.ok)
        self.assertIn("401", resultado.detail)

    def test_la_peticion_lleva_la_cabecera_y_no_el_valor_en_la_url(self):
        with mock.patch("cofre.providers.generic.request",
                        return_value=(200, {}, {})) as falso:
            GENERICO.verify("token-de-prueba", {"verify": self.cfg})
        _metodo, url, kwargs = falso.call_args[0][0], falso.call_args[0][1], \
            falso.call_args[1]
        self.assertNotIn("token-de-prueba", url)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token-de-prueba")

    def test_json_ok_y_caducidad(self):
        cfg = dict(self.cfg, json_ok="cuenta.nombre", expires="cuenta.caduca")
        resultado = self._con(200, {"cuenta": {"nombre": "sammi",
                                               "caduca": "2027-01-02T00:00:00Z"}},
                              cfg)
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.expires_at, "2027-01-02")

    def test_json_ok_que_no_esta(self):
        cfg = dict(self.cfg, json_ok="cuenta.nombre")
        resultado = self._con(200, {"cuenta": {}}, cfg)
        self.assertFalse(resultado.ok)
        self.assertIn("cuenta.nombre", resultado.detail)

    def test_varias_codigos_validos(self):
        cfg = dict(self.cfg, ok=[200, 204])
        self.assertTrue(self._con(204, {}, cfg).ok)
        self.assertFalse(self._con(202, {}, cfg).ok)

    def test_el_catalogo_no_necesita_configuracion(self):
        with mock.patch("cofre.providers.generic.request",
                        return_value=(200, {}, {"name": "sammi"})) as falso:
            resultado = get("huggingface").verify("hf_token", {})
        self.assertTrue(resultado.ok)
        cabeceras = falso.call_args[1]["headers"]
        self.assertEqual(list(cabeceras), ["Authorization"])


class TestSaludConGenerico(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-generic-"))
        self.vault = self.tmp / "cofre.json"
        master = secrets.token_bytes(32)
        v2 = VaultV2(self.vault)
        datos = v2.create(master, new_usb_slot(master, secrets.token_bytes(32), 1,
                                              "t", ""))
        v2.put(datos, master, "TAVILY_API_KEY", "tvly-largo-de-prueba", [], [],
               kind="api_token")
        v2.put(datos, master, "OTRO_TOKEN", "segundo-valor-largo", [], [],
               kind="api_token")
        v2.save(datos)
        self.store = open_any(self.vault)
        self.store._data = self.store._vault.load()
        self.store.master = master
        idx = self.store.index(self.store._data, master)
        idx["entries"]["TAVILY_API_KEY"]["provider"] = "tavily"
        idx["entries"]["OTRO_TOKEN"]["verify"] = {"url": "http://servidor-falso/x"}
        self.store._write_index(self.store._data, master, idx)
        self.store.save(self.store._data)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_salud_verifica_el_catalogo_y_lo_configurado(self):
        with mock.patch("cofre.providers.generic.request", return_value=(200, {}, {})):
            resultados = {r.nombre: r for r in health.revisar(self.store,
                                                              self.store.master)}
        self.assertEqual(resultados["TAVILY_API_KEY"].estado, "ok")
        self.assertEqual(resultados["OTRO_TOKEN"].estado, "ok")

    def test_salud_detecta_el_token_muerto(self):
        with mock.patch("cofre.providers.generic.request", return_value=(401, {}, {})):
            resultados = {r.nombre: r for r in health.revisar(self.store,
                                                              self.store.master)}
        self.assertEqual(resultados["TAVILY_API_KEY"].estado, "invalida")
        self.assertNotIn("tvly-largo-de-prueba", resultados["TAVILY_API_KEY"].detalle)


class TestContraServidorReal(unittest.TestCase):
    """Sin mocks: urllib de verdad contra un servidor local (2026-11-18)."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading

        class Manejador(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/vivo" else 401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"name": "sammi", "caduca": "2027-03-04T00:00"}')

            def log_message(self, *_a):
                pass

        cls.servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.servidor.server_close()
        cls.hilo.join(timeout=2)

    def setUp(self):
        import os
        os.environ["COFRE_GENERIC_BASE"] = self.base

    def tearDown(self):
        import os
        os.environ.pop("COFRE_GENERIC_BASE", None)

    def test_200_ok_por_la_red(self):
        cfg = {"url": "https://sitio-de-verdad.example/vivo", "json_ok": "name",
               "expires": "caduca"}
        resultado = GENERICO.verify("token", {"verify": cfg})
        self.assertTrue(resultado.ok, resultado.detail)
        self.assertEqual(resultado.expires_at, "2027-03-04")

    def test_401_invalida_por_la_red(self):
        cfg = {"url": "https://sitio-de-verdad.example/muerto"}
        resultado = GENERICO.verify("token", {"verify": cfg})
        self.assertFalse(resultado.ok)
        self.assertIn("401", resultado.detail)

    def test_sin_servidor_lo_dice_sin_el_valor(self):
        import os
        os.environ["COFRE_GENERIC_BASE"] = "http://127.0.0.1:9"
        cfg = {"url": "https://sitio-de-verdad.example/vivo"}
        resultado = GENERICO.verify("token-que-no-sale", {"verify": cfg})
        self.assertFalse(resultado.ok)
        self.assertNotIn("token-que-no-sale", resultado.detail)


if __name__ == "__main__":
    unittest.main()
