"""Pruebas de unidad (paso 0.2 del plan). Rapidas, sin pendrive ni GUI.

  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.crypto import Vault
from cofre.hosts import HostsError, allows, assign, clean_host, host_matches
from cofre.paths import atomic_write
from cofre.salt import SaltMissing, get_salt
from cofre.usb import RegistryCorrupt, load_registry, usb_session_key


class TestSalt(unittest.TestCase):
    def test_se_crea_y_se_duplica_dentro_del_cofre(self):
        tmp = Path(tempfile.mkdtemp())
        vault_path = tmp / "cofre.json"
        salt = get_salt(str(vault_path), create=True)
        session = usb_session_key(_fake_key(tmp), salt)
        Vault(vault_path).init(session, salt=salt)
        data = json.loads(vault_path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("salt"), salt.hex())

    def test_sin_sal_no_se_inventa_otra(self):
        tmp = Path(tempfile.mkdtemp())
        vault_path = tmp / "cofre.json"
        vault_path.write_text(json.dumps({"wrapper": None, "entries": {}}), encoding="utf-8")
        with self.assertRaises(SaltMissing):
            get_salt(str(vault_path))


class TestHosts(unittest.TestCase):
    def test_coincidencia_estricta(self):
        self.assertTrue(host_matches("github.com", ["github.com"]))
        self.assertTrue(host_matches("gist.github.com", ["github.com"]))
        self.assertFalse(host_matches("github.com.evil.co", ["github.com"]))
        self.assertTrue(host_matches("a.b.ejemplo.com", ["*.ejemplo.com"]))

    def test_sin_asignacion_no_se_permite(self):
        tmp = Path(tempfile.mkdtemp())
        vault_path = tmp / "cofre.json"
        ok, motivo = allows(str(vault_path), "GITHUB_TOKEN", "github.com")
        self.assertFalse(ok)
        self.assertIn("no tiene ningún sitio", motivo)
        assign(str(vault_path), "GITHUB_TOKEN", ["github.com"])
        self.assertTrue(allows(str(vault_path), "GITHUB_TOKEN", "github.com")[0])
        self.assertFalse(allows(str(vault_path), "GITHUB_TOKEN", "cloudflare.com")[0])

    def test_host_invalido(self):
        with self.assertRaises(HostsError):
            clean_host("https://github.com/login")


class TestRutaPorDefecto(unittest.TestCase):
    def test_no_devuelve_la_ruta_del_repo(self):
        import os
        from cofre.paths import default_vault
        antes = os.environ.pop("COFRE_VAULT", None)
        try:
            ruta = default_vault()
            self.assertNotIn("AI", ruta.parts[:len(ruta.parts) - 1],
                             "la ruta por defecto no debe caer en el repo")
            self.assertIn("cofre", str(ruta).lower())
        finally:
            if antes is not None:
                os.environ["COFRE_VAULT"] = antes

    def test_la_variable_manda(self):
        import os
        from cofre.paths import default_vault
        antes = os.environ.get("COFRE_VAULT")
        os.environ["COFRE_VAULT"] = r"C:	mp\otro.json"
        try:
            self.assertEqual(str(default_vault()), r"C:	mp\otro.json")
        finally:
            if antes is None:
                os.environ.pop("COFRE_VAULT", None)
            else:
                os.environ["COFRE_VAULT"] = antes


class TestRegistro(unittest.TestCase):
    def test_registro_corrupto_falla_cerrado(self):
        tmp = Path(tempfile.mkdtemp())
        vault_path = tmp / "cofre.json"
        (tmp / ".cofre-sticks.json").write_text("{ roto", encoding="utf-8")
        with self.assertRaises(RegistryCorrupt):
            load_registry(str(vault_path))

    def test_registro_vacio_no_autoriza(self):
        tmp = Path(tempfile.mkdtemp())
        self.assertEqual(load_registry(str(tmp / "cofre.json")), {"sticks": {}})


class TestAtomic(unittest.TestCase):
    def test_no_deja_tmp(self):
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "x.json"
        atomic_write(target, '{"a": 1}')
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual([p.name for p in tmp.iterdir()], ["x.json"])


def _fake_key(tmp: Path) -> str:
    key = tmp / "COFRE.KEY"
    key.write_bytes(secrets.token_bytes(32))
    return str(key)


if __name__ == "__main__":
    unittest.main()
