"""Cofre temporal para las sondas de GUI (no toca el cofre real).

Devuelve (ruta_cofre, ruta_llave, carpeta). Con llave propia y registro propio,
asi las sondas no dependen de que haya un pendrive conectado.
"""

from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_usb_slot

SECRETOS = [
    ("CF_TEST_TOKEN", "valor-de-prueba", ["prueba"], ["dash.cloudflare.com"], "api_token"),
    ("SIMULACRO_RESTAURA", "restauracion-ok-42", ["prueba"], ["ejemplo.com"], "password"),
]


def aislar(vault: Path) -> None:
    """Apunta COFRE_VAULT al cofre temporal de ESTE proceso.

    Asi cualquier sonda que llame a default_vault() sin querer sigue escribiendo
    en el temporal y no en el log real. Paso el 2026-11-17: tres sondas dejaron
    eventos en el log de verdad.
    """
    import os
    os.environ["COFRE_VAULT"] = str(vault)


def cofre_temporal(secretos=None) -> tuple[Path, Path, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="cofre-sonda-"))
    vault = tmp / "cofre.json"
    llave = tmp / "COFRE.KEY"
    llave.write_bytes(secrets.token_bytes(32))
    master = secrets.token_bytes(32)
    drive = str(tmp.drive) + "\\"
    serial = volume_serial(drive)
    if serial is None:
        raise RuntimeError(f"no se puede leer el serial de {drive}")
    v2 = VaultV2(vault)
    data = v2.create(master, new_usb_slot(master, llave.read_bytes(), serial, "temporal", ""))
    for nombre, valor, tags, urls, tipo in (secretos or SECRETOS):
        v2.put(data, master, nombre, valor, tags, urls, kind=tipo)
    v2.save(data)
    register_stick(str(vault), serial, drive)
    aislar(vault)
    import os as _os
    _os.environ["COFRE_PIPE_INFO"] = str(tmp / "pipe-name")
    return vault, llave, tmp
