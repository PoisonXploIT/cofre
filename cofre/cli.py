#!/usr/bin/env python
"""Cofre - boveda de secretos con gate de pendrive USB.

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
import os
import sys
from pathlib import Path

from cofre.audit import record, tail
from cofre.crypto import Vault
from cofre.gate import GateUnavailable, resolve_session_key
from cofre.gen import entropy, human_password, machine_password

DEFAULT_VAULT = Path(os.environ.get("COFRE_VAULT", Path.home() / "AI" / "cofre" / "cofre.json"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cofre - boveda de secretos")
    p.add_argument("--vault", default=str(DEFAULT_VAULT))
    p.add_argument("--gate", default="usb", choices=["pin", "hid", "usb", "usb-pin"])
    p.add_argument("--stick", help="ruta explicita del fichero clave del USB")
    p.add_argument("--allow-new-stick", action="store_true",
                   help="aceptar un pendrive cuyo serial no esta registrado")
    p.add_argument("--allow-pipe", action="store_true",
                   help="permitir que get/export escriba secretos a un pipe o fichero")
    sub = p.add_subparsers(dest="command", required=True)

    def with_common(sp):
        # defaults SUPPRESS: si la opcion va antes del subcomando no se pisa
        sp.add_argument("--vault", default=argparse.SUPPRESS)
        sp.add_argument("--gate", default=argparse.SUPPRESS, choices=["pin", "hid", "usb", "usb-pin"])
        sp.add_argument("--stick", default=argparse.SUPPRESS)
        sp.add_argument("--allow-new-stick", action="store_true", default=argparse.SUPPRESS)
        sp.add_argument("--allow-pipe", action="store_true", default=argparse.SUPPRESS)
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
    sd = with_common(sub.add_parser("del"))
    sd.add_argument("name")
    sx = with_common(sub.add_parser("exec"))
    sx.add_argument("--name", action="append", default=[],
                    help="secreto a pasar como variable de entorno al comando")
    sx.add_argument("cmd", nargs="+", help="comando a ejecutar, p. ej: python script.py")

    sg2 = with_common(sub.add_parser("gen"))
    sg2.add_argument("--machine", action="store_true")
    sg2.add_argument("--words", type=int, default=5)
    sg2.add_argument("--lang", default="en", choices=["en", "es"])
    sg2.add_argument("--entropy", action="store_true", help="imprimir bits, no la password")
    with_common(sub.add_parser("export"))
    with_common(sub.add_parser("probe"))
    sl = with_common(sub.add_parser("log"))
    sl.add_argument("--lines", type=int, default=20)
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
    from cofre.usb import drive_letters, load_registry, volume_serial, KEY_FILENAME

    reg = load_registry(vault)
    sticks = reg.get("sticks", {})
    if not sticks:
        print("no hay pendrives registrados")
        print("primera vez: conecta el pendrive y ejecuta init o stick-init")
        return 0
    present = set()
    for drive in drive_letters():
        if (Path(drive) / KEY_FILENAME).is_file():
            s = volume_serial(drive)
            if s is not None:
                present.add(str(s))
    print(f"{len(sticks)} pendrive(s) autorizados")
    for serial, info in sticks.items():
        mark = "conectado" if serial in present else "no conectado"
        print(f"  serial {serial}  {info.get('drive','')}  {info.get('role','?')}  "
              f"{info.get('label') or ''}  [{mark}]  registrado {info.get('registered','')}")
    return 0


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
                print("sesion compartida ni con capturas de pantalla activas.")
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


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    vault_path = Path(args.vault)
    vault = Vault(vault_path)

    if args.command == "gen":
        if args.entropy:
            info = entropy(words=args.words, lang=args.lang)
            print(f"{info['palabras']} palabras de {info['lista']} entradas "
                  f"-> {info['bits']} bits  {info['aviso']}")
            return 0
        print(machine_password() if args.machine else human_password(words=args.words, lang=args.lang))
        return 0

    if args.command == "log" and args.stats:
        from cofre.audit import stats
        s = stats(str(vault_path))
        print(f"{s['entradas']} entradas (max {s['max']}) en {s['archivo']}")
        print(f"fallos: {s['fallos']}  pendrives usados: {', '.join(s['pendrives_usados'])}")
        return 0

    if args.command == "log":
        for line in tail(vault_path, args.lines):
            print(line)
        return 0

    if args.command == "stick-role":
        from cofre.usb import set_role
        entry = set_role(str(vault_path), args.serial, args.role)
        if not entry:
            print(f"serial {args.serial} no esta registrado (run.cmd stick-list)")
            return 1
        print(f"serial {args.serial} ({entry.get('drive') or '?'}) ahora es {args.role}")
        record(str(vault_path), "stick-role", args.gate, args.serial, ok=True, detail=args.role)
        return 0

    if args.command == "stick-revoke":
        from cofre.usb import load_registry, revoke_stick
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
        for name in args.name:
            try:
                env[name] = vault.get(session, name)
            except VaultError:
                missing.append(name)
        if missing:
            print("no encontrados: " + ", ".join(missing), file=sys.stderr)
            record(str(vault_path), "exec", args.gate, serial, ok=False, detail=";".join(missing))
            return 1
        record(str(vault_path), "exec", args.gate, serial, name=",".join(args.name), ok=True)
        print(f"ejecutando con {len(args.name)} variables inyectadas (solo para ese proceso)")
        return subprocess.run(args.cmd, env=env).returncode

    if args.command == "stick-list":
        return cmd_stick_list(str(vault_path))

    if args.command == "gui":
        from cofre.gui import main as gui_main
        return gui_main(["--vault", str(vault_path), "--gate", args.gate] +
                        (["--stick", args.stick] if args.stick else []) +
                        (["--allow-new-stick"] if args.allow_new_stick else []) +
                        (["--selftest"] if getattr(args, "selftest", False) else []))

    if args.command == "shell":
        return cmd_shell(str(vault_path), args.gate, args.stick, args.allow_new_stick)

    if args.command == "stick-init":
        from cofre.usb import create_key_on, register_stick, volume_serial
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
        from cofre.usb import read_key, register_stick, volume_serial
        target = Path(args.path)
        if not target.is_file():
            print("no existe %s" % target)
            return 1
        try:
            read_key(str(target))
        except ValueError as exc:
            print(exc)
            return 1
        drive = _drive_of(str(target))
        serial = volume_serial(drive)
        register_stick(str(vault_path), serial, drive)
        print(f"serial {serial} ({drive}) autorizado como pendrive del cofre")
        record(str(vault_path), "stick-register", args.gate, serial, ok=True)
        return 0

    if args.command == "stick-copy":
        from cofre.usb import (copy_key_to, find_stick, read_key, register_stick,
                               volume_serial, StickNotFound, StickNotRegistered)
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

    try:
        session, serial = resolve_session_key(args.gate, str(vault_path),
                                             stick=args.stick, allow_new=args.allow_new_stick)
    except (GateUnavailable, EOFError) as exc:
        record(str(vault_path), args.command, args.gate, None, ok=False, detail=str(exc))
        print("gate no disponible:", exc, file=sys.stderr)
        return 1

    try:
        if args.command in ("get", "export") and not sys.stdout.isatty() and not args.allow_pipe:
            print("get/export no imprime secretos si la salida esta redirigida. "
                  "Usa --allow-pipe si de verdad quieres volcarlos a un fichero o a un pipe.",
                  file=sys.stderr)
            record(str(vault_path), args.command, args.gate, serial, ok=False,
                   detail="salida no interactiva")
            return 1

        if args.command != "init":
            if not vault.load().get("wrapper"):
                print("el cofre no esta inicializado: python -m cofre.cli init", file=sys.stderr)
                return 1
            try:
                vault.unlock(session)
            except Exception:
                print("la clave de sesion no corresponde a este cofre: pendrive equivocado "
                      "o PIN incorrecto", file=sys.stderr)
                record(str(vault_path), args.command, args.gate, serial, ok=False,
                       detail="sesion invalida")
                return 1

        if args.command == "init":
            vault.init(session)
            print("cofre inicializado en", args.vault)
            name = None
        elif args.command == "add":
            value = args.value
            if value is None:
                value = read_secret("valor del secreto: ")
            vault.add(session, args.name, value, args.tag)
            print("guardado", args.name)
            name = args.name
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
    except Exception as exc:
        record(str(vault_path), args.command, args.gate, serial, name=None, ok=False, detail=str(exc))
        raise

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
