"""Sonda de E1: los tokens nuevos y la barra de titulo oscura.

  python tools/dark_bar_probe.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.theme import COLORS, RADIUS, SIZES, SPACE, build_fonts, dark_titlebar

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def main() -> int:
    # tokens obligatorios de la paleta nueva
    for clave in ("raised", "disabled_bg", "accent_hover", "ok_bg", "ok_fg",
                  "warn_bg", "warn_fg", "rot_bg", "rot_fg", "info", "info_bg", "info_fg"):
        check(f"token {clave}", clave in COLORS, COLORS.get(clave, ""))
    check("radios del plan", RADIUS.get("btn") == 8 and RADIUS.get("dialog") == 14,
          str(RADIUS))
    check("tamanos del plan", SIZES.get("titlebar") == 36 and SIZES.get("statusbar") == 34,
          str({k: SIZES[k] for k in ("titlebar", "header", "statusbar")}))
    check("escala de espaciado", SPACE.get("x3") == 32, str(sorted(set(SPACE.values()))))

    root = tk.Tk()
    root.withdraw()
    fuentes = build_fonts(root)
    check("seis roles tipograficos",
          all(r in fuentes for r in ("display", "title", "body", "label", "mono", "meta")),
          ", ".join(sorted(fuentes)))
    check("fuente de iconos elegida", "icon" in fuentes, str(fuentes["icon"].actual("family")))

    # la barra oscura: en Windows debe aceptarla; en otro sitio, no romper
    aplicado = dark_titlebar(root)
    check("barra de titulo oscura", aplicado or sys.platform != "win32",
          "aplicada" if aplicado else "no disponible")

    hoja = tk.Toplevel(root)
    hoja.withdraw()
    check("barra oscura tambien en hojas", dark_titlebar(hoja) or sys.platform != "win32", "")
    hoja.destroy()
    root.destroy()

    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
