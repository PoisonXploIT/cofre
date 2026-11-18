"""COFRE - elegir la credencial de git para un host (paso 7.2).

Vive en el proceso de la GUI: el ayudante de git no abre el cofre, solo pide
por la tuberia. No devuelve nada si el host no esta asignado a un token o una
contrasena.
"""

from __future__ import annotations

import fnmatch

from cofre import policy


def coincide(host: str, urls: list[str]) -> bool:
    for url in urls:
        patron = str(url or "").strip().lower()
        if not patron:
            continue
        if patron == host:
            return True
        if patron.startswith("*.") and fnmatch.fnmatch(host, patron):
            return True
    return False


def buscar(vault, host: str) -> tuple[str, dict] | None:
    for nombre in vault.names():
        meta = dict(vault.meta(nombre) or {})
        tipo = str(meta.get("type") or "")
        if tipo in ("note", "canary", "private_key"):
            continue
        if tipo not in ("password", "api_key", "api_token", "oauth_app"):
            continue
        if coincide(host, list(meta.get("urls") or [])):
            return nombre, meta
    return None


def usuario(vault, nombre: str, host: str) -> str:
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
    if "github" in host:
        return "x-access-token"
    return "cofre"


def permitido(meta: dict) -> tuple[bool, str]:
    return policy.allowed(meta, "git")
