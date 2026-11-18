"""Migracion v1 -> v2 (plan 1.8), con copia previa y verificacion.

Lo que hace, en orden:
  1. Abre el v1 con el pendrive conectado.
  2. Copia cofre.json, .cofre-salt, .cofre-sticks.json y .cofre-hosts.json a
     backups/v1-AAAAMMDD-HHMMSS/ y comprueba que la copia se lee.
  3. Crea el v2 con un slot USB para el pendrive conectado y otro de recovery.
  4. Copia cada secreto y sus dominios (los que estuvieran en .cofre-hosts.json).
  5. Escribe cofre.v2.json, lo reabre y compara CADA valor con el v1.
  6. Solo si todo coincide: cofre.json -> cofre.v1.json, cofre.v2.json -> cofre.json.
  7. Devuelve el codigo de recuperacion (se muestra una sola vez).
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from cofre.crypto import Vault
from cofre.v2.recovery import new_code
from cofre.v2.slots import new_recovery_slot, new_usb_slot, open_with_stick, open_with_recovery
from cofre.v2.vault import VaultV2


class MigrateError(RuntimeError):
    pass


def _backup(vault_path: Path, files: list[Path]) -> Path:
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = vault_path.parent / "backups" / f"v1-{marca}"
    destino.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.exists():
            shutil.copy2(f, destino / f.name)
    # la copia tiene que leerse
    copia = destino / "cofre.json"
    if copia.exists():
        Vault(copia).load()
    return destino


def migrate(vault_path: str | Path, stick_key: bytes, serial: int, pin: str = "",
            dry_run: bool = False, hosts_map: dict | None = None) -> dict:
    vault_path = Path(vault_path)
    v1 = Vault(vault_path)
    data_v1 = v1.load()
    if not data_v1.get("wrapper"):
        raise MigrateError("el cofre v1 no esta inicializado (falta init)")
    from cofre.gate import _salt_for
    from cofre.usb import usb_session_key as derive

    session = derive_from_key(stick_key, _salt_for(str(vault_path)), pin)
    master_v1 = v1.unlock(session)

    nombres = v1.names()
    valores = {n: v1.get(session, n) for n in nombres}
    etiquetas = {n: v1.meta(n).get("tags", []) for n in nombres}
    dominios = dict(hosts_map or {})

    plan = {"entradas": nombres, "dominios": dominios, "destino": str(vault_path)}
    if dry_run:
        return plan

    backup = _backup(vault_path, [vault_path,
                                  vault_path.parent / ".cofre-salt",
                                  vault_path.parent / ".cofre-sticks.json",
                                  vault_path.parent / ".cofre-hosts.json"])

    # La clave maestra del v2 es nueva: el v1 no se puede reutilizar porque sus
    # entradas estaban cifradas con otra y no queremos arrastrar el esquema.
    import secrets
    master = secrets.token_bytes(32)
    codigo = new_code()
    tmp = vault_path.with_name("cofre.v2.json")
    v2 = VaultV2(tmp)
    data = v2.create(master, new_usb_slot(master, stick_key, serial,
                                          f"pendrive {serial}", pin))
    v2.add_slot(data, new_recovery_slot(master, codigo, "código en papel"))
    for nombre in nombres:
        v2.put(data, master, nombre, valores[nombre],
               tags=etiquetas[nombre], urls=dominios.get(nombre, []))
    v2.save(data)

    # verificacion: reabrir y comparar valor a valor
    releido = VaultV2(tmp).load()
    m2, _slot = open_with_stick(releido, stick_key, serial, pin)
    for nombre in nombres:
        if VaultV2(tmp).get(releido, m2, nombre) != valores[nombre]:
            raise MigrateError(f"la verificacion fallo en '{nombre}': no se cambia nada")
    m3, _ = open_with_recovery(releido, codigo)
    if m3 != m2:
        raise MigrateError("el código de recuperacion no abre la copia; se aborta")

    # intercambio
    v1_path = vault_path.with_name("cofre.v1.json")
    shutil.move(str(vault_path), str(v1_path))
    shutil.move(str(tmp), str(vault_path))
    # los dominios ya viven dentro del indice (D10)
    hosts_file = vault_path.parent / ".cofre-hosts.json"
    if hosts_file.exists():
        hosts_file.rename(hosts_file.with_name(".cofre-hosts.json.importado"))

    return {"entradas": nombres, "código": codigo, "backup": str(backup),
            "v1_guardado": str(v1_path)}


def derive_from_key(stick_key: bytes, salt: bytes, pin: str = "") -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    material = stick_key + pin.encode("utf-8")
    return Scrypt(salt=salt, length=32, n=1 << 15, r=8, p=1).derive(material)
