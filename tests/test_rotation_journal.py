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
        # una sola vista del cofre: la del store, para que el diario y las
        # entradas no se pisen
        self.v2 = self.store._vault
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
        contenido = self.v2.blob(self.store._data, self.master, "CF_API")
        contenido["pending"] = {"value": valor, "ref": ref or {},
                                "desde": "2026-11-17T22:00:00"}
        self.v2.set_blob(self.store._data, self.master, "CF_API", contenido)
        self.v2.save(self.store._data)

    def promover(self):
        contenido = self.v2.blob(self.store._data, self.master, "CF_API")
        pendiente = contenido.pop("pending", None)
        if not pendiente:
            return
        contenido.setdefault("history", []).append(
            {"value": contenido["value"], "replaced": "2026-11-17T22:10:00"})
        contenido["value"] = pendiente["value"]
        self.v2.set_blob(self.store._data, self.master, "CF_API", contenido)
        self.v2.save(self.store._data)
        R.promote(self.store, self.master)

    def descartar_pendiente(self):
        contenido = self.v2.blob(self.store._data, self.master, "CF_API")
        contenido.pop("pending", None)
        self.v2.set_blob(self.store._data, self.master, "CF_API", contenido)
        self.v2.save(self.store._data)

    def valor(self) -> str:
        return self.v2.get(self.store._data, self.master, "CF_API")

    def desplegar(self, valor: str, destinos: list[str] | None = None):
        return deploy(destinos or self.destinos, valor,
                      cloudflare_token=self.fake.admin_token)


class TestFases(unittest.TestCase):
    def setUp(self):
        self.e = Escenario()
        self.e.guardar_pendiente("valor-nuevo")
        R.begin(self.e.store, self.e.master, "CF_API", "cloudflare", "valor-nuevo",
                {"token_id": "nuevo"}, self.e.destinos)

    def tearDown(self):
        self.e.cerrar()

    def test_antes_de_promover_se_recomienda_deshacer(self):
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertEqual(plan["recomendada"], "deshacer")
        self.assertIn("continuar", plan["opciones"])

    def test_despues_de_promover_se_recomienda_continuar(self):
        self.e.promover()
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertEqual(plan["recomendada"], "continuar")

    def test_revocada_solo_continuar(self):
        self.e.promover()
        R.mark_revoked(self.e.store, self.e.master)
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertEqual(plan["opciones"], ["continuar"])

    def test_viejo_no_valido_solo_continuar(self):
        diario = R.Journal.cargar(self.e.store, self.e.master)
        diario.datos["viejo_valido"] = False
        diario.guardar()
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertEqual(plan["opciones"], ["continuar"])
        self.assertIn("ya no es válido", plan["explicación"])

    def test_aviso_de_diario_viejo(self):
        diario = R.Journal.cargar(self.e.store, self.e.master)
        diario.datos["iniciada"] = "2026-11-15T10:00:00"
        diario.guardar()
        self.assertTrue(R.plan_resume(self.e.store, self.e.master)["aviso"])


class TestDeshacerConDosDeTres(unittest.TestCase):
    def setUp(self):
        self.e = Escenario()
        self.destinos = ["cfw:cuenta:worker:A", "cfw:cuenta:worker:B",
                         "cfw:cuenta:worker:C"]
        self.e.destinos = self.destinos
        R.begin(self.e.store, self.e.master, "CF_API", "cloudflare", "valor-nuevo",
                {"token_id": "nuevo"}, self.destinos)

    def tearDown(self):
        self.e.cerrar()

    def test_muerte_con_dos_de_tres_y_deshacer(self):
        # se despliega solo en dos y se marca lo hecho
        self.e.guardar_pendiente("valor-nuevo")
        self.e.desplegar("valor-nuevo", self.destinos[:2])
        R.marcar_destino(self.e.store, self.e.master, self.destinos[0], "hecho")
        R.marcar_destino(self.e.store, self.e.master, self.destinos[1], "hecho")
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertEqual(plan["recomendada"], "deshacer")

        # deshacer: volver a poner el viejo en los ya cambiados y descartar
        hechos = [d for d, st in plan["destinos"].items() if st == "hecho"]
        self.e.desplegar("valor-viejo", hechos)
        self.e.descartar_pendiente()
        R.finish(self.e.store, self.e.master)

        secretos = self.e.fake.secretos["worker"]
        self.assertEqual(secretos["A"], "valor-viejo")
        self.assertEqual(secretos["B"], "valor-viejo")
        # el tercero nunca se toco: sigue con el viejo por definicion
        self.assertNotIn("C", secretos)
        contenido = self.e.v2.blob(self.e.store._data, self.e.master, "CF_API")
        self.assertNotIn("pending", contenido)
        self.assertEqual(contenido["value"], "valor-viejo")
        self.assertIsNone(R.plan_resume(self.e.store, self.e.master))

    def test_continuar_tras_promover_revoca_y_cierra(self):
        self.e.guardar_pendiente("valor-nuevo")
        self.e.desplegar("valor-nuevo")
        self.e.promover()
        R.mark_revoked(self.e.store, self.e.master)
        R.finish(self.e.store, self.e.master)
        self.assertEqual(self.e.valor(), "valor-nuevo")
        # el segundo escenario usa destinos A y B sobre el script "worker"
        self.assertEqual(self.e.fake.secretos["worker"]["A"], "valor-nuevo")
        self.assertIsNone(R.plan_resume(self.e.store, self.e.master))


