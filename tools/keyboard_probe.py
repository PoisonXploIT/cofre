"""Sonda de teclado y foco (paso 6.9).

No depende del foco real de Windows: comprueba que los controles son enfocables
(takefocus), que tienen Return/space y que la navegacion cambia la seleccion.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.gui import CofreGUI
from cofre.theme import dark_titlebar, enable_dpi_awareness
from tmpvault import cofre_temporal


def walk(widget):
    for hijo in widget.winfo_children():
        yield hijo
        yield from walk(hijo)


def main() -> int:
    enable_dpi_awareness()
    vault, llave, tmp = cofre_temporal()
    app = CofreGUI(str(vault), "usb", stick=str(llave))
    dark_titlebar(app.root)
    app.build()
    app.root.update_idletasks()
    app.root.update()
    resultados = []

    def check(nombre, ok, detalle=""):
        resultados.append((nombre, bool(ok)))
        print(f"{'OK   ' if ok else 'FALLO'}  {nombre}  {detalle}")

    nombres = list(app.vault.names())
    check("la lista tiene secretos para navegar", len(nombres) >= 2,
          f"{len(nombres)}")

    app._enfocar_lista()
    check("flecha abajo en el buscador selecciona el primero",
          app.selected == nombres[0], f"seleccionado {app.selected}")
    fila = app._rows.get(app.selected)
    check("la fila es enfocable y tiene Return",
          fila is not None and str(fila.canvas.cget("takefocus")) == "1"
          and bool(fila.canvas.bind("<Return>")),
          "canvas" if fila is not None else "sin fila")

    antes = app.selected
    app._mover_lista(1)
    check("las flechas cambian de secreto",
          app.selected != antes and app.selected in nombres,
          f"{antes} -> {app.selected}")
    fila2 = app._rows.get(app.selected)
    check("la fila nueva conserva la navegacion",
          fila2 is not None and bool(fila2.canvas.bind("<Down>")),
          "canvas")
    if fila2 is not None:
        fila2._focus_in()
        con_foco = fila2._foco
        fila2._focus_out()
        check("el foco de la fila se dibuja y se quita",
              con_foco and not fila2._foco)

    etiquetas = [w for w in walk(app.root)
                 if w.winfo_class() == "Label"
                 and str(w.cget("takefocus") or "") == "1"]
    check("hay acciones de texto enfocables", len(etiquetas) > 3,
          f"{len(etiquetas)} etiquetas")
    con_return = [w for w in etiquetas if w.bind("<Return>")]
    check("las acciones de texto responden a Return",
          len(con_return) >= 3, f"{len(con_return)} con Return")

    app.root.destroy()
    fallos = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallos)}/{len(resultados)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
