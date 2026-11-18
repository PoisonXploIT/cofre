"""Comprueba desbordes en la ventana principal y en las hojas secundarias.

  python tools/layout_check.py

Mide ancho Y alto: el boton Guardar de Ajustes quedaba cortado por abajo y el
chequeo anterior solo miraba el ancho. Usa un cofre temporal, no el real.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.gui import CofreGUI
from tmpvault import cofre_temporal


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def medir(ventana, etiqueta: str) -> int:
    for _ in range(3):
        ventana.update_idletasks()
        ventana.update()
    overflow = []
    for w in walk(ventana):
        parent = w.master
        if parent is None or not w.winfo_ismapped():
            continue
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if pw <= 1 or ph <= 1:
            continue
        x, y = w.winfo_x(), w.winfo_y()
        width, height = w.winfo_width(), w.winfo_height()
        clipped = (w.winfo_class() == "Frame" and hasattr(w, "set_enabled")
                   and (width < w.winfo_reqwidth()
                        or height < w.winfo_reqheight()))
        if x + width > pw + 1 or y + height > ph + 1 or clipped:
            texto = ""
            try:
                texto = str(w.cget("text"))
            except Exception:
                etiqueta_w = getattr(w, "label", None)
                if etiqueta_w is not None:
                    try:
                        texto = str(etiqueta_w.cget("text"))
                    except Exception:
                        texto = ""
            overflow.append((w.winfo_class(), texto[:34], x, y,
                             width, height, pw, ph))
    print(f"{etiqueta}: {len(overflow)} widgets fuera de su padre")
    for cls, texto, x, y, width, height, pw, ph in overflow[:8]:
        print(f"   {cls:10s} x={x:4d} y={y:4d} w={width:4d} h={height:4d} "
              f"padre={pw}x{ph}  {texto}")
    return len(overflow)


def buscar(app, titulo: str):
    import tkinter as tk
    for hijo in app.root.winfo_children():
        if isinstance(hijo, tk.Toplevel) and hijo.title() == titulo:
            return hijo
    return None


def main() -> int:
    vault, llave, tmp = cofre_temporal()
    app = CofreGUI(str(vault), "usb", stick=str(llave))
    app.build()
    malos = 0
    min_w, min_h = app.root.minsize()
    for size in ("980x620", f"{min_w}x{min_h}"):
        app.root.geometry(size)
        malos += medir(app.root, size)

    app.open_settings()
    hoja = buscar(app, "Ajustes")
    if hoja is not None:
        malos += medir(hoja, "Ajustes")
        hoja.destroy()
    app.open_keys()
    hoja = buscar(app, "Llaves y recuperación")
    if hoja is not None:
        malos += medir(hoja, "Llaves")
        hoja.destroy()
    app.root.destroy()
    return 1 if malos else 0


if __name__ == "__main__":
    sys.exit(main())
