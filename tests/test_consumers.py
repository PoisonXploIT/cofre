"""Pruebas de despliegue de consumidores (paso 5.6), con servidores falsos.

Lo importante del caso GitHub: el secreto viaja **cifrado** con caja sellada; el
servidor falso descifra y comprueba que el valor coincide, y que el cuerpo no
lleva el texto en claro.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.consumers import (Consumer, cifrar_para_github, deploy, deploy_github,
                             deploy_worker, parse)
from cofre.providers.http import ProviderError
from fake_github import FakeGitHub

try:
    from nacl import encoding, public
    HAY_NACL = True
except ImportError:                                    # pragma: no cover
    HAY_NACL = False


class TestParse(unittest.TestCase):
    def test_gha(self):
        c = parse("gha:sammi/repo:MI_SECRETO")
        self.assertEqual((c.kind, c.owner, c.repo, c.nombre),
                         ("gha", "sammi", "repo", "MI_SECRETO"))

    def test_gha_env(self):
        c = parse("gha-env:sammi/repo:produccion:MI_SECRETO")
        self.assertEqual((c.kind, c.entorno, c.nombre),
                         ("gha-env", "produccion", "MI_SECRETO"))

    def test_cfw(self):
        c = parse("cfw:cuenta1:mi-worker:API_KEY")
        self.assertEqual((c.kind, c.cuenta, c.script, c.nombre),
                         ("cfw", "cuenta1", "mi-worker", "API_KEY"))

    def test_exec_y_manual(self):
        self.assertEqual(parse("exec").kind, "exec")
        self.assertEqual(parse("manual:cambiarlo a mano").kind, "manual")

    def test_desconocido(self):
        with self.assertRaises(ProviderError):
            parse("otra-cosa:rara")


@unittest.skipUnless(HAY_NACL, "hace falta PyNaCl")
class TestGitHubSecrets(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGitHub()
        base = self.fake.start()
        os.environ["COFRE_GITHUB_API"] = base
        self.privada = public.PrivateKey.generate()
        # la clave publica se deriva del par; usar los bytes privados como si
        # fueran publicos es el error clasico y hace fallar el descifrado
        self.fake.clave_publica = (
            base64.b64encode(bytes(self.privada.public_key)).decode("ascii"), "key-1")

    def tearDown(self):
        self.fake.stop()
        os.environ.pop("COFRE_GITHUB_API", None)

    def test_el_secreto_viaja_cifrado(self):
        consumidor = parse("gha:sammi/repo:MI_SECRETO")
        deploy_github(consumidor, "valor-secreto", "ghp_x")
        cuerpo = json.loads(self.fake.secretos["MI_SECRETO"])
        self.assertNotIn("valor-secreto", json.dumps(cuerpo))
        self.assertEqual(cuerpo["key_id"], "key-1")
        # el servidor descifra con su clave privada y comprueba el valor
        caja = public.SealedBox(self.privada)
        claro = caja.decrypt(base64.b64decode(cuerpo["encrypted_value"]))
        self.assertEqual(claro.decode(), "valor-secreto")

    def test_lote_con_un_fallo_no_oculta_los_demas(self):
        resultados = deploy(["gha:sammi/repo:UNO", "otra-cosa:rara",
                             "manual:a mano"], "valor", github_token="ghp_x")
        estados = {etiqueta: ok for etiqueta, ok, _ in resultados}
        self.assertTrue(any(ok for ok in estados.values()))
        self.assertFalse(all(estados.values()))

    def test_sin_token_no_llama(self):
        resultados = deploy(["gha:sammi/repo:DOS"], "valor")
        self.assertFalse(resultados[0][1])
        self.assertIn("token", resultados[0][2])


class TestCloudflareWorker(unittest.TestCase):
    def test_sin_token_no_llama(self):
        resultados = deploy(["cfw:cuenta:script:API"], "valor")
        self.assertFalse(resultados[0][1])
        self.assertIn("token", resultados[0][2].lower())


if __name__ == "__main__":
    unittest.main()
