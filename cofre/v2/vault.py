"""VaultV2: indice cifrado + entradas cifradas, con slots por pendrive.

Estructura en disco (ver plan 1.1.a):

    {"format": 2, "vault_id", "created", "kdf", "slots": [...],
     "index": {"n","c"}, "entries": {entry_id: {"n","c"}}}

El indice descifrado lleva los metadatos de cada secreto, **incluidos los
dominios asignados** (D10): si alguien edita el fichero para anadir evil.com, el
descifrado falla por el AAD y se detecta.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from cofre.paths import atomic_write
from cofre.v2.slots import KDF, SlotError

FORMAT = 2


class Vault2Error(RuntimeError):
    pass


def _hkdf(key: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(key)


def _index_aad(vault_id: str) -> bytes:
    return b"cofre/v2/index|" + vault_id.encode()


def _entry_aad(vault_id: str, entry_id: str) -> bytes:
    return b"cofre/v2/entry|" + vault_id.encode() + b"|" + entry_id.encode()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class VaultV2:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ------------------------------------------------------------ disco

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict) -> None:
        atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True))

    @staticmethod
    def is_v2(data: dict) -> bool:
        return isinstance(data, dict) and data.get("format") == FORMAT

    # ------------------------------------------------------------ sesion

    def create(self, master: bytes, slot: dict) -> dict:
        if self.path.exists():
            raise Vault2Error("ya existe un cofre en esa ruta")
        vault_id = str(uuid.uuid4())
        data = {"format": FORMAT, "vault_id": vault_id, "created": _now(),
                "kdf": dict(KDF), "slots": [slot], "entries": {}}
        self._write_index(data, master, {"entries": {}, "settings": {}})
        self.save(data)
        return data

    def _write_index(self, data: dict, master: bytes, index: dict) -> None:
        key = _hkdf(master, b"cofre/v2/index")
        nonce = secrets.token_bytes(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(index).encode("utf-8"),
                                 _index_aad(data["vault_id"]))
        data["index"] = {"n": nonce.hex(), "c": ct.hex()}

    def index(self, data: dict, master: bytes) -> dict:
        key = _hkdf(master, b"cofre/v2/index")
        try:
            claro = AESGCM(key).decrypt(bytes.fromhex(data["index"]["n"]),
                                        bytes.fromhex(data["index"]["c"]),
                                        _index_aad(data["vault_id"]))
        except (InvalidTag, KeyError) as exc:
            raise Vault2Error(
                "el indice no se puede descifrar: el fichero se ha modificado o la "
                "clave no es de este cofre") from exc
        return json.loads(claro.decode("utf-8"))

    # ------------------------------------------------------------ entradas

    def _entry_key(self, master: bytes) -> bytes:
        return _hkdf(master, b"cofre/v2/entry")

    def _put_value(self, data: dict, master: bytes, entry_id: str, value: str,
                   extra: dict | None = None) -> None:
        key = self._entry_key(master)
        nonce = secrets.token_bytes(12)
        # Se guarda como JSON para poder anadir campos, historial y el valor
        # pendiente de una rotacion sin cambiar el formato del blob.
        contenido = {"value": value, "fields": {}, "history": []}
        contenido.update(extra or {})
        claro = json.dumps(contenido).encode("utf-8")
        ct = AESGCM(key).encrypt(nonce, claro,
                                 _entry_aad(data["vault_id"], entry_id))
        data["entries"][entry_id] = {"n": nonce.hex(), "c": ct.hex()}

    def blob(self, data: dict, master: bytes, name: str) -> dict:
        """Contenido completo de la entrada: valor, historial y pendiente."""
        idx = self.index(data, master)
        meta = idx["entries"].get(name)
        if not meta:
            raise KeyError(name)
        almacenado = data["entries"].get(meta["id"])
        if not almacenado:
            raise KeyError(name)
        key = self._entry_key(master)
        try:
            claro = AESGCM(key).decrypt(bytes.fromhex(almacenado["n"]),
                                        bytes.fromhex(almacenado["c"]),
                                        _entry_aad(data["vault_id"], meta["id"]))
        except InvalidTag as exc:
            raise Vault2Error(f"la entrada '{name}' esta alterada") from exc
        return json.loads(claro.decode("utf-8"))

    def set_blob(self, data: dict, master: bytes, name: str, contenido: dict) -> None:
        idx = self.index(data, master)
        meta = idx["entries"].get(name)
        if not meta:
            raise KeyError(name)
        self._put_value(data, master, meta["id"], str(contenido.get("value", "")),
                        {k: v for k, v in contenido.items() if k != "value"})

    def get(self, data: dict, master: bytes, name: str) -> str:
        idx = self.index(data, master)
        meta = idx["entries"].get(name)
        if not meta:
            raise KeyError(name)
        blob = data["entries"].get(meta["id"])
        if not blob:
            raise KeyError(name)
        key = self._entry_key(master)
        try:
            claro = AESGCM(key).decrypt(bytes.fromhex(blob["n"]), bytes.fromhex(blob["c"]),
                                        _entry_aad(data["vault_id"], meta["id"]))
        except InvalidTag as exc:
            raise Vault2Error(f"la entrada '{name}' esta alterada") from exc
        return json.loads(claro.decode("utf-8"))["value"]

    def put(self, data: dict, master: bytes, name: str, value: str,
            tags: list[str] | None = None, urls: list[str] | None = None,
            kind: str = "api_key") -> dict:
        idx = self.index(data, master)
        existente = idx["entries"].get(name)
        entry_id = existente["id"] if existente else str(uuid.uuid4())
        self._put_value(data, master, entry_id, value)
        meta = existente or {"id": entry_id, "name": name, "created": _now()}
        meta.update({"tags": tags if tags is not None else meta.get("tags", []),
                     "urls": urls if urls is not None else meta.get("urls", []),
                     "type": kind, "updated": _now()})
        idx["entries"][name] = meta
        self._write_index(data, master, idx)
        return data

    def delete(self, data: dict, master: bytes, name: str) -> bool:
        idx = self.index(data, master)
        meta = idx["entries"].pop(name, None)
        if not meta:
            return False
        data["entries"].pop(meta["id"], None)
        self._write_index(data, master, idx)
        return True

    def rename(self, data: dict, master: bytes, old: str, new: str) -> bool:
        idx = self.index(data, master)
        if old not in idx["entries"] or not new or new in idx["entries"]:
            return False
        meta = idx["entries"].pop(old)
        meta["name"] = new
        meta["updated"] = _now()
        idx["entries"][new] = meta
        self._write_index(data, master, idx)
        return True

    def names(self, data: dict, master: bytes) -> list[str]:
        return sorted(self.index(data, master)["entries"])

    def meta(self, data: dict, master: bytes, name: str) -> dict:
        return self.index(data, master)["entries"].get(name, {})

    # ------------------------------------------------------------ dominios (D10)

    def set_urls(self, data: dict, master: bytes, name: str, urls: list[str]) -> dict:
        idx = self.index(data, master)
        meta = idx["entries"].get(name)
        if not meta:
            raise KeyError(name)
        meta["urls"] = list(urls)
        meta["updated"] = _now()
        self._write_index(data, master, idx)
        return data

    def urls(self, data: dict, master: bytes, name: str) -> list[str]:
        return list(self.meta(data, master, name).get("urls", []))

    # ------------------------------------------------------------ slots

    def add_slot(self, data: dict, slot: dict) -> dict:
        data["slots"].append(slot)
        return data

    def remove_slot(self, data: dict, slot_id: str) -> bool:
        antes = len(data["slots"])
        data["slots"] = [s for s in data["slots"] if s.get("id") != slot_id]
        return len(data["slots"]) != antes

    def slots(self, data: dict) -> list[dict]:
        return list(data.get("slots", []))
