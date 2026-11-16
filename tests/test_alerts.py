"""Pruebas de las reglas de alerta (paso 3.2)."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.alerts import (AlertState, DEFAULTS, apply_cooldown, describe,
                          evaluate, load_settings, write_settings)


def ev(seq: int, tipo: str, ts: datetime, ok: bool = True, name: str = "-",
       detail: str = "") -> dict:
    return {"seq": seq, "ev": tipo, "ts": ts.isoformat(timespec="seconds"),
            "ok": ok, "name": name, "detail": detail}


class TestRules(unittest.TestCase):
    def setUp(self):
        self.ahora = datetime(2026, 11, 16, 14, 0, 0)
        self.state = AlertState()

    def test_solo_evalua_lo_nuevo(self):
        eventos = [ev(1, "get", self.ahora)]
        primera = evaluate(eventos, {}, self.state)
        segunda = evaluate(eventos, {}, self.state)
        self.assertEqual(self.state.last_seq, 1)
        self.assertEqual(len(segunda), 0, "no debe reevaluar lo ya visto")
        self.assertTrue(primera is not None)

    def test_senuelo_es_critico(self):
        eventos = [ev(1, "canary-access", self.ahora, ok=False, name="AWS_PROD_KEY")]
        alertas = evaluate(eventos, {}, self.state)
        self.assertTrue(any(a.rule == "senuelo" and a.severity == "critica" for a in alertas))

    def test_rafaga_de_lecturas(self):
        eventos = [ev(i, "get", self.ahora - timedelta(seconds=i)) for i in range(1, 13)]
        alertas = evaluate(eventos, {"burst_count": 10, "burst_minutes": 5}, self.state,
                           now=self.ahora.timestamp())
        self.assertTrue(any(a.rule == "rafaga" for a in alertas))

    def test_fallos_de_apertura(self):
        eventos = [ev(i, "gui-gate", self.ahora, ok=False) for i in range(1, 4)]
        alertas = evaluate(eventos, {"open_failures": 3}, self.state)
        self.assertTrue(any(a.rule == "fallos-apertura" for a in alertas))

    def test_hora_rara(self):
        madrugada = datetime(2026, 11, 16, 3, 30)
        eventos = [ev(1, "get", madrugada)]
        alertas = evaluate(eventos, {"odd_from": 1, "odd_to": 6}, self.state)
        self.assertTrue(any(a.rule == "hora-rara" for a in alertas))

    def test_reanclaje_avisa_media(self):
        eventos = [ev(1, "reanchor", self.ahora, detail="prueba")]
        alertas = evaluate(eventos, {}, self.state)
        media = [a for a in alertas if a.rule == "reanclaje"]
        self.assertTrue(media)
        self.assertEqual(media[0].severity, "media")

    def test_puente_con_origen_rechazado(self):
        eventos = [ev(1, "bridge-reject", self.ahora, ok=False, detail="origen no autorizado")]
        alertas = evaluate(eventos, {}, self.state)
        self.assertTrue(any(a.rule == "puente" for a in alertas))

    def test_log_manipulado(self):
        eventos = [ev(1, "audit-verify", self.ahora, ok=False, detail="cadena rota")]
        alertas = evaluate(eventos, {}, self.state)
        self.assertTrue(any(a.rule == "log-manipulado" and a.severity == "critica"
                            for a in alertas))

    def test_pausa_por_regla(self):
        eventos = [ev(1, "canary-access", self.ahora, ok=False)]
        primeras = apply_cooldown(evaluate(eventos, {}, self.state), self.state, {}, now=1000)
        self.assertEqual(len(primeras), 1)
        # la misma regla otra vez, dentro de la pausa
        eventos2 = [ev(2, "canary-access", self.ahora, ok=False)]
        segunda = apply_cooldown(evaluate(eventos2, {}, self.state), self.state,
                                 {"cooldown_minutes": 10}, now=1060)
        self.assertEqual(segunda, [])
        # pasado el plazo, vuelve
        eventos3 = [ev(3, "canary-access", self.ahora, ok=False)]
        tercera = apply_cooldown(evaluate(eventos3, {}, self.state), self.state,
                                 {"cooldown_minutes": 10}, now=1000 + 601)
        self.assertEqual(len(tercera), 1)


class TestSettings(unittest.TestCase):
    def test_umbrales_configurables(self):
        import tempfile
        from pathlib import Path as P
        tmp = P(tempfile.mkdtemp())
        vault = tmp / "cofre.json"
        write_settings(vault, {"burst_count": 3, "odd_from": 2})
        cfg = load_settings(vault)
        self.assertEqual(cfg["burst_count"], 3)
        self.assertEqual(cfg["odd_from"], 2)
        self.assertEqual(cfg["burst_minutes"], DEFAULTS["burst_minutes"])

    def test_describe_elige_la_peor(self):
        from cofre.alerts import Alert
        alertas = [Alert("a", "baja", "una"), Alert("b", "critica", "otra")]
        self.assertIn("CRITICA", describe(alertas))


if __name__ == "__main__":
    unittest.main()
