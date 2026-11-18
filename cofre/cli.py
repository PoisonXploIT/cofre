#!/usr/bin/env python
"""Cofre - bóveda de secretos con gate de pendrive USB.

Uso:
  python -m cofre.cli gui                     # ventana grafica (Tkinter)
  python -m cofre.cli shell                    # modo interactivo en terminal
  python -m cofre.cli init
  python -m cofre.cli add <nombre> [<valor>]   # sin valor, se pide a ciegas
  python -m cofre.cli get <nombre>
  python -m cofre.cli list
  python -m cofre.cli del <nombre>
  python -m cofre.cli exec --name VAR [--name VAR2] -- comando args...   # inyecta
  python -m cofre.cli gen [--machine] [--words 5] [--lang en|es] [--entropy]
  python -m cofre.cli export
  python -m cofre.cli probe
  python -m cofre.cli stick-init <ruta>       # crea COFRE.KEY nuevo en el pendrive
  python -m cofre.cli stick-copy <ruta>       # copia la clave a otro pendrive
  python -m cofre.cli stick-register <ruta>   # autoriza el serial de un pendrive
  python -m cofre.cli stick-list              # pendrives autorizados
  python -m cofre.cli stick-revoke <serial>   # dar de baja un pendrive
  python -m cofre.cli stick-role <serial> <principal|reserva>  # declarar el rol
  python -m cofre.cli log [--lines 20] [--stats]  # historial de accesos

Gate:
  --gate usb      clave de 32 bytes que solo existe en el pendrive (por defecto)
  --gate usb-pin  pendrive + PIN (dos factores)
  --gate pin      debil; sobre de recuperacion o pruebas
  --gate hid      llave fisica CTAP2/hmac-secret, NO operativa en esta maquina

Solo desbloquean los pendrives cuyo serial de volumen esta registrado en
.cofre-sticks.json. --allow-new-stick autoriza uno nuevo de forma puntual.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import secrets
import stat
import sys
from pathlib import Path

from cofre.audit import clear_key as audit_clear_key
from cofre.audit import record, set_key as audit_set_key, tail
from cofre.crypto import Vault
from cofre.gate import GateUnavailable, material_for, resolve_session_key, _salt_for
from cofre.gen import entropy, human_password, machine_password
from cofre.paths import atomic_write, audit_path, default_vault
from cofre.usb import (KEY_FILENAME, StickNotFound, StickNotRegistered, key_drives,
                       copy_key_to, create_key_on, find_stick, keys_to_try,
                       load_registry, read_key, register_stick, revoke_stick,
                       set_role, usb_session_key, volume_serial)
from cofre import __version__
from cofre.salt import SaltMismatch, SaltMissing, show as salt_show

DEFAULT_VAULT = default_vault()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cofre - bóveda de secretos")
    # el nombre de la opcion y el de la accion son identificadores: sin tildes
    p.add_argument("--version", "-V", action="version",   # no-tildes
                   version=f"COFRE {__version__}")
    p.add_argument("--vault", default=str(DEFAULT_VAULT))
    p.add_argument("--gate", default="usb", choices=["pin", "hid", "usb", "usb-pin"])
    p.add_argument("--stick", help="ruta explicita del fichero clave del USB")
    p.add_argument("--allow-new-stick", action="store_true",
                   help="aceptar un pendrive cuyo serial no esta registrado")
    p.add_argument("--allow-pipe", action="store_true",
                   help="permitir que get/export escriba secretos a un pipe o fichero")
    p.add_argument("--recovery", action="store_true",
                   help="abrir con el código de recuperación de papel (se pide por consola)")
    sub = p.add_subparsers(dest="command", required=True)

    def with_common(sp):
        # defaults SUPPRESS: si la opcion va antes del subcomando no se pisa
        sp.add_argument("--vault", default=argparse.SUPPRESS)
        sp.add_argument("--gate", default=argparse.SUPPRESS, choices=["pin", "hid", "usb", "usb-pin"])
        sp.add_argument("--stick", default=argparse.SUPPRESS)
        sp.add_argument("--allow-new-stick", action="store_true", default=argparse.SUPPRESS)
        sp.add_argument("--allow-pipe", action="store_true", default=argparse.SUPPRESS)
        sp.add_argument("--recovery", action="store_true", default=argparse.SUPPRESS)
        return sp

    with_common(sub.add_parser("init"))
    sp = with_common(sub.add_parser("add"))
    sp.add_argument("name")
    sp.add_argument("value", nargs="?",
                    help="si se omite, se pide a ciegas (no queda en el historial)")
    sp.add_argument("--tag", action="append", default=[])
    sg = with_common(sub.add_parser("get"))
    sg.add_argument("name")
    with_common(sub.add_parser("list"))
    rn = with_common(sub.add_parser("rename", help="cambiar el nombre de un secreto"))
    rn.add_argument("old")
    rn.add_argument("new")
    sd = with_common(sub.add_parser("del"))
    sd.add_argument("name")
    sx = with_common(sub.add_parser("exec"))
    sx.add_argument("--name", action="append", default=[],
                    help="secreto a pasar como variable de entorno al comando")
    sx.add_argument("cmd", nargs="+", help="comando a ejecutar, p. ej: python script.py")

    rn = with_common(sub.add_parser(
        "run", help="ejecutar con las variables de .cofre-env.json"))
    rn.add_argument("--check", action="store_true",
                    help="decir qué falta, sin lanzar nada")
    rn.add_argument("--si", action="store_true",
                    help="no pedir confirmación para secretos sensibles")
    rn.add_argument("--file", default="", help="ruta del .cofre-env.json")
    rn.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="comando; usa -- para separar")

    ds = with_common(sub.add_parser(
        "describe", help="JSON de secretos y salud, nunca valores"))
    ds.add_argument("--json", action="store_true", help="salida JSON (siempre)")
    ds.add_argument("--minimal", action="store_true",
                    help="solo nombre, tipo y salud (recomendado para agentes)")

    sv = sub.add_parser("serve", help="puente para el navegador (solo 127.0.0.1)")
    sv.add_argument("--port", type=int, default=47653)

    sk = with_common(sub.add_parser(
        "check", help="comprobar que existen unos secretos, SIN mostrar su valor"))
    sk.add_argument("--name", action="append", default=[],
                    help="nombre a comprobar (repetible)")

    sg2 = with_common(sub.add_parser("gen"))
    sg2.add_argument("--machine", action="store_true")
    sg2.add_argument("--words", type=int, default=5)
    sg2.add_argument("--lang", default="en", choices=["en", "es"])
    sg2.add_argument("--entropy", action="store_true", help="imprimir bits, no la password")
    with_common(sub.add_parser("export"))
    with_common(sub.add_parser("probe"))
    sl = with_common(sub.add_parser("log"))
    sl.add_argument("--lines", type=int, default=20)
    sl.add_argument("verify", nargs="?", choices=["verify"],
                    help="comprobar la cadena y la firma del log")
    sl.add_argument("--reanchor", action="store_true",
                    help="mover el punto de exigencia de firma (solo el usuario)")
    sl.add_argument("--reseal", action="store_true",
                    help="volver a sellar el checkpoint tras restaurar una copia")
    sl.add_argument("--motivo", default="", help="por que se re-ancla o se resella")
    sl.add_argument("--si", action="store_true", help="confirmar sin preguntar")
    sl.add_argument("--stats", action="store_true", help="totales, fallos y pendrives usados")

    ss = with_common(sub.add_parser("stick-init"))
    ss.add_argument("path", help="donde crear COFRE.KEY, p. ej. E:\\COFRE.KEY")
    ss.add_argument("--force", action="store_true",
                    help="sobrescribir si ya existe (PERDE el acceso al cofre actual)")

    sr = with_common(sub.add_parser("stick-register"))
    sr.add_argument("path", help="ruta de un COFRE.KEY ya existente, p. ej. F:\\COFRE.KEY")

    rv = with_common(sub.add_parser("stick-revoke"))
    rv.add_argument("serial", type=int, help="serial de volumen a dar de baja")

    ro = with_common(sub.add_parser("stick-role"))
    ro.add_argument("serial", type=int, help="serial de volumen ya registrado")
    ro.add_argument("role", choices=["principal", "reserva"],
                    help="que papel juega ese pendrive")

    sc = with_common(sub.add_parser("stick-copy"))
    sc.add_argument("dest", help="donde copiar la clave, p. ej. F:\\COFRE.KEY")
    sc.add_argument("--force", action="store_true", help="sobrescribir el destino")

    sub.add_parser("shell")
    gp = with_common(sub.add_parser("gui", help="ventana grafica (Tkinter, standalone)"))
    gp.add_argument("--selftest", action="store_true",
                    help="construir la ventana, comprobarla y salir (sin mostrar)")
    with_common(sub.add_parser("stick-list"))
    with_common(sub.add_parser("stick-verify",
                               help="comprobar que cada pendrive conectado abre el cofre"))
    ha = with_common(sub.add_parser("host-assign",
                                    help="asignar los dominios donde se puede rellenar un secreto"))
    ha.add_argument("name", help="nombre del secreto, p. ej. GITHUB_TOKEN")
    ha.add_argument("hosts", nargs="+", help="dominios: github.com  *.ejemplo.com")
    hh = with_common(sub.add_parser("host-list", help="dominios asignados a cada secreto"))
    hh.add_argument("name", nargs="?", help="solo ese secreto")
    mta = with_common(sub.add_parser("meta", help="metadatos de ciclo de vida de un secreto"))
    mta.add_argument("name")
    mta.add_argument("--provider", default="")
    mta.add_argument("--token-id", default="")
    mta.add_argument("--account-id", default="")
    mta.add_argument("--expires", default="")
    mta.add_argument("--rotate-every", type=int, default=0)
    mta.add_argument("--url", action="append", default=[])
    mta.add_argument("--consumer", action="append", default=[])
    mta.add_argument("--type", dest="kind", default="")
    mta.add_argument("--admin", action="store_true",
                     help="marcar como token de administracion (pide confirmación)")
    mta.add_argument("--app-id", default="",
                     help="id de la GitHub App (para las referencias @app)")
    mta.add_argument("--installation", default="",
                     help="id de la instalación de la GitHub App")

    rt = with_common(sub.add_parser("rotate", help="rotar un token de un proveedor"))
    rt.add_argument("name")
    rt.add_argument("--admin", default="", help="secreto con permisos de gestion")
    rt.add_argument("--dry-run", action="store_true", help="enseñar el plan, sin tocar nada")
    rt.add_argument("--si", action="store_true", help="confirmar sin preguntar")
    rt.add_argument("--revoke-old", action="store_true",
                    help="tras crear el reemplazo, borrar el token viejo")
    rt.add_argument("--manual", action="store_true",
                    help="rotación asistida: abrir la web y pegar el token nuevo")

    fl = with_common(sub.add_parser(
        "field", help="guardar un campo de una entrada v2 (para #campo)"))
    fl.add_argument("name")
    fl.add_argument("campo")

    ti = with_common(sub.add_parser("token-info",
                                    help="id, estado y caducidad de un token (sin el valor)"))
    ti.add_argument("name")

    he = with_common(sub.add_parser(
        "health", help="comprobar la salud de cada credencial con su proveedor"))
    he.add_argument("--json", action="store_true",
                    help="salida en JSON (sin valores)")

    ap = with_common(sub.add_parser("app-exec",
                                    help="ejecutar un comando con un token de GitHub App (1 h)"))
    ap.add_argument("--clave", default="GH_APP_PRIVATE_KEY",
                    help="secreto con la clave privada de la App")
    ap.add_argument("--app-id", required=True)
    ap.add_argument("--installation", required=True)
    ap.add_argument("--var", default="GITHUB_TOKEN", help="variable de entorno a inyectar")
    ap.add_argument("cmd", nargs="+")

    rs = with_common(sub.add_parser("resume",
                                    help="ver una rotación interrumpida y decidir"))
    rs.add_argument("--opcion", choices=["continuar", "deshacer"], default="")
    rs.add_argument("--si", action="store_true", help="no pedir confirmación")

    pa = with_common(sub.add_parser(
        "panic", help="emergencia: revocar todo y rehacer la clave maestra"))
    pa.add_argument("--dry-run", action="store_true",
                    help="enseñar el plan, sin tocar nada")
    pa.add_argument("--si", action="store_true",
                    help="no pedir la confirmación")
    pa.add_argument("--admin", default="",
                    help="secreto con permisos de gestión (Cloudflare)")

    rk = with_common(sub.add_parser(
        "rekey", help="cambiar la clave maestra y el código de recuperacion"))
    rk.add_argument("--motivo", default="manual",
                    help="por que se cambia (queda en el registro)")
    rk.add_argument("--si", action="store_true", help="no pedir confirmación")

    du = with_common(sub.add_parser(
        "due", help="recordatorios del calendario (sin abrir el cofre)"))
    du.add_argument("--notify", action="store_true",
                    help="mostrar el aviso si la fecha ya llego")

    al = with_common(sub.add_parser("alerts", help="evaluar las reglas de alerta"))
    al.add_argument("--reset", action="store_true",
                    help="volver a evaluar desde el principio del log")
    with_common(sub.add_parser("version",   # no-tildes: el nombre del comando
                               help="versión de COFRE y del entorno"))
    with_common(sub.add_parser("salt", help="mostrar la sal y donde esta guardada (H9)"))
    mg = with_common(sub.add_parser("migrate", help="pasar el cofre v1 al formato v2"))
    mg.add_argument("--dry-run", action="store_true", help="decir que haria, sin escribir")
    sa = with_common(sub.add_parser("stick-add-v2",
                                    help="dar llave nueva a un pendrive y anadir su ranura (D11)"))
    sa.add_argument("path", help=r"ruta del COFRE.KEY nuevo, p. ej. F:\COFRE.KEY.nuevo")
    return p


def _drive_of(path: str) -> str:
    s = str(path)
    if len(s) >= 2 and s[1] == ":":
        return s[:3]
    return ""


def read_secret(prompt: str) -> str:
    """Lee un secreto sin dejarlo en el historial.

    En terminal: getpass (no se ve al teclear).
    Sin terminal (pipes, scripts): se lee la primera linea de stdin, porque
    getpass en Windows bloquea esperando una consola real.
    """
    if sys.stdin.isatty():
        from getpass import getpass
        return getpass(prompt)
    sys.stderr.write(prompt + " (por stdin)\n")
    return sys.stdin.readline().rstrip("\n")


def cmd_stick_list(vault: str) -> int:

    reg = load_registry(vault)
    sticks = reg.get("sticks", {})
    if not sticks:
        print("no hay pendrives registrados")
        print("primera vez: conecta el pendrive y ejecuta init o stick-init")
        return 0
    present = set()
    for drive in key_drives():          # con plazo: no cuelga con un USB muerto
        serial = volume_serial(drive)
        if serial is not None:
            present.add(str(serial))
    print(f"{len(sticks)} pendrive(s) autorizados")
    for serial, info in sticks.items():
        mark = "conectado" if serial in present else "no conectado"
        print(f"  serial {serial}  {info.get('drive','')}  {info.get('role','?')}  "
              f"{info.get('label') or ''}  [{mark}]  registrado {info.get('registered','')}")
    return 0


def cmd_stick_verify(vault_path: str) -> int:
    """Probar todas las llaves conectadas (R2): cada pendrive autorizado que
    este puesto tiene que abrir de verdad el cofre."""

    vault = Vault(Path(vault_path))
    if not vault.is_v2() and not vault.load().get("wrapper"):
        print("el cofre no esta inicializado")
        return 1
    reg = load_registry(vault_path)
    authorized = set(reg.get("sticks", {}))
    drives = keys_to_try()
    if not drives:
        print("no hay ningún pendrive con %s conectado" % KEY_FILENAME)
        return 1

    ok, bad = 0, 0
    for path in drives:
        drive = _drive_of(path)
        serial = volume_serial(drive)
        etiqueta = f"{drive} serial {serial}"
        if str(serial) not in authorized:
            print(f"AVISO  {etiqueta}: no esta autorizado (no se prueba)")
            continue
        try:
            key = read_key(path)
            if vault.is_v2():
                from cofre.v2.slots import open_with_stick
                open_with_stick(vault.load(), key, serial)
            else:
                vault.unlock(usb_session_key(path, _salt_for(vault_path)))
            print(f"OK     {etiqueta}: abre el cofre")
            ok += 1
        except Exception as exc:
            print(f"FALLO  {etiqueta}: NO abre el cofre ({type(exc).__name__})")
            bad += 1
    print("")
    print(f"{ok} llave(s) buena(s), {bad} llave(s) inservible(s)")
    record(vault_path, "stick-verify", "usb", None,
           name=f"{ok} ok / {bad} fallo", ok=bad == 0)
    return 0 if bad == 0 else 1


def cmd_shell(vault_path: str, gate: str, stick: str | None, allow_new: bool) -> int:
    """Modo interactivo. Los valores se piden a ciegas: no acaban en el
    historial de la shell ni en la linea de comando del proceso."""
    from getpass import getpass

    vault = Vault(Path(vault_path))
    try:
        session, serial = resolve_session_key(gate, vault_path, stick=stick, allow_new=allow_new)
    except (GateUnavailable, EOFError) as exc:
        record(vault_path, "shell", gate, None, ok=False, detail=str(exc))
        print("gate no disponible:", exc, file=sys.stderr)
        return 1

    print(f"cofre abierto (gate {gate}, pendrive serial {serial}). 'help' para comandos.")
    while True:
        try:
            line = input("cofre> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd, rest = parts[0].lower(), parts[1:]
        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                print("add <nombre> | get <nombre> | list | del <nombre> | "
                      "gen machine | gen words <n> | export | quit")
            elif cmd == "list":
                names = vault.names()
                for n in names:
                    print("  ", n)
                record(vault_path, "list", gate, serial, name=f"{len(names)} entradas")
            elif cmd == "get":
                if not rest:
                    print("uso: get <nombre>")
                    continue
                print(vault.get(session, rest[0]))
                record(vault_path, "get", gate, serial, name=rest[0])
            elif cmd == "del":
                if not rest:
                    print("uso: del <nombre>")
                    continue
                print("borrado" if vault.delete(session, rest[0]) else "no existe")
                record(vault_path, "del", gate, serial, name=rest[0])
            elif cmd == "add":
                name = rest[0] if rest else input("nombre del secreto: ").strip()
                if not name:
                    continue
                value = read_secret("valor del secreto: ")
                vault.add(session, name, value)
                print("guardado", name)
                record(vault_path, "add", gate, serial, name=name)
            elif cmd == "gen":
                if rest and rest[0] == "machine":
                    print(machine_password())
                elif rest and rest[0] == "words":
                    n = int(rest[1]) if len(rest) > 1 else 5
                    print(human_password(words=n))
                else:
                    print(human_password(words=5))
                record(vault_path, "gen", gate, serial)
            elif cmd == "export":
                print("export vuelca los secretos a pantalla: no lo uses en una")
                print("sesión compartida ni con capturas de pantalla activas.")
                for n in vault.names():
                    print(f"{n}={vault.get(session, n)}")
                record(vault_path, "export", gate, serial, name="todos")
            else:
                print("comando desconocido:", cmd)
        except Exception as exc:
            print("error:", exc, file=sys.stderr)
            record(vault_path, cmd, gate, serial, ok=False, detail=str(exc))
    del session
    return 0


def prepare_audit(vault_path, gate: str, stick: str | None, allow_new: bool):
    """Deja el cofre ligado a la llave y el log firmando.

    Cualquier comando que escriba un evento privilegiado (rotate, meta, log,
    alerts...) tiene que pasar por aquí ANTES de registrar nada: si no, la linea
    sale sin firma y verify la marca como manipulacion. Paso tres veces.
    """
    from cofre.audit import bind_store, set_key as _set_key
    try:
        material = material_for(gate, str(vault_path), stick, allow_new)
        vault = Vault(Path(vault_path)).bind_material(material)
        if vault.is_v2():
            store = vault._v2store()
            _set_key(store.master)
            bind_store(store)
            # 5.8: el calendario se deja escrito sin nombres. Se refresca al
            # abrir y otra vez al terminar el proceso (atexit), para que un
            # cambio hecho por el comando quede reflejado.
            from cofre import schedule
            schedule.escribir(store)
            atexit.register(schedule.escribir, store)
        return vault
    except Exception:
        return Vault(Path(vault_path))


def prepare_recovery(vault_path, gate: str):
    """Abrir el cofre con el código de recuperación, sin pendrive.

    El código se pide por consola, no se escribe en el registro ni en ningun
    fichero y no queda en el historial. Es el camino del simulacro de
    restauracion (paso 8.3) y el de la pantalla de bloqueo.
    """
    from cofre.audit import bind_store, set_key as _set_key
    vault = Vault(Path(vault_path))
    if not vault.is_v2():
        print("el código de recuperación solo abre cofres v2", file=sys.stderr)
        return vault
    print("Pega el código de recuperación (25 palabras) y pulsa Enter.",
          file=sys.stderr)
    print("No se guarda en ningún fichero y no se escribe en el registro.",
          file=sys.stderr)
    print("código: ", end="", file=sys.stderr, flush=True)
    try:
        codigo = input().strip()          # el aviso va a stderr: stdout es el valor
    except EOFError:
        return vault
    if not codigo:
        return vault
    try:
        vault.bind_recovery(codigo)
        store = vault._v2store()
        if store.master is None:
            raise RuntimeError("el código no abre este cofre")
        _set_key(store.master)
        bind_store(store)
        from cofre import schedule
        schedule.escribir(store)
        atexit.register(schedule.escribir, store)
        print("cofre abierto con el código de recuperación", file=sys.stderr)
    except Exception as exc:                      # noqa: BLE001
        print(f"no se pudo abrir con ese código: {exc}", file=sys.stderr)
    return vault


def rekey_vivo(vault, vault_path, material, motivo: str = "manual",
               gate: str = "-", serial: int | None = None,
               actor: str = "cli"):
    """Rekey completo: cierra el tramo, re-cifra, archiva y cambia la clave.

    Deja el objeto `vault` y su store con la clave nueva. Devuelve
    (codigo, perdidos, error). Si el guardado falla, restaura el tramo y la
    clave vieja sigue valiendo.
    """
    from cofre import audit as audit_mod
    from cofre.v2 import rekey as rekey_mod
    store = vault._v2store()
    etiqueta = ""
    if (store.slot or {}).get("kind") == "usb":
        etiqueta = str(store.slot.get("label") or "")
    try:
        prep = rekey_mod.preparar(
            store._vault, store._data, store.master,
            stick_key=material.get("stick_key"),
            serial=material.get("serial"),
            label=etiqueta, pin=material.get("pin", ""))
    except Exception as exc:                       # noqa: BLE001
        return "", [], str(exc)
    log = audit_mod.audit_path(vault_path)
    log_antes = log.read_text(encoding="utf-8") if log.exists() else ""
    segmento = None
    try:
        # evento de cierre firmado con la clave VIEJA
        record(str(vault_path), "rekey", gate, serial, name="-", ok=True,
               detail=f"clave maestra retirada: {motivo}"[:150])
        segmento = audit_mod.close_segment(
            str(vault_path), prep.master, motivo=motivo, gate=gate,
            serial=serial, actor=actor)
        if segmento is None:
            raise RuntimeError("no hay registro que cerrar")
        idx = store._vault.index(prep.data, prep.master)
        idx.setdefault("settings", {})["audit"] = {
            "seq": int(segmento.get("seq", 1)),
            "hash": str(segmento.get("hash") or "")}
        store._vault._write_index(prep.data, prep.master, idx)
        rekey_mod.guardar(store._vault, prep)
        store._data = prep.data
        store.master = prep.master
        store.slot = prep.usb_slot
        audit_mod.set_key(prep.master)
        audit_mod.bind_store(store)
        audit_mod.stamp(store, prep.master)
        return prep.codigo, prep.perdidos, None
    except Exception as exc:                       # noqa: BLE001
        if segmento is not None:
            try:
                archivo = Path(segmento["archivo"])
                os.chmod(archivo, stat.S_IWRITE)
                archivo.unlink(missing_ok=True)
            except Exception:
                pass
            if log_antes:
                atomic_write(audit_path(vault_path), log_antes)
        return "", [], str(exc)


def _print_rekey(codigo: str, perdidos: list[dict], vault_path) -> None:
    """Codigo nuevo una vez y aviso visible de los pendrives que quedan fuera."""
    if not codigo:
        return
    print("")
    print("rekey hecho. Codigo de recuperacion nuevo (se muestra UNA vez):")
    print("  " + codigo)
    print("Apunta el código en papel.")
    if perdidos:
        from cofre.usb import load_registry
        try:
            registro = load_registry(vault_path, strict=False)
        except Exception:
            registro = {"sticks": {}}
        print("")
        print("ATENCION: estos pendrives ya NO abren el cofre:")
        for perdido in perdidos:
            if str(perdido.get("kind")) != "usb":
                print("  el código de recuperacion anterior ya no vale; "
                      "usa el nuevo de arriba")
                continue
            info = ((registro.get("sticks") or {}).get(
                str(perdido.get("serial"))) or {})
            donde = str(info.get("drive") or "").strip()
            rol = str(info.get("role") or perdido.get("label") or "")
            if not donde:
                print(f"  serial {perdido.get('serial')} ({rol}): "
                      "conéctalo y ejecuta run.cmd stick-add-v2 "
                      "<letra>:\\COFRE.KEY.nuevo")
                continue
            letra = donde if donde.endswith("\\") else donde + "\\"
            print(f"  {letra} ({rol}): conéctalo y ejecuta")
            print(f"    run.cmd stick-add-v2 {letra}COFRE.KEY.nuevo")
            print("    luego renombra COFRE.KEY.nuevo a COFRE.KEY")
    else:
        print("El pendrive con el que has abierto sigue abriendo el cofre.")


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    vault_path = Path(args.vault)
    vault = Vault(vault_path)
    _CON_CLAVE = {"meta", "rotate", "token-info", "alerts", "log", "host-assign",
                  "host-list", "get", "add", "del", "rename", "exec", "export",
                  "migrate", "stick-add-v2", "check", "list", "resume",
                  "health", "panic", "rekey", "run", "describe", "field"}
    con_codigo = bool(getattr(args, "recovery", False))
    session, serial = None, None
    if args.command in _CON_CLAVE:
        vault = prepare_audit(vault_path, args.gate, args.stick, args.allow_new_stick)

    if args.command == "version":                    # no-tildes
        import platform
        import tkinter
        print(f"COFRE {__version__}")
        print(f"Python {platform.python_version()}  Tk {tkinter.TkVersion}"
              f"  {platform.platform()}")
        print(f"cofre: {Path(__file__).resolve().parent}")
        print(f"datos: {vault_path}")
        return 0

    if args.command == "gen":
        if args.entropy:
            info = entropy(words=args.words, lang=args.lang)
            print(f"{info['palabras']} palabras de {info['lista']} entradas "
                  f"-> {info['bits']} bits  {info['aviso']}")
            return 0
        print(machine_password() if args.machine else human_password(words=args.words, lang=args.lang))
        return 0

    if args.command == "due":
        # El calendario no lleva nombres ni valores y se lee sin llave. El aviso
        # va en su propio hilo, como el resto de alertas.
        from cofre import schedule
        datos = schedule.leer(vault_path)
        if not args.notify:
            print(schedule.describe(datos))
            return 0
        if schedule.toca(datos):
            from cofre.alerts import show_message
            show_message("COFRE - recordatorio", schedule.mensaje(datos))
        else:
            print(schedule.describe(datos))
        return 0

    if args.command == "log" and args.stats:
        from cofre.audit import stats
        s = stats(str(vault_path))
        print(f"{s['entradas']} entradas (max {s['max']}) en {s['archivo']}")
        print(f"fallos: {s['fallos']}  pendrives usados: {', '.join(s['pendrives_usados'])}")
        return 0

    if args.command == "log":
        # el propio `log verify` escribe un evento: hay que tener el cofre
        # abierto y la clave ligada, o la linea queda sin firma y sin sello
        try:
            from cofre.audit import bind_store, set_key as _set_key
            material = material_for(args.gate, str(vault_path), args.stick,
                                    args.allow_new_stick)
            vault.bind_material(material)
            if vault.is_v2():
                store = vault._v2store()
                if store.master is None and material:
                    _set_key(store.unlock())
                else:
                    _set_key(store.master)
                bind_store(store)
                from cofre.audit import reseal_if_needed
                if reseal_if_needed(store, store.master):
                    print("aviso: el log iba por delante del checkpoint; resellado "
                          "con un evento 'restore' firmado")
        except Exception:
            pass
        if args.reanchor:
            # Re-anclar tapa lineas anteriores: solo lo hace el usuario, a mano y
            # con confirmación. Nunca como parte de un arreglo de código.
            if not args.motivo.strip():
                print("hace falta --motivo: por que se re-ancla", file=sys.stderr)
                return 1
            if not args.si:
                print("Esto mueve el punto desde el que se exige firma.")
                print("Las líneas anteriores quedaran exentas y el aviso saldra en log verify.")
                print(f"Motivo: {args.motivo}")
                respuesta = input("Escribe REANCLAR para confirmar: ").strip()
                if respuesta != "REANCLAR":
                    print("cancelado")
                    return 1
            record(str(vault_path), "reanchor", args.gate, None, ok=True,
                   actor="gui", detail=args.motivo[:150])
            from cofre.audit import stamp_vault
            stamp_vault(vault)
            print("re-anclado. Ejecuta 'log verify' para ver el aviso.")
            return 0

        if args.reseal:
            record(str(vault_path), "restore", args.gate, None, ok=True,
                   actor="gui", detail=(args.motivo or "checkpoint resellado tras restaurar")[:150])
            from cofre.audit import stamp_vault
            stamp_vault(vault)
            print("checkpoint resellado con un evento firmado")
            return 0

        if getattr(args, "verify", None) == "verify":
            from cofre.audit import check_checkpoint, legacy_report, verify as verify_log
            ok_legacy, txt_legacy = legacy_report(str(vault_path))
            print(("OK   " if ok_legacy else "FALLO") + "  historico v1: " + txt_legacy)
            ok, detalle = verify_log(str(vault_path))
            if ok and vault.is_v2():
                material = material_for(args.gate, str(vault_path), args.stick,
                                        args.allow_new_stick)
                vault.bind_material(material)
                store = vault._v2store() if vault.is_v2() else None
                if store is not None and store.master is not None:
                    ok2, detalle2 = check_checkpoint(store, store.master)
                    if not ok2:
                        ok, detalle = ok2, detalle2
                    else:
                        detalle += "; " + detalle2
            print(("OK   " if ok else "FALLO") + "  v2: " + detalle)
            record(str(vault_path), "audit-verify", args.gate, None, ok=ok,
                   detail=detalle[:160])
            return 0 if (ok and ok_legacy) else 1
        for line in tail(vault_path, args.lines):
            print(line)
        return 0

    if args.command == "stick-role":
        entry = set_role(str(vault_path), args.serial, args.role)
        if not entry:
            print(f"serial {args.serial} no esta registrado (run.cmd stick-list)")
            return 1
        print(f"serial {args.serial} ({entry.get('drive') or '?'}) ahora es {args.role}")
        record(str(vault_path), "stick-role", args.gate, args.serial, ok=True, detail=args.role)
        return 0

    if args.command == "stick-revoke":
        reg = load_registry(str(vault_path))
        if len(reg.get("sticks", {})) <= 1:
            print("No se puede revocar el unico pendrive registrado: perderias el cofre.")
            print("Registra primero el pendrive de recuperacion con stick-register.")
            return 1
        if revoke_stick(str(vault_path), args.serial):
            print(f"serial {args.serial} dado de baja")
            record(str(vault_path), "stick-revoke", args.gate, args.serial, ok=True)
            return 0
        print("ese serial no esta registrado")
        return 1

    if args.command == "serve":
        from cofre.serve import main as serve_main
        return serve_main(["--port", str(args.port)])

    if args.command == "check":
        # v2 no tiene `wrapper`: se abre con la llave del pendrive (o el código)
        if vault.is_v2():
            if con_codigo:
                vault = prepare_recovery(vault_path, args.gate)
                if not vault.is_v2() or vault._v2store().master is None:
                    return 1
                serial = None
            else:
                material = material_for(args.gate, str(vault_path), args.stick,
                                        args.allow_new_stick)
                vault.bind_material(material)
                if not material:
                    print("el cofre v2 necesita el pendrive de una de sus ranuras",
                          file=sys.stderr)
                    return 1
                serial = material.get("serial")
        else:
            if not vault.load().get("wrapper"):
                print("el cofre no esta inicializado", file=sys.stderr)
                return 1
            try:
                session, serial = resolve_session_key(args.gate, str(vault_path),
                                                     stick=args.stick,
                                                     allow_new=args.allow_new_stick)
            except (GateUnavailable, EOFError) as exc:
                record(str(vault_path), "check", args.gate, None, ok=False,
                       detail=str(exc))
                print("gate no disponible:", exc, file=sys.stderr)
                return 1
            try:
                vault.unlock(session)
            except Exception:
                print("la clave de sesión no corresponde a este cofre", file=sys.stderr)
                return 1
        existing = set(vault.names())
        missing = []
        for n in args.name:
            if n in existing:
                print(f"OK    {n}")
            else:
                missing.append(n)
                print(f"FALTA {n}")
        if not args.name:
            print(f"{len(existing)} secreto(s) en el cofre")
        record(str(vault_path), "check", args.gate, serial,
               name=f"{len(args.name)} nombres", ok=not missing)
        return 0 if not missing else 1

    if args.command == "describe":
        import json as _json
        if con_codigo:
            vault = prepare_recovery(vault_path, args.gate)
            if not vault.is_v2() or vault._v2store().master is None:
                return 1
        else:
            try:
                _session, serial = resolve_session_key(
                    args.gate, str(vault_path), stick=args.stick,
                    allow_new=args.allow_new_stick)
                material = material_for(args.gate, str(vault_path), args.stick,
                                        args.allow_new_stick)
                vault.bind_material(material)
            except (GateUnavailable, EOFError) as exc:
                print(f"gate no disponible: {exc}", file=sys.stderr)
                return 1
        salida = []
        for nombre in vault.names():
            meta = dict(vault.meta(nombre) or {})
            if args.minimal:
                # lo que puede acabar en un modelo de fuera: sin repos, Workers
                # ni dominios; solo que existe y como esta
                salida.append({
                    "name": nombre,
                    "type": meta.get("type") or "api_key",
                    "health": meta.get("health") or "sin_comprobar",
                })
                continue
            salida.append({
                "name": nombre,
                "type": meta.get("type") or "api_key",
                "provider": meta.get("provider") or "",
                "health": meta.get("health") or "sin_comprobar",
                "last_verified": meta.get("last_verified") or "",
                "urls": list(meta.get("urls") or []),
                "tags": list(meta.get("tags") or []),
                "consumers": list(meta.get("consumers") or []),
            })
        print(_json.dumps(salida, ensure_ascii=False, indent=2))
        record(str(vault_path), "describe", args.gate, serial, name="-",
               ok=True, detail=f"{len(salida)} entradas")
        return 0

    if args.command == "run":
        import subprocess
        from cofre import projectenv
        try:
            session, serial = resolve_session_key(
                args.gate, str(vault_path), stick=args.stick,
                allow_new=args.allow_new_stick)
            material = material_for(args.gate, str(vault_path), args.stick,
                                    args.allow_new_stick)
            vault.bind_material(material)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        ruta = Path(args.file) if args.file else projectenv.buscar(Path.cwd())
        if ruta is None or not Path(ruta).is_file():
            print("no encuentro .cofre-env.json en esta carpeta ni hacia arriba",
                  file=sys.stderr)
            return 1
        try:
            refs = projectenv.cargar(str(ruta))
        except projectenv.ProjectEnvError as exc:
            print(f"proyecto: {exc}", file=sys.stderr)
            return 1
        estados = projectenv.revisar(vault, session, refs)
        if args.check:
            fallos = 0
            for estado in estados:
                ref = estado["ref"]
                if estado["estado"] == "ok":
                    print(f"OK    {ref.destino} ({ref.etiqueta})")
                else:
                    fallos += 1
                    print(f"FALTA {ref.destino} ({ref.etiqueta}): "
                          f"{estado['detalle']}")
            record(str(vault_path), "run", args.gate, serial, name="-",
                   ok=not fallos,
                   detail=f"check {Path(ruta).name}: {len(refs)} referencias"[:150])
            return 0 if not fallos else 1
        try:
            entorno_ref = projectenv.resolver(vault, session, refs)
        except projectenv.ProjectEnvError as exc:
            print(f"proyecto: {exc}", file=sys.stderr)
            return 1
        sensibles = projectenv.sensibles(vault, refs)
        if sensibles and not args.si:
            print("Se van a usar secretos sensibles: " + ", ".join(sensibles))
            print("Escribe SI para continuar: ", end="", flush=True)
            if sys.stdin.readline().strip().upper() != "SI":
                print("cancelado: no se ha ejecutado nada")
                return 1
        comando = list(args.cmd)
        if comando and comando[0] == "--":
            comando = comando[1:]
        if not comando:
            print("falta el comando: run.cmd run -- npm start", file=sys.stderr)
            return 1
        entorno = dict(os.environ)
        entorno.update(entorno_ref)
        record(str(vault_path), "run", args.gate, serial,
               name=",".join(r.destino for r in refs), ok=True,
               detail=str(ruta)[:150])
        print(f"ejecutando con {len(entorno_ref)} variables (solo para ese proceso)")
        return subprocess.run(comando, env=entorno).returncode

    if args.command == "exec":
        import subprocess
        if not vault.load().get("wrapper"):
            print("el cofre no esta inicializado: python -m cofre.cli init", file=sys.stderr)
            return 1
        try:
            session, serial = resolve_session_key(args.gate, str(vault_path),
                                                 stick=args.stick, allow_new=args.allow_new_stick)
        except GateUnavailable as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        env = dict(os.environ)
        missing = []
        from cofre.policy import allowed as policy_allowed
        for name in args.name:
            meta = dict(vault.meta(name) or {})
            meta.setdefault("name", name)
            permitido, motivo = policy_allowed(meta, "exec")
            if not permitido:
                print(f"politica: {motivo}", file=sys.stderr)
                record(str(vault_path), "exec", args.gate, serial, name=name,
                       ok=False, detail="politica: exec")
                return 1
            try:
                env[name] = vault.get(session, name)
            except (KeyError, ValueError) as exc:  # VaultError no existe: era NameError
                missing.append(f"{name} ({type(exc).__name__})")
        if missing:
            print("no encontrados: " + ", ".join(missing), file=sys.stderr)
            record(str(vault_path), "exec", args.gate, serial, ok=False, detail=";".join(missing))
            return 1
        record(str(vault_path), "exec", args.gate, serial, name=",".join(args.name), ok=True)
        print(f"ejecutando con {len(args.name)} variables inyectadas (solo para ese proceso)")
        return subprocess.run(args.cmd, env=env).returncode

    if args.command == "resume":
        from cofre import rotation as rot
        material = material_for(args.gate, str(vault_path), args.stick,
                                args.allow_new_stick)
        vault.bind_material(material)
        if not vault.is_v2():
            print("el diario de rotación necesita un cofre v2", file=sys.stderr)
            return 1
        store = vault._v2store()
        try:
            plan = rot.plan_resume(store, store.master)
        except rot.JournalError as exc:
            print(f"no se actua: {exc}", file=sys.stderr)
            record(str(vault_path), "alert", args.gate, None, name="diario-no-fiable",
                   ok=False, detail=str(exc)[:150])
            return 1
        if plan is None:
            print("no hay ninguna rotación interrumpida")
            return 0
        print(f"rotación de '{plan['nombre']}' ({plan['proveedor']})")
        print(f"  fase: {plan['fase']}")
        print(f"  destinos: " + ", ".join(f"{d}={e}" for d, e in plan["destinos"].items()))
        print(f"  que paso: {plan['explicación']}")
        print(f"  opciones: {', '.join(plan['opciones'])} "
              f"(recomendada: {plan['recomendada']})")
        if plan["aviso"]:
            print(f"  AVISO: {plan['aviso']}")
        opcion = args.opcion or plan["recomendada"]
        if opcion not in plan["opciones"]:
            print(f"'{opcion}' no es posible en esta fase", file=sys.stderr)
            return 1
        if not args.si:
            print(f"se aplicara '{opcion}'. Escribe {opcion.upper()} para confirmar: ",
                  end="", flush=True)
            if sys.stdin.readline().strip() != opcion.upper():
                print("cancelado: no se ha tocado nada")
                return 1
        # el motor no ejecuta solo: aqui se aplica la opcion elegida. Para
        # Cloudflare hace falta el token administrador; sin el, deshacer no
        # podria borrar la credencial nueva ni continuar revocar la vieja.
        admin_valor = ""
        if str(plan.get("proveedor") or "") == "cloudflare":
            try:
                admin_valor = vault.get(None, "CLOUDFLARE_TOKEN_ADMIN")
            except Exception:
                admin_valor = ""
        token_gh = ""
        if any(str(d).startswith("gha") for d in plan.get("destinos") or {}):
            try:
                token_gh = vault.get(None, "GH_ADMIN_TOKEN")
            except Exception:
                token_gh = ""
        if opcion == "deshacer":
            rot.deshacer(store, store.master, opcion_confirmada=True,
                         admin_value=admin_valor, github_token=token_gh)
        else:
            salida = rot.continuar(store, store.master, opcion_confirmada=True,
                                   admin_value=admin_valor)
            if salida.startswith("interrumpida"):
                print(salida, file=sys.stderr)
                record(str(vault_path), "rotate", args.gate, None,
                       name=plan["nombre"], ok=False, detail=salida[:150])
                return 1
        print(f"hecho: {opcion}")
        record(str(vault_path), "rotate", args.gate, None, name=plan["nombre"],
               ok=True, detail=f"reanudada: {opcion}")
        return 0

    if args.command == "app-exec":
        # El token de la App NO se guarda en el cofre, ni en el log, ni en ningun
        # fichero: se pide, se inyecta en el proceso hijo y se olvida.
        import subprocess
        try:
            session, serial = resolve_session_key(args.gate, str(vault_path),
                                                 stick=args.stick,
                                                 allow_new=args.allow_new_stick)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        material = material_for(args.gate, str(vault_path), args.stick,
                                args.allow_new_stick)
        vault.bind_material(material)
        from cofre.providers.github import app_jwt, installation_token
        from cofre.providers.http import ProviderError
        try:
            pem = vault.get(session, args.clave)
            jwt = app_jwt(args.app_id, pem)
            valor, caduca = installation_token(jwt, args.installation)
        except (KeyError, ProviderError) as exc:
            print(f"no se pudo obtener el token de la App: {exc}", file=sys.stderr)
            return 1
        env = dict(os.environ)
        env[args.var] = valor
        record(str(vault_path), "app-exec", args.gate, serial,
               name=args.var, ok=True, detail=f"caduca {caduca[:19]}")
        del valor, jwt, pem
        print(f"ejecutando con {args.var} inyectado (caduca {caduca[:19]}, "
              "solo para ese proceso)")
        return subprocess.run(args.cmd, env=env).returncode

    if args.command == "alerts":
        # las alertas se firman: hay que tener el cofre abierto y la clave
        store = None
        try:
            from cofre.audit import bind_store, set_key as _set_key
            material = material_for(args.gate, str(vault_path), args.stick,
                                    args.allow_new_stick)
            vault.bind_material(material)
            if vault.is_v2():
                store = vault._v2store()
                _set_key(store.master or store.unlock())
                bind_store(store)
        except Exception:
            pass
        from cofre import alerts as alerts_mod
        estado_path = Path(vault_path).parent / ".cofre-alert-state.json"
        estado = alerts_mod.AlertState()
        if not args.reset and estado_path.exists():
            try:
                estado = alerts_mod.AlertState.from_dict(
                    json.loads(estado_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        eventos = alerts_mod.events_of(str(vault_path))
        cfg = alerts_mod.load_settings(str(vault_path))
        nuevas = alerts_mod.apply_cooldown(
            alerts_mod.evaluate(eventos, cfg, estado), estado, cfg)
        # credenciales viejas sin revocar: no salen de un evento sino del indice
        if store is not None:
            try:
                nuevas.extend(alerts_mod.evaluate_unrevoked(store, eventos))
            except Exception:
                pass
        if not nuevas:
            print("sin alertas nuevas")
        for a in nuevas:
            print(f"{a.severity.upper():8} {a.rule:16} {a.text}")
            record(str(vault_path), "alert", args.gate, None, name=a.rule,
                   ok=False, detail=f"{a.severity}: {a.text}"[:150])
        estado_path.write_text(json.dumps(estado.to_dict(), indent=2), encoding="utf-8")
        return 0

    if args.command == "field":
        try:
            session, serial = resolve_session_key(
                args.gate, str(vault_path), stick=args.stick,
                allow_new=args.allow_new_stick)
            material = material_for(args.gate, str(vault_path), args.stick,
                                    args.allow_new_stick)
            vault.bind_material(material)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        if not vault.is_v2():
            print("los campos solo existen en cofre v2", file=sys.stderr)
            return 1
        store = vault._v2store()
        if store.master is None:
            print("el cofre esta cerrado", file=sys.stderr)
            return 1
        try:
            contenido = store._vault.blob(store._data, store.master, args.name)
        except KeyError:
            print(f"no existe el secreto '{args.name}'", file=sys.stderr)
            return 1
        valor = read_secret(f"valor de {args.campo}: ")
        if not valor:
            print("sin valor: no se ha guardado nada", file=sys.stderr)
            return 1
        contenido.setdefault("fields", {})[args.campo] = valor
        store._vault.set_blob(store._data, store.master, args.name, contenido)
        store.save(store._data)
        record(str(vault_path), "edit", args.gate, serial, name=args.name,
               ok=True, detail=f"campo {args.campo}")
        print(f"{args.name}: campo '{args.campo}' guardado (el valor no se muestra)")
        return 0

    if args.command == "health":
        try:
            _session, serial = resolve_session_key(
                args.gate, str(vault_path), stick=args.stick,
                allow_new=args.allow_new_stick)
            material = material_for(args.gate, str(vault_path), args.stick,
                                    args.allow_new_stick)
            vault.bind_material(material)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        if not vault.is_v2():
            print("la salud de las credenciales necesita un cofre v2",
                  file=sys.stderr)
            return 1
        store = vault._v2store()
        if store.master is None:
            print("no se pudo abrir el cofre", file=sys.stderr)
            return 1
        from cofre import health
        resultados = health.revisar(store, store.master)
        health.aplicar(store, store.master, resultados)
        if args.json:
            print(json.dumps([{"nombre": r.nombre, "estado": r.estado,
                               "detalle": r.detalle, "caduca": r.caduca,
                               "comprobado": r.comprobado}
                              for r in resultados], ensure_ascii=False, indent=2))
        else:
            for resultado in resultados:
                print(f"{resultado.nombre:28} {resultado.estado:14} "
                      f"{resultado.detalle}")
            cuenta = health.resumen(resultados)
            print("")
            print(" · ".join(f"{estado}: {n}" for estado, n in cuenta.items())
                  or "sin credenciales que comprobar")
        detalle = ", ".join(f"{estado}={n}"
                            for estado, n in health.resumen(resultados).items())
        record(str(vault_path), "health", args.gate, serial, name="-",
               ok=True, detail=(detalle or "sin credenciales")[:150])
        from cofre.audit import stamp_vault
        stamp_vault(vault)
        return 0

    if args.command == "token-info":
        try:
            session, serial = resolve_session_key(args.gate, str(vault_path),
                                                 stick=args.stick,
                                                 allow_new=args.allow_new_stick)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        from cofre.providers import get as provider_get
        material = material_for(args.gate, str(vault_path), args.stick,
                                args.allow_new_stick)
        vault.bind_material(material)
        meta = dict(vault.meta(args.name) or {})
        proveedor_nombre = str(meta.get("provider") or "")
        if not proveedor_nombre:
            print("el secreto no tiene proveedor", file=sys.stderr)
            return 1
        proveedor = provider_get(proveedor_nombre)
        valor = vault.get(session, args.name)
        v = proveedor.verify(valor, meta)
        partes = [f"{args.name}: {'válido' if v.ok else 'NO válido'}"]
        if v.status:
            partes.append(f"estado {v.status}")
        if v.token_id:
            partes.append(f"id {v.token_id}")
        if v.expires_at:
            partes.append(f"caduca {v.expires_at}")
        print(" | ".join(partes))
        if v.detail and v.detail != "activo":
            print(f"  detalle: {v.detail}")
        return 0

    if args.command == "meta":
        # los metadatos viven en el indice cifrado (v2) o en el blob v1
        try:
            material = material_for(args.gate, str(vault_path), args.stick,
                                    args.allow_new_stick)
            vault.bind_material(material)
        except Exception:
            pass
        meta = dict(vault.meta(args.name) or {})
        if not meta:
            print(f"no existe el secreto '{args.name}'", file=sys.stderr)
            return 1
        ref = dict(meta.get("provider_ref") or {})
        cambios = []
        if args.provider:
            meta["provider"] = args.provider
            cambios.append("provider=" + args.provider)
        if args.token_id:
            ref["token_id"] = args.token_id
            cambios.append("token_id=" + args.token_id)
        if args.account_id:
            ref["account_id"] = args.account_id
            cambios.append("account_id=" + args.account_id)
        if args.expires:
            meta["expires_at"] = args.expires
            cambios.append("expires_at=" + args.expires)
        if args.rotate_every:
            meta["rotate_every_days"] = args.rotate_every
            cambios.append(f"rotate_every_days={args.rotate_every}")
        if args.url:
            meta["urls"] = args.url
            cambios.append("urls=" + ",".join(args.url))
        if args.consumer:
            meta["consumers"] = args.consumer
            cambios.append("consumers=" + ",".join(args.consumer))
        if args.kind:
            meta["type"] = args.kind
            cambios.append("type=" + args.kind)
        if args.app_id:
            meta["app_id"] = args.app_id
            cambios.append("app_id=" + args.app_id)
        if args.installation:
            meta["installation_id"] = args.installation
            cambios.append("installation=" + args.installation)
        if args.admin:
            etiquetas = [t for t in meta.get("tags", []) if t != "admin"] + ["admin"]
            meta["tags"] = etiquetas
            meta["policy"] = {"confirm": True, "browser": False, "exec": False}
            cambios.append("tags=admin+ (confirmar siempre, sin navegador ni exec)")
        if ref:
            meta["provider_ref"] = ref
        if not cambios:
            print(f"{args.name}: {json.dumps({k: meta.get(k) for k in ('type','provider','expires_at','rotate_every_days','urls','consumers','tags')}, ensure_ascii=False)}")
            return 0
        if vault.is_v2():
            store = vault._v2store()
            idx = store.index(store._data, store.master)
            entrada = idx["entries"].get(args.name)
            if not entrada:
                print("no se pudo leer la entrada del indice", file=sys.stderr)
                return 1
            entrada.update(meta)
            store._write_index(store._data, store.master, idx)
            store.save(store._data)
        else:
            print("los metadatos solo se editan en v2", file=sys.stderr)
            return 1
        record(str(vault_path), "meta", args.gate, None, name=args.name, ok=True,
               detail=";".join(cambios)[:150])
        print(f"{args.name}: " + ", ".join(cambios))
        return 0

    if args.command == "rotate":
        try:
            session, serial = resolve_session_key(args.gate, str(vault_path),
                                                 stick=args.stick,
                                                 allow_new=args.allow_new_stick)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        from cofre.providers import get as provider_get
        from cofre.providers.http import ProviderError
        material = material_for(args.gate, str(vault_path), args.stick,
                                args.allow_new_stick)
        vault.bind_material(material)
        meta = dict(vault.meta(args.name) or {})
        if not meta:
            print(f"no existe el secreto '{args.name}'", file=sys.stderr)
            return 1
        proveedor_nombre = str(meta.get("provider") or "")
        if not proveedor_nombre:
            print("el secreto no tiene proveedor: usa 'meta --provider cloudflare'", file=sys.stderr)
            return 1
        proveedor = provider_get(proveedor_nombre)
        valor = vault.get(session, args.name)
        ref = dict(meta.get("provider_ref") or {})
        token_id = str(ref.get("token_id") or "")
        consumidores = list(meta.get("consumers") or [])
        admin_nombre = args.admin or "CLOUDFLARE_TOKEN_ADMIN"
        via_manual = args.manual or not getattr(proveedor, "can_auto_rotate", False)

        verificacion = proveedor.verify(valor, meta)
        print(f"estado del token: {'activo' if verificacion.ok else 'NO válido'}"
              + (f" (caduca {verificacion.expires_at})" if verificacion.expires_at else "")
              + (f" - {verificacion.detail}" if verificacion.detail else ""))
        modo = "B (crear reemplazo y desplegar)" if consumidores else "A (roll del valor)"
        if via_manual:
            modo = "asistida (pegar el valor nuevo)"
        print(f"modo de rotación: {modo}")
        if consumidores:
            print("consumidores que habria que actualizar: " + ", ".join(consumidores))

        if args.dry_run:
            print("dry-run: no se ha tocado nada")
            record(str(vault_path), "rotate", args.gate, serial, name=args.name,
                   ok=True, detail="dry-run")
            return 0

        # La rotacion pasa por el motor con diario (5.7). El diario vive en el
        # indice cifrado, asi que hace falta un cofre v2 abierto. Sin destinos y
        # con proveedor automatico, la variante A (roll) no tiene vuelta atras y
        # se queda fuera del motor.
        store = vault._v2store() if vault.is_v2() else None
        con_motor = via_manual or bool(consumidores)
        if con_motor and (store is None or store.master is None):
            print("la rotación con diario necesita un cofre v2 abierto: usa 'migrate'",
                  file=sys.stderr)
            return 1

        necesita_admin = (not via_manual) or any(
            str(c).startswith("cfw:") for c in consumidores)
        admin_valor = ""
        if necesita_admin:
            # la rotacion real necesita el token administrador, que pide confirmacion
            meta_admin = dict(vault.meta(admin_nombre) or {})
            if not meta_admin:
                print(f"falta el secreto administrador '{admin_nombre}': "
                      "guardalo con la etiqueta admin", file=sys.stderr)
                return 1
            if not args.si:
                print(f"Se va a usar '{admin_nombre}' para rotar '{args.name}'.")
                print("Escribe ROTAR para confirmar: ", end="", flush=True)
                if sys.stdin.readline().strip() != "ROTAR":
                    print("cancelado")
                    return 1
            admin_valor = vault.get(session, admin_nombre)

        if not con_motor:
            # Variante A: mismo token, valor nuevo. El viejo muere en el acto y
            # no hay nada que deshacer, por eso no toca el motor ni el diario.
            try:
                nuevo = proveedor.roll_value(token_id, admin_valor, meta)
                vault.add(session, args.name, nuevo, meta.get("tags", []),
                          meta.get("urls", []))
                record(str(vault_path), "rotate", args.gate, serial, name=args.name,
                       ok=True, detail="roll")
                from cofre.audit import stamp_vault
                stamp_vault(vault)
                print("rotado: valor nuevo guardado en el cofre (no se muestra)")
                return 0
            except ProviderError as exc:
                print(f"la rotación fallo: {exc}", file=sys.stderr)
                record(str(vault_path), "rotate", args.gate, serial, name=args.name,
                       ok=False, detail=str(exc)[:150])
                return 1

        # Destinos de GitHub: el despliegue necesita un token con permiso de
        # secretos. Se avisa antes de empezar, no a mitad.
        token_gh = ""
        if any(str(c).startswith("gha") for c in consumidores):
            try:
                token_gh = vault.get(session, "GH_ADMIN_TOKEN")
            except Exception:
                print("aviso: falta GH_ADMIN_TOKEN; los destinos de GitHub Actions "
                      "fallaran al desplegar", file=sys.stderr)

        def desplegar(destinos: list[str], valor_nuevo: str) -> None:
            from cofre.consumers import deploy
            resultados = deploy(destinos, valor_nuevo, github_token=token_gh,
                                cloudflare_token=admin_valor)
            fallos = [f"{etiqueta}: {detalle}" for etiqueta, ok, detalle
                      in resultados if not ok]
            if fallos:
                raise ProviderError("; ".join(fallos)[:200])

        def crear():
            if via_manual:
                # GitHub y similares: se crea a mano en la web. Se comprueba
                # ANTES de escribir nada (ni diario, ni pendiente).
                url = proveedor.manual_url(meta)
                print(f"crea el valor nuevo en: {url}")
                nuevo = read_secret("valor nuevo: ")
                if not nuevo:
                    raise ProviderError("sin valor: no se ha tocado nada")
                verif_nuevo = proveedor.verify(nuevo, meta)
                if not verif_nuevo.ok:
                    raise ProviderError(
                        f"el valor nuevo NO es válido ({verif_nuevo.detail}). "
                        "No se guarda nada: el viejo sigue intacto.")
                verif_viejo = proveedor.verify(valor, meta)
                if (verif_viejo.ok and "usuario " in verif_viejo.detail
                        and "usuario " in verif_nuevo.detail):
                    usuario_viejo = verif_viejo.detail.split("usuario ", 1)[1].split(",")[0]
                    usuario_nuevo = verif_nuevo.detail.split("usuario ", 1)[1].split(",")[0]
                    if usuario_viejo != usuario_nuevo:
                        raise ProviderError(
                            f"el valor nuevo es de '{usuario_nuevo}' y el viejo de "
                            f"'{usuario_viejo}'. No se guarda nada.")
                ref_nuevo = dict(ref)
                if verif_nuevo.token_id:
                    # si el proveedor da el id (Cloudflare), se guarda el nuevo:
                    # dejar el viejo apuntaria a un token que ya no es el activo
                    ref_nuevo["token_id"] = verif_nuevo.token_id
                return nuevo, ref_nuevo
            nuevo, ref_nuevo = proveedor.create_replacement(meta, admin_valor)
            return nuevo, dict(ref_nuevo)

        def verificar(valor_nuevo: str) -> None:
            # Despues de desplegar: si el proveedor no acepta el valor nuevo,
            # el diario se queda en "desplegada" y lo recomendado es deshacer.
            comprobacion = proveedor.verify(valor_nuevo, meta)
            if not comprobacion.ok:
                raise ProviderError(
                    f"el valor nuevo no verifica: {comprobacion.detail}")

        def revocar() -> None:
            # GitHub revoca por valor; Cloudflare, por id de token.
            objetivo = valor if getattr(proveedor, "name", "") == "github" else token_id
            if not objetivo:
                raise ProviderError("no se sabe que credencial vieja revocar")
            proveedor.revoke(objetivo, admin_valor, meta)

        from cofre import rotation as rot
        resultado = rot.run_rotation(
            store, store.master, args.name, proveedor_nombre,
            valor_nuevo="", ref_nueva=None, destinos=consumidores,
            desplegar=desplegar, revocar=revocar,
            revocar_viejo=bool(args.revoke_old), ref_old=ref,
            crear=crear, verificar=verificar)

        from cofre.audit import stamp_vault
        if resultado == "completada":
            record(str(vault_path), "rotate", args.gate, serial, name=args.name,
                   ok=True, detail=("consumidores" if consumidores else "asistida"))
            stamp_vault(vault)
            if consumidores:
                print("rotación completada: valor nuevo desplegado")
            else:
                print("valor nuevo verificado y guardado.")
            if args.revoke_old:
                print("valor viejo revocado")
            else:
                print("la credencial vieja sigue activa: se puede revocar desde "
                      "Salud (COFRE lo recuerda y avisa a los 7 días)")
            return 0
        mensaje = resultado.split(": ", 1)[-1]
        if resultado.startswith("no-creada"):
            print(f"no se creo la credencial nueva: {mensaje}", file=sys.stderr)
            record(str(vault_path), "rotate", args.gate, serial, name=args.name,
                   ok=False, detail=("no creada: " + mensaje)[:150])
            return 1
        print(f"rotación interrumpida: {mensaje}", file=sys.stderr)
        print("no queda nada a medias: el valor viejo sigue siendo el activo. "
              "Ejecuta 'resume' para continuar o deshacer.", file=sys.stderr)
        record(str(vault_path), "rotate", args.gate, serial, name=args.name,
               ok=False, detail=("interrumpida: " + mensaje)[:150])
        stamp_vault(vault)
        return 1

    if args.command == "panic":
        try:
            session, serial = resolve_session_key(
                args.gate, str(vault_path), stick=args.stick,
                allow_new=args.allow_new_stick)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        material = material_for(args.gate, str(vault_path), args.stick,
                                args.allow_new_stick)
        vault.bind_material(material)
        if not vault.is_v2():
            print("el pánico necesita un cofre v2", file=sys.stderr)
            return 1
        store = vault._v2store()
        if store.master is None:
            print("no se pudo abrir el cofre", file=sys.stderr)
            return 1
        from cofre import panic
        admin_nombre = args.admin or "CLOUDFLARE_TOKEN_ADMIN"
        admin_meta = dict(vault.meta(admin_nombre) or {})
        admin_valor = ""
        if admin_meta:
            try:
                admin_valor = vault.get(session, admin_nombre)
            except Exception:
                admin_valor = ""
        plan = panic.planificar(store, store.master, bool(admin_meta))
        print("PANICO - plan" + (" (dry-run: no se toca nada)" if args.dry_run else ""))
        for accion in plan.acciones:
            linea = f"  {accion.tipo:7} {accion.nombre}  {accion.detalle}"
            if accion.url:
                linea += f"  {accion.url}"
            print(linea)
        for aviso in plan.avisos:
            print(f"  AVISO: {aviso}")
        if plan.canarios:
            print("  canarios que NO se tocan: " + ", ".join(plan.canarios))
        print("  despues: código de recuperacion nuevo y rekey; los pendrives "
              "que no esten conectados se quedan fuera")
        if args.dry_run:
            return 0
        if not args.si:
            print("Escribe REVOCAR TODO para confirmar: ", end="", flush=True)
            if sys.stdin.readline().strip() != "REVOCAR TODO":
                print("cancelado: no se ha tocado nada")
                return 1
        token_gh = ""
        try:
            token_gh = vault.get(session, "GH_ADMIN_TOKEN")
        except Exception:
            token_gh = ""
        resultados = panic.ejecutar(store, store.master, plan, admin_valor,
                                    token_gh=token_gh)
        fallos = 0
        for accion, ok, detalle in resultados:
            print(f"  {'OK   ' if ok else 'FALLA'} {accion.tipo} "
                  f"{accion.nombre}: {detalle}")
            if not ok:
                fallos += 1
        codigo, perdidos, error = rekey_vivo(
            vault, vault_path, material, motivo="panico", gate=args.gate,
            serial=serial, actor="cli")
        if error:
            fallos += 1
            print(f"no se pudo hacer el rekey: {error}", file=sys.stderr)
            print("los tokens ya estan revocados; el cofre sigue con la clave "
                  "anterior", file=sys.stderr)
            try:
                record(str(vault_path), "panic", args.gate, serial, name="-",
                       ok=False, detail=f"rekey fallido: {error}"[:150])
            except Exception:
                pass
        else:
            record(str(vault_path), "panic", args.gate, serial, name="-",
                   ok=(fallos == 0),
                   detail=(f"{len(plan.acciones)} acciones, {fallos} fallos; "
                           f"roll={plan.cuenta('roll')} "
                           f"revoke={plan.cuenta('revoke')}")[:150])
            _print_rekey(codigo, perdidos, vault_path)
        from cofre.audit import stamp_vault
        stamp_vault(vault)
        return 0 if fallos == 0 else 1

    if args.command == "rekey":
        try:
            _session, serial = resolve_session_key(
                args.gate, str(vault_path), stick=args.stick,
                allow_new=args.allow_new_stick)
        except (GateUnavailable, EOFError) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        material = material_for(args.gate, str(vault_path), args.stick,
                                args.allow_new_stick)
        vault.bind_material(material)
        if not vault.is_v2():
            print("el rekey necesita un cofre v2", file=sys.stderr)
            return 1
        store = vault._v2store()
        if store.master is None:
            print("no se pudo abrir el cofre", file=sys.stderr)
            return 1
        if not args.si:
            print("Se va a cambiar la clave maestra y el código de recuperacion.")
            print("Los pendrives que no esten conectados se quedan fuera.")
            print("Escribe REKEY para confirmar: ", end="", flush=True)
            if sys.stdin.readline().strip() != "REKEY":
                print("cancelado: no se ha tocado nada")
                return 1
        codigo, perdidos, error = rekey_vivo(
            vault, vault_path, material, motivo=args.motivo or "manual",
            gate=args.gate, serial=serial, actor="cli")
        if error:
            print(f"no se pudo hacer el rekey: {error}", file=sys.stderr)
            record(str(vault_path), "rekey", args.gate, serial, name="-",
                   ok=False, detail=error[:150])
            return 1
        record(str(vault_path), "rekey", args.gate, serial, name="-", ok=True,
               detail=f"clave nueva; {len(perdidos)} slots fuera")
        _print_rekey(codigo, perdidos, vault_path)
        from cofre.audit import stamp_vault
        stamp_vault(vault)
        return 0

    if args.command == "stick-list":
        return cmd_stick_list(str(vault_path))

    if args.command == "stick-verify":
        return cmd_stick_verify(str(vault_path))

    if args.command == "migrate":
        from cofre.hosts import load as load_hosts
        from cofre.v2.migrate import MigrateError, migrate
        path = Path(vault_path)
        data = vault.load()
        if data.get("format") == 2:
            print("el cofre ya esta en formato v2")
            return 0
        try:
            src, serial = find_stick([args.stick] if args.stick else None,
                                    str(path), args.allow_new_stick)
        except (StickNotFound, StickNotRegistered) as exc:
            print(f"gate no disponible: {exc}", file=sys.stderr)
            return 1
        try:
            hosts_map = load_hosts(str(path))
        except Exception:
            hosts_map = {}
        try:
            res = migrate(path, read_key(src), serial, dry_run=args.dry_run,
                          hosts_map=hosts_map)
        except MigrateError as exc:
            print(f"migracion abortada: {exc}", file=sys.stderr)
            return 1
        if args.dry_run:
            print("dry-run: se migrarian", len(res["entradas"]), "secretos:", ", ".join(res["entradas"]) or "(ninguno)")
            print("dominios que se importarian:", res["dominios"] or "(ninguno)")
            return 0
        print("migrado a v2. Secretos:", ", ".join(res["entradas"]) or "(ninguno)")
        print("copia del v1:", res["v1_guardado"])
        print("backup completo:", res["backup"])
        print("")
        print("CODIGO DE RECUPERACION (se muestra UNA sola vez, apuntalo en papel):")
        print("  " + res["código"])
        record(str(path), "migrate", args.gate, serial, name=f"{len(res['entradas'])} secretos", ok=True)
        return 0

    if args.command == "stick-add-v2":
        from cofre.v2.slots import new_usb_slot, open_with_stick, SlotError
        from cofre.v2.vault import VaultV2

        path = Path(vault_path)
        raw = VaultV2(path).load()
        if not VaultV2.is_v2(raw):
            print("el cofre no esta en v2: ejecuta migrate primero", file=sys.stderr)
            return 1
        destino = Path(args.path)
        if destino.exists() and not destino.name.endswith(".nuevo"):
            print(f"ya existe {destino}: usa un nombre .nuevo", file=sys.stderr)
            return 1
        drive = _drive_of(str(destino))
        serial = volume_serial(drive)
        if serial is None:
            print(f"no se puede leer el serial de {drive}", file=sys.stderr)
            return 1
        try:
            src, src_serial = find_stick([args.stick] if args.stick else None, str(path))
            master, _slot = open_with_stick(raw, read_key(src), src_serial)
        except Exception as exc:
            print(f"no se pudo abrir el cofre para anadir la ranura: {exc}", file=sys.stderr)
            return 1
        nueva = secrets.token_bytes(32)
        destino.write_bytes(nueva)
        nuevo_slot = new_usb_slot(master, nueva, serial, f"pendrive {serial}", "")
        VaultV2(path).add_slot(raw, nuevo_slot)
        VaultV2(path).save(raw)
        # comprobar que abre ANTES de dar por buena la llave
        try:
            releido = VaultV2(path).load()
            open_with_stick(releido, nueva, serial)
        except SlotError as exc:
            destino.unlink(missing_ok=True)
            print(f"la llave nueva no abre: {exc}. No se ha tocado nada mas.", file=sys.stderr)
            return 1
        register_stick(str(path), serial, drive)
        print(f"llave nueva escrita en {destino}")
        print(f"ranura anadida para el serial {serial} ({drive})")
        print("PASO SIGUIENTE, a mano: renombrar a COFRE.KEY cuando confirmes que abre.")
        record(str(path), "stick-add-v2", args.gate, serial, ok=True)
        return 0

    if args.command in ("host-assign", "host-list"):
        from cofre.hosts import HostsError, assign, clean_host, load
        try:
            if args.command == "host-assign":
                if vault.is_v2():
                    # D10: los dominios viven dentro del indice cifrado
                    material = material_for(args.gate, str(vault_path), args.stick,
                                            args.allow_new_stick)
                    vault.bind_material(material)
                    if args.name not in vault.names():
                        print(f"no existe el secreto '{args.name}'", file=sys.stderr)
                        return 1
                    limpios = [clean_host(h) for h in args.hosts]
                    vault.set_urls(args.name, limpios)
                    print(f"{args.name}: {', '.join(limpios)}")
                    record(str(vault_path), "host-assign", args.gate, None,
                           name=args.name, ok=True, detail=",".join(limpios))
                    return 0
                if not vault.load().get("wrapper"):
                    print("el cofre no esta inicializado", file=sys.stderr)
                    return 1
                if args.name not in vault.names():
                    print(f"no existe el secreto '{args.name}'", file=sys.stderr)
                    return 1
                mapping = assign(str(vault_path), args.name, args.hosts)
                print(f"{args.name}: {', '.join(mapping.get(args.name, []))}")
                record(str(vault_path), "host-assign", args.gate, None,
                       name=args.name, ok=True,
                       detail=",".join(mapping.get(args.name, [])))
                return 0
            if vault.is_v2():
                material = material_for(args.gate, str(vault_path), args.stick,
                                        args.allow_new_stick)
                vault.bind_material(material)
                nombres = [args.name] if args.name else vault.names()
                if not nombres:
                    print("el cofre esta vacio o cerrado")
                    return 0
                for nombre in nombres:
                    urls = vault.urls(nombre)
                    print(f"  {nombre:28} {', '.join(urls) or '(sin asignar)'}")
                return 0
            mapping = load(str(vault_path))
            if args.name:
                print(f"{args.name}: {', '.join(mapping.get(args.name, [])) or '(sin asignar)'}")
                return 0
            if not mapping:
                print("ningún secreto tiene dominios asignados")
                return 0
            for nombre in sorted(mapping):
                print(f"  {nombre:28} {', '.join(mapping[nombre])}")
            return 0
        except HostsError as exc:
            print(f"dominio inválido: {exc}", file=sys.stderr)
            return 1

    if args.command == "salt":
        try:
            info = salt_show(str(vault_path))
        except (SaltMissing, SaltMismatch) as exc:
            print(f"problema con la sal: {exc}", file=sys.stderr)
            return 1
        print(f"sal del cofre ({info['bytes']} bytes): {info['sal_base64']}")
        print(f"  fichero:      {info['fichero']}")
        print(f"  dentro del cofre: {'si' if info['dentro_del_cofre'] else 'no'}")
        print("Guarda esa cadena en un sitio resistente. Sin ella, el cofre no se")
        print("puede reabrir aunque conserves el pendrive.")
        return 0

    if args.command == "gui":
        from cofre.gui import main as gui_main
        return gui_main(["--vault", str(vault_path), "--gate", args.gate] +
                        (["--stick", args.stick] if args.stick else []) +
                        (["--allow-new-stick"] if args.allow_new_stick else []) +
                        (["--selftest"] if getattr(args, "selftest", False) else []))

    if args.command == "shell":
        return cmd_shell(str(vault_path), args.gate, args.stick, args.allow_new_stick)

    if args.command == "stick-init":
        target = Path(args.path)
        if target.exists() and not args.force:
            print("ya existe %s: no se sobrescribe (usa --force)" % target)
            return 1
        path = create_key_on(str(target))
        drive = _drive_of(str(target))
        serial = volume_serial(drive)
        register_stick(str(vault_path), serial, drive)
        print("clave de 32 bytes creada en %s" % path)
        print(f"serial de volumen registrado: {serial} ({drive})")
        print("A partir de ahora, sin este pendrive el cofre no se abre.")
        record(str(vault_path), "stick-init", args.gate, serial, ok=True)
        return 0

    if args.command == "stick-register":
        # R2 (2026-11-16): registrar un serial sin comprobar la llave crea falsos
        # sobres de recuperacion. Antes de autorizar nada, la llave de ese
        # pendrive tiene que abrir ESTE cofre. Se comprueba aquí, no de memoria.
        target = Path(args.path)
        if not target.is_file():
            print("no existe %s" % target)
            return 1
        try:
            key = read_key(str(target))
        except ValueError as exc:
            print(exc)
            return 1
        if vault.is_v2():
            from cofre.v2.slots import open_with_stick, SlotError
            try:
                open_with_stick(vault.load(), key, volume_serial(_drive_of(str(target))))
            except SlotError:
                print("esta llave NO abre una ranura de este cofre. No se registra el serial.")
                print("Si es un pendrive nuevo: python -m cofre.cli stick-add-v2 %s" % args.path)
                record(str(vault_path), "stick-register", args.gate, None, ok=False,
                       detail="la llave no abre el cofre")
                return 1
            register_stick(str(vault_path), volume_serial(_drive_of(str(target))),
                           _drive_of(str(target)))
            print("llave comprobada contra su ranura. serial autorizado")
            record(str(vault_path), "stick-register", args.gate,
                   volume_serial(_drive_of(str(target))), ok=True)
            return 0
        if not vault.load().get("wrapper"):
            print("el cofre no esta inicializado: primero init y rellena secretos")
            return 1
        try:
            session = usb_session_key(str(target), _salt_for(str(vault_path)))
            vault.unlock(session)
        except Exception as exc:
            if os.environ.get("COFRE_DEBUG"):
                import traceback
                traceback.print_exc()
            print(f"esta llave NO abre este cofre ({type(exc).__name__}). "
                  "No se registra el serial.")
            print("Si el pendrive esta vacio o tiene la llave de otro cofre, lo correcto es:")
            print("  python -m cofre.cli stick-copy %s" % args.path)
            record(str(vault_path), "stick-register", args.gate, None, ok=False,
                   detail="la llave no abre el cofre")
            return 1
        del key
        drive = _drive_of(str(target))
        serial = volume_serial(drive)
        register_stick(str(vault_path), serial, drive)
        print(f"llave comprobada: abre el cofre. serial {serial} ({drive}) autorizado")
        record(str(vault_path), "stick-register", args.gate, serial, ok=True)
        return 0

    if args.command == "stick-copy":
        target = Path(args.dest)
        if target.exists() and not args.force:
            print("ya existe %s: usa --force para sobrescribir" % target)
            return 1
        try:
            src, _src_serial = find_stick(None, str(vault_path), args.allow_new_stick)
        except (StickNotFound, StickNotRegistered) as exc:
            print(exc)
            return 1
        copy_key_to(str(target), read_key(src))
        drive = _drive_of(str(target))
        serial = volume_serial(drive)
        register_stick(str(vault_path), serial, drive)
        print("clave copiada de %s a %s" % (src, target))
        print(f"serial {serial} ({drive}) autorizado como pendrive del cofre")
        print("Dos pendrives abren ya el mismo cofre. Dos copias de la clave son")
        print("el precio del sobre de recuperacion: se tratan como dos llaves fisicas.")
        record(str(vault_path), "stick-copy", args.gate, serial, ok=True)
        return 0

    if args.command == "probe":
        for mode in ("usb", "hid"):
            try:
                key, serial = resolve_session_key(mode, str(vault_path),
                                                 stick=args.stick, allow_new=args.allow_new_stick)
                print(f"gate {mode} operativo (pendrive serial {serial})")
                del key
            except GateUnavailable as exc:
                print(f"gate {mode} NO operativo: {exc}")
        return 0

    session, serial = None, None
    if con_codigo:
        vault = prepare_recovery(vault_path, args.gate)
        if not vault.is_v2() or vault._v2store().master is None:
            return 1
    else:
        try:
            session, serial = resolve_session_key(
                args.gate, str(vault_path), stick=args.stick,
                allow_new=args.allow_new_stick)
        except (GateUnavailable, EOFError) as exc:
            record(str(vault_path), args.command, args.gate, None, ok=False,
                   detail=str(exc))
            print("gate no disponible:", exc, file=sys.stderr)
            return 1

    try:
        if vault.is_v2() and not con_codigo:
            material = material_for(args.gate, str(vault_path), args.stick,
                                    args.allow_new_stick)
            vault.bind_material(material)
            if not material:
                print("el cofre v2 necesita el pendrive de una de sus ranuras",
                      file=sys.stderr)
                return 1

        if args.command in ("get", "export") and not sys.stdout.isatty() and not args.allow_pipe:
            print("get/export no imprime secretos si la salida esta redirigida. "
                  "Usa --allow-pipe si de verdad quieres volcarlos a un fichero o a un pipe.",
                  file=sys.stderr)
            record(str(vault_path), args.command, args.gate, serial, ok=False,
                   detail="salida no interactiva")
            return 1

        if args.command != "init" and not vault.is_v2():
            if not vault.load().get("wrapper"):
                print("el cofre no esta inicializado: python -m cofre.cli init", file=sys.stderr)
                return 1
            try:
                vault.unlock(session)
            except Exception:
                print("la clave de sesión no corresponde a este cofre: pendrive equivocado "
                      "o PIN incorrecto", file=sys.stderr)
                record(str(vault_path), args.command, args.gate, serial, ok=False,
                       detail="sesión invalida")
                return 1

        try:
            audit_set_key(vault.unlock(session))
            try:
                if vault.is_v2():
                    from cofre.audit import bind_store
                    bind_store(vault._v2store())
            except Exception:
                pass
        except Exception:
            audit_clear_key()

        if args.command == "init":
            vault.init(session, salt=_salt_for(str(vault_path)))
            print("cofre inicializado en", args.vault)
            name = None
        elif args.command == "add":
            value = args.value
            if value is None:
                value = read_secret("valor del secreto: ")
            vault.add(session, args.name, value, args.tag)
            print("guardado", args.name)
            name = args.name
        elif args.command == "rename":
            ok = vault.rename(session, args.old, args.new)
            print(f"renombrado: {args.old} -> {args.new}" if ok
                  else "no se pudo renombrar (destino ocupado o nombre vacio)")
            name = args.new
            if not ok:
                return 1
        elif args.command == "del":
            print("borrado" if vault.delete(session, args.name) else "no existe")
            name = args.name
        elif args.command == "get":
            print(vault.get(session, args.name))
            name = args.name
        elif args.command == "list":
            for n in vault.names():
                print(n)
            name = f"{len(vault.names())} entradas"
        elif args.command == "export":
            for n in vault.names():
                print(f"{n}={vault.get(session, n)}")
            name = f"{len(vault.names())} entradas"
        record(str(vault_path), args.command, args.gate, serial, name=name, ok=True)
        from cofre.audit import stamp_vault
        stamp_vault(vault)
    except Exception as exc:
        record(str(vault_path), args.command, args.gate, serial, name=None, ok=False, detail=str(exc))
        raise

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
