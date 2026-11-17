"""Comprueba que nada se sale de su contenedor a 820x540 (tamano minimo).

Uso: python tools/layout_check.py
Cuenta widgets cuyo borde derecho supera el ancho de su padre, y lista los que
se solapan. Sirve para detectar el clasico "9 botones en una fila" sin mirar la
pantalla.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.gui import CofreGUI
from cofre.paths import default_vault


def walk(widget, depth=0, out=None):
    out = out if out is not None else []
    for child in widget.winfo_children():
        out.append((depth, child))
        walk(child, depth + 1, out)
    return out


def main() -> int:
    # la ruta buena, no la del repo: con la ruta antigua el cofre "no existe" y
    # el asistente de puesta en marcha cambia el layout medido
    app = CofreGUI(str(default_vault()), "usb")
    app.build()
    min_w, min_h = app.root.minsize()
    for size in ("980x620", f"{min_w}x{min_h}"):
        app.root.geometry(size)
        for _ in range(3):
            app.root.update_idletasks()
            app.root.update()
        overflow = []
        for depth, w in walk(app.root):
            parent = w.master
            if parent is None or not w.winfo_ismapped():
                continue
            pw = parent.winfo_width()
            if pw <= 1:
                continue
            x = w.winfo_x()
            width = w.winfo_width()
            clipped = (w.winfo_class() == "Frame" and hasattr(w, "set_enabled")
                       and width < w.winfo_reqwidth())
            if x + width > pw + 1 or clipped:
                label = ""
                try:
                    label = w.cget("text")
                except Exception:
                    pass
                overflow.append((w.winfo_class(), label[:34], x, width, pw))
        print(f"{size}: {len(overflow)} widgets fuera de su padre")
        for cls, label, x, width, pw in overflow[:8]:
            print(f"   {cls:10s} x={x:4d} w={width:4d} padre={pw:4d}  {label}")
    app.root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
