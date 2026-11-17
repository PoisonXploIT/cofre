"""Captura del dialogo de confirmacion (E7)."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.gui_confirm import ConfirmDialog
from cofre.theme import dark_titlebar, enable_dpi_awareness


def main() -> int:
    enable_dpi_awareness()
    root = tk.Tk()
    root.geometry("900x600+80+60")
    root.configure(bg="#15171A")
    dark_titlebar(root)
    root.update()

    dlg = ConfirmDialog(root, "Navegador - dash.cloudflare.com",
                        "CLOUDFLARE_DNS_TOKEN", timeout_ms=20000)
    dlg.win.after(900, lambda: None)     # ya armado
    dlg.win.update_idletasks()
    dlg.win.update()
    x = dlg.win.winfo_rootx() - 20
    y = dlg.win.winfo_rooty() - 20
    w = dlg.win.winfo_width() + 40
    h = dlg.win.winfo_height() + 40
    salida = Path(os.environ.get("TEMP", ".")) / "cofre_e7_confirm.png"
    ps = ("Add-Type -AssemblyName System.Drawing;"
          f"$b=New-Object System.Drawing.Bitmap {w},{h};"
          "$g=[System.Drawing.Graphics]::FromImage($b);"
          f"$g.CopyFromScreen({max(0,x)},{max(0,y)},0,0,$b.Size);"
          f"$b.Save('{salida}', [System.Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                   timeout=60)
    print("captura:", salida, salida.exists())
    dlg._close("deny")
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
