"""Pruebas del rekey de la clave maestra (paso 1.6, base del panico 5.10).

Lo que no puede fallar: el cofre nuevo se abre con el pendrive y el codigo
nuevos, no con la clave vieja; las entradas sobreviven con historial y pendiente;
los slots que no se pueden re-envolver se quitan avisando; y el log se re-firma
solo si la clave vieja verificaba toda la cadena.
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

from cofre import audit
from cofre.gate import material_for
from cofre.store import open_any
from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_recovery_slot, new_usb_slot
from cofre.v2.recovery import new_code
from cofre.v2.rekey import RekeyError, guardar, preparar
from cofre.v2.vault import Vault2Error
from cofre.v2.slots import SlotError, open_with_recovery, open_with_stick


class TestRekey(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-rekey-"))
        self.vault = self.tmp / "cofre.json"
        self.v2 = VaultV2(self.vault)
        self.master = secrets.token_bytes(32)
        self.stick = secrets.token_bytes(32)
        self.serial = 111
        self.otro_stick = secrets.token_bytes(32)
        self.otro_serial = 222
        self.codigo_viejo = new_code()

        datos = self.v2.create(
            self.master, new_usb_slot(self.master, self.stick, self.serial,
                                      "principal", ""))
        datos["slots"].append(new_recovery_slot(self.master, self.codigo_viejo,
                                                "recuperacion"))
        datos["slots"].append(new_usb_slot(self.master, self.otro_stick,
                                           self.otro_serial, "reserva", ""))
        self.v2.put(datos, self.master, "UNO", "valor-uno", ["a"], [],
                    kind="api_token")
        self.v2.put(datos, self.master, "DOS", "valor-dos", [], [],
                    kind="password")
        contenido = self.v2.blob(datos, self.master, "UNO")
        contenido["history"] = [{"value": "viejo", "replaced": "2026-11-01",
                                 "hid": "h1", "pinned": True}]
        contenido["pending"] = {"value": "pendiente", "ref": {}, "desde": "x"}
        self.v2.set_blob(datos, self.master, "UNO", contenido)
        self.v2.save(datos)
        self.original = self.v2.load()

        self.store = open_any(self.vault)
        self.store._data = self.store._vault.load()
        self.store.master = self.master

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _preparar(self, **cambios):
        opciones = dict(stick_key=self.stick, serial=self.serial,
                        label="principal", pin="")
        opciones.update(cambios)
        return preparar(self.store._vault, self.store._data, self.master,
                        **opciones)

    def test_el_cofre_nuevo_abre_con_lo_nuevo_y_no_con_lo_viejo(self):
        prep = self._preparar()
        guardar(self.store._vault, prep)

        datos = self.v2.load()
        self.assertIn("entries", self.v2.index(datos, prep.master))
        with self.assertRaises(Vault2Error):
            self.v2.index(datos, self.master)
        self.assertEqual(self.v2.get(datos, prep.master, "UNO"), "valor-uno")
        self.assertEqual(self.v2.get(datos, prep.master, "DOS"), "valor-dos")

        abierto, _slot = open_with_stick(datos, self.stick, self.serial, "")
        self.assertEqual(abierto, prep.master)
        abierto, _slot = open_with_recovery(datos, prep.codigo)
        self.assertEqual(abierto, prep.master)

    def test_historial_y_pendiente_sobreviven(self):
        prep = self._preparar()
        guardar(self.store._vault, prep)
        datos = self.v2.load()
        contenido = self.v2.blob(datos, prep.master, "UNO")
        self.assertEqual(contenido["history"][0]["value"], "viejo")
        self.assertTrue(contenido["history"][0]["pinned"])
        self.assertEqual(contenido["pending"]["value"], "pendiente")

    def test_slots_que_no_se_pueden_reenvolver_se_quitan_avisando(self):
        prep = self._preparar()
        guardar(self.store._vault, prep)
        datos = self.v2.load()
        self.assertEqual(len(datos["slots"]), 2)   # pendrive actual + recuperacion
        self.assertTrue(any(p["serial"] == self.otro_serial
                            for p in prep.perdidos))
        self.assertTrue(any(p["kind"] == "recovery" for p in prep.perdidos))
        with self.assertRaises(SlotError):
            open_with_stick(datos, self.otro_stick, self.otro_serial, "")
        with self.assertRaises(SlotError):
            open_with_recovery(datos, self.codigo_viejo)

    def test_una_copia_vieja_sigue_abriendo_con_la_clave_vieja_pero_no_con_la_nueva(self):
        copia = self.tmp / "cofre-viejo.json"
        copia.write_text(self.vault.read_text(encoding="utf-8"), encoding="utf-8")
        prep = self._preparar()
        guardar(self.store._vault, prep)
        datos_viejos = json.loads(copia.read_text(encoding="utf-8"))
        self.assertIsNotNone(self.v2.index(datos_viejos, self.master))
        with self.assertRaises(Vault2Error):
            self.v2.index(datos_viejos, prep.master)

    def test_la_clave_vieja_no_prepara_el_rekey(self):
        with self.assertRaises(RekeyError):
            preparar(self.store._vault, self.store._data, secrets.token_bytes(32),
                     stick_key=self.stick, serial=self.serial)
        # el fichero no se ha tocado
        self.assertEqual(self.v2.index(self.v2.load(), self.master)
                         .get("entries").keys(),
                         self.v2.index(self.original, self.master)
                         .get("entries").keys())


class TestSegmentos(unittest.TestCase):
    """El tramo viejo no se re-firma: se archiva y se ancla por hash."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-seg-"))
        self.vault = self.tmp / "cofre.json"
        self.vault.write_text("{}", encoding="utf-8")
        self.vieja = secrets.token_bytes(32)
        self.nueva = secrets.token_bytes(32)
        self.serial = 111
        audit.clear_key()
        audit.set_key(self.vieja)
        for i in range(3):
            audit.record(self.vault, "get", "usb", self.serial,
                         name=f"S{i}", ok=True)

    def tearDown(self):
        audit.clear_key()
        import os
        import stat
        for archivo in self.tmp.glob(audit.SEGMENT_PREFIX + "*.jsonl"):
            try:
                os.chmod(archivo, stat.S_IWRITE)
            except OSError:
                pass
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _archivos(self):
        return sorted(self.tmp.glob(audit.SEGMENT_PREFIX + "*.jsonl"))

    def test_cierra_archiva_y_ancla_sin_refirmar(self):
        log = audit.audit_path(self.vault)
        texto_viejo = log.read_text(encoding="utf-8")
        seg = audit.close_segment(self.vault, self.nueva, motivo="prueba",
                                  gate="usb", serial=self.serial)
        self.assertIsNotNone(seg)
        archivo = Path(seg["archivo"])
        self.assertTrue(archivo.exists())
        self.assertEqual(archivo.read_text(encoding="utf-8"), texto_viejo,
                         "el tramo viejo no se re-firma")
        # solo lectura
        import os
        self.assertEqual(os.stat(archivo).st_mode & 0o222, 0)

        # el tramo nuevo se verifica con la clave nueva
        audit.set_key(self.nueva)
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok, detalle)
        self.assertIn("clave retirada", detalle)
        self.assertIn(archivo.name, detalle)

        # la clave vieja ya no verifica el ancla nueva
        audit.set_key(self.vieja)
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("firma incorrecta", detalle)

    def test_un_tramo_retirado_editado_se_detecta(self):
        seg = audit.close_segment(self.vault, self.nueva, motivo="prueba")
        archivo = Path(seg["archivo"])
        import os
        import stat
        os.chmod(archivo, stat.S_IWRITE)
        with archivo.open("a", encoding="utf-8") as fh:
            fh.write("\n")
        audit.set_key(self.nueva)
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("se ha editado", detalle)

    def test_dos_tramos_retirados_se_heredan(self):
        seg1 = audit.close_segment(self.vault, self.nueva, motivo="prueba")
        audit.set_key(self.nueva)
        audit.record(self.vault, "get", "usb", self.serial, name="S3", ok=True)
        tercera = secrets.token_bytes(32)
        seg2 = audit.close_segment(self.vault, tercera, motivo="prueba2")
        audit.set_key(tercera)
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok, detalle)
        self.assertIn(Path(seg1["archivo"]).name, detalle)
        self.assertIn(Path(seg2["archivo"]).name, detalle)

    def test_un_tramo_retirado_borrado_se_detecta(self):
        seg = audit.close_segment(self.vault, self.nueva, motivo="prueba")
        archivo = Path(seg["archivo"])
        import os
        import stat
        os.chmod(archivo, stat.S_IWRITE)
        archivo.unlink()
        audit.set_key(self.nueva)
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("falta el tramo retirado", detalle)

    def test_sin_log_no_hay_nada_que_cerrar(self):
        audit.clear_key()
        audit.audit_path(self.vault).unlink(missing_ok=True)
        self.assertIsNone(audit.close_segment(self.vault, self.nueva))


