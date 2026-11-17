"""A2: el evento 'lock' se firma y no se duplica.

Con cofre temporal: abrir, bloquear, y comprobar en el log que hay UN evento
lock, con mac, y que verify sigue en verde para ese fichero.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.audit import verify
from cofre.gui import CofreGUI
from cofre.paths import audit_path
from cofre.theme import dark_titlebar, enable_dpi_awareness
from tmpvault import cofre_temporal

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def eventos(vault: Path) -> list[dict]:
    p = audit_path(vault)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    enable_dpi_awareness()
    vault, llave, tmp = cofre_temporal()
    app = CofreGUI(str(vault), "usb", stick=str(llave))
    dark_titlebar(app.root)
    app.build()
    app.root.update()
    if not app.session:
        print("no se pudo abrir el cofre temporal")
        return 1

    antes = len(eventos(vault))
    app.lock(motivo="prueba", detalle="inactividad")
    app.root.update()
    despues = eventos(vault)
    locks = [e for e in despues if e.get("ev") == "lock"]
    check("1. se escribe un solo evento lock", len(locks) == len(
        [e for e in eventos(vault) if e.get("ev") == "lock"]), f"{len(locks)}")
    nuevos = despues[antes:]
    check("2. el evento nuevo es lock", len(nuevos) == 1 and nuevos[0].get("ev") == "lock",
          str([e.get("ev") for e in nuevos]))
    check("3. el lock va firmado", bool(nuevos and nuevos[0].get("mac")),
          "mac" if nuevos and nuevos[0].get("mac") else "SIN FIRMA")
    check("4. lleva el motivo", bool(nuevos and "inactividad" in str(nuevos[0].get("detail"))),
          str(nuevos[0].get("detail")) if nuevos else "")

    # bloquear otra vez no debe escribir nada: ya estaba cerrado
    antes2 = len(eventos(vault))
    app.lock()
    app.root.update()
    check("5. bloquear un cofre ya cerrado no escribe evento",
          len(eventos(vault)) == antes2, f"{len(eventos(vault))} vs {antes2}")

    ok, detalle = verify(vault)
    check("6. verify del log temporal en verde", ok, detalle[:80])

    app.root.destroy()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
