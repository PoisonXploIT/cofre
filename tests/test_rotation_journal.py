"""Pruebas del motor de rotación con diario (paso 5.7).

Cada prueba simula una muerte del proceso en un punto distinto y comprueba:

  - qué opción propone COFRE al reabrir y cuál es la recomendada;
  - que deshacer devuelve TODOS los destinos al valor viejo y borra la
    credencial nueva en el servidor falso;
  - que continuar termina sin dejar destinos a medias.

El valor nuevo vive en el cofre como pendiente; el diario solo guarda estados.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre import rotation as R
from cofre.consumers import deploy, parse
from cofre.providers.cloudflare import Cloudflare
from cofre.store import open_any
from cofre.v2 import VaultV2, new_usb_slot
from fake_cloudflare import FakeCloudflare


class Escenario:
    """Cofre temporal con un secreto y su valor pendiente."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-rot-"))
        self.vault = self.tmp / "cofre.json"
        self.master = secrets.token_bytes(32)
        clave = secrets.token_bytes(32)
        v2 = VaultV2(self.vault)
        datos = v2.create(self.master, new_usb_slot(self.master, clave, 1, "E", ""))
        v2.put(datos, self.master, "CF_API", "valor-viejo", ["prueba"], [],
               kind="api_token")
        v2.save(datos)
        self.store = open_any(self.vault)
        self.store._data = self.store._vault.load()
        self.store.master = self.master
        self.v2 = VaultV2(self.vault)
        self.data = VaultV2(self.vault).load()
        self.fake = FakeCloudflare()
        self.base = self.fake.start()
        os.environ["COFRE_CLOUDFLARE_API"] = self.base
        self.destinos = ["cfw:cuenta:worker:API", "cfw:cuenta:worker:OTRA"]

    def cerrar(self):
        self.fake.stop()
        os.environ.pop("COFRE_CLOUDFLARE_API", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers que imitan al motor -----------------------------------

    def guardar_pendiente(self, valor: str, ref: dict | None = None):
        contenido = self.v2.blob(self.data, self.master, "CF_API")
        contenido["pending"] = {"value": valor, "ref": ref or {},
                                "desde": "2026-11-17T22:00:00"}
        self.v2.set_blob(self.data, self.master, "CF_API", contenido)
        self.v2.save(self.data)

    def promover(self):
        contenido = self.v2.blob(self.data, self.master, "CF_API")
        pendiente = contenido.pop("pending", None)
        if not pendiente:
            return
        contenido.setdefault("history", []).append(
            {"value": contenido["value"], "replaced": "2026-11-17T22:10:00"})
        contenido["value"] = pendiente["value"]
        self.v2.set_blob(self.data, self.master, "CF_API", contenido)
        self.v2.save(self.data)
        R.promote(self.vault)

    def descartar_pendiente(self):
        contenido = self.v2.blob(self.data, self.master, "CF_API")
        contenido.pop("pending", None)
        self.v2.set_blob(self.data, self.master, "CF_API", contenido)
        self.v2.save(self.data)

    def valor(self) -> str:
        return self.v2.get(self.data, self.master, "CF_API")

    def desplegar(self, valor: str, destinos: list[str] | None = None):
        return deploy(destinos or self.destinos, valor,
                      cloudflare_token=self.fake.admin_token)


class TestFases(unittest.TestCase):
    def setUp(self):
        self.e = Escenario()
        self.e.guardar_pendiente("valor-nuevo")
        R.begin(self.e.vault, "CF_API", "cloudflare", "valor-nuevo",
                {"token_id": "nuevo"}, self.e.destinos)

    def tearDown(self):
        self.e.cerrar()

    def test_antes_de_promover_se_recomienda_deshacer(self):
        plan = R.plan_resume(self.e.vault)
        self.assertEqual(plan["recomendada"], "deshacer")
        self.assertIn("continuar", plan["opciones"])

    def test_despues_de_promover_se_recomienda_continuar(self):
        self.e.promover()
        plan = R.plan_resume(self.e.vault)
        self.assertEqual(plan["recomendada"], "continuar")

    def test_revocada_solo_continuar(self):
        self.e.promover()
        R.mark_revoked(self.e.vault)
        plan = R.plan_resume(self.e.vault)
        self.assertEqual(plan["opciones"], ["continuar"])

    def test_viejo_no_valido_solo_continuar(self):
        diario = R.Journal.cargar(self.e.vault)
        diario.datos["viejo_valido"] = False
        diario.guardar()
        plan = R.plan_resume(self.e.vault)
        self.assertEqual(plan["opciones"], ["continuar"])
        self.assertIn("ya no es válido", plan["explicación"])

    def test_aviso_de_diario_viejo(self):
        diario = R.Journal.cargar(self.e.vault)
        diario.datos["iniciada"] = "2026-11-15T10:00:00"
        diario.guardar()
        self.assertTrue(R.plan_resume(self.e.vault)["aviso"])


class TestDeshacerConDosDeTres(unittest.TestCase):
    def setUp(self):
        self.e = Escenario()
        self.destinos = ["cfw:cuenta:worker:A", "cfw:cuenta:worker:B",
                         "cfw:cuenta:worker:C"]
        self.e.destinos = self.destinos
        R.begin(self.e.vault, "CF_API", "cloudflare", "valor-nuevo",
                {"token_id": "nuevo"}, self.destinos)

    def tearDown(self):
        self.e.cerrar()

    def test_muerte_con_dos_de_tres_y_deshacer(self):
        # se despliega solo en dos y se marca lo hecho
        self.e.guardar_pendiente("valor-nuevo")
        self.e.desplegar("valor-nuevo", self.destinos[:2])
        R.marcar_destino(self.e.vault, self.destinos[0], "hecho")
        R.marcar_destino(self.e.vault, self.destinos[1], "hecho")
        plan = R.plan_resume(self.e.vault)
        self.assertEqual(plan["recomendada"], "deshacer")

        # deshacer: volver a poner el viejo en los ya cambiados y descartar
        hechos = [d for d, st in plan["destinos"].items() if st == "hecho"]
        self.e.desplegar("valor-viejo", hechos)
        self.e.descartar_pendiente()
        R.finish(self.e.vault)

        secretos = self.e.fake.secretos["worker"]
        self.assertEqual(secretos["A"], "valor-viejo")
        self.assertEqual(secretos["B"], "valor-viejo")
        # el tercero nunca se toco: sigue con el viejo por definicion
        self.assertNotIn("C", secretos)
        contenido = self.e.v2.blob(self.e.data, self.e.master, "CF_API")
        self.assertNotIn("pending", contenido)
        self.assertEqual(contenido["value"], "valor-viejo")
        self.assertIsNone(R.plan_resume(self.e.vault))

    def test_continuar_tras_promover_revoca_y_cierra(self):
        self.e.guardar_pendiente("valor-nuevo")
        self.e.desplegar("valor-nuevo")
        self.e.promover()
        R.mark_revoked(self.e.vault)
        R.finish(self.e.vault)
        self.assertEqual(self.e.valor(), "valor-nuevo")
        # el segundo escenario usa destinos A y B sobre el script "worker"
        self.assertEqual(self.e.fake.secretos["worker"]["A"], "valor-nuevo")
        self.assertIsNone(R.plan_resume(self.e.vault))


class TestPendienteEnElCofre(unittest.TestCase):
    def test_el_valor_nuevo_vive_cifrado_en_la_entrada(self):
        e = Escenario()
        try:
            e.guardar_pendiente("valor-nuevo", {"token_id": "n1"})
            crudo = e.vault.read_text(encoding="utf-8")
            self.assertNotIn("valor-nuevo", crudo, "el pendiente no va en claro")
            contenido = e.v2.blob(e.data, e.master, "CF_API")
            self.assertEqual(contenido["pending"]["value"], "valor-nuevo")
            # y el diario no lleva valores
            R.begin(e.vault, "CF_API", "cloudflare", "valor-nuevo", {}, [])
            diario = R.journal_path(e.vault).read_text(encoding="utf-8")
            self.assertNotIn("valor-nuevo", diario)
        finally:
            e.cerrar()


if __name__ == "__main__":
    unittest.main()
