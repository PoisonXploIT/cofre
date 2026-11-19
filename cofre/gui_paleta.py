"""COFRE - paleta de comandos y atajos (2026-11-19).

Sacado de `gui.py` para que el fichero de la ventana se pueda leer entero. Se mezcla
en `CofreGUI` por herencia: los metodos usan `self` y las constantes de color de
`cofre/theme.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

from cofre.audit import record, tail
from cofre.messages import msg
from cofre.theme import COLORS, SIZES, SPACE
from cofre.threads import assert_main
from cofre.usb import (copy_key_to, create_key_on, find_stick, key_drives,
                       load_registry, revoke_stick, volume_serial)

PANEL = COLORS["surface"]
PANEL2 = COLORS["card"]
CAMPO = COLORS["raised"]
INPUT = COLORS["input"]
FG = COLORS["text"]
MUT = COLORS["muted"]
FAINT = COLORS["faint"]
WARN = COLORS["warn"]
WARNBG = COLORS["warn_bg"]
WARNFG = COLORS["warn_fg"]
OK = COLORS["ok"]
LINE = COLORS["border"]
LINE2 = COLORS["border_strong"]
ACC = COLORS["accent"]
ACC2 = COLORS["card"]
ONACC = COLORS["on_accent"]
DANGER = COLORS["danger"]
DIS = COLORS["disabled"]
BG = COLORS["bg"]
MASK = "\u2022" * 16
XS = SPACE["xs"]
SM = SPACE["sm"]
MD = SPACE["md"]
LG = SPACE["lg"]
XL = SPACE["xl"]
ICON_FONT = "Segoe Fluent Icons"
from cofre import widgets as W  # noqa: E402
from cofre.gen import entropy, human_password, machine_password  # noqa: E402,F401

class PaletaGUI:
    """Se mezcla en CofreGUI; no se instancia sola."""

    def open_palette(self, event=None):
        """6.4: Ctrl+K. Busca secretos y acciones; Enter ejecuta."""
        if getattr(self, "lock_screen", None) and not self.session:
            self.set_foot("abre el cofre para usar la paleta de comandos")
            return "break"
        actual = getattr(self, "_palette", None)
        if actual is not None:
            try:
                actual.win.lift()
                actual.entrada.focus_force()
            except Exception:
                pass
            return "break"
        from cofre.palette import Palette
        self._palette = Palette(self)
        return "break"

    def _foco_en_campo(self) -> bool:
        try:
            foco = self.root.focus_get()
        except Exception:
            foco = None
        return foco is not None and foco.winfo_class() in (
            "Entry", "Text", "TEntry", "TText")

    def _on_edit_shortcut(self, event=None):
        if self._foco_en_campo():
            return
        self.edit_selected()

    def _on_delete_shortcut(self, event=None):
        if self._foco_en_campo():
            return
        self.delete_selected()

    def _on_copy_name_shortcut(self, event=None):
        if self._foco_en_campo():
            return
        self.copy_name()

    def _rotar_para_paleta(self, nombre: str) -> None:
        """Rotar desde la paleta: confirmación aquí y el CLI hace el trabajo."""
        if not self.session:
            self.set_foot("abre el cofre para rotar")
            return
        meta = dict(self.vault.meta(nombre) or {})
        proveedor = str(meta.get("provider") or "")
        if not proveedor:
            self.set_foot("ese secreto no tiene proveedor")
            return
        from cofre.providers import get as provider_get
        try:
            automatico = bool(getattr(provider_get(proveedor),
                                      "can_auto_rotate", False))
        except Exception:
            automatico = False
        if not automatico:
            self.set_foot("esa rotación es asistida: ejecuta "
                          "'run.cmd rotate --manual' en una terminal")
            return
        consumidores = list(meta.get("consumers") or [])
        aviso = f"Se va a rotar '{nombre}' en {proveedor}. "
        if consumidores:
            aviso += "Se desplegará en: " + ", ".join(consumidores) + ". "
        aviso += "El valor viejo queda registrado para revocarlo desde Salud."
        if not self._confirmar_accion("Rotar credencial", aviso, "Rotar"):
            return
        material = getattr(self.vault, "_material", {}) or {}
        stick = str(material.get("stick_path") or "")
        if not stick:
            self.set_foot("sin la ruta del pendrive no se puede rotar desde aquí")
            return
        self.set_foot(f"rotando '{nombre}' con el CLI...")
        self.root.update_idletasks()
        comando = [sys.executable, "-m", "cofre.cli", "--gate", self.gate,
                   "--stick", stick, "--vault", self.vault_path,
                   "rotate", nombre, "--si"]
        entorno = dict(os.environ, COFRE_VAULT=str(self.vault_path))
        if material.get("pin"):
            entorno["COFRE_PIN"] = str(material["pin"])
        codigo = 1
        try:
            proc = subprocess.run(comando, capture_output=True, text=True,
                                  env=entorno, timeout=240)
            salida = (proc.stdout or "") + (proc.stderr or "")
            codigo = proc.returncode
        except Exception as exc:                   # noqa: BLE001
            salida = f"no se pudo ejecutar la rotación: {exc}"
        try:
            self.vault.refresh()
            self.refresh_list()
            self.refresh_detail()
            self._escribir_calendario()
        except Exception:
            pass
        self._mostrar_salida(f"Rotación de {nombre}", salida.strip())
        self.set_foot("rotación terminada" if codigo == 0
                      else "rotación con avisos: revisa la salida")
