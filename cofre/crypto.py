"""Cofre - capa criptografica (verificado 2026-11-09).

Dos capas:
  1. Clave maestra K, guardada envuelta (wrapped) con una clave de sesion S.
  2. Cada secreto individual cifrado con AES-256-GCM bajo K.

S procede del gate elegido (pendrive USB, opcionalmente + PIN).
Con el gate USB, S es determinista: el mismo pendrive da siempre la misma S.
Sin S, el envoltorio no se puede descifrar (AES-256-GCM, 2^256).
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from cofre.paths import atomic_write
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

WRAP_VERSION = 1


def _aesgcm(key: bytes) -> AESGCM:
    return AESGCM(key)


def new_master_key() -> bytes:
    return secrets.token_bytes(32)


def wrap_key(master: bytes, session: bytes) -> dict:
    nonce = secrets.token_bytes(12)
    ct = _aesgcm(session).encrypt(nonce, master, None)
    return {"v": WRAP_VERSION, "nonce": nonce.hex(), "ct": ct.hex()}


def unwrap_key(wrapper: dict, session: bytes) -> bytes:
    if wrapper.get("v") != WRAP_VERSION:
        raise ValueError("version de envoltorio no soportada")
    return _aesgcm(session).decrypt(bytes.fromhex(wrapper["nonce"]), bytes.fromhex(wrapper["ct"]), None)


def encrypt(master: bytes, plaintext: bytes) -> dict:
    nonce = secrets.token_bytes(12)
    ct = _aesgcm(master).encrypt(nonce, plaintext, None)
    return {"nonce": nonce.hex(), "ct": ct.hex()}


def decrypt(master: bytes, blob: dict) -> bytes:
    return _aesgcm(master).decrypt(bytes.fromhex(blob["nonce"]), bytes.fromhex(blob["ct"]), None)


class Vault:
    """Cofre. Si el fichero esta en formato v2, delega en cofre.store.V2Store.

    Asi CLI, GUI y puente siguen llamando igual (con `session`) y no tienen que
    saber en que formato esta el cofre. Para v2 hace falta `bind_material()` con
    la llave del pendrive: la `session` de v1 no sirve porque v2 no deriva de la
    sal suelta sino de la llave de cada ranura.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._material: dict | None = None
        self._v2 = None

    # ---------------------------------------------------------------- v2

    def bind_material(self, material: dict | None) -> "Vault":
        self._material = material
        return self

    def _v2store(self):
        if self._v2 is None:
            from cofre.store import V2Store
            self._v2 = V2Store(self.path, material=self._material)
        return self._v2

    def is_v2(self) -> bool:
        try:
            return self.load().get("format") == 2
        except Exception:
            return False

    def load(self) -> dict:
        if not self.path.exists():
            return {"wrapper": None, "entries": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict) -> None:
        # H7: escritura atómica (tmp + os.replace), no write() a secas.
        atomic_write(self.path, json.dumps(data, indent=2))

    def urls(self, name: str) -> list[str]:
        if self.is_v2():
            return self._v2store().urls(name)
        from cofre import hosts
        try:
            return hosts.hosts_for(self.path, name)
        except hosts.HostsError:
            return []

    def set_urls(self, name: str, urls: list[str]) -> None:
        if self.is_v2():
            self._v2store().set_urls(name, urls)
            return
        from cofre import hosts
        hosts.assign(self.path, name, urls)

    def init(self, session: bytes, salt: bytes | None = None) -> bytes:
        data = self.load()
        if data.get("wrapper"):
            raise ValueError("el cofre ya existe")
        master = new_master_key()
        data["wrapper"] = wrap_key(master, session)
        data["entries"] = {}
        if salt:
            # H9: la sal viaja con el cofre. Un backup de cofre.json es un
            # backup completo; sin la sal, el cofre no se puede reabrir.
            data["salt"] = salt.hex()
        self.save(data)
        return master

    def unlock(self, session: bytes) -> bytes:
        if self.is_v2():
            return self._v2store().unlock()
        data = self.load()
        if not data.get("wrapper"):
            raise FileNotFoundError("no hay cofre inicializado")
        return unwrap_key(data["wrapper"], session)

    def add(self, session: bytes, name: str, value: str, tags: list[str] | None = None,
            urls: list[str] | None = None) -> None:
        if self.is_v2():
            self._v2store().add(name, value, tags=tags, urls=urls)
            return
        master = self.unlock(session)
        data = self.load()
        data["entries"][name] = {
            "blob": encrypt(master, value.encode("utf-8")),
            "tags": tags or [],
            "kind": "secret",
        }
        self.save(data)

    def get(self, session: bytes, name: str) -> str:
        if self.is_v2():
            return self._v2store().get(name)
        master = self.unlock(session)
        data = self.load()
        if name not in data["entries"]:
            raise KeyError(name)
        return decrypt(master, data["entries"][name]["blob"]).decode("utf-8")

    def rename(self, session: bytes, old: str, new: str) -> bool:
        """Cambiar el nombre de una entrada sin tocar su blob cifrado."""
        if self.is_v2():
            return self._v2store().rename(old, new)
        self.unlock(session)
        data = self.load()
        entries = data.get("entries", {})
        if old not in entries or not new or new in entries:
            return False
        entries[new] = entries.pop(old)
        self.save(data)
        return True

    def delete(self, session: bytes, name: str) -> bool:
        if self.is_v2():
            return self._v2store().delete(name)
        """Borra una entrada. Cada secreto esta cifrado aparte, asi que quitar
        su blob no afecta a los demas."""
        self.unlock(session)  # valida que la sesion es correcta
        data = self.load()
        if name not in data.get("entries", {}):
            return False
        del data["entries"][name]
        self.save(data)
        return True

    def names(self) -> list[str]:
        if self.is_v2():
            return self._v2store().names()
        return sorted(self.load().get("entries", {}))

    def meta(self, name: str) -> dict:
        if self.is_v2():
            return self._v2store().meta(name)
        return self.load().get("entries", {}).get(name, {})
