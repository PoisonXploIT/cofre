"""Pruebas de llaves y recuperacion (paso 6.6)."""

from __future__ import annotations

import secrets
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from datetime import datetime

from cofre import keys
from cofre.v2 import VaultV2, new_recovery_slot, new_usb_slot
from cofre.v2.recovery import new_code
from cofre.v2.slots import SlotError, open_with_recovery, open_with_stick


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-keys-"))
        self.vault = self.tmp / "cofre.json"
        self.v2 = VaultV2(self.vault)
        self.master = secrets.token_bytes(32)
        self.clave_e = secrets.token_bytes(32)
        self.clave_f = secrets.token_bytes(32)
        self.codigo = new_code()
        datos = self.v2.create(
            self.master, new_usb_slot(self.master, self.clave_e, 111,
                                      "principal", ""))
        datos["slots"].append(new_usb_slot(self.master, self.clave_f, 222,
                                           "reserva", ""))
        datos["slots"].append(new_recovery_slot(self.master, self.codigo,
                                                "recuperacion"))
        self.v2.put(datos, self.master, "UNO", "valor", [], [])
        self.v2.save(datos)
        self.data = self.v2.load()
        self.registry = {"sticks": {
            "111": {"serial": 111, "drive": "E:\\", "role": "principal"},
            "222": {"serial": 222, "drive": "F:\\", "role": "reserva"},
            "333": {"serial": 333, "drive": "G:\\", "role": "reserva"},
        }}
        self.presentes = {
            "111": {"drive": "E:\\", "connected": True},
            "222": {"drive": "F:\\", "connected": False},
        }
        self.eventos = [
            {"seq": 1, "ts": "2026-11-18T10:00:00", "stick": "111"},
            {"seq": 2, "ts": "2026-11-18T11:00:00", "stick": "222"},
            {"seq": 3, "ts": "2026-11-18T12:00:00", "stick": "111"},
            {"seq": 4, "ts": "2026-11-18T13:00:00", "stick": "-"},
        ]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestReporte(Base):
    def test_lista_ranuras_estado_y_ultimo_uso(self):
        filas = keys.reporte(self.data, self.registry, self.presentes,
                             self.eventos)
        por_serial = {f["serial"]: f for f in filas if f["serial"] is not None}
        self.assertTrue(por_serial[111]["connected"])
        self.assertFalse(por_serial[222]["connected"])
        self.assertEqual(por_serial[111]["drive"], "E:\\")
        self.assertEqual(por_serial[111]["role"], "principal")
        self.assertEqual(por_serial[111]["last"], "2026-11-18T12:00")
        self.assertEqual(por_serial[222]["last"], "2026-11-18T11:00")
        recuperacion = [f for f in filas if f["kind"] == "recovery"]
        self.assertEqual(len(recuperacion), 1)
        self.assertEqual(recuperacion[0]["label"], "recuperacion")

    def test_fechas_humanas(self):
        ahora = datetime(2026, 11, 18, 19, 0)
        self.assertEqual(keys.fecha_humana("2026-11-18T18:49:00", ahora),
                         "hoy 18:49")
        self.assertEqual(keys.fecha_humana("2026-11-17T09:05:00", ahora),
                         "ayer 09:05")
        self.assertEqual(keys.fecha_humana("2026-11-15T10:00:00", ahora),
                         "hace 3 días")
        self.assertEqual(keys.fecha_humana("2026-10-01T10:00:00", ahora),
                         "01/10/2026 10:00")

    def test_registro_sin_ranura_avisa(self):
        filas = keys.reporte(self.data, self.registry, self.presentes,
                             self.eventos)
        huerfanos = [f for f in filas if f["kind"] == "huerfano"]
        self.assertEqual([f["serial"] for f in huerfanos], [333])


class TestCodigo(Base):
    def test_generar_codigo_quita_el_viejo_y_mantiene_el_pendrive(self):
        codigo, nuevo = keys.generar_codigo(self.v2, self.data, self.master)
        self.assertNotEqual(codigo, self.codigo)
        self.assertEqual(open_with_recovery(nuevo, codigo)[0], self.master)
        with self.assertRaises(SlotError):
            open_with_recovery(nuevo, self.codigo)
        self.assertEqual(open_with_stick(nuevo, self.clave_e, 111, "")[0],
                         self.master)
        self.assertEqual(open_with_stick(nuevo, self.clave_f, 222, "")[0],
                         self.master)

    def test_probar_codigo_bueno_y_malo(self):
        ok, motivo = keys.probar_codigo(self.data, self.codigo)
        self.assertTrue(ok, motivo)
        otro = new_code()
        ok, motivo = keys.probar_codigo(self.data, otro)
        self.assertFalse(ok)
        self.assertTrue(motivo)
        ok, motivo = keys.probar_codigo(self.data, " ".join(["x"] * 25))
        self.assertFalse(ok)
        # 2026-11-19: el mensaje dice donde falla (palabras fuera de la lista)
        self.assertIn("lista", motivo)


class TestQuitar(Base):
    def test_quita_la_ranura_y_deja_las_demas(self):
        nuevo, ok = keys.quitar_pendrive(self.v2, self.data, 222)
        self.assertTrue(ok)
        with self.assertRaises(SlotError):
            open_with_stick(nuevo, self.clave_f, 222, "")
        self.assertEqual(open_with_stick(nuevo, self.clave_e, 111, "")[0],
                         self.master)

    def test_no_permite_quedarse_sin_llaves(self):
        datos = dict(self.data)
        datos["slots"] = [s for s in datos["slots"] if s.get("kind") == "usb"
                          and int(s.get("serial", -1)) == 111]
        with self.assertRaises(ValueError):
            keys.quitar_pendrive(self.v2, datos, 111)


if __name__ == "__main__":
    unittest.main()
