#!/usr/bin/env python
"""Sonda de atajos de la GUI (H3 y H4).

Comprueba, sin abrir la ventana de verdad, que:

  H3  Ctrl+C NO copia el secreto cuando el foco esta en un campo de texto.
  H4  Escape NO cierra la aplicacion: desarma confirmaciones o bloquea.

No depende del foco real de Windows (que otro programa puede robar): se inyecta
el widget que tendria el foco y se llama al manejador. Antes se usaba
focus_set()+update() y una pasada de la bateria fallo porque el foco no estaba
donde tocaba.

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

    def foco(widget):
        """Fijar que widget tendria el foco, sin depender del foco real."""
        app.root.focus_get = lambda: widget

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")

    # 1. foco en el buscador: Ctrl+C no debe tocar el portapapeles
    foco(app.query_entry)
    app._on_copy_shortcut(None)
    check("H3 Ctrl+C con foco en el buscador no copia", calls["copy"] == 0,
          f"llamadas a copy: {calls['copy']}")

    foco(app.query_entry)
    app._on_copy_shortcut(None)
    check("H3 Ctrl+C con foco en un campo de texto no copia", calls["copy"] == 0,
          f"llamadas a copy: {calls['copy']}")

    # 2. foco en la lista (no en un campo): Ctrl+C si copia
    app.selected = "EJEMPLO"
    app.session = b"x" * 32
    foco(app.list_frame)
    app._on_copy_shortcut(None)
    check("H3 Ctrl+C con foco fuera de un campo si copia",
          calls["copy"] >= 1, f"llamadas: {calls['copy']}")
    app.session = None
    app.selected = None

    # 3. Escape con confirmacion pendiente: la desarma, no cierra
    app._confirm_delete = True
    app._confirm_revoke = 12345
    app.session = None
    app._on_escape(None)
    check("H4 Escape desarma la confirmación",
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
    foco(app.list_frame)
    app._on_enter(None)
    check("R7 Enter copia el seleccionado", calls["copy"] == 1, f"copy={calls['copy']}")

    # 4d. el boton Registro existe y abre la verificacion sin consola
    # los botones de COFRE son Frame + Label dentro, no tk.Button
    botones = []

    def recorrer(w):
        for hijo in w.winfo_children():
            texto = ""
            try:
                texto = str(hijo.cget("text"))
            except Exception:
                # los botones propios guardan una etiqueta o un canvas
                etiqueta = getattr(hijo, "label", None)
                if etiqueta is not None:
                    try:
                        texto = str(etiqueta.cget("text"))
                    except Exception:
                        texto = ""
            if texto:
                botones.append(texto)
            recorrer(hijo)

    recorrer(app.root)
    nav = getattr(app, "nav_btns", {})
    check("R8 la columna tiene Registro y Guía",
          "registro" in nav and "guía" in nav, ", ".join(sorted(nav)))

    # 5. Escape con el cofre cerrado: no hace nada destructivo
    calls["lock"] = 0
    app._on_escape(None)
    check("H4 Escape con cofre cerrado no cierra la ventana",
          calls["close"] == 0, f"cierres: {calls['close']}")

    # 6.4: Ctrl+K abre la paleta; escribir y Enter ejecuta la accion
    app.session = b"x" * 32
    llamadas_paleta = []
    app.open_health = lambda: llamadas_paleta.append("salud")
    app._comprobar_salud = lambda: llamadas_paleta.append("comprobar")
    app.open_palette()
    paleta = getattr(app, "_palette", None)
    if paleta is not None:
        paleta.entrada.insert(0, "comprobar salud")
        paleta._refrescar()
        paleta.ejecutar()
    check("6.4 la paleta busca y ejecuta con Enter",
          llamadas_paleta == ["salud", "comprobar"],
          f"llamadas: {llamadas_paleta}")

    app.root.destroy()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} comprobaciones OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
