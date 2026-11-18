"""Pruebas de la salud de credenciales (paso 5.9).

Contra el Cloudflare falso: valida, invalida, caduca, rotacion, duplicada,
debil y sin verificar. Nunca debe salir un valor en el resultado.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre import health
from cofre.store import open_any
from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_usb_slot
from fake_cloudflare import FakeCloudflare

HOY = date(2026, 11, 18)


def _dia(dias: int) -> str:
    return (HOY + timedelta(days=dias)).isoformat()


class TestEstimacion(unittest.TestCase):
    def test_bits(self):
        self.assertEqual(health.bits_estimados(""), 0.0)
        self.assertLess(health.bits_estimados("corta1"), health.BITS_MINIMOS)
        self.assertGreater(health.bits_estimados("Xq7!mZ2#pL9$tR4"),
                           health.BITS_MINIMOS)

    def test_huella_no_es_el_valor(self):
        clave = secrets.token_bytes(32)
        huella = health.fingerprint(clave, "valor-secreto")
        self.assertNotIn("valor-secreto", huella)
        self.assertEqual(huella, health.fingerprint(clave, "valor-secreto"))
        self.assertNotEqual(huella, health.fingerprint(clave, "otro-valor"))


class TestRevision(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-health-"))
        self.vault = self.tmp / "cofre.json"
        master = secrets.token_bytes(32)
        v2 = VaultV2(self.vault)
        datos = v2.create(master, new_usb_slot(master, secrets.token_bytes(32),
                                              1, "t", ""))
        self.valores = {
            "CF_OK": "cf-bueno",
            "CF_MALO": "cf-malo",
            "CF_CADUCA": "cf-caduca",
            "CF_ROTA": "cf-rota",
            "DUP_A": "Xq7!mZ2#pL9$tR4",
            "DUP_B": "Xq7!mZ2#pL9$tR4",
            "DEBIL": "corta1",
            "CF_VIEJO": "cf-viejo",
        }
        for nombre, valor in self.valores.items():
            v2.put(datos, master, nombre, valor, [], [], kind="api_token")
        v2.save(datos)
        self.store = open_any(self.vault)
        self.store._data = self.store._vault.load()
        self.store.master = master
        self.master = master
        self.idx = self.store.index(self.store._data, master)
        # sin proveedor: duplicadas y debil
        self.idx["entries"]["DUP_A"]["type"] = "password"
        self.idx["entries"]["DUP_B"]["type"] = "password"
        self.idx["entries"]["DEBIL"]["type"] = "password"
        for nombre in ("CF_OK", "CF_MALO", "CF_CADUCA", "CF_ROTA", "CF_VIEJO"):
            self.idx["entries"][nombre]["provider"] = "cloudflare"
        self.idx["entries"]["CF_CADUCA"]["expires_at"] = _dia(10)
        self.idx["entries"]["CF_ROTA"]["last_rotated"] = _dia(-100)
        self.idx["entries"]["CF_ROTA"]["rotate_every_days"] = 90
        self.idx["entries"]["CF_VIEJO"]["last_verified"] = _dia(-40)
        self.store._write_index(self.store._data, master, self.idx)
        self.store.save(self.store._data)

        self.fake = FakeCloudflare()
        base = self.fake.start()
        os.environ["COFRE_CLOUDFLARE_API"] = base
        for valor, nombre in (("cf-bueno", "bueno"), ("cf-caduca", "caduca"),
                              ("cf-rota", "rota"), ("cf-viejo", "viejo")):
            self.fake.add_token(valor, "id-" + nombre, nombre,
                                expires_on=_dia(60))

    def tearDown(self):
        self.fake.stop()
        os.environ.pop("COFRE_CLOUDFLARE_API", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _por_nombre(self, resultados):
        return {r.nombre: r for r in resultados}

    def test_clasifica_cada_caso(self):
        resultados = self._por_nombre(health.revisar(self.store, self.master))
        self.assertEqual(resultados["CF_OK"].estado, "ok")
        self.assertEqual(resultados["CF_MALO"].estado, "invalida")
        self.assertEqual(resultados["CF_CADUCA"].estado, "caduca")
        self.assertEqual(resultados["CF_ROTA"].estado, "rotación")
        self.assertEqual(resultados["DUP_A"].estado, "duplicada")
        self.assertEqual(resultados["DUP_B"].estado, "duplicada")
        self.assertEqual(resultados["DEBIL"].estado, "debil")
        self.assertEqual(resultados["CF_VIEJO"].estado, "ok")

    def test_sin_verificar_no_las_toca(self):
        resultados = self._por_nombre(
            health.revisar(self.store, self.master, verificar=False))
        self.assertEqual(resultados["CF_VIEJO"].estado, "sin_verificar")
        self.assertEqual(resultados["CF_OK"].estado, "sin_verificar")

    def test_ningun_valor_sale_en_el_resultado(self):
        resultados = health.revisar(self.store, self.master)
        texto = json.dumps([r.__dict__ for r in resultados])
        for valor in self.valores.values():
            self.assertNotIn(valor, texto)

    def test_aplicar_guarda_estado_y_fecha(self):
        resultados = health.revisar(self.store, self.master)
        self.assertEqual(health.aplicar(self.store, self.master, resultados),
                         len(resultados))
        meta = self.store.meta("CF_OK")
        self.assertEqual(meta["health"], "ok")
        self.assertTrue(meta["last_verified"])
        self.assertEqual(meta["expires_at"], _dia(60))
        invalida = self.store.meta("CF_MALO")
        self.assertEqual(invalida["health"], "invalida")
        self.assertIn("health_detail", invalida)
        self.assertNotIn("cf-malo", json.dumps(invalida))


class TestCliHealth(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-health-cli-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        master = secrets.token_bytes(32)
        serial = volume_serial(str(self.tmp.drive) + "\\")
        v2 = VaultV2(self.vault)
        datos = v2.create(master, new_usb_slot(master, self.llave.read_bytes(),
                                              serial, "t", ""))
        v2.put(datos, master, "CF_BUENO", "cf-bueno", [], [], kind="api_token")
        v2.put(datos, master, "CF_MALO", "cf-malo", [], [], kind="api_token")
        v2.save(datos)
        register_stick(str(self.vault), serial, str(self.tmp.drive) + "\\")

        self.fake = FakeCloudflare()
        base = self.fake.start()
        self.fake.add_token("cf-bueno", "id-bueno", "bueno",
                            expires_on=_dia(60))
        self.env = dict(os.environ, COFRE_CLOUDFLARE_API=base,
                        COFRE_VAULT=str(self.vault))
        self.cmd = [sys.executable, "-m", "cofre.cli", "--gate", "usb",
                    "--stick", str(self.llave), "--vault", str(self.vault)]
        for nombre in ("CF_BUENO", "CF_MALO"):
            subprocess.run(self.cmd + ["meta", nombre, "--provider", "cloudflare"],
                           capture_output=True, env=self.env, timeout=120)

    def tearDown(self):
        self.fake.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_sin_valores_y_estados(self):
        r = subprocess.run(self.cmd + ["health", "--json"],
                           capture_output=True, text=True, env=self.env,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        datos = json.loads(r.stdout)
        por_nombre = {d["nombre"]: d for d in datos}
        self.assertEqual(por_nombre["CF_BUENO"]["estado"], "ok")
        self.assertEqual(por_nombre["CF_MALO"]["estado"], "invalida")
        self.assertNotIn("cf-bueno", r.stdout)
        self.assertNotIn("cf-malo", r.stdout)

        store = open_any(self.vault, material=None)
        # el indice necesita la llave: se comprueba con otro store abierto
        from cofre.gate import material_for
        store = open_any(self.vault, material=material_for(
            "usb", str(self.vault), stick=str(self.llave)))
        meta = store.meta("CF_BUENO")
        self.assertEqual(meta["health"], "ok")
        self.assertTrue(meta["last_verified"])


if __name__ == "__main__":
    unittest.main()
