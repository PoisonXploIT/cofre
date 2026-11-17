"""Pruebas de la sesion (2.1) y de las politicas (2.3)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.policy import allowed, effective, needs_confirm
from cofre.session import Session


class FakeClock:
    def __init__(self):
        self.mono = 1000.0
        self.wall = 1_700_000_000.0

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += seconds


class TestSession(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.s = Session({"idle_minutes": 10, "max_hours": 8},
                         now=lambda: self.clock.mono,
                         wall=lambda: self.clock.wall)

    def test_recien_abierta_no_bloquea(self):
        self.assertIsNone(self.s.check())

    def test_inactividad(self):
        self.clock.advance(9 * 60)
        self.assertIsNone(self.s.check())
        self.clock.advance(2 * 60)
        self.assertEqual(self.s.check(), "inactividad")

    def test_tocar_la_sesion_la_mantiene_viva(self):
        for _ in range(5):
            self.clock.advance(5 * 60)
            self.s.touch()
        self.assertIsNone(self.s.check())

    def test_tiempo_maximo_aunque_haya_actividad(self):
        for _ in range(9):
            self.clock.advance(60 * 60)
            self.s.touch()
        self.assertEqual(self.s.check(), "tiempo maximo")

    def test_suspension_por_salto_de_reloj(self):
        # el monotono avanza 1 s pero el reloj de pared salta una hora
        self.clock.wall += 3600
        self.clock.mono += 1
        self.assertEqual(self.s.check(), "el equipo estuvo suspendido")

    def test_bloqueo_de_windows(self):
        # la sonda del 2026-11-17 confirmo que OpenInputDesktop distingue aqui
        estado = {"bloqueada": False}
        s = Session({"idle_minutes": 60, "max_hours": 8},
                    now=lambda: self.clock.mono, wall=lambda: self.clock.wall,
                    lock_state=lambda: estado["bloqueada"])
        self.assertIsNone(s.check())
        estado["bloqueada"] = True
        self.assertEqual(s.check(), "windows bloqueado")
        estado["bloqueada"] = False
        self.assertIsNone(s.check())
        estado["bloqueada"] = True
        self.assertEqual(s.check(), "windows bloqueado")

    def test_no_bloquea_si_se_abre_ya_bloqueada(self):
        # abrir el cofre con la sesion bloqueada no debe cerrarlo al instante
        s = Session({"idle_minutes": 60}, now=lambda: self.clock.mono,
                    wall=lambda: self.clock.wall, lock_state=lambda: True)
        self.assertIsNone(s.check())

    def test_sin_dato_de_bloqueo_no_adivina(self):
        s = Session({"idle_minutes": 60}, now=lambda: self.clock.mono,
                    wall=lambda: self.clock.wall, lock_state=lambda: None)
        self.assertIsNone(s.check())

    def test_describe_en_espanol(self):
        self.assertIn("inactividad", self.s.describe("inactividad"))
        self.assertIn("suspendido", self.s.describe("el equipo estuvo suspendido"))


class TestPolicy(unittest.TestCase):
    def test_private_key_no_va_al_navegador(self):
        meta = {"type": "private_key"}
        self.assertFalse(allowed(meta, "browser")[0])
        self.assertTrue(needs_confirm(meta))

    def test_admin_por_etiqueta(self):
        meta = {"type": "api_token", "tags": ["admin"]}
        self.assertFalse(allowed(meta, "browser")[0])
        self.assertFalse(allowed(meta, "exec")[0])
        self.assertTrue(needs_confirm(meta))

    def test_password_va_al_navegador(self):
        meta = {"type": "password"}
        self.assertTrue(allowed(meta, "browser")[0])
        self.assertFalse(allowed(meta, "exec")[0])

    def test_api_key_va_a_exec(self):
        meta = {"type": "api_key"}
        self.assertTrue(allowed(meta, "exec")[0])
        self.assertFalse(allowed(meta, "browser")[0])

    def test_politica_explicita_manda(self):
        meta = {"type": "api_key", "policy": {"browser": True}}
        self.assertTrue(allowed(meta, "browser")[0])

    def test_canary_no_sale_por_ningun_sitio(self):
        # un senuelo no se entrega nunca, ni siquiera confirmando: pedirlo tiene
        # que disparar alerta, no un dialogo
        meta = {"type": "canary", "name": "AWS_PROD_KEY"}
        for canal in ("browser", "exec", "clipboard", "reveal"):
            ok, motivo = allowed(meta, canal)
            self.assertFalse(ok, canal)
            self.assertIn("senuelo", motivo)
        self.assertFalse(needs_confirm(meta))

    def test_canal_invalido(self):
        self.assertFalse(allowed({"type": "api_key"}, "pantalla")[0])

    def test_motivo_menciona_el_nombre(self):
        meta = {"name": "GH_TOKEN", "type": "api_key"}
        ok, motivo = allowed(meta, "browser")
        self.assertFalse(ok)
        self.assertIn("GH_TOKEN", motivo)

    def test_effective_no_muta_el_meta(self):
        meta = {"type": "api_key"}
        effective(meta)
        self.assertNotIn("policy", meta)


class TestPermisosTemporales(unittest.TestCase):
    """2.4: 'Permitir 5 minutos' no sobrevive a un bloqueo."""

    def test_se_borran_al_bloquear(self):
        sys.path.insert(0, str(REPO))
        import tkinter as tk
        from cofre.gui import CofreGUI

        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("sin pantalla para Tk")
        root.withdraw()
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="cofre-perms-"))
        try:
            app = CofreGUI(str(tmp / "cofre.json"), "usb")
            app.build()          # sin widgets, lock() no tiene donde escribir
            app.confirm_grants[("CLOUDFLARE_DNS_TOKEN", "Navegador")] = 10 ** 12
            self.assertTrue(app.confirm_grants)
            app.lock()
            self.assertFalse(app.confirm_grants,
                             "los permisos de 5 minutos siguen vivos tras bloquear")
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
