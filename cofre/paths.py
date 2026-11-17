"""COFRE - rutas y escrituras seguras.

Dos cosas que antes estaban repartidas y mal:

  H8  La ruta del cofre por defecto aparecía en cinco ficheros (cli, gui,
      serve, usb, audit). Aquí vive una sola vez.
  H7  Las escrituras no eran atómicas: un corte de luz a mitad de un
      write() deja el fichero a medias y el cofre queda ilegible.
      Todo lo que se reescribe entero (registro de pendrives, log, sal,
      cofre.json) se escribe primero en un .tmp y se renombra con
      os.replace(), que es atómico en NTFS y en FAT.

Un append (el log) no necesita tmp: se añade una línea al final.
"""

from __future__ import annotations

import os
from pathlib import Path

VAULT_FILENAME = "cofre.json"
SALT_NAME = ".cofre-salt"
LOG_NAME = ".cofre-access.log"
OLD_LOG_NAME = ".cofre-access.log.old"
REGISTRY_NAME = ".cofre-sticks.json"
HOSTS_NAME = ".cofre-hosts.json"


def data_home() -> Path:
    r"""Carpeta de datos del cofre: %LOCALAPPDATA%\cofre\vault.

    Desde el 2026-11-17 los datos NO viven en el repo. Si alguien los deja
    dentro, se siguen encontrando por compatibilidad, pero el orden de busqueda
    es: variable de entorno, carpeta de datos, y solo despues la ruta antigua.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "cofre" / "vault"


def default_vault() -> Path:
    r"""Unica fuente de la ruta del cofre.

    1. COFRE_VAULT, si esta definida (es lo normal: la fija el usuario).
    2. %LOCALAPPDATA%\cofre\vault\cofre.json, si existe.
    3. la ruta antigua del repo, si existe (compatibilidad).
    4. %LOCALAPPDATA%\cofre\vault\cofre.json como destino por defecto.

    Nunca se devuelve una ruta del repo si alli no hay cofre: eso crearia uno
    nuevo y vacio sin avisar.
    """
    env = os.environ.get("COFRE_VAULT")
    if env:
        return Path(env)
    nuevo = data_home() / VAULT_FILENAME
    if nuevo.exists():
        return nuevo
    antiguo = Path.home() / "AI" / "cofre" / VAULT_FILENAME
    if antiguo.exists():
        return antiguo
    return nuevo


def atomic_write(path: str | Path, data: str | bytes) -> Path:
    """Escribir completo sin riesgo de dejar el fichero truncado."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    if isinstance(data, (bytes, bytearray)):
        tmp.write_bytes(bytes(data))
    else:
        tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, p)
    return p


def hosts_path(vault_path: str | Path) -> Path:
    """Dominios asignados a cada secreto. Vive junto al cofre, no en la extension."""
    return Path(vault_path).parent / HOSTS_NAME


def log_path(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / LOG_NAME


def old_log_path(log: str | Path) -> Path:
    """Ruta del historial rotado, a partir del propio fichero de log."""
    p = Path(log)
    return p.with_name(p.name + ".old")


AUDIT_NAME = ".cofre-audit.jsonl"
LEGACY_LOG_NAME = ".cofre-access.log"


def audit_path(vault_path: str | Path) -> Path:
    """Log encadenado con HMAC (paso 3.1)."""
    return Path(vault_path).parent / AUDIT_NAME
