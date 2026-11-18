"""Prueba de la opcion B: con gate usb-pin, enchufar NO abre el cofre.

No necesita PIN real ni tocar la boveda: comprueba las tres cosas que definen B.
  1. Con usb-pin y pendrive presente, _poll deja el estado en 'closed' y avisa.
  2. Sin PIN, unlock() no abre.
  3. Los botones del detalle estan apagados mientras no hay seleccion.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.gui import CofreGUI

path = str(Path.home() / "AI" / "cofre" / "cofre.json")

app = CofreGUI(path, "usb-pin")
app.build()
app.root.update()
# arranque: sin PIN no debe haber sesion
print("1 usb-pin sin PIN -> estado:", app.state(), "|", app.status_var.get())

# simular deteccion de pendrive con el cofre cerrado
app.pin_var.set("")
app._key_cache = set()
app._poll()
app.root.update()
print("2 tras detectar pendrive -> estado:", app.state(), "|", app.status_var.get())
print("   pie:", app.foot_var.get())

# con pin vacio unlock debe fallar
print("3 unlock sin PIN devuelve:", app.unlock(), "| sesión:", app.session)

# botones apagados sin seleccion
states = [b._enabled for b in app.action_btns]
print("4 botones del detalle habilitados:", states)
app.root.update()
print("   todos apagados:", not any(states))

app.root.destroy()

# gate usb normal: debe seguir abriendo solo
app2 = CofreGUI(path, "usb")
app2.build()
app2.root.update()
print("5 usb normal -> estado:", app2.state(), "|", app2.status_var.get())
print("6 botones sin selección:", [b._enabled for b in app2.action_btns])
app2.root.destroy()
