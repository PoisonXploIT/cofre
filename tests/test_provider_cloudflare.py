"""Pruebas del proveedor Cloudflare contra un servidor falso (paso 5.3).

Nunca se llama a Cloudflare real.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.providers.cloudflare import Cloudflare
from cofre.providers.http import ProviderError
from fake_cloudflare import FakeCloudflare


class TestCloudflare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeCloudflare()
        cls.base = cls.fake.start()
        os.environ["COFRE_CLOUDFLARE_API"] = cls.base
        cls.prov = Cloudflare()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()
        os.environ.pop("COFRE_CLOUDFLARE_API", None)

    def setUp(self):
        self.fake.tokens.clear()
        self.fake.fallar_verify = False
        self.fake.fallar_roll = False
        self.fake.llamadas.clear()
        self.fake.contador = 0
        self.fake.add_token("valor-bueno", "tok-1", "COFRE prueba",
                            expires_on="2026-11-23T00:00:00Z",
                            policies=[{"effect": "allow", "resources": {"x": "*"}}])

    def test_verify_ok(self):
        r = self.prov.verify("valor-bueno", {})
        self.assertTrue(r.ok)
        self.assertEqual(r.expires_at, "2026-11-23")

    def test_verify_rechaza_valor_desconocido(self):
        r = self.prov.verify("no-existe", {})
        self.assertFalse(r.ok)
        self.assertIn("token desconocido", r.detail)

    def test_verify_detecta_inactivo(self):
        self.fake.tokens["valor-bueno"]["status"] = "disabled"
        r = self.prov.verify("valor-bueno", {})
        self.assertFalse(r.ok)
        self.assertIn("disabled", r.detail)

    def test_roll_devuelve_valor_nuevo(self):
        meta = {"provider_ref": {"token_id": "tok-1"}}
        nuevo = self.prov.roll_value("tok-1", "admin-falso", meta)
        self.assertTrue(nuevo.startswith("valor-rotado-"))
        self.assertIn(("PUT", "/client/v4/user/tokens/tok-1/value"), self.fake.llamadas)
        self.assertFalse(self.prov.verify("valor-bueno", {}).ok)
        self.assertTrue(self.prov.verify(nuevo, {}).ok)

    def test_roll_con_admin_incorrecto_es_rechazado(self):
        with self.assertRaises(ProviderError):
            self.prov.roll_value("tok-1", "admin-malo", {"provider_ref": {"token_id": "tok-1"}})

    def test_roll_fallido_da_error_claro(self):
        self.fake.fallar_roll = True
        with self.assertRaises(ProviderError) as ctx:
            self.prov.roll_value("tok-1", "admin-falso", {"provider_ref": {"token_id": "tok-1"}})
        self.assertIn("roll rechazado", str(ctx.exception))

    def test_create_replacement_copia_politicas(self):
        meta = {"provider_ref": {"token_id": "tok-1"}, "rotate_every_days": 90,
                "name": "COFRE prueba"}
        valor, ref = self.prov.create_replacement(meta, "admin-falso")
        self.assertTrue(valor.startswith("valor-creado-"))
        self.assertTrue(ref["token_id"].startswith("id-nuevo-"))
        creado = self.fake.tokens[valor]
        self.assertIn("policies", creado)
        self.assertTrue(creado["name"].startswith("COFRE prueba (rotado "))

    def test_revoke_borra_el_viejo(self):
        self.prov.revoke("tok-1", "admin-falso", {})
        self.assertIsNone(self.fake.by_id("tok-1"))

    def test_no_expone_el_valor_en_los_errores(self):
        with self.assertRaises(ProviderError) as ctx:
            self.prov.roll_value("no-existe", "admin-falso",
                                 {"provider_ref": {"token_id": "no-existe"}})
        self.assertNotIn("valor-bueno", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
