"""Pruebas del log encadenado (paso 3.1)."""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import audit
from cofre.paths import audit_path


class TestAuditChain(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-audit-test-"))
        self.vault = self.tmp / "cofre.json"
        audit.set_key(secrets.token_bytes(32))

    def tearDown(self):
        audit.clear_key()

    def _lineas(self) -> list[str]:
        return audit_path(self.vault).read_text(encoding="utf-8").splitlines()

    def test_cadena_valida(self):
        for i in range(4):
            audit.record(self.vault, "get", "usb", 111, name=f"S{i}")
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok, detalle)
        self.assertIn("cadena intacta", detalle)

    def test_borrar_una_linea_del_medio(self):
        for i in range(4):
            audit.record(self.vault, "get", "usb", 111, name=f"S{i}")
        lineas = self._lineas()
        del lineas[1]
        audit_path(self.vault).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("cadena no cuadra", detalle)

    def test_editar_un_nombre(self):
        audit.record(self.vault, "get", "usb", 111, name="ORIGINAL")
        audit.record(self.vault, "get", "usb", 111, name="OTRO")
        lineas = self._lineas()
        ev = json.loads(lineas[0])
        ev["name"] = "CAMBIADO"
        lineas[0] = json.dumps(ev, sort_keys=True, separators=(",", ":"))
        audit_path(self.vault).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("firma incorrecta", detalle)

    def test_truncar_el_final_sin_checkpoint_no_se_ve(self):
        # honestidad: sin checkpoint, borrar la ultima linea deja una cadena
        # valida mas corta. El checkpoint es lo que lo detecta.
        for i in range(3):
            audit.record(self.vault, "get", "usb", 111, name=f"S{i}")
        lineas = self._lineas()
        audit_path(self.vault).write_text("\n".join(lineas[:-1]) + "\n", encoding="utf-8")
        ok, _ = audit.verify(self.vault)
        self.assertTrue(ok, "sin checkpoint no hay forma de saberlo")

    def test_sin_clave_las_lineas_van_sin_firma(self):
        audit.clear_key()
        audit.record(self.vault, "gui-gate", "usb", ok=False)
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok)
        self.assertIn("sin firma", detalle)

    def test_tail_y_stats_no_revientan(self):
        audit.record(self.vault, "get", "usb", 111, name="X")
        self.assertTrue(audit.tail(self.vault, 5))
        self.assertTrue(audit.tail_human(self.vault, 5))
        self.assertEqual(audit.stats(self.vault)["entradas"], 1)

    def test_no_se_guarda_ningun_valor(self):
        audit.record(self.vault, "get", "usb", 111, name="API", detail="dominio=github.com")
        crudo = audit_path(self.vault).read_text(encoding="utf-8")
        self.assertNotIn("valor", crudo)
        self.assertIn("github.com", crudo)


