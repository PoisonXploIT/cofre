"""Pruebas del proveedor GitHub contra un servidor falso (paso 5.4).

Nunca se llama a GitHub real.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.providers.github import GitHub, app_jwt, installation_token
from cofre.providers.http import ProviderError
from fake_github import FakeGitHub

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    HAY_CRYPTO = True
except ImportError:                                   # pragma: no cover
    HAY_CRYPTO = False


class TestGitHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeGitHub()
        base = cls.fake.start()
        os.environ["COFRE_GITHUB_API"] = base
        cls.prov = GitHub()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()
        os.environ.pop("COFRE_GITHUB_API", None)

    def setUp(self):
        self.fake.llamadas.clear()
        self.fake.revocados.clear()

    def test_verify_valido(self):
        r = self.prov.verify("ghp_bueno", {})
        self.assertTrue(r.ok)
        self.assertIn("sammi", r.detail)
        self.assertIn("repo", r.detail)

    def test_verify_rechaza_token_malo(self):
        r = self.prov.verify("ghp_malo", {})
        self.assertFalse(r.ok)
        self.assertIn("401", r.detail)

    def test_no_permite_rotar_por_api(self):
        with self.assertRaises(ProviderError) as ctx:
            self.prov.create_replacement({}, "x")
        self.assertIn("crea el token en", str(ctx.exception).lower())
        self.assertIn("settings/tokens", self.prov.manual_url({}))

    def test_url_fine_grained(self):
        url = self.prov.manual_url({"provider_ref": {"fine_grained": True}})
        self.assertIn("personal-access-tokens", url)

    def test_revoke_fine_grained(self):
        self.prov.revoke("abc123", "ghp_bueno", {})
        self.assertIn("abc123", self.fake.revocados)

    def test_revoke_sin_id_falla(self):
        with self.assertRaises(ProviderError):
            self.prov.revoke("", "ghp_bueno", {})


@unittest.skipUnless(HAY_CRYPTO, "hace falta cryptography")
class TestGitHubApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeGitHub()
        base = cls.fake.start()
        os.environ["COFRE_GITHUB_API"] = base
        cls.privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pem = cls.privada.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()).decode()
        cls.pem_publica = cls.privada.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo)

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()
        os.environ.pop("COFRE_GITHUB_API", None)

    def test_jwt_estructura_y_firma(self):
        token = app_jwt("123", self.pem)
        partes = token.split(".")
        self.assertEqual(len(partes), 3)
        import base64
        import json
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        cabecera = json.loads(base64.urlsafe_b64decode(partes[0] + "=="))
        self.assertEqual(cabecera["alg"], "RS256")
        cuerpo = json.loads(base64.urlsafe_b64decode(partes[1] + "=="))
        self.assertEqual(cuerpo["iss"], "123")
        firma = base64.urlsafe_b64decode(partes[2] + "==")
        self.pem_publica  # la clave publica existe
        self.privada.public_key().verify(
            firma, f"{partes[0]}.{partes[1]}".encode(), padding.PKCS1v15(), hashes.SHA256())

    def test_token_de_instalacion(self):
        token = app_jwt("123", self.pem)
        self.fake.app_jwt_esperado = token
        valor, caduca = installation_token(token, "12345")
        self.assertEqual(valor, "ghs_instalacion")
        self.assertTrue(caduca.startswith("2026-"))

    def test_token_de_instalacion_con_jwt_malo(self):
        self.fake.app_jwt_esperado = "otro"
        with self.assertRaises(ProviderError):
            installation_token("no-es-un-jwt", "12345")


if __name__ == "__main__":
    unittest.main()
