#!/usr/bin/env python
"""Sonda de atajos de la GUI (H3 y H4).

Comprueba, sin abrir la ventana de verdad, que:

  H3  Ctrl+C NO copia el secreto cuando el foco esta en un campo de texto.
  H4  Escape NO cierra la aplicacion: desarma confirmaciones o bloquea.

  python tools/gui_shortcut_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk
from cofre.gui import CofreGUI


def main() -> int:
    app = CofreGUI(str(Path.home() / "AI" / "cofre" / "cofre.json"), "usb")
    app.build()
    calls = {"copy": 0, "close": 0, "lock": 0}

    app.copy_to_clipboard = lambda event=None: calls.__setitem__("copy", calls["copy"] + 1)
    app._on_close = lambda: calls.__setitem__("close", calls["close"] + 1)
    app.lock = lambda event=None: calls.__setitem__("lock", calls["lock"] + 1)

    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")

    # 1. foco en el buscador: Ctrl+C no debe tocar el portapapeles
    app.query_entry.focus_set()
    app.root.update()
    app._on_copy_shortcut(None)
    check("H3 Ctrl+C con foco en el buscador no copia", calls["copy"] == 0,
          f"llamadas a copy: {calls['copy']}")

    app.name_entry.focus_set()
    app.root.update()
    app._on_copy_shortcut(None)
    check("H3 Ctrl+C con foco en el campo de valor no copia", calls["copy"] == 0,
          f"llamadas a copy: {calls['copy']}")

    # 2. foco en la lista (no en un campo): Ctrl+C si copia
    app.selected = "EJEMPLO"
    app.session = b"x" * 32
    app.list_frame.focus_set()
    app.root.update()
    focused = app.root.focus_get()
    app._on_copy_shortcut(None)
    check("H3 Ctrl+C con foco fuera de un campo si copia",
          calls["copy"] >= 1, f"foco {focused.winfo_class() if focused else 'None'}, llamadas: {calls['copy']}")
    app.session = None
    app.selected = None

    # 3. Escape con confirmacion pendiente: la desarma, no cierra
    app._confirm_delete = True
    app._confirm_revoke = 12345
    app.session = None
    app._on_escape(None)
    check("H4 Escape desarma la confirmacion",
          not app._confirm_delete and app._confirm_revoke is None and calls["close"] == 0,
          f"cierres: {calls['close']}")

    # 4. Escape con el cofre abierto: NO bloquea y NO cierra (R7, 2026-11-16).
    # Bloquear es solo Ctrl+L.
    if app.help_box.winfo_ismapped():
        app.help_box.pack_forget()
        app.root.update_idletasks()
    app.session = b"x" * 32
    app._on_escape(None)
    check("R7 Escape no bloquea ni cierra",
          calls["close"] == 0 and calls["lock"] == 0,
          f"lock={calls['lock']} close={calls['close']}")

    # 4b. Ctrl+L si bloquea
    app.lock()
    check("R7 Ctrl+L bloquea", calls["lock"] == 1, f"lock={calls['lock']}")

    # 4c. Enter copia el seleccionado
    calls["copy"] = 0
    app.selected = "EJEMPLO"
    app.session = b"x" * 32
    app.list_frame.focus_set()
    app.root.update()
    app._on_enter(None)
    check("R7 Enter copia el seleccionado", calls["copy"] == 1, f"copy={calls['copy']}")

    # 5. Escape con el cofre cerrado: no hace nada destructivo
    calls["lock"] = 0
    app._on_escape(None)
    check("H4 Escape con cofre cerrado no cierra la ventana",
          calls["close"] == 0, f"cierres: {calls['close']}")

    app.root.destroy()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} comprobaciones OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
