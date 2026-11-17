"""Sonda de E3: la pantalla de bloqueo.

  python tools/lock_screen_probe.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.gui import CofreGUI
from cofre.theme import dark_titlebar, enable_dpi_awareness
from tmpvault import cofre_temporal

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def main() -> int:
    enable_dpi_awareness()
    vault, llave, tmp = cofre_temporal()
    app = CofreGUI(str(vault), "usb", stick=str(llave))
    dark_titlebar(app.root)
    app.build()
    app.root.update()
    time.sleep(0.4)
    app.root.update()

    capa = app.lock_screen
    check("1. la capa existe", capa is not None, "")
    check("2. con el cofre abierto esta oculta", not capa.winfo_ismapped(),
          f"mapeada={capa.winfo_ismapped()}")

    # bloquear a mano: aparece y dice el motivo
    app.lock(motivo="cofre bloqueado: prueba de la sonda")
    app.root.update()
    check("3. al bloquear aparece", capa.winfo_ismapped(), "")
    check("4. ensena el motivo", "prueba de la sonda" in capa.motivo.cget("text"),
          capa.motivo.cget("text"))

    # llaves: con el pendrive conectado debe listarlas y habilitar Abrir
    filas = capa.llaves.winfo_children()
    check("5. lista las llaves del cofre", bool(filas), f"{len(filas)} fila(s)")
    check("6. el boton Abrir esta habilitado con llave",
          capa.b_abrir._estado == "normal", capa.b_abrir._estado)

    # abrir desde la propia capa
    capa._abrir()
    app.root.update()
    check("7. abrir desde la capa deja el cofre operativo",
          bool(app.session) and not capa.winfo_ismapped(),
          f"sesion={'si' if app.session else 'no'} mapeada={capa.winfo_ismapped()} "
          f"pie={app.foot_var.get()[:70]!r}")

    # volver a bloquear y capturar
    app.lock(motivo="bloqueado por inactividad (10 min sin usarlo)")
    app.root.update()
    time.sleep(0.4)
    app.root.update()
    salida = Path(os.environ.get("TEMP", ".")) / "cofre_e3_bloqueo.png"
    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    ps = ("Add-Type -AssemblyName System.Drawing;"
          f"$b=New-Object System.Drawing.Bitmap {w},{h};"
          "$g=[System.Drawing.Graphics]::FromImage($b);"
          f"$g.CopyFromScreen({x},{y},0,0,$b.Size);"
          f"$b.Save('{salida}', [System.Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                   timeout=60)
    check("8. captura de la pantalla de bloqueo", salida.exists(), str(salida))

    app.root.destroy()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
