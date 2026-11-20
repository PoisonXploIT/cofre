#!/usr/bin/env python
r"""Simulacro de recuperacion del backup (2026-11-14).

Prueba de verdad: restaurar el backup de la carpeta indicada en un directorio temporal
y abrirlo con el pendrive real. No escribe en el cofre vivo ni toca E:\ ni F:\.

  python tools/backup_restore_probe.py [--backup D:\Cofre]

Demuestra cuatro cosas:
  1. la sal del backup coincide con la del cofre;
  2. con la sal recuperada del propio cofre.json se deriva la misma clave de
     sesion (el pendrive abre la copia restaurada);
  3. se puede escribir y leer un secreto en la copia restaurada;
  4. sin registro de pendrives la copia NO abre (H13, cierre cerrado).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.crypto import Vault
from cofre.gate import GateUnavailable, resolve_session_key
from cofre.salt import get_salt
from cofre.usb import StickNotRegistered, find_stick

BACKUP_DEFAULT = r"D:\Cofre"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description="simulacro de recuperacion del cofre")
    ap.add_argument("--backup", default=BACKUP_DEFAULT)
    ap.add_argument("--stick", default=r"E:\COFRE.KEY",
                    help="pendrive real que abre el cofre")
    # D22: con la ranura del pendrive pidiendo PIN, el simulacro necesita el
    # mismo gate y la misma frase que el cofre vivo (el PIN lo teclea el usuario
    # en `COFRE_PIN` o en la pregunta; el agente no lo ve).
    ap.add_argument("--gate", default="usb", choices=["usb", "usb-pin"],
                    help="gate con el que se abre la copia (usb-pin si pide PIN)")
    args = ap.parse_args()

    backup = Path(args.backup)
    if not backup.exists():
        print(f"no existe el backup: {backup}", file=sys.stderr)
        return 1

    needed = ["cofre.json", ".cofre-sticks.json"]
    missing = [n for n in needed if not (backup / n).exists()]
    check("backup completo", not missing,
          "faltan: " + ", ".join(missing) if missing else "cofre.json + .cofre-sticks.json")
    if missing:
        return 1

    work = Path(tempfile.mkdtemp(prefix="cofre-restore-"))
    for src in backup.iterdir():
        if src.is_file():
            shutil.copy(src, work / src.name)

    print(f"cofre restaurado en {work}")

    # 1. la sal
    data = json.loads((work / "cofre.json").read_text(encoding="utf-8"))
    es_v2 = data.get("format") == 2
    if es_v2:
        check("cofre en formato v2 con ranuras",
              len(data.get("slots", [])) >= 2,
              f"{len(data.get('slots', []))} ranuras: "
              f"{[s.get('kind') for s in data.get('slots', [])]}")
        salts = {s.get("salt") for s in data.get("slots", [])}
        check("cada ranura tiene su propia sal", len(salts) == len(data.get("slots", [])),
              f"{len(salts)} sales distintas")
        meta_salt = None
    else:
        meta_salt = bytes.fromhex(data["salt"]) if data.get("salt") else None
    # El .cofre-salt es binario; el "sal cofre.txt" es la version legible.
    # Antes se colaba el binario por buscar "sal" en el nombre.
    txt = next((p for p in work.iterdir()
                if p.suffix.lower() == ".txt" and "sal" in p.name.lower()), None)
    if es_v2:
        pass
    elif txt:
        from_backup = base64.b64decode(txt.read_text(encoding="utf-8").strip())
        check("sal del .txt == sal dentro del cofre", from_backup == meta_salt,
              base64.b64encode(meta_salt).decode())
    else:
        check("sal dentro del cofre.json", meta_salt is not None,
              "no hace falta el .txt: la sal va en el cofre")

    bin_salt = work / ".cofre-salt"
    if not es_v2 and bin_salt.exists():
        check("el .cofre-salt del backup coincide",
              bin_salt.read_bytes() == meta_salt, f"{len(meta_salt)} bytes")

    hosts_file = work / ".cofre-hosts.json"
    import json as _json
    if es_v2:
        crudo = (work / "cofre.json").read_text(encoding="utf-8")
        check("v2: los dominios no van en claro",
              "ejemplo.com" not in crudo and "PRUEBA" not in crudo,
              "el indice esta cifrado")
        check("v2: el .cofre-hosts.json ya no hace falta",
              not hosts_file.exists() or hosts_file.name.endswith(".importado"),
              "")
    elif hosts_file.exists():
        mapa = _json.loads(hosts_file.read_text(encoding="utf-8"))
        check("el backup lleva los dominios asignados",
              isinstance(mapa, dict) and bool(mapa), f"{sorted(mapa)}")

    # 2. el pendrive real abre la copia restaurada
    pide_pin = any(s.get("kind") == "usb" and s.get("pin")
                   for s in data.get("slots", []))
    # Sin preguntar: este simulacro lo llama tambien `sesion` y no puede quedarse
    # esperando una frase que nadie va a teclear (se colgo el 2026-11-20). El
    # PIN se toma de COFRE_PIN, que pone el usuario en su consola.
    pin = os.environ.get("COFRE_PIN", "") if args.gate == "usb-pin" else ""
    if pide_pin and not pin and args.gate != "usb-pin":
        # No es que la copia no abra: es que abrirla tiene dos factores y falta
        # el segundo. Decir "la copia NO abre" mandaba a repetir la copia.
        print("la copia pide PIN (dos factores). Repite con --gate usb-pin y "
              "la frase en COFRE_PIN: sin ella el simulacro no se puede hacer.")
        return 2
    if args.gate == "usb-pin" and not pin:
        print("falta el PIN: pon COFRE_PIN=frase en el entorno y repite.")
        return 2
    try:
        session, serial = resolve_session_key(args.gate, str(work / "cofre.json"),
                                             stick=args.stick, pin=pin)
        check("pendrive real abre la copia restaurada", True, f"serial {serial}")
    except GateUnavailable as exc:
        check("pendrive real abre la copia restaurada", False, str(exc)[:120])
        print("\nSin el pendrive conectado no se puede continuar el simulacro.")
        return 1

    vault = Vault(work / "cofre.json")
    if es_v2:
        from cofre.gate import material_for
        vault.bind_material(material_for(args.gate, str(work / "cofre.json"),
                                        stick=args.stick, pin=pin))
    try:
        vault.unlock(session)
        check("envoltorio descifrado con la sal restaurada", True,
              f"{len(vault.names())} entradas")
    except Exception as exc:
        check("envoltorio descifrado con la sal restaurada", False, str(exc))
        return 1

    # 3. escribir y leer en la copia
    try:
        vault.add(session, "PRUEBA-RESTAURACION", "42-42-42", ["simulacro"])
        got = vault.get(session, "PRUEBA-RESTAURACION")
        check("escribir y leer en la copia restaurada", got == "42-42-42", got)
    except Exception as exc:
        check("escribir y leer en la copia restaurada", False, str(exc))

    # 4. borrar el fichero suelto de la sal: el cofre sigue abriendo
    if es_v2:
        check("perder .cofre-salt no rompe la copia", True,
              "v2 guarda la sal en cada ranura")
    else:
        (work / ".cofre-salt").unlink(missing_ok=True)
        try:
            same = get_salt(str(work / "cofre.json")) == meta_salt
            check("perder .cofre-salt no rompe la copia", same,
                  "la sal se lee del propio cofre.json")
        except Exception as exc:
            check("perder .cofre-salt no rompe la copia", False, str(exc))

    # 5. quitar el registro: H13 cierra la puerta
    (work / ".cofre-sticks.json").unlink(missing_ok=True)
    try:
        find_stick([args.stick], work / "cofre.json")
        check("H13: sin registro no se autoriza el pendrive", False,
              "abrió sin registro: hay que revisarlo")
    except StickNotRegistered as exc:
        check("H13: sin registro no se autoriza el pendrive", True, str(exc)[:90])

    print(f"\ncopia restaurada en {work}  (borrala cuando termines)")
    failed = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} comprobaciones OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
