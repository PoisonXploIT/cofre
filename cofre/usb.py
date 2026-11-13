"""Cofre - gate de USB convencional.

Un pendrive no deriva la clave: la GUARDA. La diferencia con la llave FIDO2 es
honesta y hay que decirla:

  - FIDO2 (hmac-secret): el secreto se deriva dentro del hardware, no existe
    en ningun fichero, y puede cambiar en cada toque.
  - USB normal: aqui hay 32 bytes aleatorios en un fichero del pendrive. El gate
    sigue siendo real (quien no tenga el pendrive no puede descifrar el cofre,
    2^256), pero es posesion, no derivacion de hardware.

Lo que si se consigue de verdad:
  - el master key envuelto con una clave que solo esta en el pendrive;
  - sin el pendrive, descifrar cofre.json es brute force de 2^256;
  - se puede combinar con PIN (dos factores: lo que tienes + lo que sabes).

Control de serial (implementado el 2026-11-09):
  - cada pendrive autorizado se registra por su numero de serie de volumen en
    .cofre-sticks.json (junto al cofre);
  - un COFRE.KEY copiado a un pendrive distinto NO desbloquea, porque el serial
    no coincide;
  - eso frena la copia casual. Un atacante determinado puede clonar el volumen
    entero con su serial (dd + reescritura del BPB de NTFS), asi que esto es
    defensa en profundidad, no una muralla.

No hay fallback silencioso: si el gate falla, el cofre no se abre.
"""

from __future__ import annotations

import ctypes
import json
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from cofre.paths import REGISTRY_NAME, atomic_write, default_vault

KEY_FILENAME = "COFRE.KEY"


class StickNotFound(RuntimeError):
    """No hay ningún fichero COFRE.KEY accesible."""


class StickNotRegistered(RuntimeError):
    """Hay un COFRE.KEY, pero su volumen no está en la lista autorizada."""


class RegistryCorrupt(RuntimeError):
    """El fichero de pendrives autorizados existe pero no se puede leer.

    H13: antes esto se traducía silenciosamente en "registro vacío", y un
    registro vacío autoriza cualquier pendrive con COFRE.KEY. Un JSON roto no
    puede ser una puerta abierta."""""


def drive_letters() -> list[str]:
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{c}:\\" for c in string.ascii_uppercase if mask & (1 << (ord(c) - 65))]


def volume_serial(drive: str) -> int | None:
    buf = ctypes.create_string_buffer(64)
    serial = ctypes.c_ulong(0)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive), buf, ctypes.sizeof(buf),
        ctypes.byref(serial), None, None, None, 0,
    )
    if not ok:
        return None
    return int(serial.value)


def volume_label(drive: str) -> str:
    buf = ctypes.create_string_buffer(64)
    serial = ctypes.c_ulong(0)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive), buf, ctypes.sizeof(buf),
        ctypes.byref(serial), None, None, None, 0,
    )
    if not ok:
        return ""
    label = buf.value.decode("utf-8", errors="replace").strip()
    # Windows deja basura en el buffer cuando el volumen no tiene etiqueta
    return label if len(label) >= 2 else ""


