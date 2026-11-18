"""Captura del asistente de primer uso (6.8) con un cofre temporal vacio."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.firstuse import Wizard, crear_cofre
from cofre.gui import CofreGUI
from cofre.theme import dark_titlebar, enable_dpi_awareness


def captura(win, nombre):
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


def buscar(app, titulo):
    for hijo in app.root.winfo_children():
        if isinstance(hijo, tk.Toplevel) and hijo.title() == titulo:
            return hijo
    return None


def main() -> int:
    enable_dpi_awareness()
    tmp = Path(tempfile.mkdtemp(prefix="cofre-wizard-"))
    vault = tmp / "cofre.json"
    llave = tmp / "COFRE.KEY"
    estado = crear_cofre(vault, str(tmp.drive) + "\\", clave=llave)
    app = CofreGUI(str(vault), "usb", stick=str(llave))
    dark_titlebar(app.root)
    app.build()
    wizard = Wizard(app)
    win = buscar(app, "COFRE - primera vez")
    if win is None:
        print("no se abrió el asistente")
        app.root.destroy()
        return 1
    win.geometry("760x580+80+60")
    ruta1 = captura(win, "cofre_6_8_bienvenida.png")
    wizard.codigo = estado["código"]
    wizard.datos = estado["data"]
    wizard.master = estado["master"]
    wizard.llave = estado["llave"]
    wizard.drive = estado["drive"]
    wizard._paso_codigo()
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
            ph = padre.winfo_height()
            if (hijo.winfo_x() + hijo.winfo_width() > pw + 1
                    or hijo.winfo_y() + hijo.winfo_height() > ph + 1):
                fuera.append(hijo.winfo_class())
    print(f"asistente: {len(fuera)} widgets fuera de su padre")
    ruta2 = captura(win, "cofre_6_8_codigo.png")
    print("bienvenida:", ruta1, ruta1.exists())
    print("código:", ruta2, ruta2.exists())
    wizard.cerrar()
    app.root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
