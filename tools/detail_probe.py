"""Sonda de E5: el detalle con chips, sitios, usado en y ciclo de vida.

  python tools/detail_probe.py
"""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.gui import CofreGUI
from cofre.theme import dark_titlebar, enable_dpi_awareness
from tmpvault import cofre_temporal

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def textos(widget) -> str:
    partes = []
    for w in widget.winfo_children():
        texto = ""
        try:
            texto = str(w.cget("text"))
        except Exception:
            texto = str(getattr(w, "text", ""))
        if texto:
            partes.append(texto)
        partes.append(textos(w))
    return " | ".join(partes)


def main() -> int:
    enable_dpi_awareness()
    vault, llave, tmp = cofre_temporal()
    app = CofreGUI(str(vault), "usb", stick=str(llave))
    dark_titlebar(app.root)
    app.build()
    app.root.geometry("1080x640")
    app.root.update()
    time.sleep(0.3)
    app.root.update()

    if not app.session:
        print("no se pudo abrir el cofre de prueba")
        app.root.destroy()
        return 1

    nombres = app.vault.names()
    check("1. hay secretos para probar", bool(nombres), str(nombres))
    if not nombres:
        app.root.destroy()
        return 1

    elegido = "SIMULACRO_RESTAURA" if "SIMULACRO_RESTAURA" in nombres else nombres[0]
    app.select(elegido)
    app.root.update()

    chips = textos(app.chips_row)
    check("2. el chip de tipo aparece", "api_key" in chips or "password" in chips, chips[:60])
    check("3. hay chip de sitio", "sitio" in chips, chips[:60])

    sitios = textos(app.sites_box)
    esperado = "ejemplo.com" if elegido == "SIMULACRO_RESTAURA" else "dash.cloudflare.com"
    check("4. lista los sitios asignados", esperado in sitios, sitios[:60])
    check("5. cada sitio se puede quitar", "Quitar" in sitios, "")

    consumidores = textos(app.consumers_box)
    check("6. la seccion 'usado en' tiene contenido", "nada desplegado" in consumidores,
          consumidores[:40])

    vida = textos(app.life_box)
    check("7. ciclo de vida informa", bool(vida), vida[:60])

    check("8. el valor sigue oculto",
          "•" in app.value_box.get("1.0", "end").strip(), app.value_box.get("1.0", "end").strip())

    # asignar y quitar un sitio de prueba, por la via de la GUI
    app.selected = elegido
    app.vault.set_urls(elegido, [esperado, "prueba-sonda.test"])
    app.refresh_detail()
    app.root.update()
    check("9. al asignar un sitio aparece en la lista",
          "prueba-sonda.test" in textos(app.sites_box), textos(app.sites_box)[:70])
    app.remove_site("prueba-sonda.test")
    app.root.update()
    check("10. al quitarlo desaparece",
          "prueba-sonda.test" not in textos(app.sites_box), textos(app.sites_box)[:70])

    # captura
    salida = Path(os.environ.get("TEMP", ".")) / "cofre_e5_detalle.png"
    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    import subprocess
    ps = ("Add-Type -AssemblyName System.Drawing;"
          f"$b=New-Object System.Drawing.Bitmap {w},{h};"
          "$g=[System.Drawing.Graphics]::FromImage($b);"
          f"$g.CopyFromScreen({x},{y},0,0,$b.Size);"
          f"$b.Save('{salida}', [System.Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                   timeout=60)
    check("11. captura del detalle", salida.exists(), str(salida))

    app.root.destroy()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
