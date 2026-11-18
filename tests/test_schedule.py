"""Pruebas del calendario de recordatorios (paso 5.8).

Lo importante: el fichero que se lee sin pendrive no puede llevar nombres ni
valores, solo fechas y contadores; y el aviso no debe dispararse antes de tiempo.
"""

from __future__ import annotations

import contextlib
import io
import json
import secrets
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import schedule
from cofre.paths import atomic_write
from cofre.store import open_any
from cofre.v2 import VaultV2, new_usb_slot

HOY = date(2026, 11, 18)


def _dia(dias: int) -> str:
    return (HOY + timedelta(days=dias)).isoformat()


class TestCalculo(unittest.TestCase):
    def test_sin_nada_no_hay_fecha(self):
        datos = schedule.calcular([], False, HOY)
        self.assertIsNone(datos["next_due"])
        self.assertEqual(datos["vencidas"], 0)
        self.assertEqual(datos["caducan"], 0)
        self.assertEqual(datos["sin_revocar"], 0)
        self.assertEqual(datos["rotacion_abierta"], 0)

    def test_caduca_en_diez_dias_avisa_ya(self):
        datos = schedule.calcular([{"expires_at": _dia(10)}], False, HOY)
        self.assertEqual(datos["caducan"], 1)
        self.assertEqual(datos["next_due"], HOY)

    def test_caduca_lejos_avisa_catorce_dias_antes(self):
        datos = schedule.calcular([{"expires_at": _dia(40)}], False, HOY)
        self.assertEqual(datos["caducan"], 0)
        self.assertEqual(datos["next_due"], HOY + timedelta(days=26))

    def test_ya_caducada_cuenta_como_vencida(self):
        datos = schedule.calcular([{"expires_at": _dia(-3)}], False, HOY)
        self.assertEqual(datos["vencidas"], 1)
        self.assertEqual(datos["next_due"], HOY)

    def test_rotacion_vencida_y_futura(self):
        vieja = schedule.calcular(
            [{"last_rotated": _dia(-100), "rotate_every_days": 90}], False, HOY)
        self.assertEqual(vieja["vencidas"], 1)
        self.assertEqual(vieja["next_due"], HOY)

        futura = schedule.calcular(
            [{"last_rotated": _dia(-10), "rotate_every_days": 90}], False, HOY)
        self.assertEqual(futura["vencidas"], 0)
        self.assertEqual(futura["next_due"], HOY + timedelta(days=80))

    def test_sin_revocar_cuenta_pero_avisa_a_los_siete_dias(self):
        joven = schedule.calcular(
            [{"old_unrevoked": [{"desde": _dia(-1)}]}], False, HOY)
        self.assertEqual(joven["sin_revocar"], 1)
        self.assertEqual(joven["next_due"], HOY + timedelta(days=6))

        vieja = schedule.calcular(
            [{"old_unrevoked": [{"desde": _dia(-10)}]}], False, HOY)
        self.assertEqual(vieja["sin_revocar"], 1)
        self.assertEqual(vieja["next_due"], HOY)

    def test_rotacion_a_medias_avisa_ya(self):
        datos = schedule.calcular([], True, HOY)
        self.assertEqual(datos["rotacion_abierta"], 1)
        self.assertEqual(datos["next_due"], HOY)

    def test_serializar_pone_fecha_o_vacio(self):
        datos = schedule.serializar(schedule.calcular([], False, HOY))
        self.assertEqual(datos["next_due"], "")
        datos = schedule.serializar(
            schedule.calcular([{"expires_at": _dia(-1)}], False, HOY))
        self.assertEqual(datos["next_due"], HOY.isoformat())


class TestFichero(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-sched-"))
        self.vault = self.tmp / "cofre.json"
        master = secrets.token_bytes(32)
        v2 = VaultV2(self.vault)
        datos = v2.create(master, new_usb_slot(master, secrets.token_bytes(32),
                                              1, "E", ""))
        v2.put(datos, master, "SECRETO_CON_NOMBRE", "valor-que-no-debe-salir",
               [], [], kind="api_token")
        v2.save(datos)
        self.store = open_any(self.vault)
        self.store._data = self.store._vault.load()
        self.store.master = master

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _meta(self, **cambios) -> None:
        idx = self.store.index(self.store._data, self.store.master)
        meta = idx["entries"]["SECRETO_CON_NOMBRE"]
        meta.update(cambios)
        self.store._write_index(self.store._data, self.store.master, idx)
        self.store.save(self.store._data)

    def test_el_fichero_no_lleva_nombres_ni_valores(self):
        self._meta(provider="github", expires_at=_dia(10),
                   last_rotated=_dia(-100), rotate_every_days=90,
                   old_unrevoked=[{"ref": {}, "desde": _dia(-8)}])
        ruta = schedule.escribir(self.store)
        self.assertIsNotNone(ruta)
        crudo = ruta.read_text(encoding="utf-8")
        self.assertNotIn("SECRETO_CON_NOMBRE", crudo)
        self.assertNotIn("valor-que-no-debe-salir", crudo)
        datos = json.loads(crudo)
        self.assertEqual(set(datos), {"next_due", "vencidas", "caducan",
                                      "sin_revocar", "rotacion_abierta"})
        self.assertEqual(datos["vencidas"], 1)
        self.assertEqual(datos["caducan"], 1)
        self.assertEqual(datos["sin_revocar"], 1)
        self.assertEqual(datos["rotacion_abierta"], 0)

    def test_leer_y_toca(self):
        self.assertIsNone(schedule.leer(self.vault))
        self._meta(expires_at=_dia(-1))
        schedule.escribir(self.store)
        datos = schedule.leer(self.vault)
        self.assertTrue(schedule.toca(datos))
        self.assertIn("vencidas", schedule.describe(datos))
        self.assertIn("Conecta el pendrive", schedule.mensaje(datos))


class TestCliDue(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-due-"))
        self.vault = self.tmp / "cofre.json"
        self.vault.write_text("{}", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _escribir(self, cuando: date) -> None:
        atomic_write(schedule.ruta(self.vault), json.dumps({
            "next_due": cuando.isoformat(), "vencidas": 1, "caducan": 0,
            "sin_revocar": 0, "rotacion_abierta": 0}))

    def _correr(self, *args: str) -> tuple[int, str]:
        from cofre import cli
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = cli.main(["--vault", str(self.vault), "due", *args])
        return codigo, salida.getvalue()

    def test_sin_calendario_lo_dice(self):
        codigo, salida = self._correr()
        self.assertEqual(codigo, 0)
        self.assertIn("no hay calendario", salida)

    def test_due_sin_notify_solo_imprime(self):
        self._escribir(date.today())
        codigo, salida = self._correr()
        self.assertEqual(codigo, 0)
        self.assertIn("próxima fecha", salida)

    def test_due_notify_avisa_si_la_fecha_llego(self):
        self._escribir(date.today() - timedelta(days=1))
        with mock.patch("cofre.alerts.show_message") as aviso:
            codigo, _ = self._correr("--notify")
        self.assertEqual(codigo, 0)
        aviso.assert_called_once()
        self.assertIn("Conecta el pendrive", aviso.call_args.args[1])

    def test_due_notify_no_avisa_antes_de_tiempo(self):
        self._escribir(date.today() + timedelta(days=3))
        with mock.patch("cofre.alerts.show_message") as aviso:
            codigo, _ = self._correr("--notify")
        self.assertEqual(codigo, 0)
        aviso.assert_not_called()


if __name__ == "__main__":
    unittest.main()
