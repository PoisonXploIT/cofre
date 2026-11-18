"""Pruebas del boton de panico (paso 5.10) contra servidores falsos.

Dry-run no toca nada; la ejecucion rota Cloudflare (administrador el ultimo),
revoca los PAT de GitHub, no toca el señuelo y deja el cofre con clave nueva:
el pendrive sigue abriendo, el codigo nuevo se muestra una vez y el viejo ya no.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.gate import material_for
from cofre.store import open_any
from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_recovery_slot, new_usb_slot
from cofre.v2.recovery import new_code
from cofre.v2.slots import SlotError, open_with_recovery
from fake_cloudflare import FakeCloudflare
from fake_github import FakeGitHub


class TestPanico(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-panic-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        self.master = secrets.token_bytes(32)
        self.serial = volume_serial(str(self.tmp.drive) + "\\")
        self.codigo_viejo = new_code()
        self.otro_serial = 222

        v2 = VaultV2(self.vault)
        datos = v2.create(self.master, new_usb_slot(
            self.master, self.llave.read_bytes(), self.serial, "principal", ""))
        datos["slots"].append(new_recovery_slot(self.master, self.codigo_viejo,
                                                "recuperacion"))
        datos["slots"].append(new_usb_slot(self.master, secrets.token_bytes(32),
                                           self.otro_serial, "reserva", ""))
        v2.put(datos, self.master, "CLOUDFLARE_TOKEN_ADMIN", "admin-falso",
               ["admin"], [], kind="api_token")
        v2.put(datos, self.master, "CF_DNS", "cf-dns", [], [], kind="api_token")
        v2.put(datos, self.master, "GH_PAT", "ghp_prueba", [], [], kind="api_token")
        v2.put(datos, self.master, "APP_KEY", "-----PRIVADA-----", ["admin"], [],
               kind="private_key")
        v2.put(datos, self.master, "SENUELO", "no-se-toca", [], [], kind="canary")
        v2.put(datos, self.master, "AWS_KEY", "aws-secreta", [], [], kind="api_token")
        v2.save(datos)
        register_stick(str(self.vault), self.serial, str(self.tmp.drive) + "\\")
        register_stick(str(self.vault), self.otro_serial, "F:\\", role="reserva")

        self.fake = FakeCloudflare()
        base = self.fake.start()
        self.fake.add_token("admin-falso", "tok-admin", "admin")
        self.fake.add_token("cf-dns", "tok-dns", "dns")
        self.fake_gh = FakeGitHub()
        base_gh = self.fake_gh.start()
        self.env = dict(os.environ, COFRE_CLOUDFLARE_API=base,
                        COFRE_GITHUB_API=base_gh,
                        COFRE_VAULT=str(self.vault))
        self.cmd = [sys.executable, "-m", "cofre.cli", "--gate", "usb",
                    "--stick", str(self.llave), "--vault", str(self.vault)]
        for nombre, extra in (
                ("CLOUDFLARE_TOKEN_ADMIN", ["--provider", "cloudflare",
                                            "--token-id", "tok-admin"]),
                ("CF_DNS", ["--provider", "cloudflare", "--token-id", "tok-dns",
                            "--consumer", "cfw:cuenta:worker:API",
                            "--consumer", "cfw:cuenta"]),
                ("GH_PAT", ["--provider", "github"]),
                ("AWS_KEY", ["--provider", "aws"])):
            subprocess.run(self.cmd + ["meta", nombre, *extra],
                           capture_output=True, env=self.env, timeout=120)
        self.fake.llamadas.clear()

    def tearDown(self):
        self.fake.stop()
        self.fake_gh.stop()
        import stat
        for archivo in self.tmp.glob(".cofre-audit-retirado-*.jsonl"):
            try:
                os.chmod(archivo, stat.S_IWRITE)
            except OSError:
                pass
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def correr(self, *args: str, entrada: str = ""):
        return subprocess.run(self.cmd + list(args), input=entrada,
                              capture_output=True, text=True, env=self.env,
                              timeout=180)

    def abrir(self, path: Path | None = None):
        return open_any(path or self.vault, material=material_for(
            "usb", str(path or self.vault), stick=str(self.llave)))

    def _codigo_nuevo(self, salida: str) -> str:
        lineas = salida.splitlines()
        marca = ("rekey hecho. Codigo de recuperacion nuevo "
                 "(se muestra UNA vez):")
        indice = lineas.index(marca)
        return lineas[indice + 1].strip()

    def test_dry_run_no_toca_nada(self):
        antes = self.vault.read_text(encoding="utf-8")
        r = self.correr("panic", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dry-run", r.stdout)
        self.assertIn("roll", r.stdout)
        self.assertIn("revoke", r.stdout)
        self.assertIn("canarios que NO se tocan: SENUELO", r.stdout)
        self.assertEqual(self.vault.read_text(encoding="utf-8"), antes)
        self.assertEqual(self.fake.llamadas, [])
        self.assertEqual(self.fake_gh.revocados, [])

    def test_sin_confirmacion_no_hace_nada(self):
        antes = self.vault.read_text(encoding="utf-8")
        r = self.correr("panic", entrada="NO\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cancelado", r.stdout)
        self.assertEqual(self.vault.read_text(encoding="utf-8"), antes)
        self.assertEqual(self.fake.llamadas, [])

    def test_panico_completo(self):
        copia = self.tmp / "cofre-viejo.json"
        copia.write_text(self.vault.read_text(encoding="utf-8"), encoding="utf-8")
        r = self.correr("panic", "--si")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        # Cloudflare: primero el token normal, el administrador el ultimo
        rolls = [ruta for metodo, ruta in self.fake.llamadas
                 if metodo == "PUT" and ruta.endswith("/value")]
        self.assertEqual([ruta.split("/")[-2] for ruta in rolls],
                         ["tok-dns", "tok-admin"])
        # GitHub: revocado por valor
        self.assertEqual(self.fake_gh.revocados, ["ghp_prueba"])
        # el roll de CF_DNS intento desplegar en sus dos destinos: uno bien, otro mal
        self.assertIn("desplegado en 1/2 consumidores", r.stdout)
        self.assertIn("FALLA", r.stdout)
        self.assertIn("cfw:cuenta", r.stdout)
        self.assertEqual(self.fake.secretos["worker"]["API"], "valor-rotado-1")
        # el señuelo y la clave privada no se tocan
        self.assertIn("SENUELO", r.stdout)
        self.assertIn("regenerar la clave privada", r.stdout)
        self.assertIn("aws", r.stdout.lower())

        # el cofre abre con el mismo pendrive y el codigo nuevo, no con el viejo
        store = self.abrir()
        self.assertEqual(store.get("CF_DNS"), "valor-rotado-1")
        self.assertEqual(store.get("CLOUDFLARE_TOKEN_ADMIN"), "valor-rotado-2")
        self.assertEqual(store.get("SENUELO"), "no-se-toca")
        nuevo_master = store.master
        codigo = self._codigo_nuevo(r.stdout)
        datos = VaultV2(self.vault).load()
        self.assertEqual(open_with_recovery(datos, codigo)[0], nuevo_master)
        with self.assertRaises(SlotError):
            open_with_recovery(datos, self.codigo_viejo)
        self.assertNotIn(codigo, (self.tmp / ".cofre-audit.jsonl").read_text(
            encoding="utf-8"))

        # una copia anterior no se abre con la clave nueva
        viejos = json.loads(copia.read_text(encoding="utf-8"))
        with self.assertRaises(Exception):
            VaultV2(self.vault).index(viejos, nuevo_master)

        # el registro sigue cuadrando: tramo viejo archivado y anclado por hash
        ver = self.correr("log", "verify")
        self.assertEqual(ver.returncode, 0, ver.stdout + ver.stderr)
        self.assertNotIn("manipulad", (ver.stdout + ver.stderr).lower())
        self.assertIn("clave retirada", ver.stdout + ver.stderr)
        retirados = list(self.tmp.glob(".cofre-audit-retirado-*.jsonl"))
        self.assertEqual(len(retirados), 1)

        # el informe avisa de F: y de como volver a anadirlo
        self.assertIn("F:", r.stdout)
        self.assertIn("stick-add-v2", r.stdout)
        self.assertIn("COFRE.KEY.nuevo", r.stdout)

    def test_el_codigo_se_muestra_una_sola_vez(self):
        r = self.correr("panic", "--si")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        codigo = self._codigo_nuevo(r.stdout)
        self.assertEqual(r.stdout.count(codigo), 1)


if __name__ == "__main__":
    unittest.main()
