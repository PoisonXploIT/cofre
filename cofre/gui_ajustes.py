"""COFRE - ajustes y emergencia (2026-11-19).

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

class AjustesGUI:
    """Se mezcla en CofreGUI; no se instancia sola."""

    def open_settings(self, event=None) -> None:
        """6.7: seguridad, generador, alertas, navegador, copias y Acerca de."""
        from cofre import alerts as alerts_mod
        from cofre import settings as st
        from cofre import widgets as W
        cfg = st.load(self.vault_path)
        alertas = alerts_mod.load_settings(self.vault_path)
        win = self._sheet(msg("ajustes.titulo"))
        win.geometry("840x660")
        cab = tk.Frame(win, bg=PANEL)
        cab.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(cab, text=msg("ajustes.titulo"), fg=FG, bg=PANEL, font=self.f_title,
                 anchor="w").pack(side="left")
        self._btn(cab, msg("comun.cerrar"), win.destroy).pack(side="right")
        tk.Label(win, text=msg("ajustes.intro"),
                 fg=MUT, bg=PANEL, font=self.f_small, anchor="w").pack(
            fill="x", padx=16)

        cuerpo = tk.Frame(win, bg=PANEL)
        cuerpo.pack(fill="both", expand=True, padx=16, pady=(6, 0))
        izq = tk.Frame(cuerpo, bg=PANEL)
        izq.pack(side="left", fill="both", expand=True, padx=(0, 14))
        der = tk.Frame(cuerpo, bg=PANEL)
        der.pack(side="left", fill="both", expand=True)

        def seccion(parent, titulo: str) -> None:
            tk.Label(parent, text=titulo.upper(), fg=FAINT, bg=PANEL,
                     font=self.f_small, anchor="w").pack(fill="x", pady=(10, 2))

        def campo(parent, etiqueta: str, var, ancho: int = 8):
            fila = tk.Frame(parent, bg=PANEL)
            fila.pack(fill="x", pady=2)
            tk.Label(fila, text=etiqueta, fg=MUT, bg=PANEL,
                     font=self.f_small, width=34, anchor="w").pack(side="left")
            entrada = tk.Entry(fila, textvariable=var, width=ancho, bg=CAMPO,
                               fg=FG, insertbackground=FG, relief="flat",
                               highlightthickness=1, highlightbackground=LINE,
                               font=self.f_body)
            entrada.pack(side="left")
            return entrada

        def segmentado(parent, etiqueta: str, var, opciones, etiquetas):
            fila = tk.Frame(parent, bg=PANEL)
            fila.pack(fill="x", pady=2)
            tk.Label(fila, text=etiqueta, fg=MUT, bg=PANEL,
                     font=self.f_small, width=34, anchor="w").pack(side="left")
            W.Segmented(fila, var, opciones, etiquetas,
                        bg=PANEL).pack(side="left")

        v_idle = tk.StringVar(value=str(cfg["idle_minutes"]))
        v_max = tk.StringVar(value=str(cfg["max_hours"]))
        v_clip = tk.StringVar(value=str(cfg["clipboard_seconds"]))
        v_reveal = tk.StringVar(value=str(cfg["reveal_seconds"]))
        v_perfil = tk.StringVar(value=str(cfg["gen_profile"]))
        v_palabras = tk.StringVar(value=str(cfg["gen_words"]))
        v_idioma = tk.StringVar(value=str(cfg["gen_lang"]))
        v_bridge = tk.BooleanVar(value=bool(cfg["bridge_on_start"]))
        v_carpeta = tk.StringVar(value=str(cfg["backup_folder"]))
        v_burst = tk.StringVar(value=str(alertas["burst_count"]))
        v_bmin = tk.StringVar(value=str(alertas["burst_minutes"]))
        v_desde = tk.StringVar(value=str(alertas["odd_from"]))
        v_hasta = tk.StringVar(value=str(alertas["odd_to"]))
        v_pausa = tk.StringVar(value=str(alertas["cooldown_minutes"]))
        v_fallos = tk.StringVar(value=str(alertas["open_failures"]))
        v_rot = tk.StringVar(value=str(alertas["rotation_hours"]))

        seccion(izq, msg("ajustes.seguridad"))
        campo(izq, msg("ajustes.inactividad"), v_idle)
        campo(izq, msg("ajustes.maximo"), v_max)
        campo(izq, msg("ajustes.portapapeles"), v_clip)
        campo(izq, msg("ajustes.revelar"), v_reveal)

        seccion(izq, msg("ajustes.generador"))
        segmentado(izq, "Perfil por defecto", v_perfil,
                   ["machine", "human"], ["Para máquinas", "Palabras"])
        segmentado(izq, "Palabras", v_palabras, ["4", "6", "8"],
                   ["4", "6", "8"])
        segmentado(izq, "Idioma", v_idioma, ["es", "en"], ["es", "en"])

        seccion(izq, msg("ajustes.alertas"))
        campo(izq, msg("ajustes.rafaga"), v_burst)
        campo(izq, msg("ajustes.rafaga_min"), v_bmin)
        campo(izq, msg("ajustes.desde"), v_desde)
        campo(izq, msg("ajustes.hasta"), v_hasta)
        campo(izq, msg("ajustes.pausa"), v_pausa)
        campo(izq, msg("ajustes.fallos"), v_fallos)
        campo(izq, msg("ajustes.rotación"), v_rot)

        seccion(der, msg("ajustes.navegador"))
        v_nav = tk.BooleanVar(value=bool(self.browser_on))
        fila_nav = tk.Frame(der, bg=PANEL)
        fila_nav.pack(fill="x", pady=(6, 2))
        punto = tk.Canvas(fila_nav, width=12, height=12, bg=PANEL,
                          highlightthickness=0)
        punto.pack(side="left", padx=(0, 6))
        estado_nav = tk.Label(fila_nav, text="", fg=MUT, bg=PANEL,
                              font=self.f_body, anchor="w")
        estado_nav.pack(side="left")
        self._btn(fila_nav, msg("ajustes.emparejar"),
                  lambda e: self._emparejar_host()).pack(side="right",
                                                         padx=(8, 0))
        tk.Label(fila_nav, text=msg("ajustes.conectar"), fg=MUT, bg=PANEL,
                 font=self.f_small).pack(side="right", padx=(0, 4))
        W.Switch(fila_nav, v_nav, bg=PANEL).pack(side="right")

        def pintar_nav() -> None:
            conectado = bool(self.browser_on)
            punto.delete("all")
            punto.create_oval(2, 2, 10, 10,
                              fill=OK if conectado else LINE, outline="")
            estado_nav.configure(
                text=msg("ajustes.conectado") if conectado else msg("ajustes.desconectado"),
                fg=OK if conectado else MUT)

        def cambiar_nav(*_a) -> None:
            if bool(v_nav.get()) != bool(self.browser_on):
                self.toggle_browser()
            if bool(v_nav.get()) != bool(self.browser_on):
                v_nav.set(bool(self.browser_on))
            pintar_nav()

        v_nav.trace_add("write", cambiar_nav)
        pintar_nav()

        seccion(der, msg("ajustes.copias"))
        fila_copia = tk.Frame(der, bg=PANEL)
        fila_copia.pack(fill="x", pady=2)
        tk.Entry(fila_copia, textvariable=v_carpeta, bg=CAMPO, fg=FG,
                 insertbackground=FG, relief="flat", highlightthickness=1,
                 highlightbackground=LINE, font=self.f_body).pack(
            side="left", fill="x", expand=True)
        self._btn(fila_copia, msg("ajustes.carpeta"),
                  lambda e: self._elegir_carpeta(v_carpeta)).pack(
            side="left", padx=6)
        self._btn(der, msg("ajustes.copiar"),
                  lambda e: self._copiar_copia(v_carpeta.get())).pack(
            anchor="w", pady=4)
        tk.Label(der, text=msg("ajustes.copia_aviso"),
                 fg=FAINT, bg=PANEL, font=self.f_small, anchor="w",
                 wraplength=360, justify="left").pack(fill="x")

        seccion(der, msg("ajustes.acerca"))
        formato = "v2 (índice y entradas cifrados)" if self.vault.is_v2() else "v1"
        tk.Label(der, text=msg("ajustes.versión", version=st.VERSION, formato=formato),
                 fg=FG, bg=PANEL, font=self.f_body, anchor="w").pack(fill="x")
        tk.Label(der, text=str(self.vault_path), fg=MUT, bg=PANEL,
                 font=self.f_small, anchor="w", wraplength=360,
                 justify="left").pack(fill="x")

        seccion(der, msg("ajustes.emergencia"))
        self._btn(der, msg("ajustes.panico"), self.open_panic,
                  danger=True).pack(anchor="w")

        def guardar(event=None) -> None:
            try:
                nuevo = st.clamp({
                    "idle_minutes": int(v_idle.get()),
                    "max_hours": int(v_max.get()),
                    "clipboard_seconds": int(v_clip.get()),
                    "reveal_seconds": int(v_reveal.get()),
                    "gen_profile": v_perfil.get(),
                    "gen_words": int(v_palabras.get()),
                    "gen_lang": v_idioma.get(),
                    "bridge_on_start": bool(v_bridge.get()),
                    "backup_folder": v_carpeta.get().strip(),
                })
                nuevos_alertas = {
                    "burst_count": int(v_burst.get()),
                    "burst_minutes": float(v_bmin.get()),
                    "odd_from": int(v_desde.get()),
                    "odd_to": int(v_hasta.get()),
                    "cooldown_minutes": float(v_pausa.get()),
                    "open_failures": int(v_fallos.get()),
                    "rotation_hours": int(v_rot.get()),
                }
            except ValueError:
                self.set_foot("los tiempos y umbrales tienen que ser números")
                return
            st.save(self.vault_path, nuevo)
            alerts_mod.write_settings(self.vault_path, nuevos_alertas)
            self._aplicar_settings(nuevo)
            self.set_foot("ajustes guardados")
            win.destroy()

        # Guardar arriba, junto a Cerrar: abajo se quedaba cortado
        self._btn(cab, msg("comun.guardar"), guardar, accent=True).pack(side="right",
                                                             padx=8)

    def _aplicar_settings(self, cfg: dict) -> None:
        self._cfg = dict(cfg)
        self.clipboard_ttl = int(cfg["clipboard_seconds"])
        self.reveal_ms = int(cfg["reveal_seconds"]) * 1000
        self._gen_lang = str(cfg["gen_lang"])
        self._bridge_on_start = bool(cfg["bridge_on_start"])
        if self.session_obj is not None:
            self.session_obj.settings["idle_minutes"] = int(cfg["idle_minutes"])
            self.session_obj.settings["max_hours"] = int(cfg["max_hours"])

    def _elegir_carpeta(self, var) -> None:
        from tkinter import filedialog
        carpeta = filedialog.askdirectory(parent=self.root)
        if carpeta:
            var.set(carpeta)

    def _copiar_copia(self, carpeta: str) -> None:
        from datetime import datetime
        import shutil
        carpeta = str(carpeta or "").strip()
        if not carpeta:
            self.set_foot("elige primero la carpeta de copias")
            return
        destino_dir = Path(carpeta)
        if not destino_dir.is_dir():
            self.set_foot("la carpeta de copias no existe")
            return
        destino = destino_dir / ("cofre-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
        try:
            shutil.copy2(self.vault_path, destino)
        except Exception as exc:                   # noqa: BLE001
            self.set_foot(f"no se pudo copiar: {exc}")
            return
        record(self.vault_path, "backup", self.gate, self.serial, name="-",
               ok=True, detail=str(destino)[:150])
        self.set_foot(f"copia escrita en {destino}. La llave NO va en esa carpeta.")

    def _emparejar_host(self) -> None:
        aviso = ("Se va a registrar el host de mensajería nativa para el "
                 "navegador. Cierra el navegador si el instalador lo pide.")
        if not self._confirmar_accion("Emparejar el navegador", aviso,
                                      "Emparejar"):
            return
        instalador = Path(__file__).resolve().parent.parent / "tools" / "install_host.py"
        try:
            proc = subprocess.run([sys.executable, str(instalador)],
                                  capture_output=True, text=True, timeout=120)
            salida = ((proc.stdout or "") + (proc.stderr or "")).strip()
        except Exception as exc:                   # noqa: BLE001
            salida = f"no se pudo ejecutar el instalador: {exc}"
        self._mostrar_salida("Emparejar el navegador", salida)

    def revoke_from_gui(self, lab) -> None:
        serial = lab.cget("text").split("serial ")[1].split(" ")[0] if "serial " in lab.cget("text") else None
        if serial is None:
            return
        if not getattr(self, "_confirm_revoke", None):
            self._confirm_revoke = serial
            self.set_foot(f"pulsa Revocar otra vez para dar de baja el pendrive {serial}")
            self.root.after(6000, lambda: setattr(self, "_confirm_revoke", None))
            return
        self._confirm_revoke = None
        if self.revoke_stick_safe(int(serial)):
            self.refresh_sticks()
            self.set_foot(f"pendrive {serial} dado de baja")

    def revoke_stick_safe(self, serial: int) -> bool:
        reg = load_registry(self.vault_path)
        if len(reg.get("sticks", {})) <= 1:
            self.set_foot("no se puede revocar el unico pendrive: perderias el cofre")
            return False
        ok = revoke_stick(self.vault_path, serial)
        if ok:
            record(self.vault_path, "stick-revoke", self.gate, serial, ok=True)
        return ok
