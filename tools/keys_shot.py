"""Captura de la pantalla de llaves y recuperación (6.6), con cofre temporal.

  python tools/keys_shot.py

No toca el cofre real. Añade al temporal una llave de reserva y un código de
recuperación para que la captura enseñe los tres tipos de fila.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.gui import CofreGUI
from cofre.theme import dark_titlebar, enable_dpi_awareness
from cofre.usb import register_stick
from cofre.v2.recovery import new_code
from cofre.v2.slots import new_recovery_slot, new_usb_slot
from tmpvault import cofre_temporal


def captura(win, nombre: str) -> Path:
    win.update_idletasks()
    win.update()
    salida = Path(os.environ.get("TEMP", ".")) / nombre
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    ps = ("Add-Type -AssemblyName System.Drawing;"
          f"$b=New-Object System.Drawing.Bitmap {w},{h};"
          "$g=[System.Drawing.Graphics]::FromImage($b);"
          f"$g.CopyFromScreen({x},{y},0,0,$b.Size);"
          f"$b.Save('{salida}', [System.Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=60)
    return salida


def main() -> int:
    enable_dpi_awareness()
    vault, llave, tmp = cofre_temporal()
    app = CofreGUI(str(vault), "usb", stick=str(llave))
    dark_titlebar(app.root)
    app.build()
    try:
        store = app.vault._v2store()
        if store.master is not None:
            datos = store._data
            reserva = new_usb_slot(store.master, secrets.token_bytes(32),
                                   222333, "reserva", "")
            datos["slots"].append(reserva)
            datos["slots"].append(new_recovery_slot(
                store.master, new_code(), "recuperacion"))
            store._vault.save(datos)
            store._data = datos
            register_stick(str(vault), 222333, "F:\\", role="reserva")
    except Exception as exc:
        print("no se pudo preparar el temporal:", exc)
    app.open_keys()
    win = None
    for hijo in app.root.winfo_children():
        if isinstance(hijo, tk.Toplevel) and hijo.title() == "Llaves y recuperación":
            win = hijo
    if win is None:
        print("no se abrió la hoja de llaves")
        app.root.destroy()
        return 1
    win.geometry("760x560+80+60")
    win.update_idletasks()
    win.update()
    fuera = []
    pila = [win]
    while pila:
        padre = pila.pop()
        pw = padre.winfo_width()
        for hijo in padre.winfo_children():
            pila.append(hijo)
            if not hijo.winfo_ismapped() or pw <= 1:
                continue
            if hijo.winfo_x() + hijo.winfo_width() > pw + 1:
                fuera.append((hijo.winfo_class(),
                              str(hijo.cget("text") if hasattr(hijo, "cget") else "")[:30],
                              hijo.winfo_x(), hijo.winfo_width(), pw))
    print(f"llaves: {len(fuera)} widgets fuera de su padre")
    for dato in fuera[:6]:
        print("  ", dato)
    ruta = captura(win, "cofre_6_6_llaves.png")
    print("captura:", ruta, "existe=", ruta.exists())
    win.destroy()
    app.root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