if __name__ == "__main__":
    unittest.main()


class TestCliRekey(unittest.TestCase):
    """El comando rekey hace el ciclo completo: tramo, clave y código nuevo."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-cli-rekey-"))
        self.vault = self.tmp / "cofre.json"
        self.llave = self.tmp / "COFRE.KEY"
        self.llave.write_bytes(secrets.token_bytes(32))
        self.master = secrets.token_bytes(32)
        self.serial = volume_serial(str(self.tmp.drive) + "\\")
        self.codigo_viejo = new_code()
        v2 = VaultV2(self.vault)
        datos = v2.create(self.master, new_usb_slot(
            self.master, self.llave.read_bytes(), self.serial, "principal", ""))
        datos["slots"].append(new_recovery_slot(self.master, self.codigo_viejo,
                                                "recuperacion"))
        v2.put(datos, self.master, "UNO", "valor-uno", [], [])
        v2.save(datos)
        register_stick(str(self.vault), self.serial,
                       str(self.tmp.drive) + "\\")
        self.cmd = [sys.executable, "-m", "cofre.cli", "--gate", "usb",
                    "--stick", str(self.llave), "--vault", str(self.vault)]
        self.env = dict(os.environ, COFRE_VAULT=str(self.vault))

    def tearDown(self):
        import stat
        for archivo in self.tmp.glob(audit.SEGMENT_PREFIX + "*.jsonl"):
            try:
                os.chmod(archivo, stat.S_IWRITE)
            except OSError:
                pass
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rekey_cli(self):
        r = subprocess.run(self.cmd + ["rekey", "--si", "--motivo", "prueba"],
                           capture_output=True, text=True, env=self.env,
                           timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        marca = ("rekey hecho. Codigo de recuperacion nuevo "
                 "(se muestra UNA vez):")
        lineas = r.stdout.splitlines()
        codigo = lineas[lineas.index(marca) + 1].strip()

        datos = VaultV2(self.vault).load()
        self.assertEqual(open_with_recovery(datos, codigo)[0] is not None, True)
        with self.assertRaises(SlotError):
            open_with_recovery(datos, self.codigo_viejo)
        self.assertEqual(open_with_stick(datos, self.llave.read_bytes(),
                                         self.serial, "")[0] is not None, True)

        store = open_any(self.vault, material=material_for(
            "usb", str(self.vault), stick=str(self.llave)))
        self.assertEqual(store.get("UNO"), "valor-uno")

        ver = subprocess.run(self.cmd + ["log", "verify"], capture_output=True,
                             text=True, env=self.env, timeout=180)
        self.assertEqual(ver.returncode, 0, ver.stdout + ver.stderr)
        self.assertIn("clave retirada", ver.stdout + ver.stderr)
        log = audit.audit_path(self.vault).read_text(encoding="utf-8")
        self.assertNotIn(codigo, log)
