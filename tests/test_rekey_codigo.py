"""M1 de la revisión independiente (2026-11-19): el código se apunta antes de guardar.

Fallo: `rekey_vivo` escribía el cofre re-cifrado y **después** devolvía el código
nuevo. Si el cofre se había abierto con el código de papel (sin pendrive), el cofre
nuevo solo tiene esa ranura: un corte antes de ver el código dejaba el cofre
imposible de abrir.

Ahora, cuando no queda ninguna ranura de pendrive, se enseña el código y se piden
dos palabras por su posición antes de escribir; si no coinciden, el cofre no se toca.

Prueba: se prepara un rekey sobre un cofre que solo tiene código de recuperación y se
comprueba que el fichero **no cambia** si la confirmación falla.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


class TestCodigoAntesDeGuardar(unittest.TestCase):
    def setUp(self):
        from cofre.firstuse import crear_cofre
        from cofre.gate import material_for
        from cofre.crypto import Vault
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-m1-"))
        self.vault_path = self.tmp / "cofre.json"
        self.key = self.tmp / "COFRE.KEY"
        # crear_cofre deja una ranura usb Y una de recuperación
        self.estado = crear_cofre(self.vault_path, str(self.tmp.drive) + "\\",
                                  clave=self.key)
        # quitar la ranura usb para simular "abierto solo con el papel"
        from cofre.v2 import VaultV2
        v2 = VaultV2(self.vault_path)
        datos = v2.load()
        datos["slots"] = [s for s in datos["slots"] if s.get("kind") != "usb"]
        v2.save(datos)
        self.material = {"recovery": True}
        self.vault = Vault(self.vault_path)
        self.vault.bind_recovery(self.estado["código"])
        self.store = self.vault._v2store()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rekey(self, confirmar):
        from cofre.cli import rekey_vivo
        return rekey_vivo(self.vault, self.vault_path, self.material,
                          motivo="prueba", gate="usb", serial=None,
                          actor="cli", confirmar=confirmar)

    def test_sin_confirmar_no_se_escribe(self):
        antes = self.vault_path.read_bytes()
        codigo, perdidos, error = self._rekey(lambda c: False)
        self.assertEqual(codigo, "")
        self.assertIn("no se ha confirmado", error)
        despues = self.vault_path.read_bytes()
        self.assertEqual(antes, despues, "el cofre se tocó sin confirmar el código")

    def test_confirmando_si_se_escribe_y_abre(self):
        visto = {}

        def confirmar(codigo):
            visto["código"] = codigo
            return True

        codigo, perdidos, error = self._rekey(confirmar)
        self.assertIsNone(error)
        self.assertEqual(codigo, visto.get("código"))
        # el código nuevo abre el cofre recién escrito
        from cofre.v2 import VaultV2
        from cofre.v2.slots import open_with_recovery
        datos = VaultV2(self.vault_path).load()
        master, _slot = open_with_recovery(datos, codigo)
        self.assertTrue(master)


if __name__ == "__main__":
    unittest.main()
