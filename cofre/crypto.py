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
import os
import secrets
from pathlib import Path

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
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {"wrapper": None, "entries": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def init(self, session: bytes) -> bytes:
        data = self.load()
        if data.get("wrapper"):
            raise ValueError("el cofre ya existe")
        master = new_master_key()
        data["wrapper"] = wrap_key(master, session)
        data["entries"] = {}
        self.save(data)
        return master

    def unlock(self, session: bytes) -> bytes:
        data = self.load()
        if not data.get("wrapper"):
            raise FileNotFoundError("no hay cofre inicializado")
        return unwrap_key(data["wrapper"], session)

    def add(self, session: bytes, name: str, value: str, tags: list[str] | None = None) -> None:
        master = self.unlock(session)
        data = self.load()
        data["entries"][name] = {
            "blob": encrypt(master, value.encode("utf-8")),
            "tags": tags or [],
            "kind": "secret",
        }
        self.save(data)

    def get(self, session: bytes, name: str) -> str:
        master = self.unlock(session)
        data = self.load()
        if name not in data["entries"]:
            raise KeyError(name)
        return decrypt(master, data["entries"][name]["blob"]).decode("utf-8")

    def delete(self, session: bytes, name: str) -> bool:
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
        return sorted(self.load().get("entries", {}))
