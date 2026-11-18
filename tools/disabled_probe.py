"""Comprueba 4.1: los botones del detalle se encienden y apagan segun selección."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cofre.gui as G
import cofre.usb as U

fake = Path(os.environ["TEMP"]) / "probe41"
fake.mkdir(exist_ok=True)
U.drive_letters = lambda: [str(fake) + os.sep]
U.volume_serial = lambda d: 999888777
G.drive_letters = U.drive_letters
G.volume_serial = U.volume_serial

app = G.CofreGUI(str(fake / "v.json"), "usb")
app.build()
app.root.update()
app.dest_var.set(str(fake) + os.sep)
app.wizard_create_key()
app.wizard_init()
print("0 sesión abierta:", app.session is not None, "| wrapper:",
      app.vault.load().get("wrapper") is not None)
app.name_var.set("DEMO")
app.val_var.set("un-valor-de-prueba")
app.add_secret()
print("1 sin selección:", [b._enabled for b in app.action_btns][:4], "...")
app.selected = None
app.refresh_list()
print("2 tras limpiar selección:", app.action_btns[0]._enabled)
app.select("DEMO")
app.root.update()
print("3 con selección:", [b._enabled for b in app.action_btns])
app.lock()
print("4 tras bloquear:", [b._enabled for b in app.action_btns])
print("5 label del ojo:", app.show_val_btn.label.cget("text"))
app.toggle_show_value()
print("6 tras pulsar:", app.show_val_btn.label.cget("text"))
app.root.destroy()

for f in ("v.json", ".cofre-sticks.json", ".cofre-salt", ".cofre-access.log", "COFRE.KEY"):
    p = fake / f
    if p.exists():
        p.unlink()