class TestPendienteEnElCofre(unittest.TestCase):
    def test_el_valor_nuevo_vive_cifrado_en_la_entrada(self):
        e = Escenario()
        try:
            e.guardar_pendiente("valor-nuevo", {"token_id": "n1"})
            crudo = e.vault.read_text(encoding="utf-8")
            self.assertNotIn("valor-nuevo", crudo, "el pendiente no va en claro")
            contenido = e.v2.blob(e.store._data, e.master, "CF_API")
            self.assertEqual(contenido["pending"]["value"], "valor-nuevo")
            # y el diario no lleva valores
            R.begin(e.store, e.master, "CF_API", "cloudflare", "valor-nuevo", {}, [])
            datos = R.Journal.cargar(e.store, e.master).datos
            self.assertNotIn("valor-nuevo", json.dumps(datos))
        finally:
            e.cerrar()


class TestDiarioNoSePuedeFalsificar(unittest.TestCase):
    """Antes el diario era un fichero en claro: cambiar el ID de la credencial
    nueva hacia que 'deshacer' borrase otro token. Ahora va cifrado y cualquier
    cambio se detecta."""

    def setUp(self):
        self.e = Escenario()
        self.e.guardar_pendiente("valor-nuevo", {"token_id": "nuevo"})
        R.begin(self.e.store, self.e.master, "CF_API", "cloudflare",
                "valor-nuevo", {"token_id": "nuevo"}, self.e.destinos)

    def tearDown(self):
        self.e.cerrar()

    def test_no_hay_fichero_en_claro(self):
        self.assertFalse((self.e.tmp / ".cofre-rotation.json").exists())

    def test_editar_el_diario_rompe_el_descifrado(self):
        crudo = self.e.vault.read_text(encoding="utf-8")
        datos = json.loads(crudo)
        # se manipula el indice cifrado: el AAD y la firma lo detectan
        datos["index"]["c"] = datos["index"]["c"][:-8] + "00000000"
        self.e.vault.write_text(json.dumps(datos), encoding="utf-8")
        store = self.e.store
        store._data = store._vault.load()
        with self.assertRaises(R.JournalError):
            R.plan_resume(store, store.master)

    def test_un_token_ajeno_no_llega_a_borrarse(self):
        # el ID vive cifrado: no se puede cambiar desde fuera, asi que
        # 'deshacer' no puede apuntar a otro token
        datos = R.Journal.cargar(self.e.store, self.e.master).datos
        self.assertEqual(datos["ref_nueva"]["token_id"], "nuevo")
        self.assertNotIn("nuevo", self.e.vault.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class TestFalloEnCadaFase(unittest.TestCase):
    """El motor deja el diario en la fase correcta si algo falla."""

    def setUp(self):
        self.e = Escenario()
        self.destinos = ["cfw:cuenta:worker:U", "cfw:cuenta:worker:V"]

    def tearDown(self):
        self.e.cerrar()

    def _correr(self, falla_en: str, revocar_viejo: bool = True):
        desplegados = []
        revocados = []

        def desplegar(destinos, valor):
            if falla_en == "desplegar" and len(desplegados) == 1:
                raise RuntimeError("fallo simulado al desplegar")
            desplegados.append((destinos[0], valor))

        def revocar():
            if falla_en == "revocar":
                raise RuntimeError("fallo simulado al revocar")
            revocados.append("viejo")

        return R.run_rotation(
            self.e.store, self.e.master, "CF_API", "cloudflare", "valor-nuevo",
            {"token_id": "nuevo"}, self.destinos, desplegar, revocar,
            revocar_viejo=revocar_viejo,
            ref_old={"token_id": "viejo"}), desplegados, revocados

    def test_fallo_al_desplegar_deja_fase_intermedia(self):
        resultado, desplegados, _ = self._correr("desplegar")
        self.assertIn("interrumpida", resultado)
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertIn(plan["fase"], ("desplegando", "pendiente_creada"))
        self.assertEqual(plan["recomendada"], "deshacer")

    def test_fallo_al_revocar_deja_promovida(self):
        resultado, desplegados, revocados = self._correr("revocar")
        self.assertIn("interrumpida", resultado)
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertEqual(plan["fase"], "promovida")
        self.assertEqual(plan["recomendada"], "continuar")
        self.assertEqual(revocados, [])

    def test_sin_revocar_queda_promovida(self):
        resultado, desplegados, revocados = self._correr("nada", revocar_viejo=False)
        self.assertEqual(resultado, "completada")
        self.assertIsNone(R.plan_resume(self.e.store, self.e.master))
        self.assertEqual(revocados, [])
        self.assertEqual(len(desplegados), 2)
        self.assertEqual(self.e.valor(), "valor-nuevo")
        # la vieja sigue viva en el proveedor: queda anotada con su referencia
        antiguas = R._antiguas(R._meta(self.e.store, self.e.master, "CF_API"))
        self.assertEqual(len(antiguas), 1)
        self.assertEqual(antiguas[0]["ref"]["token_id"], "viejo")
        self.assertTrue(antiguas[0]["desde"])

    def test_ciclo_completo_cierra_el_diario(self):
        resultado, _, revocados = self._correr("nada")
        self.assertEqual(resultado, "completada")
        self.assertEqual(revocados, ["viejo"])
        self.assertIsNone(R.plan_resume(self.e.store, self.e.master))
        self.assertEqual(R._antiguas(R._meta(self.e.store, self.e.master,
                                            "CF_API")), [])


class TestCrearYVerificar(unittest.TestCase):
    """Faltaban dos casos: fallo al crear y fallo al verificar lo desplegado."""

    def setUp(self):
        self.e = Escenario()
        self.destinos = ["cfw:cuenta:worker:U", "cfw:cuenta:worker:V"]

    def tearDown(self):
        self.e.cerrar()

    def test_fallo_al_crear_no_deja_nada(self):
        tocados = []

        def crear():
            raise RuntimeError("fallo simulado al crear")

        def desplegar(destinos, valor):
            tocados.append(destinos[0])

        resultado = R.run_rotation(
            self.e.store, self.e.master, "CF_API", "cloudflare",
            destinos=self.destinos, desplegar=desplegar, crear=crear)

        self.assertTrue(resultado.startswith("no-creada"), resultado)
        # ni diario abierto, ni pendiente, ni destinos tocados
        self.assertIsNone(R.plan_resume(self.e.store, self.e.master))
        self.assertIsNone(R.Journal.cargar(self.e.store, self.e.master))
        contenido = self.e.v2.blob(self.e.store._data, self.e.master, "CF_API")
        self.assertNotIn("pending", contenido)
        self.assertEqual(contenido["value"], "valor-viejo")
        self.assertEqual(self.e.valor(), "valor-viejo")
        self.assertEqual(tocados, [])

    def test_fallo_al_verificar_tras_desplegar_deja_desplegada(self):
        tocados = []

        def crear():
            return "valor-nuevo", {"token_id": "nuevo"}

        def desplegar(destinos, valor):
            tocados.append((destinos[0], valor))

        def verificar(valor):
            raise RuntimeError("el valor nuevo no verifica")

        resultado = R.run_rotation(
            self.e.store, self.e.master, "CF_API", "cloudflare",
            destinos=self.destinos, desplegar=desplegar, crear=crear,
            verificar=verificar)

        self.assertIn("interrumpida", resultado)
        plan = R.plan_resume(self.e.store, self.e.master)
        self.assertEqual(plan["fase"], "desplegada")
        self.assertEqual(plan["recomendada"], "deshacer")
        self.assertEqual(len(tocados), 2, "se desplego en los dos destinos")
        # aun no se promovio: el activo sigue siendo el viejo
        self.assertEqual(self.e.valor(), "valor-viejo")
        contenido = self.e.v2.blob(self.e.store._data, self.e.master, "CF_API")
        self.assertIn("pending", contenido)

    def test_sin_crear_no_escribe_nada(self):
        def crear():
            return "", {}

        resultado = R.run_rotation(
            self.e.store, self.e.master, "CF_API", "cloudflare",
            destinos=self.destinos, desplegar=lambda d, v: None, crear=crear)
        self.assertTrue(resultado.startswith("no-creada"))
        self.assertIsNone(R.plan_resume(self.e.store, self.e.master))


class TestAntiguaSinRevocar(unittest.TestCase):
    """Al cerrar sin revocar, la credencial vieja no se olvida."""

    def setUp(self):
        self.e = Escenario()

    def tearDown(self):
        self.e.cerrar()

    def _ciclo(self, revocar_viejo: bool, ref_old: dict | None = None):
        return R.run_rotation(
            self.e.store, self.e.master, "CF_API", "cloudflare",
            destinos=[], desplegar=lambda d, v: None,
            crear=lambda: ("valor-nuevo", {"token_id": "id-nuevo"}),
            revocar=lambda: None, revocar_viejo=revocar_viejo,
            ref_old=ref_old or {"token_id": "id-viejo"})

    def test_sin_revocar_guarda_ref_y_fecha(self):
        self.assertEqual(self._ciclo(False), "completada")
        self.assertIsNone(R.plan_resume(self.e.store, self.e.master))
        meta = R._meta(self.e.store, self.e.master, "CF_API")
        antiguas = R._antiguas(meta)
        self.assertEqual(len(antiguas), 1)
        self.assertEqual(antiguas[0]["ref"]["token_id"], "id-viejo")
        self.assertTrue(antiguas[0]["desde"])
        self.assertEqual(meta["provider_ref"]["token_id"], "id-nuevo")

    def test_revocar_limpia_la_nota(self):
        self.assertEqual(self._ciclo(True), "completada")
        meta = R._meta(self.e.store, self.e.master, "CF_API")
        self.assertEqual(R._antiguas(meta), [])

    def test_dos_rotaciones_sin_revocar_no_se_pisan(self):
        self.assertEqual(self._ciclo(False), "completada")
        self.assertEqual(self._ciclo(False), "completada")
        antiguas = R._antiguas(R._meta(self.e.store, self.e.master, "CF_API"))
        self.assertEqual(len(antiguas), 2)


class TestRevocarLaAntigua(unittest.TestCase):
    def setUp(self):
        self.e = Escenario()
        self.e.fake.add_token("valor-viejo", "tok-viejo", "viejo")
        self.e.fake.add_token(self.e.fake.admin_token, "tok-admin", "admin")

    def tearDown(self):
        self.e.cerrar()

    def _anotar(self, dato: dict) -> None:
        R._actualizar_meta(self.e.store, self.e.master, "CF_API",
                           {"provider": "cloudflare", "old_unrevoked": [dato]})

    def test_revoca_por_id_y_limpia(self):
        self._anotar({"ref": {"token_id": "tok-viejo"},
                      "desde": "2026-11-01T10:00:00"})
        texto = R.revocar_antigua(self.e.store, self.e.master, "CF_API",
                                  self.e.fake.admin_token)
        self.assertIn("revocada", texto)
        self.assertIsNone(self.e.fake.by_id("tok-viejo"))
        self.assertEqual(R._antiguas(R._meta(self.e.store, self.e.master,
                                            "CF_API")), [])

    def test_github_revoca_por_el_valor_del_historial(self):
        from unittest import mock
        contenido = self.e.v2.blob(self.e.store._data, self.e.master, "CF_API")
        contenido["history"] = [{"value": "ghp_viejo", "replaced": "2026-11-01"}]
        self.e.v2.set_blob(self.e.store._data, self.e.master, "CF_API", contenido)
        self.e.v2.save(self.e.store._data)
        R._actualizar_meta(self.e.store, self.e.master, "CF_API", {
            "provider": "github",
            "old_unrevoked": [{"ref": {}, "history": 0,
                               "desde": "2026-11-01T10:00:00"}]})
        with mock.patch("cofre.providers.github.revoke_credentials") as rev:
            texto = R.revocar_antigua(self.e.store, self.e.master, "CF_API")
        rev.assert_called_once_with(["ghp_viejo"])
        self.assertIn("revocada", texto)
        self.assertEqual(R._antiguas(R._meta(self.e.store, self.e.master,
                                            "CF_API")), [])


class TestAlertaDeLaAntigua(unittest.TestCase):
    """A los 7 días, una alerta baja (y no se repite en cada pasada)."""

    def test_avisa_a_los_siete_dias_una_sola_vez(self):
        from datetime import datetime, timedelta

        from cofre.alerts import evaluate_unrevoked

        e = Escenario()
        try:
            viejo = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
            reciente = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
            R._actualizar_meta(e.store, e.master, "CF_API", {
                "provider": "cloudflare",
                "old_unrevoked": [
                    {"ref": {"token_id": "viejo"}, "desde": viejo},
                    {"ref": {"token_id": "otro"}, "desde": reciente},
                ]})
            alertas = evaluate_unrevoked(e.store, [])
            self.assertEqual(len(alertas), 1)
            alerta = alertas[0]
            self.assertEqual(alerta.rule, "credencial-sin-revocar")
            self.assertEqual(alerta.severity, "baja")
            self.assertIn("CF_API", alerta.text)
            # ya escrito en el log: no se repite
            eventos = [{"ev": "alert", "name": "credencial-sin-revocar",
                        "detail": f"baja: {alerta.text}"}]
            self.assertEqual(evaluate_unrevoked(e.store, eventos), [])
        finally:
            e.cerrar()


class TestHistorialFijado(unittest.TestCase):
    """Los valores pendientes de revocar no salen del historial aunque se llene.

    GitHub revoca por valor: si el valor se cae del historial, la credencial
    vieja queda viva para siempre. Las versiones fijadas no cuentan para el
    tope de 5 hasta que se revocan o se descartan.
    """

    def setUp(self):
        self.e = Escenario()
        R._actualizar_meta(self.e.store, self.e.master, "CF_API",
                           {"provider": "github"})

    def tearDown(self):
        self.e.cerrar()

    def _rotar(self, valor_nuevo: str) -> None:
        resultado = R.run_rotation(
            self.e.store, self.e.master, "CF_API", "github", destinos=[],
            desplegar=lambda d, v: None,
            crear=lambda: (valor_nuevo, {}), ref_old={})
        self.assertEqual(resultado, "completada")

    def test_seis_rotaciones_sin_revocar_siguen_siendo_revocables(self):
        for i in range(6):
            self._rotar(f"valor-{i}")

        antiguas = R._antiguas(R._meta(self.e.store, self.e.master, "CF_API"))
        self.assertEqual(len(antiguas), 6)
        contenido = self.e.v2.blob(self.e.store._data, self.e.master, "CF_API")
        historia = contenido["history"]
        self.assertEqual(len(historia), 6,
                         "las fijadas no cuentan para el tope de 5")
        self.assertTrue(all(entrada.get("pinned") for entrada in historia))

        # cada nota encuentra su valor, incluida la mas vieja
        valores = [R._valor_de_la_antigua(self.e.store, self.e.master,
                                          "CF_API", antigua)
                   for antigua in antiguas]
        self.assertNotIn("", valores)
        self.assertEqual(set(valores),
                         {"valor-viejo", "valor-0", "valor-1", "valor-2",
                          "valor-3", "valor-4"})

        from unittest import mock
        with mock.patch("cofre.providers.github.revoke_credentials") as rev:
            for pendiente in R.pendientes_de_revocar(self.e.store,
                                                     self.e.master):
                R.revocar_antigua(self.e.store, self.e.master, "CF_API",
                                  desde=pendiente["desde"])
        self.assertEqual(rev.call_count, 6)
        revocados = {llamada.args[0][0] for llamada in rev.call_args_list}
        self.assertEqual(revocados, set(valores))
        self.assertEqual(R._antiguas(R._meta(self.e.store, self.e.master,
                                            "CF_API")), [])
        # ya sin fijar, el historial vuelve a su tope
        contenido = self.e.v2.blob(self.e.store._data, self.e.master, "CF_API")
        self.assertEqual(len(contenido["history"]), 5)
        self.assertNotIn("valor-viejo",
                         [entrada["value"] for entrada in contenido["history"]])

    def test_el_tope_recorta_solo_las_libres(self):
        historia = [{"value": f"v{i}", "hid": f"h{i}", "pinned": i < 2}
                    for i in range(8)]
        contenido = {"value": "activo", "history": historia}
        self.assertTrue(R._recortar_historial(contenido))
        self.assertEqual([entrada["value"] for entrada in contenido["history"]],
                         ["v0", "v1", "v3", "v4", "v5", "v6", "v7"])

    def test_descartar_quita_la_nota_sin_tocar_el_proveedor(self):
        self._rotar("valor-0")
        antes = R._antiguas(R._meta(self.e.store, self.e.master, "CF_API"))
        self.assertEqual(len(antes), 1)
        texto = R.descartar_antigua(self.e.store, self.e.master, "CF_API",
                                    desde=antes[0]["desde"])
        self.assertIn("descartado", texto)
        self.assertEqual(R._antiguas(R._meta(self.e.store, self.e.master,
                                            "CF_API")), [])
        contenido = self.e.v2.blob(self.e.store._data, self.e.master, "CF_API")
        self.assertFalse(any(entrada.get("pinned")
                             for entrada in contenido["history"]))
