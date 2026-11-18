"""Pruebas de .cofre-env.json / run y describe (paso 7.1 y 7.3)."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import projectenv
from cofre.crypto import Vault
from cofre.gate import material_for
from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_usb_slot


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-proj-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        self.master = secrets.token_bytes(32)
        self.serial = volume_serial(str(self.tmp.drive) + "\\")
        v2 = VaultV2(self.vault)
        datos = v2.create(self.master, new_usb_slot(
            self.master, self.llave.read_bytes(), self.serial, "t", ""))
        v2.put(datos, self.master, "TAVILY", "tvly-x", [], ["app.example"],
               kind="api_key")
        v2.put(datos, self.master, "POSTGRES", "pw", [], [], kind="api_key")
        v2.put(datos, self.master, "GITHUB_APP", "-----PEM-----", ["admin"], [],
               kind="private_key")
        v2.put(datos, self.master, "SENSIBLE", "priv", ["admin"], [],
               kind="private_key")
        contenido = v2.blob(datos, self.master, "POSTGRES")
        contenido["fields"] = {"username": "sammi"}
        v2.set_blob(datos, self.master, "POSTGRES", contenido)
        idx = v2.index(datos, self.master)
        idx["entries"]["GITHUB_APP"]["app_id"] = "123"
        idx["entries"]["GITHUB_APP"]["installation_id"] = "456"
        idx["entries"]["GITHUB_APP"]["type"] = "private_key"
        idx["entries"]["SENSIBLE"]["type"] = "private_key"
        v2._write_index(datos, self.master, idx)
        v2.save(datos)
        register_stick(str(self.vault), self.serial,
                       str(self.tmp.drive) + "\\")
        self.proyecto = self.tmp / "proyecto"
        (self.proyecto / "sub").mkdir(parents=True)
        (self.proyecto / ".cofre-env.json").write_text(json.dumps({
            "TAVILY_API_KEY": "cofre://TAVILY",
            "DB_USER": "cofre://POSTGRES#username",
        }), encoding="utf-8")
        (self.proyecto / "app.json").write_text(json.dumps({
            "GITHUB_TOKEN": "cofre://GITHUB_APP@app",
        }), encoding="utf-8")
        self.cmd = [sys.executable, "-m", "cofre.cli", "--gate", "usb",
                    "--stick", str(self.llave), "--vault", str(self.vault)]
        self.env = dict(os.environ, COFRE_VAULT=str(self.vault),
                        PYTHONPATH=str(REPO))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def abrir(self):
        material = material_for("usb", str(self.vault), stick=str(self.llave))
        return Vault(self.vault).bind_material(material)


class TestModulo(Base):
    def test_buscar_hacia_arriba_y_cargar(self):
        self.assertEqual(projectenv.buscar(self.proyecto / "sub"),
                         self.proyecto / ".cofre-env.json")
        refs = projectenv.cargar(self.proyecto / ".cofre-env.json")
        self.assertEqual([r.destino for r in refs],
                         ["TAVILY_API_KEY", "DB_USER"])
        self.assertEqual(refs[1].campo, "username")
        app_refs = projectenv.cargar(self.proyecto / "app.json")
        self.assertTrue(app_refs[0].app)

    def test_un_valor_literal_se_rechaza(self):
        ruta = self.tmp / "malo.json"
        ruta.write_text('{"X": "valor-en-claro"}', encoding="utf-8")
        with self.assertRaises(projectenv.ProjectEnvError):
            projectenv.cargar(ruta)

    def test_revisar_y_resolver(self):
        vault = self.abrir()
        refs = projectenv.cargar(self.proyecto / ".cofre-env.json")
        estados = {e["ref"].destino: e["estado"]
                   for e in projectenv.revisar(vault, None, refs)}
        self.assertEqual(estados["TAVILY_API_KEY"], "ok")
        self.assertEqual(estados["DB_USER"], "ok")
        env = projectenv.resolver(vault, None, refs)
        self.assertEqual(env["TAVILY_API_KEY"], "tvly-x")
        self.assertEqual(env["DB_USER"], "sammi")
        self.assertEqual(projectenv.sensibles(vault, refs), [])
        app_refs = projectenv.cargar(self.proyecto / "app.json")
        with mock.patch("cofre.providers.github.app_jwt", return_value="jwt"),                 mock.patch("cofre.providers.github.installation_token",
                           return_value=("token-app", "2026-11-18T20:00:00Z")):
            app_env = projectenv.resolver(vault, None, app_refs)
        self.assertEqual(app_env["GITHUB_TOKEN"], "token-app")
        self.assertEqual(projectenv.sensibles(vault, app_refs), ["GITHUB_TOKEN"])

    def test_politica_deniega_private_key_sin_app(self):
        ruta = self.tmp / "sensible.json"
        ruta.write_text('{"PRIV": "cofre://SENSIBLE"}', encoding="utf-8")
        vault = self.abrir()
        refs = projectenv.cargar(ruta)
        estados = projectenv.revisar(vault, None, refs)
        self.assertEqual(estados[0]["estado"], "politica")


class TestCli(Base):
    def correr(self, *args, cwd=None):
        return subprocess.run(self.cmd + list(args), capture_output=True,
                              text=True, env=self.env, cwd=str(cwd or self.proyecto),
                              timeout=180)

    def test_check_sin_valores(self):
        r = self.correr("run", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK    TAVILY_API_KEY", r.stdout)
        self.assertIn("DB_USER", r.stdout)
        self.assertNotIn("tvly-x", r.stdout + r.stderr)
        self.assertNotIn("sammi", r.stdout + r.stderr)

    def test_run_ejecuta_con_el_entorno(self):
        codigo = ("import os,sys;"
                  "sys.exit(0 if os.environ.get('TAVILY_API_KEY')=='tvly-x' "
                  "and os.environ.get('DB_USER')=='sammi' else 3)")
        r = self.correr("run", "--si", "--", sys.executable, "-c", codigo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("tvly-x", r.stdout + r.stderr)

    def test_describe_sin_valores(self):
        r = self.correr("describe")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        datos = json.loads(r.stdout)
        nombres = {d["name"] for d in datos}
        self.assertIn("TAVILY", nombres)
        self.assertNotIn("tvly-x", r.stdout)
        self.assertTrue(all("value" not in d for d in datos))

    def test_describe_minimal_sin_infraestructura(self):
        r = self.correr("describe", "--minimal")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        datos = json.loads(r.stdout)
        self.assertTrue(datos)
        for entrada in datos:
            self.assertEqual(set(entrada), {"name", "type", "health"})
        self.assertNotIn("app.example", r.stdout)
        self.assertNotIn("urls", r.stdout)


if __name__ == "__main__":
    unittest.main()
