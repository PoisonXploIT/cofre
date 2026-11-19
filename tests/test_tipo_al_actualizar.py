"""A1 de la revisión independiente (2026-11-19): cambiar el valor conserva el tipo.

Fallo: `VaultV2.put` ponía `type: api_key` siempre, también al reescribir una
entrada existente. Con eso, editar un señuelo lo convertía en clave normal (se
entrega y no avisa), una clave privada perdía la confirmación y una contraseña
dejaba de rellenarse en el navegador.

Regla: si no se dice otro tipo, se conserva el que tenía; si la entrada es nueva,
`api_key`.
"""

from __future__ import annotations

import secrets
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import policy                                   # noqa: E402
from cofre.crypto import Vault                             # noqa: E402
from cofre.v2 import VaultV2, new_usb_slot                 # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        from cofre.salt import get_salt
        from cofre.store import open_any
        from cofre.usb import register_stick, usb_session_key, volume_serial
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-tipo-"))
        self.vault_path = self.tmp / "cofre.json"
        self.key = self.tmp / "COFRE.KEY"
        self.key.write_bytes(secrets.token_bytes(32))
        master = secrets.token_bytes(32)
        v2 = VaultV2(self.vault_path)
        datos = v2.create(master, new_usb_slot(master, self.key.read_bytes(), 1, "t", ""))
        for nombre, tipo in (("SENUELO", "canary"), ("CLAVE", "private_key"),
                             ("BANCO", "password"), ("TOKEN", "api_token")):
            v2.put(datos, master, nombre, "valor-viejo-" + nombre, [], [], kind=tipo)
        v2.save(datos)
        salt = get_salt(str(self.vault_path), create=True)
        self.session = usb_session_key(str(self.key), salt)
        self.vault = Vault(self.vault_path)
        # la ranura se creo con serial 1 y estos 32 bytes: se liga el material para
        # que el Vault pueda escribir (como hace la GUI al abrir)
        self.vault.bind_material({"stick_key": self.key.read_bytes(), "serial": 1,
                                  "pin": ""})
        self.store = open_any(self.vault_path)
        self.store._data = self.store._vault.load()
        self.store.master = master
        self.master = master
        self.v2 = self.store._vault

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _indice(self) -> dict:
        # el mismo store que usa el Vault (no una copia cargada aparte)
        store = self.vault._v2store()
        return store.index(store._data, store.master)

    def tipo(self, nombre: str) -> str:
        return str((self._indice().get("entries") or {}).get(nombre, {}).get("type"))

    def meta(self, nombre: str) -> dict:
        return dict((self._indice().get("entries") or {}).get(nombre) or {})


class TestConservaElTipo(Base):
    def test_el_senuelo_sigue_siendo_senuelo(self):
        self.vault.add(self.session, "SENUELO", "valor-nuevo")
        self.assertEqual(self.tipo("SENUELO"), "canary")
        meta = self.meta("SENUELO")
        meta["name"] = "SENUELO"
        permitido, _motivo = policy.allowed(meta, "browser")
        self.assertFalse(permitido, "un señuelo editado se entregaría")

    def test_la_clave_privada_sigue_pidiendo_confirmacion(self):
        self.vault.add(self.session, "CLAVE", "-----BEGIN-----nueva")
        self.assertEqual(self.tipo("CLAVE"), "private_key")
        self.assertTrue(policy.effective(self.meta("CLAVE"))["confirm"])

    def test_la_contrasena_sigue_rellenandose_en_el_navegador(self):
        self.vault.add(self.session, "BANCO", "otra-contraseña")
        self.assertEqual(self.tipo("BANCO"), "password")
        self.assertTrue(policy.effective(self.meta("BANCO"))["browser"])

    def test_el_token_sigue_siendo_api_token(self):
        self.vault.add(self.session, "TOKEN", "valor-nuevo")
        self.assertEqual(self.tipo("TOKEN"), "api_token")

    def test_entrada_nueva_es_api_key(self):
        self.vault.add(self.session, "NUEVO", "valor")
        self.assertEqual(self.tipo("NUEVO"), "api_key")

    def test_se_puede_cambiar_el_tipo_a_proposito(self):
        self.vault.add(self.session, "TOKEN", "valor", kind="password")
        self.assertEqual(self.tipo("TOKEN"), "password")


class TestUnaSolaEscritura(Base):
    def test_add_con_tipo_no_pasa_por_api_key(self):
        # antes: se guardaba como api_key y luego se parcheaba el índice; si se
        # cortaba entre medias, quedaba api_key
        self.vault.add(self.session, "OTRO", "valor", kind="canary")
        self.assertEqual(self.tipo("OTRO"), "canary")


if __name__ == "__main__":
    unittest.main()
