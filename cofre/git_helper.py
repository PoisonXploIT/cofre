"""COFRE - ayudante de credenciales para git (paso 7.2).

Git llama a este programa con `get`, `store` o `erase` y el contexto por stdin
(`protocol=`, `host=`). Para `get`, si hay una entrada con `urls` que coincide
con el host y es un token o una contraseña, responde usuario y valor; el valor
solo va a stdout (git lo consume), nunca al log.

Con el cofre cerrado no responde nada: git pedirá la contraseña como siempre.
`store` y `erase` no hacen nada: COFRE no aprende credenciales solo.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from pathlib import Path

from cofre import audit
from cofre.crypto import Vault
from cofre.gate import GateUnavailable, material_for, resolve_session_key
from cofre.paths import default_vault


def _leer_stdin() -> dict[str, str]:
    datos: dict[str, str] = {}
    for linea in sys.stdin:
        linea = linea.rstrip("\r\n")
        if not linea:
            break
        if "=" in linea:
            clave, valor = linea.split("=", 1)
            datos[clave.strip()] = valor.strip()
    return datos


def _host(datos: dict[str, str]) -> str:
    host = datos.get("host", "")
    if host:
        return host.lower()
    url = datos.get("url", "")
    if "://" in url:
        return url.split("://", 1)[1].split("/", 1)[0].lower()
    return ""


def _coincide(host: str, urls: list[str]) -> bool:
    for url in urls:
        patron = str(url or "").strip().lower()
        if not patron:
            continue
        if patron == host:
            return True
        if patron.startswith("*.") and fnmatch.fnmatch(host, patron):
            return True
    return False


def _usuario(vault, nombre: str, host: str, datos: dict) -> str:
    if vault.is_v2():
        store = vault._v2store()
        if store.master is not None:
            try:
                contenido = store._vault.blob(store._data, store.master, nombre)
                campos = contenido.get("fields") or {}
                if campos.get("username"):
                    return str(campos["username"])
            except Exception:                      # noqa: BLE001
                pass
    if datos.get("username"):
        return datos["username"]
    if "github" in host:
        return "x-access-token"
    return "cofre"


def _buscar(vault, host: str) -> tuple[str, dict] | None:
    for nombre in vault.names():
        meta = dict(vault.meta(nombre) or {})
        tipo = str(meta.get("type") or "")
        if tipo in ("note", "canary", "private_key"):
            continue
        if tipo not in ("password", "api_key", "api_token", "oauth_app"):
            continue
        if _coincide(host, list(meta.get("urls") or [])):
            return nombre, meta
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    operacion = argv[0] if argv else "get"
    datos = _leer_stdin()
    if operacion != "get":
        return 0
    host = _host(datos)
    if not host:
        return 0
    vault_path = Path(os.environ.get("COFRE_VAULT") or default_vault())
    gate = os.environ.get("COFRE_GATE", "usb")
    stick = os.environ.get("COFRE_STICK")
    pin = os.environ.get("COFRE_PIN", "")
    try:
        session, serial = resolve_session_key(
            gate, str(vault_path), stick=stick, allow_new=False, pin=pin or None)
        material = material_for(gate, str(vault_path), stick=stick,
                                allow_new=False, pin=pin or None)
        vault = Vault(vault_path).bind_material(material)
        if vault.is_v2():
            store = vault._v2store()
            if store.master is None:
                return 0
            audit.set_key(store.master)
            audit.bind_store(store)
        else:
            audit.set_key(vault.unlock(session))
    except (GateUnavailable, EOFError):
        return 0
    except Exception:                              # noqa: BLE001
        return 0
    encontrado = _buscar(vault, host)
    if encontrado is None:
        return 0
    nombre, _meta = encontrado
    try:
        valor = vault.get(session, nombre)
    except Exception:                              # noqa: BLE001
        return 0
    usuario = _usuario(vault, nombre, host, datos)
    sys.stdout.write(f"username={usuario}\npassword={valor}\n\n")
    sys.stdout.flush()
    audit.record(str(vault_path), "git-get", gate, serial, name=nombre, ok=True,
                 detail=host[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
