import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.gui import CofreGUI

app = CofreGUI(str(Path.home() / "AI" / "cofre" / "cofre.json"), "usb")
app.build()
app.root.update()

print("estado:", app.state(), "|", app.status_var.get())

app.dest_var.set("E:\\")
print("respaldo en E: (no conectada) ->", app.wizard_backup())
print("pie:", app.foot_var.get())

app.dest_var.set("F:\\")
print("respaldo en F: (ya tiene COFRE.KEY) ->", app.wizard_backup())
print("pie:", app.foot_var.get())

print("pendrives:", app.stick_report())
app.root.destroy()
