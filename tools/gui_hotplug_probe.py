"""Arranca la GUI y registra en stdout cada cambio de estado/pendrives.

Prueba de 1.3 (deteccion en caliente) sin mirar la pantalla: si el polling
funciona, aparecen lineas nuevas al enchufar o desenchufar un pendrive sin
pulsar Reconectar.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.gui import CofreGUI

app = CofreGUI(str(Path.home() / "AI" / "cofre" / "cofre.json"), "usb")
app.build()
app.root.update()

last = None
print(f"{time.strftime('%H:%M:%S')} ARRANQUE estado={app.state()} status={app.status_var.get()}", flush=True)

end = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 120)
while time.time() < end:
    app.root.update()
    snap = (app.state(), app.status_var.get(), tuple(r.cget("text") for r in app.stick_rows))
    if snap != last:
        last = snap
        print(f"{time.strftime('%H:%M:%S')} CAMBIO estado={snap[0]} status={snap[1]}", flush=True)
        for row in snap[2]:
            if row:
                print(f"{time.strftime('%H:%M:%S')}   fila: {row}", flush=True)
    time.sleep(0.5)

app.root.destroy()