class TestFirmaExigible(unittest.TestCase):
    """La firma solo se exige a eventos que no pueden ocurrir con el cofre cerrado."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-firma-"))
        self.vault = self.tmp / "cofre.json"
        audit.set_key(secrets.token_bytes(32))

    def tearDown(self):
        audit.clear_key()

    def test_alerta_de_fallos_sin_firma_no_es_manipulacion(self):
        # tres aperturas fallidas ocurren con el cofre cerrado, y su alerta
        # tambien: no puede marcarse como manipulacion
        audit.clear_key()
        for _ in range(3):
            audit.record(self.vault, "gui-gate", "usb", ok=False, detail="sin pendrive")
        audit.record(self.vault, "alert", "usb", name="fallos-apertura", ok=False,
                     detail="media: 3 fallos de apertura seguidos")
        audit.set_key(secrets.token_bytes(32))
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok, detalle)
        self.assertIn("sin firma", detalle)

    def test_evento_privilegiado_sin_firma_tras_ancla(self):
        audit.record(self.vault, "reanchor", "usb", ok=True, detail="prueba")
        texto = audit_path(self.vault).read_text(encoding="utf-8")
        # se anade a mano un browser-get sin firma y con prev correcto
        import hashlib
        ultima = texto.splitlines()[-1]
        falso = json.dumps({"seq": 2, "ev": "browser-get", "tok": "x",
                            "prev": hashlib.sha256(ultima.encode()).hexdigest(),
                            "mac": None}, sort_keys=True, separators=(",", ":"))
        contenido = texto + falso + "\n"
        audit_path(self.vault).write_text(contenido, encoding="utf-8")
        ok, detalle = audit.verify(self.vault)
        self.assertFalse(ok)
        self.assertIn("van sin firma", detalle)
        self.assertIn("browser-get", detalle)

    def test_reanclar_mueve_el_punto_de_exigencia(self):
        audit.record(self.vault, "lock", "usb", ok=True)          # sin contexto: sin firma
        audit.record(self.vault, "reanchor", "usb", ok=True, detail="decision del usuario")
        ok, detalle = audit.verify(self.vault)
        self.assertTrue(ok, detalle)
        self.assertIn("re-anclado en la línea 2", detalle)
        self.assertIn("exentas de firma", detalle)

    def test_restaurar_copia_antigua_avisa_pero_no_falla(self):
        from cofre.v2 import VaultV2, new_usb_slot
        from cofre.store import open_any

        vp = self.tmp / "cofre.json"
        master = secrets.token_bytes(32)
        VaultV2(vp).create(master, new_usb_slot(master, secrets.token_bytes(32), 1, "E", ""))
        store = open_any(vp)
        store._data = store._vault.load()
        store.master = master
        audit.set_key(master)
        audit.record(vp, "get", "usb", 1, name="A")
        audit.stamp(store, master)
        # el log sigue creciendo despues del checkpoint (como tras restaurar)
        audit.record(vp, "get", "usb", 1, name="B")
        store.refresh()
        ok, detalle = audit.check_checkpoint(store, master)
        self.assertTrue(ok, detalle)
        self.assertIn("por delante del checkpoint", detalle)

    def test_checkpoint_por_detras_del_log_si_falla(self):
        from cofre.v2 import VaultV2, new_usb_slot
        from cofre.store import open_any

        vp = self.tmp / "cofre2.json"
        master = secrets.token_bytes(32)
        VaultV2(vp).create(master, new_usb_slot(master, secrets.token_bytes(32), 1, "E", ""))
        store = open_any(vp)
        store._data = store._vault.load()
        store.master = master
        audit.set_key(master)
        for i in range(3):
            audit.record(vp, "get", "usb", 1, name=f"S{i}")
        audit.stamp(store, master)
        lineas = audit_path(vp).read_text(encoding="utf-8").splitlines()
        recortado = "\n".join(lineas[:-1]) + "\n"
        audit_path(vp).write_text(recortado, encoding="utf-8")
        ok, detalle = audit.check_checkpoint(store, master)
        self.assertFalse(ok)
        self.assertIn("faltan líneas", detalle)


class TestFirmaDeCheck(unittest.TestCase):
    """'check' abre el cofre: no puede ir sin firma."""

    def test_check_no_esta_entre_los_esperados(self):
        from cofre.audit import EXPECTED_UNSIGNED
        self.assertNotIn("check", EXPECTED_UNSIGNED)
        # audit-verify se anadio el 2026-11-19: log verify corre con el cofre
        # cerrado y no puede firmar. `check` sigue SIN estar: abre con la llave.
        self.assertEqual(EXPECTED_UNSIGNED,
                         {"gui-gate", "alert", "bridge-reject", "audit-verify"})

    def test_un_check_sin_firma_es_manipulacion(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="cofre-check-"))
        vault = tmp / "cofre.json"
        audit.set_key(secrets.token_bytes(32))
        try:
            audit.record(vault, "reanchor", "usb", ok=True, detail="ancla")
            texto = audit_path(vault).read_text(encoding="utf-8")
            import hashlib
            falso = json.dumps({"seq": 2, "ev": "check", "ok": True,
                                "prev": hashlib.sha256(texto.splitlines()[-1].encode()).hexdigest(),
                                "mac": None}, sort_keys=True, separators=(",", ":"))
            audit_path(vault).write_text(texto + falso + chr(10), encoding="utf-8")
            ok, detalle = audit.verify(vault)
            self.assertFalse(ok)
            self.assertIn("check", detalle)
        finally:
            audit.clear_key()


class TestSellado(unittest.TestCase):
    """Sellado automático: solo cuando lo pendiente es lo esperado."""

    def _cofre(self):
        from cofre.v2 import VaultV2, new_usb_slot
        from cofre.store import open_any
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="cofre-seal-"))
        vp = tmp / "cofre.json"
        master = secrets.token_bytes(32)
        VaultV2(vp).create(master, new_usb_slot(master, secrets.token_bytes(32), 1, "E", ""))
        store = open_any(vp)
        store._data = store._vault.load()
        store.master = master
        return vp, store, master

    def test_sella_los_intentos_esperados(self):
        vp, store, master = self._cofre()
        audit.clear_key()
        for _ in range(3):
            audit.record(vp, "gui-gate", "usb", ok=False, detail="sin pendrive")
        self.assertEqual(audit.pending_unsigned(vp), 3)
        audit.set_key(master)
        audit.bind_store(store)
        self.assertTrue(audit.auto_seal(store, master))
        self.assertEqual(audit.pending_unsigned(vp), 0)
        eventos = [json.loads(l) for l in
                   (vp.parent / ".cofre-audit.jsonl").read_text(encoding="utf-8").splitlines()]
        sellos = [e for e in eventos if e.get("ev") == "seal"]
        self.assertTrue(sellos and sellos[0].get("mac"), "el sello debe ir firmado")

    def test_no_sella_si_hay_algo_raro(self):
        vp, store, master = self._cofre()
        audit.set_key(master)
        audit.bind_store(store)
        audit.record(vp, "get", "usb", 111, name="X")
        # se rompe la cadena a mano: verify falla y no debe sellar
        p = vp.parent / ".cofre-audit.jsonl"
        p.write_text(p.read_text(encoding="utf-8").replace('"ev":"get"', '"ev":"get "'),
                     encoding="utf-8")
        self.assertFalse(audit.auto_seal(store, master))


class TestCheckpoint(unittest.TestCase):
    def test_checkpoint_detecta_lineas_borradas(self):
        from cofre.crypto import Vault
        from cofre.salt import get_salt
        from cofre.store import open_any
        from cofre.v2 import VaultV2, new_usb_slot

        tmp = Path(tempfile.mkdtemp(prefix="cofre-checkpoint-"))
        vp = tmp / "cofre.json"
        master = secrets.token_bytes(32)
        v2 = VaultV2(vp)
        data = v2.create(master, new_usb_slot(master, secrets.token_bytes(32), 111, "E", ""))

        audit.set_key(master)
        try:
            for i in range(3):
                audit.record(vp, "get", "usb", 111, name=f"S{i}")
            store = open_any(vp)
            store._data = data
            store.master = master
            audit.stamp(store, master)
            ok, detalle = audit.check_checkpoint(store, master)
            self.assertTrue(ok, detalle)

            lineas = audit_path(vp).read_text(encoding="utf-8").splitlines()
            audit_path(vp).write_text("\n".join(lineas[:-1]) + "\n", encoding="utf-8")
            ok, detalle = audit.check_checkpoint(store, master)
            self.assertFalse(ok)
            self.assertIn("faltan líneas", detalle)
        finally:
            audit.clear_key()


if __name__ == "__main__":
    unittest.main()


class TestFirmaObligatoria(unittest.TestCase):
    """2026-11-19: `lock` sin clave parece manipulacion; `audit-verify` no.

    El 2026-11-17 la GUI anoto `lock` cuando el cofre no habia llegado a abrirse
    (pendrive retirado al abrir): 17 lineas sin firma que `log verify` marcaba como
    manipulacion. Y `log verify` sin pendrive anotaba `audit-verify` sin firma.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path as _P
        self.tmp = _P(tempfile.mkdtemp(prefix="cofre-firma-"))
        self.vault = self.tmp / "cofre.json"
        self.master = b"k" * 32

    def tearDown(self):
        import shutil
        from cofre import audit as _audit
        _audit.clear_key()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clave_ligada(self):
        from cofre import audit as _audit
        _audit.clear_key()
        self.assertFalse(_audit.clave_ligada())
        _audit.set_key(self.master)
        self.assertTrue(_audit.clave_ligada())

    def test_lock_sin_llave_es_error_de_programa(self):
        # D21 corregido (2026-11-19): un privilegiado sin clave se anota como
        # `sin-clave` (no se disfraza de gui-gate) y verify lo cuenta aparte.
        from cofre import audit as _audit
        _audit.clear_key()
        _audit.record(self.vault, "lock", "usb", 1, detail="sin llave")
        eventos = _audit._events(self.vault)
        self.assertEqual(eventos[0]["ev"], "sin-clave")
        self.assertIn("sin clave: lock", eventos[0]["detail"])
        _audit.set_key(self.master)
        ok, detalle = _audit.verify(str(self.vault))
        self.assertTrue(ok, detalle)
        self.assertIn("errores de programa", detalle)

    def test_audit_verify_puede_ir_sin_firma(self):
        from cofre import audit as _audit
        _audit.clear_key()
        _audit.record(self.vault, "audit-verify", "usb", 1, detail="sin llave")
        _audit.set_key(self.master)
        ok, detalle = _audit.verify(str(self.vault))
        self.assertTrue(ok, detalle)

    def test_lock_con_llave_se_firma(self):
        from cofre import audit as _audit
        _audit.set_key(self.master)
        _audit.record(self.vault, "lock", "usb", 1)
        eventos = [e for e in _audit._events(self.vault) if e.get("ev") == "lock"]
        self.assertTrue(eventos[0].get("mac"))


