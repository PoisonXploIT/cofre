"""Cofre - gates de desbloqueo.

Decision (2026-11-09): la llave FIDO2 se abandona. El interface HID FIDO se
enumera (HID\\VID_096E&PID_0854&MI_01, usage 0xF1D0) pero el driver fidohid.inf
de Windows no deja pasar trafico CTAP2: INIT no responde con timeout de 20 s y
HidD_SetFeature da err=1. No hay gate de hardware posible con esta llave en
esta maquina.

Nivel de seguridad de cada gate:
  hid        : fuerte en teoria. NO FUNCIONA en esta maquina (ver arriba).
  usb        : medio-fuerte. S = scrypt(clave de 32 bytes que solo existe en el
               pendrive). No deriva del hardware: el secreto vive en el USB.
               Quien no tenga el pendrive no puede descifrar el cofre.
               S es determinista: el mismo pendrive da la misma S.
  usb-pin    : dos factores (posesion + conocimiento).
  pin        : debil. Solo pruebas o sobre de recuperacion.
  browser    : WebAuthn prf desde Chrome. Registro OK, asercion pendiente.
               No integrado en resolve_session_key.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from cofre.salt import SaltMismatch, SaltMissing, get_salt


def _scrypt(secret: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=1 << 15, r=8, p=1).derive(secret.encode("utf-8"))


class GateUnavailable(RuntimeError):
    pass


def hid_session_key(nonce: bytes) -> bytes:
    """Deriva la clave de sesión hablando CTAP2 con la llave (hmac-secret)."""
    try:
        from fido2.ctap2 import Ctap2  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise GateUnavailable("fido2 no esta instalado") from exc

    from fido2.hid import CtapHidDevice

    devices = list(CtapHidDevice.list_devices())
    if not devices:
        raise GateUnavailable(
            "no se enumeran dispositivos CTAP2 por HID en Windows. "
            "El driver FIDO del sistema reclama la llave; hace falta el "
            "enumerador propio (ver tools/hid_enum.py)."
        )
    dev = devices[0]
    ctap = Ctap2(dev)
    info = ctap.info
    if "hmac-secret" not in (info.extensions or {}):
        raise GateUnavailable("el autenticador no reporta hmac-secret")
    raise GateUnavailable(
        "enumeracion OK pero el flujo hmac-secret (autenticate con salt) "
        "toda no implementado en esta versión"
    )


def pin_session_key(pin: str, salt: bytes) -> bytes:
    return _scrypt(pin, salt)


def _es_v2(vault_path: str) -> bool:
    """El cofre v2 no usa la sal suelta: cada ranura tiene la suya."""
    try:
        import json
        with open(vault_path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("format") == 2
    except Exception:
        return False


def _salt_for(vault_path: str) -> bytes:
    """H5 y H9: una sola ruta para sacar la sal, y nunca se inventa en silencio.

    Se crea solo si el cofre aun no existe (init). Si el cofre existe y la sal
    no esta, se aborta: regenerarla deja el cofre cerrado para siempre.
    """
    if _es_v2(vault_path):
        # En v2 la sesion de v1 no se usa para descifrar: el material de la
        # llave va aparte (gate.material_for). Se devuelve una sal fija para no
        # exigir un fichero que v2 no tiene.
        return b"cofre-v2-sin-sal"
    try:
        return get_salt(vault_path, create=not Path(vault_path).exists())
    except (SaltMissing, SaltMismatch) as exc:
        raise GateUnavailable(str(exc)) from exc


def usb_session_key(vault_path: str, pin: str = "", stick: str | None = None,
                    allow_new: bool = False) -> tuple[bytes, int | None]:
    """Clave de sesion derivada del fichero COFRE.KEY del pendrive.

    Sin el pendrive no hay S, y el envoltorio del master key es AES-256-GCM con
    256 bits de clave: no se puede fuerza. El USB no deriva la clave, la guarda.
    El serial del volumen debe estar registrado (.cofre-sticks.json); una copia
    del fichero en otro pendrive no vale.
    """
    from cofre.usb import (StickNotFound, StickNotRegistered, RegistryCorrupt,
                           find_stick, usb_session_key as _usb_key)

    try:
        path, serial = find_stick([stick] if stick else None, vault_path, allow_new)
    except (StickNotFound, StickNotRegistered, RegistryCorrupt) as exc:
        raise GateUnavailable(str(exc)) from exc
    return _usb_key(path, _salt_for(vault_path), pin), serial


def material_for(mode: str, vault_path: str, stick: str | None = None,
                 allow_new: bool = False, pin: str | None = None) -> dict:
    """Material de la llave para v2: la llave del pendrive, su serial y el PIN.

    v1 deriva de (llave + sal) y v2 de (llave + PIN) por ranura, asi que el
    material se devuelve aparte y el cofre v2 lo usa con bind_material().
    """
    from cofre.usb import find_stick, read_key

    if mode not in ("usb", "usb-pin"):
        return {}
    try:
        path, serial = find_stick([stick] if stick else None, vault_path, allow_new)
    except Exception:
        return {}
    try:
        return {"stick_key": read_key(path), "serial": serial,
                "pin": pin or "", "stick_path": path}
    except Exception:
        return {}


def pide_pin(vault_path: str) -> bool:
    """¿Alguna ranura de pendrive de este cofre exige la frase (D22)?

    Sirve para que los avisos digan la causa real: si el pendrive esta puesto y
    pide frase, "conecta el pendrive" manda a repetir un gesto inutil.
    """
    try:
        import json
        with open(vault_path, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except Exception:
        return False
    return any(s.get("kind") == "usb" and s.get("pin")
               for s in (datos.get("slots") or []))


def read_pin(prompt: str = "PIN del cofre: ") -> str:
    """COFRE_PIN permite uso no interactivo (scripts, pruebas)."""
    env = os.environ.get("COFRE_PIN")
    if env:
        return env
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    from getpass import getpass

    return getpass(prompt)


def resolve_session_key(mode: str, vault_path: str, nonce: bytes | None = None,
                        stick: str | None = None,
                        allow_new: bool = False,
                        pin: str | None = None) -> tuple[bytes, int | None]:
    """Devuelve (clave de sesion, serial del pendrive usado o None).

    pin: si se pasa, se usa tal cual (la GUI). Si no, se pide por terminal
    o por la variable COFRE_PIN.
    """
    if mode == "hid":
        return hid_session_key(nonce or os.urandom(32)), None
    if mode == "usb":
        return usb_session_key(vault_path, stick=stick, allow_new=allow_new)
    if mode == "usb-pin":
        if pin is None:
            pin = read_pin()
        if not pin:
            # texto neutral: el mismo mensaje sale en la ventana (motivo de la
            # capa de bloqueo) y en la consola. Pedir "pulsa Reconectar" en el
            # CLI o "escribe en el campo" en la consola confundia (2026-11-20).
            raise GateUnavailable("falta la frase del cofre (el PIN)")
        return usb_session_key(vault_path, pin=pin, stick=stick, allow_new=allow_new)
    if mode == "pin":
        return pin_session_key(read_pin(), _salt_for(vault_path)), None
    raise ValueError(f"modo de gate desconocido: {mode}")
