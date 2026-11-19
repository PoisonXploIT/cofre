"""Pruebas de la GitHub App por manifest (M5, 2026-11-19).

Sin navegador y sin red: el servidor de un solo uso se prueba de verdad en
127.0.0.1 y el canje contra un servidor falso (`COFRE_GITHUB_API`).

Lo importante: que `state` se valide (CSRF), que el `pem` no se imprima y que un
código malo no se guarde.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import github_app


class TestManifest(unittest.TestCase):
    def test_lo_minimo_que_pide_github(self):
        m = github_app.manifest("cofre-sammi", "http://127.0.0.1:9/cb",
                                "https://github.com/Sammi")
        self.assertEqual(m["url"], "https://github.com/Sammi")
        self.assertEqual(m["redirect_url"], "http://127.0.0.1:9/cb")
        self.assertIs(m["public"], False)
        self.assertNotIn("hook_attributes", m, "no queremos webhook")
        self.assertEqual(m["default_permissions"],
                         {"contents": "read", "metadata": "read"})

    def test_permisos_y_descripcion(self):
        m = github_app.manifest("x", "http://127.0.0.1:9/cb",
                                "https://github.com/Sammi",
                                {"secrets": "write"}, "para desplegar")
        self.assertEqual(m["default_permissions"], {"secrets": "write"})
        self.assertEqual(m["description"], "para desplegar")

    def test_url_obligatoria(self):
        with self.assertRaises(ValueError):
            github_app.manifest("x", "http://127.0.0.1:9/cb", "no-es-una-url")


class TestServidorDeUnUso(unittest.TestCase):
    def setUp(self):
        self.manifiesto = github_app.manifest("cofre-sammi", "http://127.0.0.1/cb",
                                              "https://github.com/Sammi")
        self.servidor = github_app.Servidor(self.manifiesto)
        self.base = self.servidor.arrancar()

    def tearDown(self):
        self.servidor.parar()

    def test_la_pagina_lleva_el_manifest_y_el_state(self):
        pagina = urllib.request.urlopen(self.base, timeout=10).read().decode("utf-8")
        self.assertIn("settings/apps/new", pagina)
        self.assertIn("cofre-sammi", pagina)
        self.assertIn(self.servidor.state, pagina)

    def test_state_malo_se_rechaza_y_no_guarda_codigo(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "callback?code=abc&state=otro",
                                   timeout=10)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIsNone(self.servidor.codigo)
        self.assertIn("state", self.servidor.error)

    def test_state_bueno_guarda_el_codigo(self):
        estado = self.servidor.state
        resp = urllib.request.urlopen(
            self.base + f"callback?code=abc123&state={estado}", timeout=10)
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.servidor.codigo, "abc123")

    def test_sin_codigo_no_vale(self):
        estado = self.servidor.state
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + f"callback?state={estado}", timeout=10)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIsNone(self.servidor.codigo)

    def test_ruta_desconocida(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "otra", timeout=10)
        self.assertEqual(ctx.exception.code, 404)


class TestCanje(unittest.TestCase):
    """Contra un api.github.com falso: el pem nunca se imprime."""

    @classmethod
    def setUpClass(cls):
        cls.visto = {}

        class Manejador(BaseHTTPRequestHandler):
            def do_POST(self):                      # noqa: N802
                largo = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(largo)
                TestCanje.visto["ruta"] = self.path
                TestCanje.visto["acepta"] = self.headers.get("Accept")
                cuerpo = json.dumps({"id": 123456, "slug": "cofre-sammi",
                                     "pem": "-----BEGIN RSA PRIVATE KEY-----\nXX\n"
                                            "-----END RSA PRIVATE KEY-----\n",
                                     "webhook_secret": "no-se-usa"}).encode()
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *_a):
                pass

        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.server_close()
        cls.hilo.join(timeout=2)

    def setUp(self):
        self.base = f"http://127.0.0.1:{self.servidor.server_address[1]}"
        self.parche = mock.patch.dict(os.environ, {"COFRE_GITHUB_API": self.base})
        self.parche.start()

    def tearDown(self):
        self.parche.stop()

    def test_canjea_el_codigo_y_devuelve_id_y_pem(self):
        respuesta = github_app.canjear("abc123")
        self.assertEqual(respuesta["id"], 123456)
        self.assertIn("BEGIN RSA PRIVATE KEY", respuesta["pem"])
        self.assertEqual(TestCanje.visto["ruta"],
                         "/app-manifests/abc123/conversions")
        self.assertIn("github+json", TestCanje.visto["acepta"])

    def test_un_201_sin_pem_es_error(self):
        class Manejador(BaseHTTPRequestHandler):
            def do_POST(self):                      # noqa: N802
                cuerpo = b'{"id": 1}'
                self.send_response(201)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *_a):
                pass

        otro = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        hilo = threading.Thread(target=otro.serve_forever, daemon=True)
        hilo.start()
        try:
            with mock.patch.dict(os.environ,
                                 {"COFRE_GITHUB_API":
                                  f"http://127.0.0.1:{otro.server_address[1]}"}):
                with self.assertRaises(github_app.ProviderError):
                    github_app.canjear("abc")
        finally:
            otro.server_close()
            hilo.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
