"""Sonda de E2: los widgets nuevos, en todos sus estados.

Crea la galeria, comprueba medidas y estados, y guarda una captura.

  python tools/widgets_probe.py
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

from cofre.theme import COLORS, enable_dpi_awareness, dark_titlebar
from cofre.widgets import (Button, Chip, Field, IconButton, ListRow, round_rect)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def main() -> int:
    enable_dpi_awareness()
    root = tk.Tk()
    root.title("COFRE - galeria de widgets")
    root.configure(bg=COLORS["bg"])
    dark_titlebar(root)
    root.geometry("720x520+120+90")

    # botones: los cinco tipos y el desactivado
    fila = tk.Frame(root, bg=COLORS["bg"])
    fila.pack(anchor="w", padx=16, pady=(16, 8))
    b_primary = Button(fila, "Guardar secreto", kind="primary", command=lambda: None)
    b_primary.pack(side="left", padx=(0, 8))
    b_secondary = Button(fila, "Cancelar", command=lambda: None)
    b_secondary.pack(side="left", padx=(0, 8))
    b_text = Button(fila, "Ver guia", kind="text", command=lambda: None)
    b_text.pack(side="left", padx=(0, 8))
    b_danger = Button(fila, "Borrar", kind="danger", command=lambda: None)
    b_danger.pack(side="left", padx=(0, 8))
    b_icon = IconButton(fila, "\ue72e", command=lambda: None)   # candado
    b_icon.pack(side="left")

    fila2 = tk.Frame(root, bg=COLORS["bg"])
    fila2.pack(anchor="w", padx=16, pady=(0, 12))
    b_off = Button(fila2, "Desactivado", command=lambda: None)
    b_off.set_enabled(False)
    b_off.pack(side="left", padx=(0, 8))

    # chips
    chips = tk.Frame(root, bg=COLORS["bg"])
    chips.pack(anchor="w", padx=16, pady=(0, 12))
    for texto, kind in (("abierto", "ok"), ("caduca 7 d", "warn"),
                        ("rotar", "rot"), ("sin asignar", "neutral"),
                        ("info", "info")):
        Chip(chips, texto, kind).pack(side="left", padx=(0, 6))

    # campos
    campos = tk.Frame(root, bg=COLORS["bg"])
    campos.pack(anchor="w", padx=16, pady=(0, 12))
    f1 = Field(campos, placeholder="buscar secreto", width=260)
    f1.pack(side="left", padx=(0, 8))
    f2 = Field(campos, placeholder="contrasena", show="*", width=200)
    f2.pack(side="left")

    # filas
    lista = tk.Frame(root, bg=COLORS["surface"])
    lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    r1 = ListRow(lista, "CLOUDFLARE_DNS_TOKEN", "cloudflare - dash.cloudflare.com",
                 "C", ("abierto", "ok"), on_click=lambda n: None)
    r1.pack(fill="x")
    r2 = ListRow(lista, "GITHUB_TOKEN", "github - api.github.com", "G",
                 ("rotar", "rot"), on_click=lambda n: None)
    r2.pack(fill="x")
    r2.set_seleccionada(True)
    ListRow(lista, "SIMULACRO_RESTAURA", "prueba - ejemplo.com", "S").pack(fill="x")

    root.update_idletasks()
    root.update()
    time.sleep(0.5)

    # comprobaciones
    check("1. el boton primario usa el acento",
          b_primary._colores()[0] == COLORS["accent"], b_primary._colores()[0])
    b_primary._on_enter()
    check("2. el hover solo cambia el borde o el tono, no el texto",
          b_primary._colores()[1] == COLORS["on_accent"], "")
    b_primary._on_leave()

    b_off._on_enter()
    check("3. un boton desactivado ignora el hover", b_off._colores()[0] == COLORS["disabled_bg"],
          b_off._colores()[0])
    b_off._on_leave()

    b_text._on_enter()
    check("4. el boton de texto no pinta caja", b_text._colores()[0] == COLORS["bg"], "")
    b_text._on_leave()

    check("5. el chip mide lo que ocupa su texto",
          int(Chip(root, "abierto").cget("height")) == 24, "")
    check("6. el campo devuelve lo escrito",
          (f1.set("abc") or f1.get()) == "abc", f1.get())
    check("7. el campo con contrasena oculta lo escrito",
          str(f2.entry.cget("show")) == "*", "")
    check("8. la fila alta es la del plan", ListRow.ALTO == 56, str(ListRow.ALTO))
    check("9. la fila se marca como seleccionada", r2.seleccionada, "")
    check("10. round_rect devuelve un elemento del canvas",
          isinstance(round_rect(tk.Canvas(root, width=50, height=50), 2, 2, 48, 48, 8,
                                fill=COLORS["card"]), int), "")

    salida = Path(os.environ.get("TEMP", ".")) / "cofre_e2_widgets.png"
    root.update()
    ps = ("Add-Type -AssemblyName System.Drawing,System.Windows.Forms;"
          "$b=New-Object System.Drawing.Bitmap 760,560;"
          "$g=[System.Drawing.Graphics]::FromImage($b);"
          "$g.CopyFromScreen(110,80,0,0,$b.Size);"
          f"$b.Save('{salida}', [System.Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                   timeout=60)
    check("11. captura guardada", salida.exists(), str(salida))

    root.destroy()
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
