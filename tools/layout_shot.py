"""Captura del layout a los dos tamanos del plan (E4).

  python tools/layout_shot.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.gui import CofreGUI
from tmpvault import cofre_temporal  # noqa: E402
from cofre.theme import dark_titlebar, enable_dpi_awareness


def captura(app, nombre: str) -> Path:
    app.root.update_idletasks()
    app.root.update()
    time.sleep(0.5)
    app.root.update()
    salida = Path(os.environ.get("TEMP", ".")) / nombre
    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
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
    for tam, nombre in (("1000x640", "cofre_e4_1000.png"),
                        ("1440x900", "cofre_e4_1440.png")):
        app.root.geometry(tam)
        destino = captura(app, nombre)
        print(f"{tam}: {destino} existe={destino.exists()}")
    app.root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
