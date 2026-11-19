"""Pruebas del candado en exec/run y del filtro de salida (D20, 2026-11-19).

Los tres huecos que vio el agente:

  1. `exec`/`run` dejaban que el programa hijo imprimiera el valor (el agente lo
     lee). Ahora, con COFRE_AGENT=1, se pide confirmación en la ventana cada vez y
     la salida se filtra: el valor (y sus formas en base64, hex o URL) sale como
     `[REDACTADO]`.
  2. git podía dar el valor con `git credential fill` sin preguntar durante los 5
     minutos. Ahora, si quien pide es un agente, se confirma siempre y el diálogo lo
     dice.
  3. `field` se revisó: solo escribe (pide el valor a ciegas), no muestra nada.

Lo que NO hace, y conviene tenerlo escrito: un agente hostil puede quitarse la
variable o transformar el valor (minúsculas, inverso, ofuscado). Esto frena el
descuido, no a un atacante; la barrera de verdad son las confirmaciones en pantalla.
"""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import bridge_ops, redact   # noqa: E402

VALOR = "s3cr3t-ABC_123"


class TestRedaccion(unittest.TestCase):
    def _formas(self):
        crudo = VALOR.encode("utf-8")
        signos = "".join(chr(b) if chr(b).isalnum() else "%%%02X" % b for b in crudo)
        return {
            "tal cual": VALOR,
            "base64": base64.b64encode(crudo).decode(),
            "base64 sin relleno": base64.b64encode(crudo).decode().rstrip("="),
            "hex": crudo.hex(),
            "hex mayusculas": crudo.hex().upper(),
            "url signos": signos,
            "url todo": "".join("%%%02X" % b for b in crudo),
        }

    def test_tapa_todas_las_formas(self):
        for nombre, forma in self._formas().items():
            with self.subTest(nombre=nombre):
                salida = redact.redactar(
                    f"antes {forma} despues", {"SECRETO": VALOR})
                self.assertNotIn(forma, salida)
                self.assertIn(redact.MARCA, salida)

    def test_no_toca_lo_que_no_es_el_valor(self):
        self.assertEqual(redact.redactar("hola mundo", {"S": VALOR}), "hola mundo")

    def test_varias_valores(self):
        texto = redact.redactar("uno y dos", {"A": "uno", "B": "dos"})
        self.assertEqual(texto, f"{redact.MARCA} y {redact.MARCA}")

    def test_vacio_no_rompe(self):
        self.assertEqual(redact.redactar("", {"S": VALOR}), "")
        self.assertEqual(redact.redactar("x", {"S": ""}), "x")

    def test_comando_visible(self):
        self.assertEqual(redact.comando_visible(["npm", "start"]), "npm start")


class FalsoApp:
    session = b"x"
    gate = "usb"
    serial = 1
    vault_path = Path("C:/tmp/cofre.json")

    def __init__(self, respuesta="grant"):
        self.respuesta = respuesta
        self.llamadas = []

    def request_confirm(self, who, what, contexto=None, cachear=True):
        self.llamadas.append({"who": who, "what": what, "contexto": contexto,
                              "cachear": cachear})
        return self.respuesta


class TestConfirmacionDeExec(unittest.TestCase):
    def test_pide_confirmacion_sin_cache_y_ensena_el_comando(self):
        app = FalsoApp()
        r = bridge_ops.dispatch(app, {"type": "exec-confirm", "agent": True,
                                      "command": "python -c print(1)",
                                      "secrets": ["TAVILY_API_KEY"]})
        self.assertTrue(r["ok"] and r["allowed"])
        llamada = app.llamadas[0]
        self.assertFalse(llamada["cachear"], "no puede usar el permiso de 5 minutos")
        self.assertIn("python -c", llamada["what"])
        self.assertIn("TAVILY_API_KEY", llamada["what"])
        self.assertIn("agente", llamada["who"])

    def test_denegado(self):
        app = FalsoApp("deny")
        r = bridge_ops.dispatch(app, {"type": "exec-confirm",
                                      "command": "dir", "secrets": ["X"]})
        self.assertFalse(r["allowed"])

    def test_sin_comando_no_pregunta(self):
        app = FalsoApp()
        self.assertFalse(bridge_ops.dispatch(app, {"type": "exec-confirm"})["ok"])
        self.assertEqual(app.llamadas, [])


class TestGitDeAgente(unittest.TestCase):
    def _app(self):
        app = FalsoApp()
        app.vault = SimpleNamespace(
            refresh=lambda: None, names=lambda: ["TOKEN"],
            meta=lambda n: {"type": "api_token", "urls": ["github.com"],
                            "policy": {"git": True}},
            is_v2=lambda: True, get=lambda *a, **k: VALOR,
            _v2store=lambda: SimpleNamespace(master=None))
        return app

    def test_agente_se_confirma_siempre(self):
        from cofre import git_cred
        app = self._app()
        with mock.patch.object(git_cred, "permitido", return_value=(True, "")), \
                mock.patch.object(git_cred, "buscar",
                                  return_value=("TOKEN", {"type": "api_token"})), \
                mock.patch.object(git_cred, "usuario", return_value="yo"):
            r = bridge_ops.dispatch(app, {"type": "git", "host": "github.com",
                                          "agent": True,
                                          "_client": {"pid": 1}})
        self.assertTrue(r.get("ok"), r)
        llamada = app.llamadas[0]
        self.assertFalse(llamada["cachear"])
        self.assertIn("agente", llamada["who"])

    def test_humano_mantiene_el_permiso(self):
        from cofre import git_cred
        app = self._app()
        with mock.patch.object(git_cred, "permitido", return_value=(True, "")), \
                mock.patch.object(git_cred, "buscar",
                                  return_value=("TOKEN", {"type": "api_token"})), \
                mock.patch.object(git_cred, "usuario", return_value="yo"):
            bridge_ops.dispatch(app, {"type": "git", "host": "github.com",
                                      "_client": {"pid": 1}})
        self.assertTrue(app.llamadas[0]["cachear"])


class TestAyudanteMarcaAgente(unittest.TestCase):
    def test_el_ayudante_envia_la_marca(self):
        import io
        import os
        from cofre import git_helper
        enviado = {}

        def falso_forward(mensaje, reply_timeout_ms=0):
            enviado.update(mensaje)
            return {"ok": True, "username": "yo", "password": VALOR}

        with mock.patch.dict(os.environ, {"COFRE_AGENT": "1"}), \
                mock.patch.object(git_helper, "forward", falso_forward), \
                mock.patch("sys.stdin", io.StringIO("protocol=https\nhost=github.com\n\n")), \
                mock.patch("sys.stdout", io.StringIO()) as salida:
            git_helper.main(["get"])
        self.assertTrue(enviado.get("agent"))
        self.assertIn("password=", salida.getvalue())

    def test_sin_la_variable_no_lo_marca(self):
        import io
        import os
        from cofre import git_helper
        enviado = {}

        def falso_forward(mensaje, reply_timeout_ms=0):
            enviado.update(mensaje)
            return {"ok": True, "username": "yo", "password": VALOR}

        entorno = dict(os.environ)
        entorno.pop("COFRE_AGENT", None)
        with mock.patch.dict(os.environ, entorno, clear=True), \
                mock.patch.object(git_helper, "forward", falso_forward), \
                mock.patch("sys.stdin", io.StringIO("protocol=https\nhost=github.com\n\n")), \
                mock.patch("sys.stdout", io.StringIO()):
            git_helper.main(["get"])
        self.assertFalse(enviado.get("agent"))


if __name__ == "__main__":
    unittest.main()
