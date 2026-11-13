#!/usr/bin/env python
r"""Sonda de endurecimiento (H1, H5, H7, H8, H9, H13).

Se ejecuta SIEMPRE contra un cofre sintético en un directorio temporal.
Nunca toca E:\ ni F:\ ni el cofre real.

  python tools/hardening_probe.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.crypto import Vault
from cofre.gate import GateUnavailable, resolve_session_key
from cofre.salt import SaltMissing, get_salt, show as salt_show
from cofre.usb import RegistryCorrupt, StickNotRegistered, load_registry, save_registry

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cofre-probe-"))
    vault_path = tmp / "cofre.json"
    fake_key = tmp / "COFRE.KEY"
    fake_key.write_bytes(b"A" * 32)

    print(f"cofre de prueba en {tmp}")

    # H5/H9: la sal se crea una sola vez y se duplica dentro del cofre
    salt = get_salt(str(vault_path), create=True)
    check("H9 sal creada con init", len(salt) == 16, f"{len(salt)} bytes")

    session, serial = resolve_session_key("usb", str(vault_path),
                                         stick=str(fake_key), allow_new=True)
    vault = Vault(vault_path)
    vault.init(session, salt=salt)
    data = json.loads(vault_path.read_text(encoding="utf-8"))
    check("H9 sal dentro de cofre.json", data.get("salt") == salt.hex(),
          "campo salt presente")

    vault.add(session, "PRUEBA", "valor-de-prueba")
    check("roundtrip cifrado", vault.get(session, "PRUEBA") == "valor-de-prueba")

    # H9: borrar el fichero suelto NO rompe el cofre (la sal está dentro)
    salt_file = tmp / ".cofre-salt"
    salt_file.unlink()
    try:
        again = get_salt(str(vault_path))
        check("H9 perder .cofre-salt es recuperable", again == salt,
              "la sal se lee del cofre y se recrea el fichero")
    except Exception as exc:
        check("H9 perder .cofre-salt es recuperable", False, str(exc))

    # H9: si se pierde TODA la sal, no se inventa otra en silencio
    (tmp / ".cofre-salt").unlink(missing_ok=True)
    data = json.loads(vault_path.read_text(encoding="utf-8"))
    data.pop("salt", None)
    vault_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        get_salt(str(vault_path))
        check("H9 sin sal no se regenera en silencio", False,
              "se genero una sal nueva: el cofre quedaria cerrado para siempre")
    except SaltMissing as exc:
        check("H9 sin sal aborta con mensaje claro", "no existe la sal" in str(exc),
              str(exc)[:80])

    # Devolver la sal al cofre para seguir probando (en la vida real esto
    # sería restaurar el backup).
    data["salt"] = salt.hex()
    vault_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    check("H9 restaurar la sal desde el cofre reabre el acceso",
          get_salt(str(vault_path)) == salt, "sal recuperada del campo salt")

    # H13: registro vacío ya no autoriza cualquier pendrive
    reg_path = tmp / ".cofre-sticks.json"
    if reg_path.exists():
        reg_path.unlink()
    try:
        resolve_session_key("usb", str(vault_path), stick=str(fake_key))
        check("H13 registro vacío falla cerrado", False,
              "se autorizo un pendrive sin registro")
    except (StickNotRegistered, GateUnavailable) as exc:
        check("H13 registro vacío falla cerrado", "no hay ningun pendrive autorizado" in str(exc),
              str(exc)[:80])

    # H13: un registro corrupto tampoco abre la puerta
    reg_path.write_text("{ esto no es json", encoding="utf-8")
    try:
        load_registry(str(vault_path))
        check("H13 registro corrupto falla cerrado", False, "se tragó el JSON roto")
    except RegistryCorrupt as exc:
        check("H13 registro corrupto falla cerrado", "corrupto" in str(exc), str(exc)[:80])

    # H7: escrituras atómicas, sin .tmp colgando
    save_registry(str(vault_path), {"sticks": {}})
    leftovers = [p for p in tmp.iterdir() if p.name.endswith(".tmp")]
    check("H7 sin ficheros .tmp pendientes", not leftovers, f"restos: {leftovers}")

    # H1: exec con un secreto inexistente
    reg_path.write_text(json.dumps({"sticks": {}}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "cofre.cli", "--vault", str(vault_path),
         "--gate", "usb", "--stick", str(fake_key), "--allow-new-stick",
         "exec", "--name", "NO_EXISTE", "--", "python", "-c", "print('no debería ejecutarse')"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    out = (proc.stdout + proc.stderr).lower()
    check("H1 exec sin NameError", "nameerror" not in out,
          f"exit={proc.returncode} salida={proc.stdout.strip()[:60]!r}")
    check("H1 exec avisa de lo que falta", "no encontrados" in out, proc.stderr.strip()[:80])

    # H8: una sola fuente de la ruta por defecto
    from cofre.paths import default_vault
    check("H8 ruta única", "cofre.json" in str(default_vault()), str(default_vault()))

    info = salt_show(str(vault_path))
    check("sal visible para backup", info["sal_base64"] and info["dentro_del_cofre"],
          info["sal_base64"])

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} comprobaciones OK")
    if failed:
        print("pendientes: " + ", ".join(r[0] for r in failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
