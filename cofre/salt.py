"""COFRE - la sal del cofre (H9).

La sal de scrypt NO es un secreto: publicarla no abre el cofre. Pero sin ella
no se puede recomponer la clave de sesion, y eso significa que perder
.cofre-salt equivale a perder el cofre para siempre, aunque tengas el
pendrive.

Dos arreglos:

  1. La sal se copia dentro de cofre.json (campo "salt", en hex). Ya no puede
     perderse por separado: el backup del cofre lleva la sal.
  2. Nadie genera una sal nueva en silencio. Si el cofre existe y no hay sal,
     se aborta con un mensaje claro. Antes se creaba una con os.urandom y el
     cofre simplemente dejaba de abrirse, pareciendo un PIN equivocado.

Orden de lectura: fichero suelto (.cofre-salt) y campo dentro del cofre.
Si existen los dos y no coinciden, es un error: alguien regenero la sal.
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

from cofre.paths import SALT_NAME, atomic_write


class SaltMissing(RuntimeError):
    """El cofre existe pero no se puede encontrar su sal."""


class SaltMismatch(RuntimeError):
    """Hay dos salvas distintas para el mismo cofre."""


def salt_path(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / SALT_NAME


def _vault_json(vault_path: str | Path) -> dict | None:
    p = Path(vault_path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SaltMissing(f"no se puede leer {p}: {exc}") from exc
    return data if isinstance(data, dict) else None


def _mirror_into_vault(vault_path: Path, salt: bytes) -> None:
    """Guardar la sal dentro de cofre.json sin tocar nada mas."""
    data = _vault_json(vault_path)
    if data is None:
        return
    if data.get("salt") == salt.hex():
        return
    data["salt"] = salt.hex()
    try:
        atomic_write(vault_path, json.dumps(data, indent=2))
    except OSError as exc:
        print(f"aviso: no se pudo duplicar la sal dentro del cofre: {exc}",
              file=sys.stderr)


def get_salt(vault_path: str | Path, create: bool = False) -> bytes:
    """Sal de scrypt del cofre. La única fuente de verdad son los dos sitios.

    create=True solo tiene sentido cuando el cofre aun no existe (init).
    """
    vp = Path(vault_path)
    sp = salt_path(vp)

    side = None
    if sp.exists():
        side = sp.read_bytes()
        if not side:
            side = None

    meta = None
    data = _vault_json(vp)
    if data and isinstance(data.get("salt"), str):
        try:
            meta = bytes.fromhex(data["salt"])
        except ValueError:
            meta = None

    if side and meta:
        if side != meta:
            raise SaltMismatch(
                f"hay dos salvas distintas para este cofre ({sp} y el campo "
                "'salt' de {vp}). La sal correcta es la que abre el cofre: "
                "compara ambas con 'python -m cofre.cli salt' y deja la que funcione."
            )
        return side

    if side:
        _mirror_into_vault(vp, side)
        return side

    if meta:
        try:
            atomic_write(sp, meta)
        except OSError as exc:
            print(f"aviso: no se pudo escribir {sp}: {exc}", file=sys.stderr)
        return meta

    if create:
        salt = secrets.token_bytes(16)
        atomic_write(sp, salt)
        _mirror_into_vault(vp, salt)
        return salt

    raise SaltMissing(
        f"no existe la sal del cofre ({sp}). Sin ella la clave de sesion no se "
        "puede derivar y el cofre no se abre. Si tienes una copia de cofre.json "
        "con el campo 'salt', restaura esa sal. Si no, el cofre esta perdido: "
        "hay que inicializar uno nuevo (init) y rellenar los secretos."
    )


def show(vault_path: str | Path) -> dict:
    """Estado de la sal, listo para imprimir y para hacer backup."""
    sp = salt_path(vault_path)
    salt = get_salt(vault_path)
    data = _vault_json(vault_path) or {}
    return {
        "sal_base64": __import__("base64").b64encode(salt).decode("ascii"),
        "bytes": len(salt),
        "fichero": str(sp),
        "dentro_del_cofre": isinstance(data.get("salt"), str),
    }
