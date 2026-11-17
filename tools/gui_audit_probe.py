"""Sonda del boton Registro de la GUI (verificacion del log sin consola).

  python tools/gui_audit_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import tkinter as tk
from cofre.gui import CofreGUI

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    app = CofreGUI(str(REPO / "cofre.json"), "usb")
    app.build()
    app.root.update()

    # con el cofre cerrado no debe abrir nada
    app.session = None
    app.open_audit()
    abiertas = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    check("1. sin cofre abierto no abre la ventana", not abiertas,
          app.root.foot_text if hasattr(app.root, "foot_text") else "")

    # con sesion: abre, verifica y muestra las lineas
    app.session = b"x" * 32
    app.open_audit()
    app.root.update()
    abiertas = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    check("2. con el cofre abierto abre la ventana", bool(abiertas), f"{len(abiertas)}")
    if abiertas:
        textos = []
        def recorrer(w):
            for h in w.winfo_children():
                try:
                    if h.winfo_class() in ("Label", "Text"):
                        textos.append(str(h.cget("text")) if h.winfo_class() == "Label"
                                      else h.get("1.0", "end"))
                except Exception:
                    pass
                recorrer(h)
        recorrer(abiertas[0])
        junto = " ".join(textos)
        check("3. dice si la cadena esta bien",
              ("correctas" in junto) or ("PROBLEMA" in junto), junto[:70])
        check("4. ensena entradas del registro",
              "llave" in junto or "eventos" in junto, "")
        for w in abiertas:
            w.destroy()

    root.destroy()
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
