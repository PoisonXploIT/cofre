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


def default_vault() -> Path:
    """Unica fuente de la ruta del cofre. COFRE_VAULT la sobrepone."""
    return Path(os.environ.get("COFRE_VAULT", Path.home() / "AI" / "cofre" / VAULT_FILENAME))


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
