"""Prueba de aceptacion del enganche: `rotate` pasa por el motor con diario.

Antes de 5.7 el comando rotate hacia el despliegue a mano y no escribia el
diario: una muerte a mitad dejaba destinos cambiados sin forma de saberlo.
Aqui se lanza un `rotate` real contra el servidor falso de Cloudflare y se
comprueba, fallando cada fase a proposito, que `resume` encuentra el diario en
la fase correcta y recomienda lo que toca.

  python -m unittest tests.test_rotate_hooked
"""

from __future__ import annotations

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
from cofre.v2 import VaultV2, new_usb_slot
from fake_cloudflare import FakeCloudflare

CONSUMIDORES = ["cfw:cuenta:worker:API", "cfw:cuenta:worker:OTRO"]


class TestRotateEnganchado(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-hook-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        master = secrets.token_bytes(32)
        self.serial = volume_serial(str(self.tmp.drive) + "\\")
        v2 = VaultV2(self.vault)
        datos = v2.create(master, new_usb_slot(master, self.llave.read_bytes(),
                                               self.serial, "t", ""))
        v2.put(datos, master, "CF_API", "valor-viejo", ["prueba"], [],
               kind="api_token")
        v2.put(datos, master, "CLOUDFLARE_TOKEN_ADMIN", "admin-falso",
               ["admin"], [], kind="api_token")
        v2.save(datos)
        register_stick(str(self.vault), self.serial, str(self.tmp.drive) + "\\")

        self.fake = FakeCloudflare()
        base = self.fake.start()
        self.fake.add_token("valor-viejo", "tok-viejo", "viejo")
        self.fake.add_token("admin-falso", "tok-admin", "admin")
        self.env = dict(os.environ, COFRE_CLOUDFLARE_API=base,
                        COFRE_VAULT=str(self.vault))
        self.cmd = [sys.executable, "-m", "cofre.cli", "--gate", "usb",
                    "--stick", str(self.llave), "--vault", str(self.vault)]
        subprocess.run(self.cmd + ["meta", "CF_API", "--provider", "cloudflare",
                                   "--token-id", "tok-viejo",
                                   "--account-id", "cuenta"]
                       + sum((["--consumer", c] for c in CONSUMIDORES), []),
                       capture_output=True, env=self.env, timeout=120)

    def tearDown(self):
        self.fake.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ ayudas

    def correr(self, *args: str, entrada: str = ""):
        return subprocess.run(self.cmd + list(args), input=entrada,
                              capture_output=True, text=True, env=self.env,
                              timeout=120)

    def abrir(self):
        return open_any(self.vault, material=material_for(
            "usb", str(self.vault), stick=str(self.llave)))

    def resume(self):
        return self.correr("resume", entrada="\n")

    # ------------------------------------------------------------ casos

    def test_fallo_al_crear_no_deja_diario_ni_pendiente_ni_destino(self):
        self.fake.fallar_create = True
        r = self.correr("rotate", "CF_API", "--si")
        salida = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0, salida)
        self.assertIn("no se creo la credencial nueva", salida)

        store = self.abrir()
        self.assertEqual(store.get("CF_API"), "valor-viejo")
        idx = store.index(store._data, store.master)
        self.assertNotIn("rotation", idx.get("settings") or {})
        contenido = store._vault.blob(store._data, store.master, "CF_API")
        self.assertNotIn("pending", contenido)
        self.assertEqual(self.fake.secretos, {}, "no se toco ningún destino")

        r2 = self.resume()
        self.assertIn("no hay ninguna rotación interrumpida", r2.stdout)

    def test_fallo_al_desplegar_deja_desplegando(self):
        self.fake.fallar_deploy_en = 1
        r = self.correr("rotate", "CF_API", "--si")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("interrumpida", r.stdout + r.stderr)

        r2 = self.resume()
        self.assertIn("fase: desplegando", r2.stdout)
        self.assertIn("recomendada: deshacer", r2.stdout)
        self.assertIn("API=pendiente", r2.stdout)

    def test_fallo_al_verificar_la_nueva_deja_desplegada(self):
        self.fake.fallar_verificar_creados = True
        r = self.correr("rotate", "CF_API", "--si")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

        r2 = self.resume()
        self.assertIn("fase: desplegada", r2.stdout)
        self.assertIn("recomendada: deshacer", r2.stdout)
        # el activo sigue siendo el viejo: no se promovio
        store = self.abrir()
        self.assertEqual(store.get("CF_API"), "valor-viejo")
        contenido = store._vault.blob(store._data, store.master, "CF_API")
        self.assertIn("pending", contenido)

    def test_fallo_al_revocar_deja_promovida(self):
        self.fake.fallar_delete = True
        r = self.correr("rotate", "CF_API", "--si", "--revoke-old")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

        r2 = self.resume()
        self.assertIn("fase: promovida", r2.stdout)
        self.assertIn("recomendada: continuar", r2.stdout)

    def test_ciclo_completo_con_revoke(self):
        r = self.correr("rotate", "CF_API", "--si", "--revoke-old")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("valor viejo revocado", r.stdout)

        store = self.abrir()
        meta = store.meta("CF_API")
        self.assertEqual(meta["provider_ref"]["token_id"], "id-nuevo-1")
        self.assertNotIn("old_unrevoked", meta)
        self.assertIsNone(self.fake.by_id("tok-viejo"))
        nuevo = store.get("CF_API")
        self.assertEqual(self.fake.secretos["worker"]["API"], nuevo)
        self.assertEqual(self.fake.secretos["worker"]["OTRO"], nuevo)
        self.assertIn("no hay ninguna rotación interrumpida", self.resume().stdout)

    def test_sin_revoke_queda_anotada_la_vieja(self):
        r = self.correr("rotate", "CF_API", "--si")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("credencial vieja sigue activa", r.stdout)

        store = self.abrir()
        meta = store.meta("CF_API")
        self.assertEqual(meta["provider_ref"]["token_id"], "id-nuevo-1")
        antiguas = meta.get("old_unrevoked") or []
        self.assertEqual(len(antiguas), 1)
        self.assertEqual(antiguas[0]["ref"]["token_id"], "tok-viejo")
        self.assertTrue(antiguas[0]["desde"])
        # sigue viva en el proveedor, que es justo lo que hay que recordar
        self.assertIsNotNone(self.fake.by_id("tok-viejo"))

    def test_resume_deshacer_repone_el_viejo_y_borra_la_nueva(self):
        # el primer destino se despliega y el segundo falla: el diario queda en
        # "desplegando" con un destino hecho
        self.fake.fallar_deploy_en = 2
        r = self.correr("rotate", "CF_API", "--si")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

        r2 = self.correr("resume", "--opcion", "deshacer", "--si")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertEqual(self.fake.secretos["worker"]["API"], "valor-viejo")
        self.assertNotIn("OTRO", self.fake.secretos["worker"],
                         "el segundo destino nunca se toco")
        self.assertIsNone(self.fake.by_id("id-nuevo-1"),
                          "la credencial nueva se borro en el proveedor")
        store = self.abrir()
        contenido = store._vault.blob(store._data, store.master, "CF_API")
        self.assertNotIn("pending", contenido)
        self.assertEqual(store.get("CF_API"), "valor-viejo")
        self.assertIn("no hay ninguna rotación interrumpida", self.resume().stdout)

    def test_resume_continuar_revoca_la_vieja_y_cierra(self):
        self.fake.fallar_delete = True
        r = self.correr("rotate", "CF_API", "--si", "--revoke-old")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.fake.fallar_delete = False

        r2 = self.correr("resume", "--opcion", "continuar", "--si")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIsNone(self.fake.by_id("tok-viejo"))
        meta = self.abrir().meta("CF_API")
        self.assertNotIn("old_unrevoked", meta)
        self.assertIn("no hay ninguna rotación interrumpida", self.resume().stdout)


if __name__ == "__main__":
    unittest.main()
