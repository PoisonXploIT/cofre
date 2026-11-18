"""Prueba del auto-bloqueo: simula que desaparece el pendrive de la sesion.

No desenchufa nada: sustituye stick_report() por una lista donde el serial que
abrio la sesion figura como no conectado, y comprueba que _poll bloquea.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.gui import CofreGUI

app = CofreGUI(str(Path.home() / "AI" / "cofre" / "cofre.json"), "usb")
app.build()
app.root.update()
print("1 abierto:", app.state(), "|", app.status_var.get())
print("  serial de la sesión:", app.serial)

used = app.serial
if used is None:
    print("no hay sesión abierta: conectar un pendrive y repetir")
    raise SystemExit(1)

real = app.stick_report
app.stick_report = lambda: [
    dict(s, connected=False) if s["serial"] == str(used) else s for s in real()
]
app._poll()
app.root.update()
print("2 tras retirar el pendrive:", app.state(), "|", app.status_var.get())
print("3 pie:", app.foot_var.get())
print("4 sesión viva?", app.session is not None, "| serial:", app.serial)

app.stick_report = real
app.unlock()
app.root.update()
print("5 al reconectar:", app.state(), "|", app.status_var.get())
app.root.destroy()
