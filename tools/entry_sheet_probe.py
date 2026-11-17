"""Sonda de E6: la hoja de alta y edicion.

  python tools/entry_sheet_probe.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.entry_sheet import EntrySheet
from cofre.gui import CofreGUI
from cofre.theme import dark_titlebar, enable_dpi_awareness
from tmpvault import cofre_temporal

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


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

    # el formulario fijo ya no existe
    check("1. no queda formulario fijo en la ventana",
          not hasattr(app, "name_entry") and not hasattr(app, "val_entry"), "")

    # hoja de alta
    hoja = EntrySheet(app, mode="new")
    app.root.update()
    check("2. la hoja se abre", hoja.win.winfo_exists(), "")
    check("3. empieza sin valor", hoja.campo_valor.get() == "", "")
    hoja.campo_nombre.set("NUEVO_PRUEBA")
    hoja.campo_valor.set("valor-de-prueba")
    hoja.campo_tags.set("prueba, sonda")
    hoja.campo_sitios.set("ejemplo.com")
    hoja.tipo_var.set("password")
    hoja.guardar()
    app.root.update()
    check("4. guarda el secreto", "NUEVO_PRUEBA" in app.vault.names(), str(app.vault.names()))
    check("5. guarda el valor",
          app.vault.get(app.session, "NUEVO_PRUEBA") == "valor-de-prueba", "")
    check("6. guarda etiquetas", "sonda" in (app.vault.meta("NUEVO_PRUEBA").get("tags") or []),
          str(app.vault.meta("NUEVO_PRUEBA").get("tags")))
    check("7. guarda el sitio", app.vault.urls("NUEVO_PRUEBA") == ["ejemplo.com"],
          str(app.vault.urls("NUEVO_PRUEBA")))
    check("8. guarda el tipo", app.vault.meta("NUEVO_PRUEBA").get("type") == "password",
          str(app.vault.meta("NUEVO_PRUEBA").get("type")))

    # nombre obligatorio
    hoja2 = EntrySheet(app, mode="new")
    hoja2.campo_valor.set("x")
    hoja2.guardar()
    check("9. sin nombre no guarda y avisa", "nombre" in hoja2.aviso.cget("text").lower(),
          hoja2.aviso.cget("text"))
    hoja2.win.destroy()

    # hoja de edicion: precarga y no deja cambiar el nombre
    hoja3 = EntrySheet(app, mode="edit", nombre="NUEVO_PRUEBA")
    app.root.update()
    check("10. editar precarga el valor", hoja3.campo_valor.get() == "valor-de-prueba", "")
    check("11. editar no deja renombrar",
          str(hoja3.campo_nombre.entry.cget("state")) == "readonly", "")
    hoja3.campo_valor.set("valor-cambiado")
    hoja3.guardar()
    app.root.update()
    check("12. editar cambia el valor",
          app.vault.get(app.session, "NUEVO_PRUEBA") == "valor-cambiado", "")

    # generadores dentro de la hoja
    hoja4 = EntrySheet(app, mode="new")
    hoja4._generar("machine")
    check("13. el generador de maquina rellena", len(hoja4.campo_valor.get()) >= 40,
          str(len(hoja4.campo_valor.get())))
    hoja4._generar("words", 4)
    check("14. el generador de palabras rellena", len(hoja4.campo_valor.get()) > 8, "")
    hoja4.win.destroy()

    app.root.destroy()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
