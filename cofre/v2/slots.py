"""Slots del cofre v2: una ranura por pendrive y una de recuperacion.

Cada ranura guarda la clave maestra K envuelta con una clave que se deriva del
material de esa ranura:

  USB       material = COFRE.KEY (32 bytes) [+ PIN utf-8]
  recovery  material = codigo de recuperacion normalizado

AAD distinta por ranura (tipo, id, serial): mover un blob de una ranura a otra,
o cambiar el serial en el JSON, rompe el descifrado. Eso cubre H11 y H12.
"""

from __future__ import annotations

import secrets
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from cofre.v2.recovery import normalize

KDF = {"name": "scrypt", "n": 32768, "r": 8, "p": 1}


class SlotError(RuntimeError):
    pass


def _derive(material: bytes, salt: bytes, kdf: dict) -> bytes:
    return Scrypt(salt=salt, length=32, n=int(kdf["n"]), r=int(kdf["r"]),
                  p=int(kdf["p"])).derive(material)


def _usb_aad(slot_id: str, serial: int) -> bytes:
    return b"cofre/v2/slot|" + slot_id.encode() + b"|usb|" + str(serial).encode()


def _recovery_aad(slot_id: str) -> bytes:
    return b"cofre/v2/slot|" + slot_id.encode() + b"|recovery|"


def _wrap(master: bytes, material: bytes, salt: bytes, aad: bytes, kdf: dict) -> dict:
    key = _derive(material, salt, kdf)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, master, aad)
    return {"n": nonce.hex(), "c": ct.hex()}


def new_usb_slot(master: bytes, stick_key: bytes, serial: int, label: str,
                 pin: str, kdf: dict | None = None) -> dict:
    kdf = kdf or dict(KDF)
    slot_id = str(uuid.uuid4())
    salt = secrets.token_bytes(16)
    material = stick_key + pin.encode("utf-8")
    wrap = _wrap(master, material, salt, _usb_aad(slot_id, serial), kdf)
    return {"id": slot_id, "kind": "usb", "serial": int(serial), "label": label,
            "pin": bool(pin), "salt": salt.hex(), "wrap": wrap}


def new_recovery_slot(master: bytes, code: str, label: str,
                      kdf: dict | None = None) -> dict:
    kdf = kdf or dict(KDF)
    slot_id = str(uuid.uuid4())
    salt = secrets.token_bytes(16)
    material = normalize(code).encode("utf-8")
    wrap = _wrap(master, material, salt, _recovery_aad(slot_id), kdf)
    return {"id": slot_id, "kind": "recovery", "label": label,
            "salt": salt.hex(), "wrap": wrap}


def try_open_slot(slot: dict, material: bytes, kdf: dict | None = None) -> bytes | None:
    """Devuelve K o None. Nunca lanza por InvalidTag."""
    kdf = kdf or KDF
    try:
        if slot.get("kind") == "usb":
            aad = _usb_aad(str(slot["id"]), int(slot["serial"]))
        else:
            aad = _recovery_aad(str(slot["id"]))
        key = _derive(material, bytes.fromhex(slot["salt"]), kdf)
        return AESGCM(key).decrypt(bytes.fromhex(slot["wrap"]["n"]),
                                   bytes.fromhex(slot["wrap"]["c"]), aad)
    except (InvalidTag, KeyError, ValueError):
        return None


def open_with_stick(vault: dict, stick_key: bytes, serial: int,
                    pin: str = "", kdf: dict | None = None) -> tuple[bytes, dict]:
    candidatos = [s for s in vault.get("slots", [])
                  if s.get("kind") == "usb" and int(s.get("serial", -1)) == int(serial)]
    if not candidatos:
        raise SlotError("ese pendrive no tiene ranura en este cofre")
    material = stick_key + pin.encode("utf-8")
    for slot in candidatos:
        master = try_open_slot(slot, material, kdf)
        if master:
            return master, slot
    raise SlotError("la llave del pendrive no abre su ranura (PIN incorrecto o llave ajena)")


def open_with_recovery(vault: dict, code: str, kdf: dict | None = None) -> tuple[bytes, dict]:
    material = normalize(code).encode("utf-8")
    for slot in vault.get("slots", []):
        if slot.get("kind") != "recovery":
            continue
        master = try_open_slot(slot, material, kdf)
        if master:
            return master, slot
    raise SlotError("el codigo de recuperacion no abre este cofre")