def registry_path(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / REGISTRY_NAME


def load_registry(vault_path: str | Path, strict: bool = True) -> dict:
    """Leer la lista de pendrives autorizados.

      - fichero inexistente  -> registro vacío (es la primera vez)
      - fichero corrupto     -> RegistryCorrupt si strict; vacío si no
    """
    p = registry_path(vault_path)
    if not p.exists():
        return {"sticks": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        if strict:
            raise RegistryCorrupt(
                f"{p} esta corrupto y no se puede leer ({exc}). "
                "No se autoriza ningun pendrive hasta arreglarlo: borralo y "
                "registra de nuevo con 'python -m cofre.cli stick-register E:\\COFRE.KEY'"
            ) from exc
        return {"sticks": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sticks"), dict):
        if strict:
            raise RegistryCorrupt(f"{p} no tiene la forma esperada ({'sticks': {...}})")
        return {"sticks": {}}
    return data


def save_registry(vault_path: str | Path, reg: dict) -> Path:
    # H7: escritura atómica. Un corte de luz no puede dejar el registro a medias.
    return atomic_write(registry_path(vault_path), json.dumps(reg, indent=2))


def register_stick(vault_path: str | Path, serial: int, drive: str = "",
                   role: str | None = None) -> dict:
    reg = load_registry(vault_path)
    if role is None:
        # primera llave = principal, las siguientes = reserva
        role = "principal" if not reg.get("sticks") else "reserva"
    if role not in ("principal", "reserva"):
        raise ValueError("role debe ser principal o reserva")
    entry = {
        "serial": int(serial),
        "drive": drive,
        "label": volume_label(drive) if drive else "",
        "role": role,
        "registered": datetime.now().isoformat(timespec="seconds"),
    }
    reg = load_registry(vault_path)
    reg["sticks"][str(int(serial))] = entry
    save_registry(vault_path, reg)
    return entry


def set_role(vault_path: str | Path, serial: int, role: str) -> dict | None:
    """Declarar explicitamente si un pendrive es principal o reserva."""
    reg = load_registry(vault_path)
    entry = reg.get("sticks", {}).get(str(int(serial)))
    if not entry:
        return None
    entry["role"] = role
    save_registry(vault_path, reg)
    return entry


def revoke_stick(vault_path: str | Path, serial: int) -> bool:
    """Quitar un pendrive de la lista. Si es el unico, avisar: se pierde el acceso."""
    reg = load_registry(vault_path)
    key = str(int(serial))
    if key not in reg.get("sticks", {}):
        return False
    del reg["sticks"][key]
    save_registry(vault_path, reg)
    return True


def is_registered(vault_path: str | Path, serial: int | None) -> bool:
    if serial is None:
        return False
    return str(int(serial)) in load_registry(vault_path).get("sticks", {})


def _candidates(extra_paths: list[str] | None) -> list[tuple[str, int | None, str]]:
    out: list[tuple[str, int | None, str]] = []
    for extra in extra_paths or []:
        p = Path(extra)
        if p.is_file():
            drive = str(p.resolve())[:3]  # "C:\" etc.
            out.append((str(p), volume_serial(drive), volume_label(drive)))
    for drive in drive_letters():
        p = Path(drive) / KEY_FILENAME
        if p.is_file():
            out.append((str(p), volume_serial(drive), volume_label(drive)))
    return out


def find_stick(extra_paths: list[str] | None = None, vault_path: str | Path | None = None,
               allow_new: bool = False) -> tuple[str, int | None]:
    """Devuelve (ruta, serial) del pendrive autorizado.

    Reglas (H13 corregida el 2026-11-13):
      - no hay registro: no se autoriza NINGUNO salvo que se diga explicitamente
        (--allow-new-stick o stick-register). Antes se autorizaban todos los
        volúmenes con COFRE.KEY y se registraban solos;
      - registro corrupto: fallo cerrado, no vacío;
      - con registro, solo pasa un serial registrado, salvo allow_new.
    """
    cands = _candidates(extra_paths)
    if not cands:
        raise StickNotFound(
            f"no se encontro {KEY_FILENAME} en ningun volumen. "
            "Conecta el pendrive o us --stick E:\\COFRE.KEY"
        )

    if vault_path is None:
        vault_path = default_vault()

    reg = load_registry(vault_path)  # lanza RegistryCorrupt si esta roto
    if not reg.get("sticks"):
        if not allow_new:
            seen = ", ".join(str(s) for _p, s, _l in cands if s is not None) or "ninguno"
            raise StickNotRegistered(
                f"no hay ningun pendrive autorizado en {registry_path(vault_path)}. "
                f"Se han encontrado COFRE.KEY en estos volumenes: {seen}. "
                "No se autorizan por defecto. Registra el tuyo: "
                "python -m cofre.cli stick-register E:\\COFRE.KEY  (o "
                "--allow-new-stick para aceptarlo y registrarlo ahora)"
            )
        registered = []
        for path, serial, label in cands:
            if serial is None:
                continue
            register_stick(vault_path, serial, str(Path(path).parent))
            registered.append(serial)
        print(
            f"aviso: el registro estaba vacio; se autorizan y registran los "
            f"seriales {', '.join(map(str, registered))} por usar --allow-new-stick. "
            "Una copia del fichero en otro pendrive ya no desbloqueara.",
            file=sys.stderr,
        )
        return cands[0][0], cands[0][1]

    for path, serial, _label in cands:
        if is_registered(vault_path, serial):
            return path, serial

    if allow_new:
        serial = cands[0][1]
        if serial is not None:
            register_stick(vault_path, serial, str(Path(cands[0][0]).parent))
        print(
            "aviso: se acepta un pendrive no registrado (--allow-new-stick) y se "
            "registra para el uso normal.",
            file=sys.stderr,
        )
        return cands[0][0], serial

    seen = ", ".join(str(s) for _p, s, _l in cands)
    authorized = ", ".join(sorted(load_registry(vault_path).get("sticks", {})))
    raise StickNotRegistered(
        f"COFRE.KEY encontrado en {cands[0][0]} pero el serial del volumen "
        f"({seen}) no esta registrado. Seriales autorizados: {authorized}. "
        "Si es un pendrive nuevo o de recuperacion: "
        "python -m cofre.cli stick-register <ruta> (o --allow-new-stick)"
    )


def create_key_on(path: str) -> str:
    """Escribe 32 bytes aleatorios en path. Devuelve la ruta."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(secrets.token_bytes(32))
    return str(p)


def copy_key_to(dest: str, key: bytes) -> str:
    """Escribe una clave ya existente en dest (sobre de recuperacion)."""
    if len(key) != 32:
        raise ValueError("la clave a copiar no tiene 32 bytes")
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(key)
    return str(p)


def read_key(path: str) -> bytes:
    data = Path(path).read_bytes()
    if len(data) != 32:
        raise ValueError(f"{path} no contiene 32 bytes (tiene {len(data)})")
    return data


def usb_session_key(stick_path: str, salt: bytes, pin: str = "") -> bytes:
    material = read_key(stick_path) + pin.encode("utf-8")
    return Scrypt(salt=salt, length=32, n=1 << 15, r=8, p=1).derive(material)
