"""Pruebas de los ajustes no secretos (paso 6.7)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import alerts, settings


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-set-"))
        self.vault = self.tmp / "cofre.json"
        self.vault.write_text("{}", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_por_defecto(self):
        cfg = settings.load(self.vault)
        self.assertEqual(cfg["idle_minutes"], 10)
        self.assertEqual(cfg["max_hours"], 8)
        self.assertEqual(cfg["clipboard_seconds"], 30)
        self.assertEqual(cfg["gen_lang"], "es")

    def test_guardar_y_releer(self):
        settings.save(self.vault, {"idle_minutes": 5, "clipboard_seconds": 0,
                                   "gen_lang": "en", "backup_folder": r"D:\Cofre"})
        cfg = settings.load(self.vault)
        self.assertEqual(cfg["idle_minutes"], 5)
        self.assertEqual(cfg["clipboard_seconds"], 0)
        self.assertEqual(cfg["gen_lang"], "en")
        self.assertEqual(cfg["backup_folder"], r"D:\Cofre")

    def test_no_pisa_las_alertas(self):
        alerts.write_settings(self.vault, {"burst_count": 7,
                                           "odd_from": 2, "odd_to": 5})
        settings.save(self.vault, {"idle_minutes": 7})
        cfg = alerts.load_settings(self.vault)
        self.assertEqual(cfg["burst_count"], 7)
        self.assertEqual(cfg["odd_from"], 2)
        self.assertEqual(settings.load(self.vault)["idle_minutes"], 7)

    def test_limites(self):
        cfg = settings.clamp({"idle_minutes": 0, "max_hours": 999,
                              "clipboard_seconds": -4, "reveal_seconds": 1,
                              "gen_words": 99, "gen_lang": "fr"})
        self.assertEqual(cfg["idle_minutes"], 1)
        self.assertEqual(cfg["max_hours"], 72)
        self.assertEqual(cfg["clipboard_seconds"], 0)
        self.assertEqual(cfg["reveal_seconds"], 3)
        self.assertEqual(cfg["gen_words"], 8)
        self.assertEqual(cfg["gen_lang"], "es")


if __name__ == "__main__":
    unittest.main()