class TestSinClaveNoHayPrivilegiado(unittest.TestCase):
    """D21 (2026-11-19): sin clave, un evento privilegiado se anota como gui-gate.

    Una ventana con la sesion puesta pero sin llave escribia `get`, `bridge-start` y
    `browser-list` sin firma; el verificador lo llamaba manipulacion. Ahora no puede
    existir: si no hay clave, se degrada a gui-gate con el nombre original.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path as _P
        self.tmp = _P(tempfile.mkdtemp(prefix="cofre-sinclave-"))
        self.vault = self.tmp / "cofre.json"
        from cofre import audit as _audit
        _audit.clear_key()

    def tearDown(self):
        import shutil
        from cofre import audit as _audit
        _audit.clear_key()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_se_anota_como_error_de_programa(self):
        from cofre import audit as _audit
        _audit.record(self.vault, "get", "usb", 1, name="X")
        _audit.record(self.vault, "bridge-start", "usb", 1)
        _audit.record(self.vault, "browser-list", "usb", 1)
        eventos = _audit._events(self.vault)
        self.assertEqual([e["ev"] for e in eventos], ["sin-clave"] * 3)
        self.assertIn("sin clave: get", eventos[0]["detail"])
        self.assertIn("sin clave: bridge-start", eventos[1]["detail"])
        _audit.set_key(b"k" * 32)
        ok, detalle = _audit.verify(str(self.vault))
        self.assertTrue(ok, detalle)
        self.assertIn("3 errores de programa", detalle)

    def test_con_clave_se_firma_normal(self):
        from cofre import audit as _audit
        _audit.set_key(b"k" * 32)
        _audit.record(self.vault, "get", "usb", 1, name="X")
        eventos = _audit._events(self.vault)
        self.assertEqual(eventos[0]["ev"], "get")
        self.assertTrue(eventos[0].get("mac"))


class TestNotaQueExplica(unittest.TestCase):
    """La nota firmada explica líneas sin firma sin mover el ancla (D21).

    Las tres líneas reales del 19-11 (`411 get`, `421 bridge-start`, `422
    browser-list`) son eventos privilegiados escritos por la ventana rota, antes de
    que existiera el tipo `sin-clave`. La nota firmada las da por explicadas y el
    punto de exigencia de firma no se mueve.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path as _P
        from cofre import audit as _audit
        self.tmp = _P(tempfile.mkdtemp(prefix="cofre-nota-"))
        self.vault = self.tmp / "cofre.json"
        self.master = b"k" * 32
        self.ruta = _audit.audit_path(self.vault)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        _audit.set_key(self.master)
        # línea 1: privilegiada sin firma, escrita "a mano" como las de la ventana rota
        base = {"seq": 1, "ts": "2026-11-19T21:36:26", "ev": "get", "entry": "-",
                "name": "X", "actor": "gui", "ok": True, "stick": "1",
                "gate": "usb", "detail": "", "prev": _audit.GENESIS}
        linea1 = _audit._canonical(base).decode("utf-8")
        # línea 2: nota firmada
        nota = {"seq": 2, "ts": "2026-11-19T22:30:00", "ev": "audit-note",
                "entry": "-", "name": "explicadas: 1", "actor": "gui", "ok": True,
                "stick": "-", "gate": "usb",
                "detail": "explica las líneas 1: prueba",
                "prev": _audit._line_hash(linea1)}
        clave = _audit._subkey(self.master)
        import hashlib, hmac
        mac = hmac.new(clave, _audit._canonical(nota), hashlib.sha256).hexdigest()
        nota["mac"] = mac
        self.ruta.write_text(linea1 + "\n" + json.dumps(nota, sort_keys=True,
                                                         separators=(",", ":")) + "\n",
                             encoding="utf-8")

    def tearDown(self):
        import shutil
        from cofre import audit as _audit
        _audit.clear_key()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_la_nota_explica_la_linea(self):
        from cofre import audit as _audit
        ok, detalle = _audit.verify(str(self.vault))
        self.assertTrue(ok, detalle)
        self.assertIn("explicadas por la nota firmada", detalle)

    def test_sin_la_nota_saltaria(self):
        from cofre import audit as _audit
        lineas = self.ruta.read_text(encoding="utf-8").splitlines()
        self.ruta.write_text(lineas[0] + "\n", encoding="utf-8")
        ok, detalle = _audit.verify(str(self.vault))
        self.assertFalse(ok, detalle)
        self.assertIn("sin firma", detalle)
