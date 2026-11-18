#!/usr/bin/env python
"""COFRE - interfaz grafica standalone (Tkinter).

No integra nada: no abre puertos, no habla con servicios, no toca el navegador.
Usa los mismos modulos que la CLI (crypto, gate, audit, gen). Sin
dependencias: Tkinter viene con Python.

Uso:
  python -m cofre.gui
  run.cmd gui
  python -m cofre.gui --gate usb-pin      # el PIN se teclea en la propia ventana

Lo que aplica:
  - el valor esta oculto; solo un click de raton en "Ver" lo muestra, y se
    oculta solo a los 15 s ("Fijar" evita la auto-ocultacion);
  - Copiar escribe en el portapapeles real de Windows (avisa: cualquier
    proceso de la sesión puede leerlo);
  - los secretos no se escriben en ningún fichero de la interfaz;
  - cada accion queda en .cofre-access.log (nombre y gate, nunca el valor).
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import font as tkfont

from cofre.audit import clear_key as audit_clear_key
from cofre.audit import record, set_key as audit_set_key, tail
from cofre.crypto import Vault
from cofre.gate import GateUnavailable, material_for, resolve_session_key
from cofre.gen import entropy, human_password, machine_password
from cofre.paths import default_vault
from cofre.theme import (COLORS, SIZES, SPACE, apply_tk_scaling, build_fonts,
                         dark_titlebar, enable_dpi_awareness)
from cofre.usb import (KEY_FILENAME, DRIVE_FIXED, DRIVE_REMOVABLE, copy_key_to,
                       create_key_on, drive_kind, drive_letters, key_drives,
                       find_stick, load_registry, read_key, register_stick,
                       revoke_stick, volume_serial)

# Nombres cortos sobre los tokens de cofre/theme.py. Un color que no este en
# COLORS no se usa en esta interfaz.
BG = COLORS["bg"]
PANEL = COLORS["surface"]
PANEL2 = COLORS["card"]
CAMPO = COLORS["raised"]
WARNBG = COLORS["warn_bg"]
WARNFG = COLORS["warn_fg"]
INPUT = COLORS["input"]
FG = COLORS["text"]
MUT = COLORS["muted"]
FAINT = COLORS["faint"]
DIS = COLORS["disabled"]
ACC = COLORS["accent"]
ONACC = COLORS["on_accent"]
ACC2 = COLORS["card"]
WARN = COLORS["warn"]
OK = COLORS["ok"]
DANGER = COLORS["danger"]
LINE = COLORS["border"]
LINE2 = COLORS["border_strong"]

XS, SM, MD, LG, XL, XXL = (SPACE["xs"], SPACE["sm"], SPACE["md"],
                           SPACE["lg"], SPACE["xl"], SPACE["xxl"])

MASK = "•" * 16
ICON_FONT = "Segoe Fluent Icons"   # glifos; nunca emojis
SESION_IDLE = 10                   # minutos, igual que cofre/session.py
SESION_MAX = 8                     # horas
REVEAL_MS = 15000


class CofreGUI:
    def __init__(self, vault_path: str, gate: str, stick: str | None = None,
                 allow_new: bool = False, root: tk.Tk | None = None):
        self.vault_path = vault_path
        self.vault = Vault(Path(vault_path))
        self.gate = gate
        self.stick = stick
        self.allow_new = allow_new
        self.session = None
        self.serial = None
        self.selected = None
        self.reveal_id = None
        self.sticky = False
        self.needs_init = False
        self.bridge = None
        self.bridge_ctl = None
        self.session_obj = None
        self.confirm_queue = None
        self.confirm_grants: dict[tuple[str, str], float] = {}
        self.alert_state = None
        self.browser_on = False
        from cofre import settings as _settings
        self._cfg = _settings.load(self.vault_path)
        self.clipboard_ttl = int(self._cfg.get("clipboard_seconds", 30))
        self.reveal_ms = int(self._cfg.get("reveal_seconds", 15)) * 1000
        self._gen_lang = str(self._cfg.get("gen_lang", "es"))
        self._bridge_on_start = bool(self._cfg.get("bridge_on_start"))
        self._clip_id = None
        self._key_cache: set[str] = set()

        self.root = root or tk.Tk()
        self.root.title("COFRE - bóveda de secretos")
        self._set_icon()
        self.root.configure(bg=BG)
        self.root.geometry("980x620+30+30")
        # Medido el 2026-11-10: por debajo de 920 px los botones de la fila 2
        # (Renombrar, Borrar) quedan por debajo de su ancho y se recorta el
        # texto. La Fase B (layout responsivo) bajara este minimo.
        # E4: tres columnas necesitan mas ancho que las dos de antes.
        # 1080 deja ~440 px para el detalle, que es lo minimo para los
        # botones del panel de puesta en marcha sin recortarse.
        self.root.minsize(1080, 640)

        f = build_fonts(self.root)
        self.f_title = f["display"]
        self.f_h2 = f["title"]
        self.f_sub = f["label"]
        self.f_body = f["body"]
        self.f_mono = f["mono"]
        self.f_small = f["meta"]
        self.f_icon = f["icon"]

    # ---------- piezas de estilo ----------

    def _set_icon(self) -> None:
        """Icono de la ventana y de la barra de tareas. Si falta el .ico, la
        ventana funciona igual: no es un requisito."""
        for candidate in (Path(__file__).resolve().parent.parent / "assets" / "cofre.ico",
                          Path(__file__).resolve().parent / "assets" / "cofre.ico"):
            if candidate.is_file():
                try:
                    # las dos formas: una para esta ventana, otra para las que
                    # se abran despues (hojas modales de la fase C)
                    self.root.iconbitmap(str(candidate))
                    self.root.iconbitmap(default=str(candidate))
                except Exception:
                    pass
                return


    def _sheet(self, titulo: str) -> tk.Toplevel:
        """Toplevel con la misma barra oscura que la ventana principal."""
        win = tk.Toplevel(self.root)
        win.title(titulo)
        win.configure(bg=PANEL)
        try:
            win.transient(self.root)
        except Exception:
            pass
        dark_titlebar(win)
        return win

    def _text_btn(self, parent, texto: str, command, danger: bool = False,
                  alinear: str = "center"):
        """Boton de texto sin caja: el que usa la maqueta para acciones."""
        color = DANGER if danger else MUT
        try:
            fondo = str(parent.cget("bg"))
        except Exception:
            fondo = PANEL2
        frame = tk.Frame(parent, bg=fondo)
        lab = tk.Label(frame, text=texto, fg=color, bg=fondo,
                       font=self.f_body if alinear == "w" else self.f_small,
                       cursor="hand2", anchor=alinear, takefocus=1,
                       highlightthickness=2, highlightbackground=fondo,
                       highlightcolor=ACC,
                       padx=6 if alinear == "w" else 0, pady=3 if alinear == "w" else 0)
        if alinear == "w":
            lab.pack(fill="x")
        else:
            lab.pack()
        frame.label = lab
        frame._enabled = True
        frame._danger = danger

        def click(_e=None):
            if not frame._enabled:
                return
            command()

        lab.bind("<Button-1>", click)
        lab.bind("<Return>", click)
        lab.bind("<space>", click)
        lab.bind("<Enter>", lambda _e: lab.configure(
            fg=DANGER if danger else ACC, bg=CAMPO) if frame._enabled else None)
        lab.bind("<Leave>", lambda _e: lab.configure(fg=color, bg=fondo))

        def set_enabled(on: bool):
            frame._enabled = on
            lab.configure(fg=color if on else FAINT, cursor="hand2" if on else "")

        frame.set_colores = lambda fg, bg: (
            lab.configure(fg=fg, bg=bg), frame.configure(bg=bg))

        frame.set_enabled = set_enabled
        return frame

    def _icon_btn(self, parent, glyph: str, command, nombre: str = ""):
        """Boton de icono que pasa el evento real de Tk.

        `reveal` exige un clic de verdad; con un boton propio hay que entregarle
        el evento del canvas, no una llamada sin argumentos.
        """
        frame = tk.Frame(parent, bg=CAMPO)
        canvas = tk.Canvas(frame, width=30, height=30, bg=CAMPO, bd=0,
                           highlightthickness=0, takefocus=1)
        canvas.pack()
        canvas.create_text(15, 15, text=glyph, fill=MUT, font=(ICON_FONT, 12))
        frame.canvas = canvas
        frame._enabled = True
        frame.label = canvas

        def click(event):
            if not frame._enabled:
                return
            try:
                command(event)
            except TypeError:
                command()

        canvas.bind("<ButtonRelease-1>", click)
        canvas.bind("<Enter>", lambda _e: canvas.configure(bg=PANEL2))
        canvas.bind("<Leave>", lambda _e: canvas.configure(bg=CAMPO))
        if nombre == "ver":
            self._ver_targets_extra = getattr(self, "_ver_targets_extra", [])
            self._ver_targets_extra.append(canvas)

        def set_enabled(on: bool):
            frame._enabled = on
            canvas.configure(cursor="hand2" if on else "")

        frame.set_enabled = set_enabled
        return frame

    def _btn(self, parent, text, command, accent=False, danger=False):
        """Boton de la ventana principal usando los widgets redondeados (E2).

        Se mantiene la API antigua (`label.configure(text=...)`,
        `set_enabled`, `_enabled`) porque hay código que la usa; el widget nuevo
        expone `label` como un proxy de texto.
        """
        from cofre import widgets as W

        kind = "primary" if accent else ("danger" if danger else "secondary")
        try:
            bg = str(parent.cget("bg"))
        except Exception:
            bg = PANEL2
        boton = W.Button(parent, text, kind=kind, command=lambda: command(None), bg=bg)
        boton._enabled = True

        class _Proxy:
            """`boton.label.configure(text=...)` -> `boton.set_text(...)`."""

            def __init__(self, dueno):
                self._dueno = dueno

            def configure(self, **kw):
                if "text" in kw:
                    self._dueno.set_text(str(kw["text"]))
                if "fg" in kw:
                    pass          # el color lo decide el kind

            config = configure

            def cget(self, clave):
                if clave == "text":
                    return self._dueno.text
                return ""

        boton.label = _Proxy(boton)

        def set_enabled(on: bool):
            boton._enabled = on
            boton.set_enabled(on)

        boton.set_enabled = set_enabled
        return boton

    def _draw_pill(self) -> None:
        """Pildora redondeada: fondo ok_bg, texto corto y punto de estado."""
        if not hasattr(self, "pill"):
            return
        from cofre import widgets as W
        abierto = bool(self.session)
        fondo = COLORS["ok_bg"] if abierto else COLORS["raised"]
        color = COLORS["ok_fg"] if abierto else COLORS["muted"]
        texto = self.status_var.get()
        self.pill.delete("all")
        ancho = max(120, self.f_sub.measure(texto) + 46)
        self._pill_ancho = ancho
        self.pill.configure(width=ancho)
        W.round_rect(self.pill, 1, 1, ancho - 1, 27, 13, fill=fondo, outline="")
        self.pill.create_oval(11, 11, 19, 19,
                              fill=COLORS["ok"] if abierto else COLORS["faint"],
                              outline="")
        self.pill.create_text(27, 14, text=texto, anchor="w", fill=color,
                              font=self.f_sub)

    def _actualizar_pildora_tiempo(self) -> None:
        """'Abierto · llave E: · se bloquea en 9:42'."""
        base = getattr(self, "_pill_texto", "Abierto")
        if self.session_obj is not None:
            try:
                resta = max(0, int(self.session_obj.settings["idle_minutes"] * 60
                                   - self.session_obj.idle_seconds()))
                base += f" · se bloquea en {resta // 60}:{resta % 60:02d}"
            except Exception:
                pass
        self.status_var.set(base)
        self._draw_pill()

    def _placeholder(self, texto: str, entry, var) -> None:
        """Texto de ayuda gris dentro del campo, que desaparece al escribir."""
        if var.get():
            return
        entry.insert(0, texto)
        entry.configure(fg=FAINT)
        self._placeholder_text = texto

        def dentro(_e=None):
            if entry.get() == texto:
                entry.delete(0, "end")
                entry.configure(fg=FG)

        def fuera(_e=None):
            if not entry.get():
                entry.insert(0, texto)
                entry.configure(fg=FAINT)

        entry.bind("<FocusIn>", dentro, add="+")
        entry.bind("<FocusOut>", fuera, add="+")

    def _entry(self, parent, var, mono=False, show=None):
        return tk.Entry(parent, textvariable=var, bg=INPUT, fg=FG,
                        font=self.f_mono if mono else self.f_body,
                        relief="flat", borderwidth=0,
                        highlightbackground=LINE, highlightthickness=1,
                        insertbackground=FG, show=show)

    def build(self):
        # ---------- cabecera ----------
        header = tk.Frame(self.root, bg=PANEL)
        header.pack(fill="x")

        top = tk.Frame(header, bg=PANEL)
        top.pack(fill="x", padx=16, pady=12)
        tk.Label(top, text="COFRE", fg=FG, font=self.f_title, bg=PANEL).pack(side="left")


        # E7: pildora redondeada y verde, con texto corto, a la izquierda de
        # los botones: pildora, Bloquear, Nuevo.
        self.status_var = tk.StringVar(value="Cerrado")
        self.pill = tk.Canvas(top, height=28, bg=PANEL, highlightthickness=0, bd=0)
        self.pill.pack(side="left", padx=(10, 12))
        self._pill_ancho = 250
        self.pill.configure(width=self._pill_ancho)
        self.status_label = None
        self._draw_pill()

        self._btn(top, "Bloquear", self.lock).pack(side="right", padx=(0, 10))
        self._btn(top, "Nuevo", self._focus_new, accent=True).pack(side="right",
                                                                   padx=(0, 0))
        # E4: el buscador vive en la cabecera, no en la lista
        self.query_var = tk.StringVar()
        caja_buscar = tk.Frame(top, bg=PANEL2, highlightthickness=1,
                               highlightbackground=LINE)
        caja_buscar.pack(side="left", padx=(16, 0))
        tk.Label(caja_buscar, text="", fg=MUT, bg=PANEL2,
                 font=(ICON_FONT, 11)).pack(side="left", padx=(8, 4))
        self.query_entry = self._entry(caja_buscar, self.query_var)
        self.query_entry.configure(width=30, bg=PANEL2, highlightthickness=0, bd=0)
        self.query_entry.pack(side="left", pady=5)
        self._placeholder("Buscar secretos y acciones", self.query_entry, self.query_var)
        tk.Label(caja_buscar, text="Ctrl K", fg=FAINT, bg=PANEL2,
                 font=self.f_small).pack(side="left", padx=(6, 8))
        self.query_entry.bind("<KeyRelease>", lambda _e: self.refresh_list())
        self.query_entry.bind("<FocusIn>", lambda _e: caja_buscar.configure(
            highlightbackground=ACC))
        self.query_entry.bind("<FocusOut>", lambda _e: caja_buscar.configure(
            highlightbackground=LINE))
        self.query_entry.bind("<Down>", self._enfocar_lista)

        # ---------- banda de alertas (E7) ----------
        self.alert_band = tk.Frame(self.root, bg=WARNBG)
        self.alert_icon = tk.Label(self.alert_band, text="", fg=WARNFG,
                                   bg=WARNBG, font=(ICON_FONT, 12))
        self.alert_icon.pack(side="left", padx=(14, 6), pady=6)
        self.alert_text = tk.Label(self.alert_band, text="", fg=WARNFG, bg=WARNBG,
                                   font=self.f_small, anchor="w")
        self.alert_text.pack(side="left", fill="x", expand=True)
        self._text_btn(self.alert_band, "Descartar", self.dismiss_alerts).pack(
            side="right", padx=(6, 16))
        self._text_btn(self.alert_band, "Ver detalle",
                       lambda: self._mostrar_vista("salud")).pack(
            side="right", padx=6)
        self._alerts_visibles = []

        # ---------- cuerpo ----------
        body = tk.Frame(self.root, bg=BG)
        self.body = body
        body.pack(fill="both", expand=True, padx=16, pady=16)

        # E4: tres columnas. Barra lateral (llaves y puesta en marcha), lista
        # de secretos y detalle. Antes la lista y el detalle compartian columna
        # y el formulario empujaba todo hacia abajo.
        left = tk.Frame(body, bg=PANEL, width=SIZES["sidebar"])
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        # E7: la columna izquierda es navegacion, no un panel de estado.
        self.filtro = "todos"
        self.nav_btns = {}

        def seccion(titulo: str) -> None:
            tk.Label(self._nav_box if hasattr(self, "_nav_box") else left,
                     text=titulo.upper(), fg=FAINT, font=self.f_small,
                     bg=PANEL, anchor="w").pack(fill="x", padx=14, pady=(10, 2))

        self.nav_counts = {}

        self.nav_dots = {}

        def entrada(clave: str, texto: str, comando, contador: bool = True,
                    punto: str | None = None) -> None:
            fila = tk.Frame(self._nav_box, bg=PANEL)
            fila.pack(fill="x", padx=12, pady=1)
            if punto:
                punto_lab = tk.Label(fila, text="●", fg=punto, bg=PANEL,
                                     font=(self.f_small.actual("family"), 8))
                punto_lab.pack(side="left", padx=(2, 4))
                self.nav_dots[clave] = punto_lab
            b = self._text_btn(fila, texto, comando, alinear="w")
            b.label.configure(pady=1)
            b.pack(side="left", fill="x", expand=True)
            self.nav_btns[clave] = b
            if contador:
                lab = tk.Label(fila, text="", fg=FAINT, bg=PANEL, font=self.f_small)
                lab.pack(side="right", padx=(0, 6))
                self.nav_counts[clave] = lab

        nav = tk.Frame(left, bg=PANEL)
        nav.pack(fill="both", expand=True)
        self._nav_box = nav

        seccion("Biblioteca")
        entrada("todos", "Todos", lambda: self.set_filtro("todos"))
        entrada("password", "Contraseñas", lambda: self.set_filtro("password"))
        entrada("api", "Claves y tokens", lambda: self.set_filtro("api"))
        entrada("note", "Notas", lambda: self.set_filtro("note"))

        seccion("Vigilar")
        entrada("atencion", "Atención", lambda: self.set_filtro("atencion"),
                punto=WARN)
        entrada("caducan", "Caducan pronto", lambda: self.set_filtro("caducan"),
                punto=COLORS["rot_fg"])
        entrada("rotación", "Rotación pendiente", lambda: self.set_filtro("rotación"),
                punto=COLORS["rot_fg"])
        entrada("papelera", "Papelera", lambda: self.set_filtro("papelera"))

        sistema = tk.Frame(left, bg=PANEL)
        # antes que el bloque expandible: si no, el fondo de la columna se
        # queda sin altura y las entradas de Sistema salen cortadas (lo cazó
        # layout_check al medir el alto, no solo el ancho)
        sistema.pack(side="bottom", fill="x", pady=(0, 8), before=nav)

        def seccion_sistema(titulo: str) -> None:
            tk.Label(sistema, text=titulo.upper(), fg=FAINT, font=self.f_small,
                     bg=PANEL, anchor="w").pack(fill="x", padx=14, pady=(6, 2))

        def entrada_sistema(clave: str, texto: str, comando) -> None:
            fila = tk.Frame(sistema, bg=PANEL)
            fila.pack(fill="x", padx=12, pady=1)
            b = self._text_btn(fila, texto, comando, alinear="w")
            b.label.configure(pady=1)
            b.pack(side="left", fill="x", expand=True)
            self.nav_btns[clave] = b

        seccion_sistema("Sistema")
        entrada_sistema("salud", "Salud", self.open_health)
        entrada_sistema("llaves", "Llaves y recuperación", self.open_keys)
        entrada_sistema("registro", "Registro", self.open_audit)
        entrada_sistema("guía", "Guía", self.open_guide)
        entrada_sistema("ajustes", "Ajustes", self.open_settings)

        lista_col = tk.Frame(body, bg=PANEL, width=SIZES["list"])
        lista_col.pack(side="left", fill="y", padx=(12, 0))
        lista_col.pack_propagate(False)
        cab_lista = tk.Frame(lista_col, bg=PANEL)
        cab_lista.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(cab_lista, text="Secretos", fg=FG, font=self.f_sub, bg=PANEL).pack(side="left")
        self.count_var = tk.StringVar(value="0 entradas")
        tk.Label(cab_lista, textvariable=self.count_var, fg=MUT, font=self.f_small,
                 bg=PANEL).pack(side="right")
        self.list_frame = tk.Frame(lista_col, bg=PANEL)
        self.list_frame.pack(fill="both", expand=True, padx=8)

        # la ayuda larga vive en la hoja Guía (F1), no en la columna
        self.help_box = tk.Frame(left, bg=PANEL2)

        # derecha: wizard + detalle + alta
        # Columna derecha desplazable: medido el 2026-11-10, el formulario de
        # alta no cabia a 620 px de alto y sus campos quedaban con ancho 1.
        right_outer = tk.Frame(body, bg=PANEL2)
        right_outer.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.canvas = tk.Canvas(right_outer, bg=PANEL2, highlightthickness=0, bd=0)
        # El tk.Scrollbar nativo ignora los colores en Windows. ttk con tema
        # clam si los respeta, y el cambio de tema solo afecta a widgets ttk.
        from tkinter import ttk
        estilo = ttk.Style(self.root)
        try:
            estilo.theme_use("clam")
        except Exception:
            pass
        estilo.layout("Cofre.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {
                "sticky": "ns",
                "children": [("Vertical.Scrollbar.thumb",
                              {"expand": 1, "sticky": "nswe"})]})])
        estilo.configure("Cofre.Vertical.TScrollbar",
                         troughcolor=PANEL2, background=LINE,
                         bordercolor=PANEL2, lightcolor=LINE, darkcolor=LINE,
                         gripcount=0, width=SIZES["scrollbar"])
        estilo.map("Cofre.Vertical.TScrollbar",
                   background=[("active", LINE2)])
        self.vbar = ttk.Scrollbar(right_outer, orient="vertical",
                                  style="Cofre.Vertical.TScrollbar",
                                  command=self.canvas.yview)
        self.vbar_visible = True
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        right = tk.Frame(self.canvas, bg=PANEL2)
        self.right = right
        self._right_win = self.canvas.create_window((0, 0), window=right, anchor="nw")

        def _sync_scroll(_e=None):
            caja = self.canvas.bbox("all")
            self.canvas.configure(scrollregion=caja)
            self.canvas.itemconfigure(self._right_win, width=self.canvas.winfo_width())
            # la barra solo se ve si el contenido no cabe
            cabe = bool(caja) and (caja[3] - caja[1]) <= self.canvas.winfo_height() + 1
            if cabe and self.vbar_visible:
                self.vbar.pack_forget()
                self.vbar_visible = False
            elif not cabe and not self.vbar_visible:
                self.vbar.pack(side="right", fill="y")
                self.vbar_visible = True

        right.bind("<Configure>", _sync_scroll)
        self.canvas.bind("<Configure>", _sync_scroll)

        def _wheel(e):
            if self.canvas.bbox("all") is None:
                return
            first, last = self.canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self.canvas.bind_all("<MouseWheel>", _wheel)

        self.wizard = tk.Frame(right, bg=PANEL)
        tk.Label(self.wizard, text="Puesta en marcha", fg=FG, font=self.f_h2,
                 bg=PANEL).pack(anchor="w", padx=16, pady=(12, 4))
        self.wizard_msg = tk.StringVar(value="")
        tk.Label(self.wizard, textvariable=self.wizard_msg, fg=MUT, font=self.f_sub,
                 bg=PANEL).pack(anchor="w", padx=16, pady=(0, 8))
        # 6.8: el asistente sustituye los botones sueltos de la fase 1
        tk.Label(self.wizard,
                 text="Crea la llave del pendrive, el cofre y el código de "
                      "recuperación en cinco pasos.",
                 fg=MUT, font=self.f_small, bg=PANEL, anchor="w",
                 wraplength=300, justify="left").pack(fill="x", padx=16)
        wrow3 = tk.Frame(self.wizard, bg=PANEL)
        wrow3.pack(fill="x", padx=16, pady=(8, 8))
        self._btn(wrow3, "Abrir el asistente", self.open_first_use,
                  accent=True).pack(side="left", padx=4)

        self.detail_name = tk.Label(right, text="sin selección", fg=FG,
                                    font=self.f_h2, bg=PANEL2)
        self.detail_name.pack(anchor="w", padx=16, pady=(12, 4))
        self.meta_var = tk.StringVar(value="selecciona un secreto de la lista")
        self.meta_label = tk.Label(right, textvariable=self.meta_var, fg=MUT,
                                   font=self.f_sub, bg=PANEL2)
        self.meta_label.pack(anchor="w", padx=16, pady=(0, 8))

        # E5: chips de estado bajo el nombre
        self.chips_row = tk.Frame(right, bg=PANEL2)
        self.chips_row.pack(fill="x", padx=16, pady=(0, 6))

        self.tarjeta_valor = tk.Frame(right, bg=CAMPO)
        self.tarjeta_valor.pack(fill="x", padx=16, pady=(2, 8))
        self.valor_label = tk.Label(self.tarjeta_valor, text="VALOR", fg=FAINT,
                                    font=self.f_small, bg=CAMPO, anchor="w")
        self.valor_label.pack(fill="x", padx=16)
        campo_valor = tk.Frame(self.tarjeta_valor, bg=CAMPO)
        self.campo_valor = campo_valor
        campo_valor.pack(fill="x", padx=8, pady=(2, 8))
        self.value_box = tk.Text(campo_valor, height=1, bg=CAMPO, fg=FG,
                                 font=self.f_mono, relief="flat", borderwidth=0,
                                 highlightthickness=0, wrap="none", padx=10, pady=10)
        self.value_box.pack(side="left", fill="x", expand=True)
        self.value_box.insert("1.0", MASK)
        self.value_box.configure(fg=MUT)
        self._icon_btn(campo_valor, "", self.reveal, "ver").pack(side="right", padx=2)
        self._icon_btn(campo_valor, "", self.copy_to_clipboard, "copiar").pack(
            side="right", padx=2)

        # E5: sitios asignados (dominios donde se puede rellenar)
        tarjeta_sitios = tk.Frame(right, bg=CAMPO)
        self.tarjeta_sitios = tarjeta_sitios
        tarjeta_sitios.pack(fill="x", padx=16, pady=(0, 8))
        cab_sitios = tk.Frame(tarjeta_sitios, bg=CAMPO)
        self.cab_sitios = cab_sitios
        cab_sitios.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(cab_sitios, text="Sitios donde se puede rellenar", fg=FG,
                 font=self.f_sub, bg=PANEL2).pack(side="left")
        self._btn(cab_sitios, "Asignar sitio", self.assign_site).pack(side="right")
        self.sites_box = tk.Frame(tarjeta_sitios, bg=CAMPO)
        self.sites_box.pack(fill="x", padx=8, pady=(2, 8))

        # E5: usado en (consumidores) y ciclo de vida
        # E8: sitios y "usado en" en una fila de dos tarjetas
        fila_info = tk.Frame(right, bg=PANEL2)
        self.fila_info = fila_info
        fila_info.pack(fill="x", padx=16, pady=(0, 8))
        col_uso = tk.Frame(fila_info, bg=CAMPO)
        col_uso.pack(side="left", fill="both", expand=True, ipadx=8, ipady=6)
        tk.Label(col_uso, text="USADO EN", fg=FAINT, font=self.f_small,
                 bg=CAMPO, anchor="w").pack(fill="x")
        self.consumers_box = tk.Frame(col_uso, bg=CAMPO)
        self.consumers_box.pack(fill="x")
        col_vida = tk.Frame(fila_info, bg=CAMPO)
        col_vida.pack(side="left", fill="both", expand=True, padx=(8, 0),
                      ipadx=8, ipady=6)
        tk.Label(col_vida, text="CICLO DE VIDA", fg=FAINT, font=self.f_small,
                 bg=CAMPO, anchor="w").pack(fill="x")
        self.life_box = tk.Frame(col_vida, bg=CAMPO)
        self.life_box.pack(fill="x")

        # Dos filas, no una. Regla medida: con etiquetas largas, nueve botones
        # en una fila no caben ni a 980 px (los ultimos quedaban con ancho 1).
        # Fila 1: acciones sobre el valor. Fila 2: acciones sobre la entrada.
        # E7/E4: acciones como botones de TEXTO (sin caja), una sola fila.
        # Ver y copiar viven dentro del campo del valor; Ocultar sobra (el ojo
        # alterna) y Fijar se ha movido a Ajustes.
        self._ver_targets = set()
        self.action_btns = []
        acciones = tk.Frame(right, bg=PANEL2)
        acciones.pack(fill="x", padx=16, pady=(2, 6))
        for texto, comando in (("Editar", self.edit_selected),
                               ("Historial", self._show_history),
                               ("Comando exec", self.copy_exec_command)):
            b = self._text_btn(acciones, texto, comando)
            b.pack(side="left", padx=(0, 12))
            self.action_btns.append(b)
        self.del_btn = self._text_btn(acciones, "Mover a la papelera",
                                      self.delete_selected, danger=True)
        self.del_btn.pack(side="right")
        self.action_btns.append(self.del_btn)
        self.edit_btn = self.action_btns[0]
        self.rename_btn = None      # renombrar y copiar nombre viven en la hoja Editar
        self.sticky_btn = None
        self.show_val_btn = None
        self._ver_frame = None

        # (sin raya decorativa: separa el aire, no una linea)

        # E6: el alta vive en una hoja (cofre/entry_sheet.py). Aqui solo quedan
        # las variables de estado que usan otros sitios del código.
        self.name_var = tk.StringVar()
        self.val_var = tk.StringVar()
        self.pin_var = tk.StringVar()
        self.lang_var = tk.StringVar(value="es")
        self.words_var = tk.StringVar(value="5")
        self.tags_var = tk.StringVar(value="")

        self.pinrow = tk.Frame(right, bg=PANEL)
        tk.Label(self.pinrow, text="PIN del cofre", fg=MUT, font=self.f_sub,
                 bg=PANEL).pack(side="left")
        pin_entry = self._entry(self.pinrow, self.pin_var, show="*")
        pin_entry.configure(width=1)
        pin_entry.pack(side="left", fill="x", expand=True, padx=8)
        if self.gate == "usb-pin":
            self.pinrow.pack(fill="x", padx=16, pady=(4, 4))

        # E7: el registro de actividad ya no vive dentro del detalle; esta en
        # el boton Registro del pie y en la pantalla de registro.
        self.log_labels = []

        # E7: estado vacio del detalle. Sin selección no se muestran campos ni
        # botones grises: solo el mensaje y el boton Nuevo.
        # el estado vacio va sobre el lienzo, no dentro del contenido que se
        # desplaza: asi se centra en el hueco visible
        self.empty_detail = tk.Frame(self.canvas, bg=PANEL2)
        centro_vacio = tk.Frame(self.empty_detail, bg=PANEL2)
        centro_vacio.pack(expand=True)
        tk.Label(centro_vacio, text="", fg=FAINT, bg=PANEL2,
                 font=(ICON_FONT, 30)).pack()
        tk.Label(centro_vacio, text="Elige un secreto de la lista", fg=MUT,
                 bg=PANEL2, font=self.f_sub).pack(pady=(6, 10))
        self._btn(centro_vacio, "Nuevo secreto", self._focus_new,
                  accent=True).pack()
        self._detail_piezas = [self.detail_name, self.meta_label, self.chips_row,
                               self.tarjeta_valor, self.tarjeta_sitios, acciones,
                               self.fila_info]
        self._update_detail_visible()

        # ---------- pie ----------
        foot = tk.Frame(self.root, bg=PANEL)
        foot.pack(fill="x")
        tk.Frame(foot, bg=LINE, height=1).pack(fill="x")
        self.foot_var = tk.StringVar(value="listo")
        footrow = tk.Frame(foot, bg=PANEL)
        footrow.pack(fill="x", padx=16, pady=6)
        tk.Label(footrow, textvariable=self.foot_var, fg=MUT, font=self.f_small,
                 bg=PANEL, anchor="w", justify="left",
                 wraplength=640).pack(side="left", fill="x", expand=True)
        # el interruptor del navegador vive en Ajustes; en el pie solo avisos
        self.browser_btn = None
        # Guía, Registro y ajustes viven en la columna izquierda; en el pie solo
        # queda el interruptor del navegador y los avisos breves.

        # Con pythonw no hay consola: si un callback lanza, Tk imprime el
        # traceback en un stderr invisible y la ventana sigue como si nada.
        # Se captura y se muestra en el pie, que es donde el usuario mira.
        self.root.report_callback_exception = self._on_tk_error

        # H4: Escape no cierra la aplicacion. Cierra dialogs, desarma la
        # confirmación pendiente y, si no hay nada pendiente, bloquea el cofre.
        # Para cerrar la ventana: la X, Ctrl+Q o el menu del sistema.
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<Control-q>", lambda _e: self._on_close())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-l>", lambda _e: self.lock())
        self.root.bind("<Control-f>", lambda _e: self.query_entry.focus_set())
        self.root.bind("<Control-n>", lambda _e: self._focus_new())
        self.root.bind("<Control-k>", self.open_palette)
        self.root.bind("<Control-e>", self._on_edit_shortcut)
        self.root.bind("<Control-Shift-KeyPress-C>", self._on_copy_name_shortcut)
        self.root.bind("<Delete>", self._on_delete_shortcut)
        # H3: Ctrl+C solo copia el secreto cuando NO estas tecleando en un
        # campo. Si el foco esta en un Entry/Text, ese Ctrl+C es el normal.
        self.root.bind("<Control-c>", self._on_copy_shortcut)
        self.root.bind("<Return>", self._on_enter)
        self.root.bind("<Prior>", lambda _e: self.move_selection(-1))
        self.root.bind("<Next>", lambda _e: self.move_selection(1))
        self.root.bind("<F1>", lambda _e: self.open_shortcuts())
        from cofre.gui_confirm import ConfirmQueue
        self.confirm_queue = ConfirmQueue(self.root)
        self.root.after(200, self._pump_confirm)
        from cofre.lock_screen import LockScreen
        self.lock_screen = LockScreen(self.root, self)
        self.lock_screen.mostrar("abriendo el cofre...")

        self.refresh_wizard()
        self.unlock()
        self._key_cache = self._key_drives()
        self.root.after(2000, self._poll)

    # ---------- estado ----------

    def set_status(self, text, warn=False):
        self.status_var.set(text)
        self._draw_pill()
        try:
            if warn:
                self.pill.configure(bg=PANEL)
        except Exception:
            pass

    def refresh_log(self):
        from cofre.audit import tail_human
        entries = tail_human(self.vault_path, len(self.log_labels))
        for i, lab in enumerate(self.log_labels):
            lab.configure(text=entries[i] if i < len(entries) else "")

    def set_foot(self, text, ttl: int = 8000):
        """Aviso breve en el pie. Se borra solo, o al cambiar de estado."""
        self.foot_var.set(text)
        self.refresh_log()
        if getattr(self, "_foot_id", None):
            try:
                self.root.after_cancel(self._foot_id)
            except Exception:
                pass
            self._foot_id = None
        if ttl:
            self._foot_id = self.root.after(ttl, self._clear_foot)

    def _clear_foot(self) -> None:
        self._foot_id = None
        self.foot_var.set("")

    def stick_report(self) -> list[dict]:
        """Pendrives autorizados, con letra, rol y si estan conectados ahora."""
        reg = load_registry(self.vault_path)
        sticks = list(reg.get("sticks", {}).values())
        sticks.sort(key=lambda s: s.get("registered", ""))
        present = {}
        for drive in key_drives():
            serial = volume_serial(drive)
            if serial is not None:
                present[str(serial)] = drive
        # si la sesión se abrio con una ruta explicita (--stick), esa llave
        # cuenta como presente mientras el fichero exista. Sin esto, el
        # auto-bloqueo por pendrive retirado dispara con llaves fuera de un
        # volumen con COFRE.KEY (pruebas, sobres de recuperacion).
        if getattr(self, "stick", None):
            try:
                from pathlib import Path as _P
                llave = _P(self.stick)
                if llave.is_file():
                    serial = volume_serial(str(llave.resolve())[:3])
                    if serial is not None:
                        present.setdefault(str(serial), str(llave.resolve())[:3])
            except Exception:
                pass
        out = []
        for i, s in enumerate(sticks):
            serial = str(s.get("serial"))
            drive = s.get("drive") or present.get(serial, "?")
            out.append({
                "serial": serial,
                "drive": drive,
                "label": s.get("label") or "",
                "role": s.get("role") or ("principal" if i == 0 else "reserva"),
                "connected": serial in present,
                "present": serial in present,
            })
        return out

    def refresh_sticks(self) -> None:
        """Los pendrives ya no se listan en la columna: se ven en su hoja."""
        self._stick_text = " | ".join(
            f"{d['drive']} ({d['role']}){' conectada' if d.get('present') else ''}"
            for d in self.stick_report())

    def _bind_material(self) -> None:
        """v2 necesita la llave del pendrive, no solo la sesión derivada."""
        if self.vault.is_v2():
            self.vault.bind_material(
                material_for(self.gate, str(self.vault_path), self.stick, self.allow_new))

    def unlock(self, event=None):
        # En usb-pin la GUI siempre pasa su propio PIN (aunque este vacio),
        # para no quedarse esperando una lectura de terminal.
        pin = self.pin_var.get() if self.gate == "usb-pin" else ""
        try:
            self.session, self.serial = resolve_session_key(
                self.gate, self.vault_path, stick=self.stick, allow_new=self.allow_new,
                pin=pin)
        except (GateUnavailable, EOFError) as exc:
            self.session = None
            self._pill_texto = "Cerrado"
            self.set_status("Cerrado", warn=True)
            self.set_foot("conecta un pendrive del cofre y pulsa Reconectar", ttl=0)
            record(self.vault_path, "gui-gate", self.gate, None, ok=False, detail=str(exc))
            self.refresh_sticks()
            self.refresh_wizard()
            self.refresh_list()
            if getattr(self, "lock_screen", None):
                self.lock_screen.mostrar(str(exc) or "no se encuentra la llave")
            return False

        self._bind_material()

        if not self.vault.is_v2() and not self.vault.load().get("wrapper"):
            self.needs_init = True
            self.set_status("hay llave, pero el cofre no esta inicializado", warn=True)
            self.set_foot("cofre no inicializado: usa 'Inicializar cofre' en el "
                          "panel de Puesta en marcha")
            self.refresh_sticks()
            self.refresh_wizard()
            self.refresh_list()
            return False

        # 2.1: sesión con inactividad y tiempo maximo
        from cofre.session import Session
        self.session_obj = Session(self._session_settings())

        # 3.1: con la clave en memoria, el log va firmado; y al abrir se
        # comprueba que nadie lo ha tocado
        try:
            audit_set_key(self.vault.unlock(self.session))
            try:
                if self.vault.is_v2():
                    from cofre.audit import bind_store
                    bind_store(self.vault._v2store())
            except Exception:
                pass
            from cofre.audit import auto_seal, verify_vault
            try:
                if self.vault.is_v2():
                    store = self.vault._v2store()
                    if store.master is not None:
                        auto_seal(store, store.master)
            except Exception:
                pass
            _ok, _det = verify_vault(self.vault)
            if not _ok:
                self.set_foot(f"AVISO: el registro de accesos no cuadra: {_det}")
                record(self.vault_path, "audit-verify", self.gate, self.serial,
                       ok=False, detail=_det[:150])
        except Exception:
            audit_clear_key()

        used = next((s for s in self.stick_report()
                     if s["serial"] == str(self.serial)), None)
        which = f"{used['drive']} ({used['role']})" if used else str(self.serial)
        n = len(self.vault.names())
        if getattr(self, "lock_screen", None):
            self.lock_screen.ocultar()
        if getattr(self, "stick", None):
            # llave suelta: se avisa, porque el auto-bloqueo por pendrive no
            # puede funcionar con un fichero que no esta en un volumen
            self._pill_texto = "Abierto · llave de prueba"
            self.set_status(self._pill_texto, warn=True)
            try:
                record(self.vault_path, "gate-explicit", self.gate, self.serial,
                       ok=True, detail="stick-explicito")
            except Exception:
                pass
        else:
            self._pill_texto = f"Abierto · llave {which.split(' ')[0]}"
            self._actualizar_pildora_tiempo()
            self.set_foot("listo", ttl=0)
        self.refresh_sticks()
        self.refresh_wizard()
        self.refresh_list()
        self._escribir_calendario()
        if getattr(self, "_bridge_on_start", False) and not self.bridge:
            try:
                self.start_bridge()
            except Exception:
                pass
        return True

    def _escribir_calendario(self) -> None:
        """5.8: resumen sin nombres para la tarea programada de Windows."""
        try:
            if not self.vault.is_v2():
                return
            store = self.vault._v2store()
            if store.master is None:
                return
            from cofre import schedule
            schedule.escribir(store)
        except Exception:
            pass

    def lock(self, event=None, motivo: str | None = None, detalle: str = "",
             sin_evento: bool = False):
        """Bloquear: se tira la clave de sesión de la RAM. Hace falta el
        pendrive otra vez para abrir."""
        try:
            from cofre.audit import stamp_vault
            stamp_vault(self.vault)
        except Exception:
            pass
        # los permisos de 5 minutos (2.4) no sobreviven al bloqueo, por el
        # motivo que sea: a mano, por inactividad o por suspension
        self.confirm_grants.clear()
        # el evento se firma ANTES de tirar la clave: un 'lock' sin firma no
        # existe si el cofre estaba abierto. Y si no habia sesión no se escribe
        # nada: bloquear un cofre ya cerrado no es un evento.
        if self.session and not sin_evento:
            record(self.vault_path, "lock", self.gate, self.serial, ok=True,
                   detail=detalle or "manual")
        # el calendario se escribe antes de soltar la llave
        self._escribir_calendario()
        audit_clear_key()
        self.session = None
        self.serial = None
        self.selected = None
        self.stop_bridge()
        if self.gate == "usb-pin":
            self.pin_var.set("")
        self.hide()
        self.detail_name.configure(text="sin selección")
        self.meta_var.set("cofre bloqueado")
        self.selected = None
        self.refresh_list()
        self.refresh_wizard()
        self._update_detail_visible()
        self._pill_texto = "Cerrado"
        self.set_status("Cerrado", warn=True)
        self._clear_foot()
        if getattr(self, "lock_screen", None):
            texto = motivo or "la llave ya no esta en memoria. Conecta un pendrive "
            self.lock_screen.mostrar(texto)

    def refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not self.session:
            self.count_var.set("gate cerrado")
            self._names = []
            self._refresh_actions()
            return
        q = self.query_var.get().strip().lower()
        if q and q == str(getattr(self, "_placeholder_text", "")).lower():
            q = ""
        tags = []
        if q.startswith("tag:"):
            tags = [t for t in q[4:].split(",") if t]
            q = ""
        names = []
        for n in self.vault.names():
            meta = self.vault.meta(n) or {}
            if not self._pasa_filtro(n, meta):
                continue
            if q and q not in n.lower():
                continue
            if tags:
                entry_tags = [t.lower() for t in self.vault.meta(n).get("tags", [])]
                if not all(t in entry_tags for t in tags):
                    continue
            names.append(n)
        self._names = names
        if self.selected not in names:
            self.selected = None
            self.detail_name.configure(text="sin selección")
            self.meta_var.set("selecciona un secreto de la lista")
        self._refresh_actions()
        self._update_detail_visible()
        self._refresh_nav_counts()
        self.count_var.set(f"{len(names)} entrada(s)")
        if not names:
            empty = tk.Frame(self.list_frame, bg=PANEL)
            empty.pack(fill="x", pady=LG)
            texto_vacio = ("Todavía no hay secretos" if not self.vault.names()
                           else "Ninguno coincide con la búsqueda")
            if self.filtro == "papelera":
                texto_vacio = "La papelera esta vacia (todavía no existe)"
            elif self.filtro not in ("todos",) and self.vault.names():
                texto_vacio = "Nada en este filtro"
            tk.Label(empty, text=texto_vacio,
                     fg=MUT, font=self.f_sub, bg=PANEL, anchor="w").pack(fill="x")
            tk.Label(empty, text="El nombre es como lo llamaras luego: TAVILY_API_KEY, "
                                 "GMAIL_PASSWORD...",
                     fg=FAINT, font=self.f_small, bg=PANEL, anchor="w",
                     wraplength=250, justify="left").pack(fill="x", pady=(XS, SM))
            if not self.vault.names():
                self._btn(empty, "Guardar el primero", self._focus_new,
                          accent=True).pack(anchor="w")
            return
        self._rows = {}
        for n in names:
            meta = self.vault.meta(n) or {}
            proveedor = str(meta.get("provider") or "") or self._proveedor_por_nombre(n)
            try:
                sitio = (self.vault.urls(n) or [""])[0]
            except Exception:
                sitio = ""
            sub = " · ".join(p for p in (proveedor or self._kind_of(n), sitio) if p)
            chip = self._chip_de(n, meta)
            fila = tk.Frame(self.list_frame, bg=PANEL)
            fila.pack(fill="x", pady=1)
            L = None
            try:
                from cofre import widgets as W
                L = W.ListRow(fila, n, sub, inicial=(proveedor or n)[:1].upper(),
                              chip=chip, on_click=lambda _t, name=n: self._click_row(name),
                              bg=PANEL, color=W.color_de_proveedor(proveedor or n),
                              on_move=self._mover_lista)
            except Exception:
                L = None
            if L is None:
                lab = tk.Label(fila, text=n, fg=FG, font=self.f_body, bg=PANEL,
                               anchor="w")
                lab.pack(fill="x", padx=SM, pady=SM)
                lab.bind("<Button-1>", lambda _e, name=n: self._click_row(name))
            else:
                L.pack(fill="x")
                self._rows[n] = L
                if n == self.selected:
                    L.set_seleccionada(True)

    def _mover_lista(self, delta: int) -> None:
        """Flechas dentro de una fila: cambia de secreto y mantiene el foco."""
        self.move_selection(delta)
        fila = getattr(self, "_rows", {}).get(self.selected)
        if fila is not None:
            try:
                fila.canvas.focus_set()
            except Exception:
                pass

    def _enfocar_lista(self, event=None):
        """Flecha abajo en el buscador: primer resultado con el foco."""
        nombres = getattr(self, "_names", [])
        if not nombres:
            return "break"
        if self.selected not in nombres:
            self.select(nombres[0])
        fila = getattr(self, "_rows", {}).get(self.selected)
        if fila is not None:
            try:
                fila.canvas.focus_set()
            except Exception:
                pass
        return "break"

    def _click_row(self, name: str) -> None:
        """Seleccionar con el raton y dejar el foco donde Ctrl+C si copia."""
        self.select(name)
        try:
            self.list_frame.focus_set()
        except Exception:
            pass

    def _refresh_nav_counts(self) -> None:
        """Contadores de la navegacion: cuantos secretos caen en cada vista."""
        try:
            todos = self.vault.names()
        except Exception:
            return
        metas = {n: (self.vault.meta(n) or {}) for n in todos}
        cuentas = {
            "todos": len(todos),
            "password": sum(1 for m in metas.values() if m.get("type") == "password"),
            "api": sum(1 for m in metas.values()
                       if m.get("type") in ("api_key", "api_token", "oauth_app", "private_key")),
            "note": sum(1 for m in metas.values() if m.get("type") == "note"),
            "atencion": sum(1 for n, m in metas.items() if self._necesita_atencion(n, m)),
            "rotación": sum(1 for m in metas.values() if self._rotacion_pendiente(m)),
            "caducan": sum(1 for m in metas.values() if self._caduca_pronto(m)),
            "papelera": 0,
        }
        for clave, etiqueta in getattr(self, "nav_counts", {}).items():
            valor = cuentas.get(clave, 0)
            etiqueta.configure(text=str(valor) if valor else "",
                               fg=WARN if (clave == "atencion" and valor) else FAINT)

    def _proveedor_por_nombre(self, nombre: str) -> str:
        """SOLO para el color del cuadro y el subtitulo de la fila.

        No se usa (ni se debe usar) para politicas, rotacion ni despliegues:
        eso mira `meta["provider"]`, que es lo que el usuario declaro. Deducir
        el proveedor del nombre es una comodidad visual, no un dato.
        """
        prefijos = {"CF_": "cloudflare", "CLOUDFLARE": "cloudflare",
                    "GH_": "github", "GITHUB": "github",
                    "GOOGLE": "google", "GCP_": "google",
                    "AWS_": "aws", "AZURE": "azure", "OPENAI": "openai"}
        arriba = nombre.upper()
        for prefijo, proveedor in prefijos.items():
            if arriba.startswith(prefijo):
                return proveedor
        return ""

    def _chip_de(self, nombre: str, meta: dict) -> tuple[str, str] | None:
        """Solo etiquetas que piden atencion: si esta sano, sin etiqueta."""
        caduca = str(meta.get("expires_at") or "")
        if caduca:
            try:
                from datetime import date
                dias = (date.fromisoformat(caduca[:10]) - date.today()).days
                if dias <= 30:
                    return (f"caduca en {max(dias, 0)} d", "rot")
            except Exception:
                pass
        if self._rotacion_pendiente(meta):
            return ("rotar", "rot")
        try:
            if not self.vault.urls(nombre) and str(meta.get("type")) != "note":
                return ("sin sitio", "warn")
        except Exception:
            pass
        return None

    def _kind_of(self, name: str) -> str:
        """Etiqueta corta a la derecha de la fila, sin llamar al cifrado."""
        tags = self.vault.meta(name).get("tags", [])
        if tags:
            return tags[0]
        low = name.lower()
        if any(k in low for k in ("api", "key", "token", "secret", "hec")):
            return "clave"
        if any(k in low for k in ("pass", "pwd", "contras")):
            return "contraseña"
        return ""

    def _focus_new(self, event=None):
        """Abrir la hoja de alta (E6)."""
        if not self.session:
            self.set_foot("abre el cofre antes de guardar un secreto")
            return
        from cofre.entry_sheet import EntrySheet
        self._sheet_nueva = EntrySheet(self, mode="new")
        self.canvas.yview_moveto(1.0)
        self.set_foot("escribe el nombre (p. ej. TAVILY_API_KEY), el valor, y pulsa Guardar")

    # ---------- errores ----------

    def _on_tk_error(self, exc_type, exc_value, tb) -> None:
        """Un fallo en un callback no puede quedarse mudo."""
        import traceback
        text = traceback.format_exception(exc_type, exc_value, tb)
        sys.stderr.write("".join(text))
        try:
            self.set_foot(f"error interno: {exc_type.__name__}: {exc_value}. "
                          "Usa el acceso COFRE (diagnostico) para ver el detalle.")
        except Exception:
            pass
        try:
            record(self.vault_path, "gui-error", self.gate, self.serial, ok=False,
                   detail=f"{exc_type.__name__}: {exc_value}"[:120])
        except Exception:
            pass

    # ---------- puente para el navegador ----------


    def toggle_browser(self) -> None:
        if self.bridge:
            self.stop_bridge()
            self.set_foot("puente del navegador cerrado")
        else:
            self.start_bridge()

    def start_bridge(self) -> None:
        """Puente del navegador. Por defecto, tuberia con nombre (paso 4.0).

        La via TCP queda detras de COFRE_BRIDGE=tcp hasta que la tabla 4.0.e
        lleve unos días sin fallos.
        """
        import os

        if not self.session:
            self.set_foot("abre el cofre con el pendrive antes de activar el navegador")
            return

        if os.environ.get("COFRE_BRIDGE", "pipe").lower() == "tcp":
            from cofre.serve import SecretServer, allowed_origins_for

            origins = allowed_origins_for()
            if not origins:
                self.set_foot("el navegador necesita la extension: ejecuta "
                              "tools/install_extension.py una vez")
                return
            try:
                self.bridge = SecretServer(self.vault_path, origins, gate=self.gate,
                                           stick=self.stick).start()
            except OSError as exc:
                self.set_foot(f"no se pudo abrir el puerto 47653: {exc}")
                self.bridge = None
                return
            self.browser_on = True
            self.set_foot("navegador conectado por TCP (respaldo)")
            record(self.vault_path, "bridge-start", self.gate, self.serial, ok=True)
            self.set_foot(f"navegador conectado en {self.bridge.origin} "
                          "(solo mientras el cofre este abierto)")
            return

        from cofre import bridge_ops
        from cofre.pipe_server import BridgeController
        from cofre.serve import allowed_origins_for

        if not allowed_origins_for():
            self.set_foot("el navegador necesita la extension: ejecuta "
                          "tools/install_extension.py una vez")
            return
        if self.bridge_ctl is None:
            self.bridge_ctl = BridgeController(
                self.root,
                lambda msg: bridge_ops.dispatch(self, msg),
                log=lambda m: self.set_foot(f"puente: {m}"))
        try:
            self.bridge_ctl.start()
        except Exception as exc:                      # noqa: BLE001
            self.set_foot(f"no se pudo crear la tuberia: {exc}")
            self.bridge_ctl = None
            return
        self.browser_on = True
        self.set_foot("navegador conectado por tubería local")
        record(self.vault_path, "bridge-start", self.gate, self.serial, ok=True)
        self.set_foot("navegador conectado por tuberia local "
                      "(solo mientras el cofre este abierto)")
        self._pump_bridge()

    def _pump_bridge(self) -> None:
        """Atiende las peticiones del navegador en el hilo de Tkinter."""
        if not self.bridge_ctl:
            return
        try:
            self.bridge_ctl.poll()
        except Exception:
            pass
        self.root.after(60, self._pump_bridge)

    def stop_bridge(self) -> None:
        if self.bridge:
            try:
                self.bridge.stop()
            except Exception:
                pass
            self.bridge = None
        if getattr(self, "bridge_ctl", None):
            try:
                self.bridge_ctl.stop()
            except Exception:
                pass
            self.bridge_ctl = None
        self.browser_on = False
        self.set_foot("navegador desconectado")

    def _current_salt(self) -> bytes | None:
        """La sal del cofre, para guardarla dentro de cofre.json (H9)."""
        try:
            from cofre.salt import get_salt
            return get_salt(self.vault_path, create=not Path(self.vault_path).exists())
        except Exception:
            return None

    def _on_escape(self, event=None) -> None:
        """Escape: desarma confirmaciones, bloquea; nunca cierra la ventana."""
        if getattr(self, "_confirm_delete", False) or getattr(self, "_confirm_revoke", None):
            self._cancel_delete()
            self._confirm_revoke = None
            self.set_foot("confirmación cancelada")
            return
        if getattr(self, "help_box", None) is not None and self.help_box.winfo_ismapped():
            self.toggle_help()
            return
        # R7 (2026-11-16): Escape no bloquea nunca. Bloquear es Ctrl+L y solo
        # Ctrl+L; un Escape que cambia de efecto segun el momento es impredecible.
        self.set_foot("Escape no bloquea ni cierra. Bloquear: Ctrl+L. Salir: Ctrl+Q")

    def _on_enter(self, event=None) -> None:
        """Enter copia el secreto seleccionado (plan 6.4). No hace nada si el
        foco esta en un campo de texto: ahi Enter es del formulario."""
        focused = None
        try:
            focused = self.root.focus_get()
        except Exception:
            focused = None
        if focused is not None and focused.winfo_class() in ("Entry", "Text", "TEntry", "TText"):
            return
        if self.selected and self.session:
            self.copy_to_clipboard()

    def _on_copy_shortcut(self, event=None) -> None:
        focused = None
        try:
            focused = self.root.focus_get()
        except Exception:
            focused = None
        if focused is None:
            # Sin foco conocido no se sabe qué quería copiar la persona.
            # La copia de un secreto es la acción peligrosa: no la hacemos.
            self.set_foot("Ctrl+C no copia: pulsa primero sobre un secreto de la lista")
            return
        if focused.winfo_class() in ("Entry", "Text", "TEntry", "TText"):
            self.set_foot("Ctrl+C no copia el secreto mientras tecleas en un campo")
            return
        self.copy_to_clipboard()

    def _on_close(self) -> None:
        # cerrar la ventana es otro camino de bloqueo: se firma antes de soltar
        # la clave, igual que el resto
        if self.session:
            try:
                self.lock(motivo="se cerro la ventana", detalle="cerrar ventana")
            except Exception:
                pass
        self.stop_bridge()
        self.root.destroy()

    def _key_drives(self) -> set[str]:
        # usb.key_drives acota cada volumen con un plazo: un pendrive a medio
        # quitar bloquea is_file() para siempre y deja la ventana en blanco
        # (paso el 2026-11-16 con E:).
        return set(key_drives())

    def state(self) -> str:
        if self.session and (self.vault.is_v2() or self.vault.load().get("wrapper")):
            return "empty" if not self.vault.names() else "open"
        if not self._key_drives() and not self.stick:
            return "no-key"
        if not self.vault.is_v2() and not self.vault.load().get("wrapper"):
            return "key-no-vault"
        return "closed"

    def refresh_wizard(self) -> None:
        st = self.state()
        drives = sorted(self._key_drives())
        if st == "no-key":
            self.wizard_msg.set(
                "No hay COFRE.KEY en ningún volumen. Conecta el pendrive y "
                "pulsa 'Crear llave' (se escriben 32 bytes aleatorios en el USB).")
            if self.detail_name.winfo_manager():
                self.wizard.pack(fill="x", padx=16, pady=(12, 4),
                                 before=self.detail_name)
            else:
                self.wizard.pack(fill="x", padx=16, pady=(12, 4))
        elif st == "key-no-vault":
            self.wizard_msg.set(
                f"Hay una llave en {', '.join(drives)} pero no hay cofre. "
                "Abre el asistente para crear el cofre y el código.")
            if self.detail_name.winfo_manager():
                self.wizard.pack(fill="x", padx=16, pady=(12, 4),
                                 before=self.detail_name)
            else:
                self.wizard.pack(fill="x", padx=16, pady=(12, 4))
        else:
            self.wizard.pack_forget()

    def wizard_create_key(self, event=None):
        drive = self.dest_var.get().strip().rstrip("\\") + "\\"
        try:
            path = create_key_on(drive + KEY_FILENAME)
            serial = volume_serial(drive)
            register_stick(self.vault_path, serial, drive)
            record(self.vault_path, "stick-init", self.gate, serial, ok=True)
            self.set_foot(f"llave de 32 bytes creada en {path} (serial {serial})")
        except Exception as exc:
            self.set_foot(f"no se pudo crear la llave: {exc}")
            return
        self.unlock()
        return True

    def wizard_init(self, event=None):
        if not self.session:
            if not self.unlock():
                return False
        try:
            self.vault.init(self.session, salt=self._current_salt())
            record(self.vault_path, "init", self.gate, self.serial, ok=True)
            self.set_foot("cofre inicializado. Ahora pulsa Guardar para guardar "
                          "tu primer secreto.")
        except Exception as exc:
            self.set_foot(f"no se pudo inicializar: {exc}")
            return False
        self.needs_init = False
        self.unlock()
        self.refresh_wizard()
        return True

    def wizard_backup(self, event=None):
        drive = self.dest_var.get().strip().rstrip("\\") + "\\"
        target = Path(drive) / KEY_FILENAME
        if not Path(drive).exists():
            self.set_foot(f"la unidad {drive} no esta conectada. Enchufa el "
                         "pendrive y pulsa de nuevo.")
            return False
        try:
            src, _src_serial = find_stick(None, self.vault_path, False)
        except Exception as exc:
            self.set_foot(f"no hay llave que copiar: {exc}")
            return False
        if Path(src).resolve() == target.resolve():
            self.set_foot("la unidad destino es la misma que tiene la llave: "
                         "elige otro pendrive")
            return False
        if target.is_file():
            self.set_foot(f"{target} ya contiene una llave. No se sobrescribe: eso "
                         "dejaria el cofre inaccesible si esa llave es otra.")
            return False
        try:
            copy_key_to(str(target), read_key(src))
            serial = volume_serial(drive)
            register_stick(self.vault_path, serial, drive, role="reserva")
            record(self.vault_path, "stick-copy", self.gate, serial, ok=True)
            self.set_foot(f"llave copiada de {src} a {drive}{KEY_FILENAME}. Dos "
                         "copias de la misma llave: es el precio del respaldo.")
        except Exception as exc:
            self.set_foot(f"no se pudo copiar la llave: {exc}")
            return False
        self.refresh_sticks()
        return True

    def _session_settings(self) -> dict:
        try:
            idx = self.vault._v2store()._vault.index(self.vault._v2store()._data,
                                                     self.vault._v2store().master)                 if self.vault.is_v2() and self.vault._v2store().master else {}
            base = dict(idx.get("settings", {}))
            from cofre import settings as _settings
            cfg = _settings.load(self.vault_path)
            base["idle_minutes"] = int(cfg["idle_minutes"])
            base["max_hours"] = int(cfg["max_hours"])
            return base
        except Exception:
            return {}

    def request_confirm(self, who: str, what: str) -> str:
        """Pregunta a la persona (2.4). Se llama desde el hilo del puente."""
        if not self.confirm_queue:
            return "deny"
        clave = (self.selected or what, who.split(" - ")[0])
        hasta = self.confirm_grants.get(clave)
        if hasta and hasta > __import__("time").time():
            return "grant"
        resultado = self.confirm_queue.ask(who, what)
        if resultado == "grant":
            self.confirm_grants[clave] = __import__("time").time() + 300
        return resultado

    def _pump_confirm(self) -> None:
        if not self.confirm_queue:
            return
        try:
            if self.confirm_queue.poll():
                self.root.after(10, self._pump_confirm)
                return
        except Exception:
            pass
        self.root.after(200, self._pump_confirm)

    def _check_rotation(self) -> None:
        """Si hay una rotación interrumpida, avisar en la banda (no ejecutar)."""
        try:
            from cofre import rotation as rot
            if not self.vault.is_v2():
                return
            store = self.vault._v2store()
            if store.master is None:
                return
            plan = rot.plan_resume(store, store.master)
        except Exception:
            return
        if not plan:
            return
        texto = (f"rotación interrumpida de '{plan['nombre']}' "
                 f"(fase {plan['fase']}); lo recomendado es {plan['recomendada']}")
        if plan.get("aviso"):
            texto = plan["aviso"] + ". " + texto
        if getattr(self, "_rotation_avisada", None) != plan["fase"] + texto:
            self._rotation_avisada = plan["fase"] + texto
            self.show_alerts([texto])
            record(self.vault_path, "alert", self.gate, self.serial,
                   name="rotación-interrumpida", ok=False, detail=texto[:150])

    def _comprobar_salud(self) -> None:
        """5.9: preguntar a los proveedores en un hilo, sin bloquear Tkinter."""
        if not self.session:
            self.set_foot("el cofre esta bloqueado")
            return
        if getattr(self, "_salud_busy", False):
            self.set_foot("ya hay una comprobación de salud en curso")
            return
        try:
            store = self.vault._v2store()
            master = store.master
        except Exception as exc:                   # noqa: BLE001
            self.set_foot(f"no se pudo abrir el cofre: {exc}")
            return
        if master is None:
            self.set_foot("el cofre esta bloqueado")
            return
        if getattr(self, "_salud_cola", None) is None:
            self._salud_cola = queue.Queue()
        self._salud_busy = True
        self.set_foot("comprobando credenciales con sus proveedores...")
        from cofre import health

        def trabajo():
            try:
                resultados = health.revisar(store, master)
                self._salud_cola.put((resultados, None))
            except Exception as exc:               # noqa: BLE001
                self._salud_cola.put((None, exc))

        threading.Thread(target=trabajo, daemon=True).start()

    def _recoger_salud(self) -> None:
        """Lo llama el sondeo: aplicar el resultado sin tocar Tk desde el hilo."""
        cola = getattr(self, "_salud_cola", None)
        if cola is None:
            return
        try:
            resultados, error = cola.get_nowait()
        except queue.Empty:
            return
        self._salud_terminada(resultados, error)

    def _salud_terminada(self, resultados, error) -> None:
        self._salud_busy = False
        if error is not None:
            self.set_foot(f"no se pudo comprobar la salud: {error}")
            return
        if not self.session:
            return
        try:
            from cofre import health
            store = self.vault._v2store()
            if store.master is None:
                return
            health.aplicar(store, store.master, resultados)
            cuenta = health.resumen(resultados)
            record(self.vault_path, "health", self.gate, self.serial, name="-",
                   ok=True,
                   detail=", ".join(f"{k}={v}" for k, v in cuenta.items())[:150])
            from cofre.audit import stamp_vault
            stamp_vault(self.vault)
        except Exception as exc:                   # noqa: BLE001
            self.set_foot(f"no se pudo guardar la salud: {exc}")
            return
        resumen = ", ".join(f"{health.ETIQUETAS.get(k, k)} {v}"
                            for k, v in cuenta.items()) or "sin credenciales"
        self.set_foot("salud comprobada: " + resumen)
        if getattr(self, "vista", "") == "salud":
            self._mostrar_vista("salud")
        elif self.selected:
            self.refresh_detail()

    def _check_alerts(self) -> None:
        """3.2: evaluar solo lo nuevo, registrar cada alerta y avisar."""
        try:
            from cofre import alerts as alerts_mod
            if self.alert_state is None:
                self.alert_state = alerts_mod.AlertState()
            eventos = alerts_mod.events_of(self.vault_path)
            cfg = alerts_mod.load_settings(self.vault_path)
            nuevas = alerts_mod.evaluate(eventos, cfg, self.alert_state)
            try:
                # credenciales viejas sin revocar: salen del indice, no de un
                # evento, y solo avisan a partir de los 7 dias
                if self.vault.is_v2():
                    store = self.vault._v2store()
                    if store.master is not None:
                        nuevas.extend(
                            alerts_mod.evaluate_unrevoked(store, eventos))
            except Exception:
                pass
            nuevas = alerts_mod.apply_cooldown(nuevas, self.alert_state, cfg)
            if not nuevas:
                return
            for a in nuevas:
                record(self.vault_path, "alert", self.gate, self.serial,
                       name=a.rule, ok=False, detail=f"{a.severity}: {a.text}"[:150])
            self.show_alerts([f"{a.severity.upper()}: {a.text}" for a in nuevas])
            alerts_mod.notify(nuevas)      # MessageBoxW en su propio hilo
            try:
                from cofre.audit import stamp_vault
                stamp_vault(self.vault)
            except Exception:
                pass
        except Exception:
            pass

    def _check_session(self) -> None:
        """2.1: bloquear si la sesión caduca."""
        if not self.session or not self.session_obj:
            return
        motivo = self.session_obj.check()
        if motivo:
            texto = self.session_obj.describe(motivo)
            self.session_obj = None
            self.lock(motivo=texto, detalle=motivo)
            self.set_foot(texto)

    def _poll(self) -> None:
        self._recoger_salud()
        self._check_session()
        self._check_alerts()
        self._check_rotation()
        if getattr(self, "lock_screen", None) and not self.session:
            try:
                self.lock_screen.refrescar()
            except Exception:
                pass
        drives = self._key_drives()
        if drives != self._key_cache:
            self._key_cache = drives
            self.refresh_sticks()
            self.refresh_wizard()
            if not self.session and drives:
                if any(s["connected"] for s in self.stick_report()):
                    if self.gate == "usb-pin":
                        # B (2026-11-10): con PIN, enchufar no abre. Se exige
                        # teclear el PIN y pulsar Reconectar.
                        self.set_status("pendrive detectado  |  escribe el PIN y pulsa "
                                        "Reconectar", warn=False)
                        self.set_foot("pendrive detectado. Por usar gate usb-pin, el "
                                      "cofre no se abre solo: escribe el PIN y pulsa "
                                      "Reconectar.")
                    else:
                        self.unlock()
        # Auto-bloqueo: si desaparece el pendrive que abrio la sesión, la llave
        # no debe seguir viva en RAM. Reabrir es un click con el otro pendrive.
        if self.session and self.serial is not None:
            used = next((s for s in self.stick_report()
                         if s["serial"] == str(self.serial)), None)
            if used is not None and not used["connected"]:
                label = f"{used['drive']} ({used['role']})"
                self.lock(motivo=f"se quito el pendrive {label}",
                          detalle="pendrive retirado")
                self.set_status(f"bloqueado: se quito el pendrive {label}", warn=True)
                self.set_foot(f"se retiro el pendrive {label}: el cofre se ha bloqueado "
                              "solo. Conecta cualquier pendrive del cofre y pulsa Reconectar.")
        self.root.after(2000, self._poll)

    def move_selection(self, delta: int) -> None:
        names = getattr(self, "_names", [])
        if not names:
            return
        try:
            i = names.index(self.selected) if self.selected in names else 0
        except ValueError:
            i = 0
        self.select(names[(i + delta) % len(names)])

    # ---------- guía de uso ----------

    GUIDE_TITLE = "Como se usa el cofre, paso a paso"

    GUIDE = [
        ("1. Conecta el pendrive", [
            "Enchufa cualquiera de los dos: E: (principal) o F: (reserva).",
            "Solo hace falta uno. No los dos.",
            "El pendrive es la llave: sin el, el cofre no se abre.",
        ]),
        ("2. Abre el cofre", [
            "Doble click en el icono COFRE del escritorio.",
            "Arriba a la derecha tiene que poner 'abierto' con el punto verde.",
            "Si pone 'cerrado', enchufa el pendrive y pulsa Reconectar.",
        ]),
        ("3. Guardar una clave", [
            "Nombre: como la vas a llamar. Sin espacios. Ej: TAVILY_API_KEY",
            "Valor: la clave tal cual. Puedes pegarla o generarla con un boton.",
            "Tags: opcional, para agrupar. Ej: google, trabajo",
            "Pulsa Guardar. Aparece en la lista de la izquierda.",
        ]),
        ("4. Usarla en una web", [
            "Selecciona el secreto en la lista.",
            "Pulsa 'Copiar valor' y pega en la web (Ctrl+V).",
            "El portapapeles se vacia solo en 30 segundos.",
            "Para verla en pantalla: boton Ver (se oculta a los 15 s).",
        ]),
        ("5. Usarla en un programa", [
            "Pulsa 'Comando exec' y pega en la terminal.",
            "Queda así: run.cmd exec --name TAVILY_API_KEY -- python script.py",
            "La clave va dentro de ese proceso, no a ningún fichero.",
            "Cuando el proceso termina, la clave desaparece con el.",
        ]),
        ("6. Terminar", [
            "Pulsa Bloquear: la llave se borra de la memoria.",
            "O quita el pendrive: el cofre se bloquea solo.",
            "Cerrar la ventana tambien bloquea.",
        ]),
        ("Si algo va mal", [
            "'cerrado': el pendrive no esta puesto o no es de este cofre.",
            "'cofre no inicializado': falta crearlo (panel Puesta en marcha).",
            "'serial no registrado': ese pendrive no es de este cofre.",
            "'la clave no corresponde': pendrive de otro cofre o PIN mal.",
            "Si no abre y no dice nada: usa el acceso COFRE (diagnostico).",
        ]),
    ]

    # ---------- pantallas de la columna izquierda (E7) ----------

    def show_alerts(self, textos: list[str]) -> None:
        """Banda bajo la cabecera con la alerta y dos acciones."""
        self._alerts_visibles = list(textos)
        if not textos:
            self.alert_band.pack_forget()
            return
        self.alert_text.configure(text=textos[0][:150])
        # la banda va justo debajo de la cabecera: se empaqueta antes del cuerpo
        try:
            self.alert_band.pack(fill="x", before=self.body)
        except Exception:
            self.alert_band.pack(fill="x")

    def dismiss_alerts(self) -> None:
        self._alerts_visibles = []
        self.alert_band.pack_forget()

    def set_filtro(self, clave: str) -> None:
        """Vista activa con fondo `raised` y texto normal: el laton es solo para
        la accion principal de la pantalla (Nuevo), no para la navegacion."""
        self.filtro = clave
        for nombre, boton in getattr(self, "nav_btns", {}).items():
            try:
                activo = nombre == clave
                fondo = CAMPO if activo else PANEL
                boton.configure(bg=fondo)
                boton.label.configure(bg=fondo,
                                      fg=TEXT if activo else
                                      (DANGER if nombre == "papelera" else MUT))
            except Exception:
                pass
        self.refresh_list()

    def _pasa_filtro(self, nombre: str, meta: dict) -> bool:
        f = self.filtro
        tipo = str(meta.get("type") or "api_key")
        if f in ("todos", "papelera"):
            return True
        if f == "password":
            return tipo == "password"
        if f == "api":
            return tipo in ("api_key", "api_token", "oauth_app", "private_key")
        if f == "note":
            return tipo == "note"
        if f == "atencion":
            return self._necesita_atencion(nombre, meta)
        if f == "rotación":
            return self._rotacion_pendiente(meta)
        if f == "caducan":
            return self._caduca_pronto(meta)
        return True

    def _caduca_pronto(self, meta: dict) -> bool:
        caduca = str(meta.get("expires_at") or "")
        if not caduca:
            return False
        try:
            from datetime import date, timedelta
            fecha = date.fromisoformat(caduca[:10])
            return fecha <= date.today() + timedelta(days=30)
        except Exception:
            return False

    def _rotacion_pendiente(self, meta: dict) -> bool:
        cada = meta.get("rotate_every_days")
        if not cada:
            return False
        ultima = str(meta.get("last_rotated") or meta.get("created") or "")
        try:
            from datetime import date, timedelta
            base = date.fromisoformat(ultima[:10])
            return base + timedelta(days=int(cada)) <= date.today()
        except Exception:
            return False

    def _necesita_atencion(self, nombre: str, meta: dict) -> bool:
        try:
            sin_sitio = not self.vault.urls(nombre)
        except Exception:
            sin_sitio = True
        return (self._rotacion_pendiente(meta) or self._caduca_pronto(meta)
                or (sin_sitio and str(meta.get("type")) != "note"))

    def open_health(self) -> None:
        """Vista de salud dentro de la ventana: tarjetas que filtran la lista."""
        self._mostrar_vista("salud")

    def _salud_panel(self) -> None:
        """Panel de salud dentro de la columna del detalle."""
        if getattr(self, "_salud_frame", None) is not None:
            self._salud_frame.destroy()
        panel = tk.Frame(self.right, bg=PANEL2)
        self._salud_frame = panel
        panel.pack(fill="both", expand=True, padx=16, pady=12)
        # la GUI cachea el cofre: se relee antes de contar (una rotacion hecha
        # desde la CLI no se veria)
        try:
            self.vault.refresh()
        except Exception:
            pass
        tk.Label(panel, text="Salud del cofre", fg=FG, bg=PANEL2,
                 font=self.f_h2, anchor="w").pack(fill="x")

        nombres = self.vault.names()
        metas = {n: (self.vault.meta(n) or {}) for n in nombres}
        tarjetas = [
            ("sin sitio", sum(1 for n, m in metas.items()
                              if not self.vault.urls(n) and str(m.get("type")) != "note"),
             "warn", "atencion"),
            ("caducan en 30 d", sum(1 for m in metas.values() if self._caduca_pronto(m)),
             "rot", "caducan"),
            ("rotación pendiente", sum(1 for m in metas.values()
                                       if self._rotacion_pendiente(m)), "rot", "rotación"),
            ("secretos", len(nombres), "ok", "todos"),
        ]
        fila = tk.Frame(panel, bg=PANEL2)
        fila.pack(fill="x", pady=(12, 8))
        for titulo, valor, kind, filtro in tarjetas:
            # tarjetas neutras: solo el numero lleva color si hay algo que mirar
            fondo = CAMPO
            color = {"warn": WARNFG, "rot": COLORS["rot_fg"], "ok": OK}[kind]                 if valor else MUT
            tarjeta = tk.Frame(fila, bg=fondo, highlightthickness=0, cursor="hand2")
            tarjeta.pack(side="left", padx=(0, 8), ipadx=12, ipady=6)
            n_lab = tk.Label(tarjeta, text=str(valor), fg=color, bg=fondo,
                             font=self.f_title)
            n_lab.pack()
            t_lab = tk.Label(tarjeta, text=titulo, fg=MUT, bg=fondo,
                             font=self.f_small)
            t_lab.pack()
            for w in (tarjeta, n_lab, t_lab):
                w.bind("<Button-1>", lambda _e, f=filtro: (
                    self.set_filtro(f), self._mostrar_vista("detalle")))

        # 5.9: comprobar cada credencial con su proveedor (en un hilo) y
        # mostrar los avisos de la ultima comprobacion guardada.
        fila_salud = tk.Frame(panel, bg=PANEL2)
        fila_salud.pack(fill="x", pady=(0, 6))
        self._text_btn(fila_salud, "Comprobar ahora",
                       self._comprobar_salud).pack(side="left")
        if getattr(self, "_salud_busy", False):
            tk.Label(fila_salud, text="comprobando...", fg=MUT, bg=PANEL2,
                     font=self.f_small).pack(side="left", padx=(8, 0))
        from cofre import health as _salud
        avisos = [(n, str(m.get("health") or ""),
                   str(m.get("health_detail") or ""))
                  for n, m in metas.items()
                  if str(m.get("health") or "") in
                  ("invalida", "caduca", "rotación", "duplicada", "debil")]
        if avisos:
            tk.Label(panel,
                     text=(f"{len(avisos)} credenciales con aviso"
                           if len(avisos) != 1 else "1 credencial con aviso"),
                     fg=WARNFG, bg=PANEL2, font=self.f_sub,
                     anchor="w").pack(fill="x", pady=(4, 2))
            for nombre, estado, detalle in avisos:
                tk.Label(panel,
                         text=(f"{nombre} · {_salud.ETIQUETAS.get(estado, estado)}"
                               f" · {detalle}"),
                         fg=MUT, bg=PANEL2, font=self.f_small,
                         anchor="w").pack(fill="x")
        else:
            comprobadas = sum(1 for m in metas.values()
                              if m.get("last_verified") or m.get("health"))
            tk.Label(panel,
                     text=("sin avisos de salud" if comprobadas
                           else "sin comprobar todavía"),
                     fg=FAINT, bg=PANEL2, font=self.f_small,
                     anchor="w").pack(fill="x", pady=(2, 0))

        try:
            from cofre.audit import pending_unsigned, verify_vault
            ok, detalle = verify_vault(self.vault)
            pendientes = pending_unsigned(self.vault)
        except Exception as exc:                      # noqa: BLE001
            ok, detalle, pendientes = False, f"no se pudo verificar ({exc})", 0
        fila_reg = tk.Frame(panel, bg=PANEL2)
        fila_reg.pack(fill="x", pady=(6, 0))
        tk.Label(fila_reg, text="", fg=OK if ok else WARN, bg=PANEL2,
                 font=(ICON_FONT, 11)).pack(side="left")
        tk.Label(fila_reg, text="Registro íntegro" if ok else "Registro con problemas",
                 fg=OK if ok else WARN, bg=PANEL2, font=self.f_small).pack(
            side="left", padx=(6, 10))
        if pendientes:
            fila_pend = tk.Frame(panel, bg=PANEL2)
            fila_pend.pack(fill="x", pady=(2, 0))
            tk.Label(fila_pend, text="", fg=WARNFG, bg=PANEL2,
                     font=(ICON_FONT, 11)).pack(side="left")
            tk.Label(fila_pend, text=f"{pendientes} eventos sin sellar",
                     fg=WARNFG, bg=PANEL2, font=self.f_small).pack(side="left",
                                                                  padx=(6, 10))
            self._text_btn(fila_pend, "Sellar", self._sellar_registro).pack(side="left")

        # Credenciales viejas que se quedaron vivas al cerrar una rotacion sin
        # revocar. Se recuerdan en la entrada (indice cifrado): aqui se ven y se
        # pueden revocar sin volver a rotar.
        try:
            from cofre import rotation as rot
            store = self.vault._v2store() if self.vault.is_v2() else None
            viejas = (rot.pendientes_de_revocar(store, store.master)
                      if store is not None and store.master is not None else [])
        except Exception:
            viejas = []
        if viejas:
            cuanto = ("1 credencial antigua sin revocar" if len(viejas) == 1
                      else f"{len(viejas)} credenciales antiguas sin revocar")
            tk.Label(panel, text=cuanto, fg=WARNFG, bg=PANEL2,
                     font=self.f_sub, anchor="w").pack(fill="x", pady=(10, 2))
            for pendiente in viejas:
                nombre = str(pendiente.get("nombre") or "")
                dias = rot.dias_desde(str(pendiente.get("desde") or ""))
                fila_vieja = tk.Frame(panel, bg=PANEL2)
                fila_vieja.pack(fill="x", pady=(2, 0))
                tk.Label(fila_vieja,
                         text=(f"{nombre} · {pendiente.get('proveedor') or 'sin proveedor'}"
                               f" · hace {dias} d"),
                         fg=MUT, bg=PANEL2, font=self.f_small,
                         anchor="w").pack(side="left")
                self._text_btn(
                    fila_vieja, "Revocar",
                    lambda n=nombre, d=str(pendiente.get("desde") or ""):
                    self._revocar_antigua(n, d)).pack(side="left", padx=(8, 0))
                self._text_btn(
                    fila_vieja, "Descartar",
                    lambda n=nombre, d=str(pendiente.get("desde") or ""):
                    self._descartar_antigua(n, d), danger=True).pack(
                        side="left", padx=(6, 0))


        for datos in self.stick_report():
            estado = "conectada" if datos.get("present") else "no conectada"
            if getattr(self, "stick", None):
                estado = "llave de prueba (fichero)"
            linea = (f"llave {datos.get('drive')} · {datos.get('role')} · {estado}")
            tk.Label(panel, text=linea, fg=MUT if datos.get("present") else FAINT,
                     bg=PANEL2, font=self.f_small, anchor="w").pack(fill="x")

    def _sellar_registro(self) -> None:
        """Sellar el registro desde la vista de salud."""
        try:
            from cofre.audit import auto_seal
            store = self.vault._v2store() if self.vault.is_v2() else None
            hecho = bool(store) and auto_seal(store, store.master, forzar=True)
        except Exception:
            hecho = False
        self.set_foot("registro sellado" if hecho else "no se pudo sellar")
        self._mostrar_vista("salud")

    def _confirmar_accion(self, titulo: str, texto: str, etiqueta: str) -> bool:
        """Confirmacion explicita para una accion destructiva de la GUI."""
        win = self._sheet(titulo)
        win.geometry("500x220")
        tk.Label(win, text=texto, fg=FG, bg=PANEL, font=self.f_body,
                 wraplength=450, justify="left", anchor="w").pack(
            fill="x", padx=18, pady=(18, 12))
        salida = {"ok": False}

        def aceptar():
            salida["ok"] = True
            win.destroy()

        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=18, pady=8)
        self._btn(fila, "Cancelar", win.destroy).pack(side="right")
        self._btn(fila, etiqueta, aceptar, accent=True).pack(side="right", padx=8)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_force()
        self.root.wait_window(win)
        return salida["ok"]

    def _revocar_antigua(self, nombre: str, desde: str = "") -> None:
        """Revocar en el proveedor una credencial vieja que se quedo viva.

        No toca la credencial activa: la que usa COFRE es otra.
        """
        if not self.session:
            self.set_foot("el cofre esta bloqueado")
            return
        try:
            store = self.vault._v2store()
            store.refresh()
        except Exception as exc:                       # noqa: BLE001
            self.set_foot(f"no se pudo releer el cofre: {exc}")
            return
        if store.master is None:
            self.set_foot("el cofre esta bloqueado")
            return
        meta = dict(self.vault.meta(nombre) or {})
        proveedor = str(meta.get("provider") or "")
        aviso = (f"Se va a revocar en {proveedor or 'el proveedor'} la credencial "
                 f"antigua de '{nombre}'. La que COFRE usa ahora no se toca.")
        if not self._confirmar_accion("Revocar credencial antigua", aviso,
                                     "Revocar"):
            return
        admin_valor = ""
        if proveedor == "cloudflare":
            try:
                admin_valor = self.vault.get(self.session, "CLOUDFLARE_TOKEN_ADMIN")
            except Exception:
                self.set_foot("falta CLOUDFLARE_TOKEN_ADMIN para revocar en Cloudflare")
                return
        try:
            from cofre import rotation as rot
            texto = rot.revocar_antigua(store, store.master, nombre,
                                        admin_valor, desde=desde or None)
        except Exception as exc:                       # noqa: BLE001
            self.set_foot(f"no se pudo revocar: {exc}")
            return
        record(self.vault_path, "revoke", self.gate, self.serial, name=nombre,
               ok=True, detail=texto[:150])
        self.set_foot(f"{nombre}: {texto}")
        self._mostrar_vista("salud")
        self._escribir_calendario()

    def _descartar_antigua(self, nombre: str, desde: str = "") -> None:
        """Quitar el aviso sin tocar el proveedor (la credencial ya no existe)."""
        if not self.session:
            self.set_foot("el cofre esta bloqueado")
            return
        aviso = (f"Se va a quitar el aviso de la credencial antigua de "
                 f"'{nombre}'. No se toca el proveedor: si esa credencial sigue "
                 "viva, seguira viva. Usalo solo si ya la revocaste a mano.")
        if not self._confirmar_accion("Descartar aviso", aviso, "Descartar"):
            return
        try:
            store = self.vault._v2store()
            store.refresh()
            from cofre import rotation as rot
            texto = rot.descartar_antigua(store, store.master, nombre,
                                          desde=desde or None)
        except Exception as exc:                       # noqa: BLE001
            self.set_foot(f"no se pudo descartar: {exc}")
            return
        record(self.vault_path, "discard", self.gate, self.serial, name=nombre,
               ok=True, detail=texto[:150])
        self.set_foot(f"{nombre}: {texto}")
        self._mostrar_vista("salud")
        self._escribir_calendario()

    def _mostrar_vista(self, vista: str) -> None:
        """Cambia entre el detalle normal y las vistas (salud)."""
        self.vista = vista
        if vista == "salud":
            for w in getattr(self, "_detail_piezas", []):
                try:
                    w.pack_forget()
                except Exception:
                    pass
            self.empty_detail.place_forget()
            self._salud_panel()
            return
        if getattr(self, "_salud_frame", None) is not None:
            self._salud_frame.destroy()
            self._salud_frame = None
        self._update_detail_visible()
        self.refresh_detail()

    def open_first_use(self, event=None) -> None:
        """6.8: asistente de primer uso. Solo si no hay cofre."""
        if self.session:
            self.set_foot("el cofre ya está abierto")
            return
        if self.vault.path.exists() and self.vault.path.stat().st_size > 0:
            self.set_foot("ya hay un cofre en esa ruta; usa Llaves o la migración")
            return
        from cofre.firstuse import Wizard
        self._wizard = Wizard(self)

    def open_keys(self) -> None:
        """6.6: llaves del cofre, estado, último uso y acciones."""
        if not self.session:
            self.set_foot("abre el cofre para ver las llaves")
            return
        win = self._sheet("Llaves y recuperación")
        win.geometry("760x560")
        cab = tk.Frame(win, bg=PANEL)
        cab.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(cab, text="Llaves del cofre", fg=FG, bg=PANEL,
                 font=self.f_title, anchor="w").pack(side="left")
        self._btn(cab, "Añadir pendrive",
                  lambda e: self._add_pendrive(win)).pack(side="right")
        self._btn(cab, "Nuevo código",
                  lambda e: self._nuevo_codigo()).pack(side="right", padx=6)
        self._btn(cab, "Probar código",
                  lambda e: self._probar_codigo()).pack(side="right", padx=6)
        tk.Label(win, text="Todo lo que abre este cofre. El código de "
                           "recuperación vive en papel; no se puede leer aquí.",
                 fg=MUT, bg=PANEL, font=self.f_small, anchor="w",
                 wraplength=720, justify="left").pack(fill="x", padx=14)
        filas = tk.Frame(win, bg=PANEL)
        filas.pack(fill="both", expand=True, padx=14, pady=(8, 4))
        try:
            llaves = self._llaves_datos()
        except Exception as exc:                   # noqa: BLE001
            llaves = []
            tk.Label(filas, text=f"no se pudieron leer las llaves: {exc}",
                     fg=WARN, bg=PANEL, font=self.f_body).pack(anchor="w")
        for datos in llaves:
            self._fila_llave(filas, datos, win)
        tk.Label(win, text="Dar de baja un pendrive lo saca del cofre. Si "
                           "cambias la clave maestra, las copias viejas dejan "
                           "de abrir con la nueva y los pendrives no conectados "
                           "se quedan fuera.",
                 fg=FAINT, bg=PANEL, font=self.f_small, anchor="w",
                 wraplength=720, justify="left").pack(fill="x", padx=14)
        self._btn(win, "Cerrar", win.destroy).pack(pady=(8, 12))

    def _llaves_datos(self) -> list[dict]:
        if not self.vault.is_v2():
            return []
        from cofre import keys as keys_mod
        from cofre.audit import _events
        presentes = {}
        for drive in key_drives():
            serial = volume_serial(drive)
            if serial is not None:
                presentes[str(serial)] = {"drive": drive, "connected": True}
        for datos in self.stick_report():
            presentes.setdefault(str(datos["serial"]),
                                 {"drive": datos["drive"],
                                  "connected": datos["connected"]})
        return keys_mod.reporte(self.vault.load(),
                                load_registry(self.vault_path), presentes,
                                _events(self.vault_path))

    def _fecha_humana(self, texto: str) -> str:
        from cofre import keys as keys_mod
        return keys_mod.fecha_humana(texto)

    def _fila_llave(self, parent, datos: dict, win) -> None:
        from cofre import widgets as W
        caja = tk.Frame(parent, bg=CAMPO)
        caja.pack(fill="x", pady=3)
        kind = str(datos.get("kind") or "")
        icono = tk.Canvas(caja, width=34, height=34, bg=CAMPO,
                          highlightthickness=0)
        icono.pack(side="left", padx=(8, 4), pady=6)
        if kind == "recovery":
            icono.create_text(17, 17, text="", fill=MUT,
                              font=(ICON_FONT, 15))
            tk.Label(caja, text="Código de recuperación en papel", fg=FG,
                     bg=CAMPO, font=self.f_body, anchor="w").pack(side="left")
            W.Chip(caja, "Papel", "neutral", bg=CAMPO).pack(side="right",
                                                            padx=8)
            return
        if kind == "huerfano":
            icono.create_text(17, 17, text="", fill=WARN,
                              font=(ICON_FONT, 15))
            tk.Label(caja, text=f"{datos.get('drive') or '?'} · registro sin ranura",
                     fg=WARN, bg=CAMPO, font=self.f_body, anchor="w").pack(
                side="left")
            W.Chip(caja, "Sin ranura", "warn", bg=CAMPO).pack(side="right",
                                                              padx=8)
            return
        serial = datos.get("serial")
        actual = str(serial) == str(self.serial)
        conectada = bool(datos.get("connected"))
        registrada = bool(datos.get("registered"))
        if actual:
            estado, tipo = "Abierta ahora", "info"
        elif conectada:
            estado, tipo = "Conectada", "ok"
        elif not registrada:
            estado, tipo = "Sin registrar", "warn"
        else:
            estado, tipo = "No conectada", "neutral"
        icono.create_text(17, 17, text="",
                          fill=ACC if (conectada or actual) else MUT,
                          font=(ICON_FONT, 15))
        W.Chip(caja, estado, tipo, bg=CAMPO).pack(side="right", padx=(8, 6))
        if not actual:
            # la llave abierta solo lleva su chip "Abierta ahora"; el texto
            # repetia la etiqueta
            self._text_btn(
                caja, "Dar de baja",
                lambda s=serial, w=win: self._baja_pendrive(int(s), w),
                danger=True).pack(side="right", padx=8)
        texto = tk.Frame(caja, bg=CAMPO)
        texto.pack(side="left", fill="x", expand=True)
        titulo = (f"{datos.get('drive') or 'sin letra'} · "
                  f"{datos.get('role') or datos.get('label') or 'pendrive'} "
                  f"· serial {serial}")
        tk.Label(texto, text=titulo, fg=FG, bg=CAMPO, font=self.f_body,
                 anchor="w").pack(fill="x")
        ultimo = str(datos.get("last") or "")
        pie = ("último uso: " + self._fecha_humana(ultimo)
               if ultimo else "sin uso registrado")
        tk.Label(texto, text=pie, fg=MUT, bg=CAMPO, font=self.f_small,
                 anchor="w").pack(fill="x")

    def _baja_pendrive(self, serial: int, win_keys) -> None:
        if not self.session:
            self.set_foot("abre el cofre para dar de baja un pendrive")
            return
        if int(serial) == int(self.serial or -1):
            self.set_foot("abre el cofre con el otro pendrive y vuelve a intentarlo")
            return
        reg = load_registry(self.vault_path)
        if len(reg.get("sticks") or {}) <= 1:
            self.set_foot("no se puede dar de baja el único pendrive: añade otro antes")
            return
        info = (reg.get("sticks") or {}).get(str(serial)) or {}
        donde = info.get("drive") or f"serial {serial}"
        win = self._sheet("Dar de baja un pendrive")
        win.geometry("640x360")
        tk.Label(win, text=f"Vas a quitar la ranura del pendrive {donde}.",
                 fg=FG, bg=PANEL, font=self.f_sub, anchor="w",
                 wraplength=600, justify="left").pack(fill="x", padx=18,
                                                      pady=(16, 6))
        tk.Label(win, text="Ese pendrive dejará de abrir el cofre. Si eliges "
                           "cambiar la clave maestra, las copias viejas no se "
                           "abrirán con la nueva y los pendrives que no estén "
                           "conectados se quedarán fuera. El cambio cierra el "
                           "tramo del registro y empieza otro.",
                 fg=MUT, bg=PANEL, font=self.f_body, anchor="w",
                 wraplength=600, justify="left").pack(fill="x", padx=18)
        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=18, pady=16)

        def solo() -> None:
            win.destroy()
            if self._quitar_slot(serial):
                win_keys.destroy()
                self.open_keys()

        def con_rekey() -> None:
            win.destroy()
            if not self._quitar_slot(serial):
                return
            win_keys.destroy()
            self._rekey_gui(f"baja de {donde}")

        self._btn(fila, "Cancelar", win.destroy).pack(side="right")
        self._btn(fila, "Dar de baja y cambiar la clave", con_rekey,
                  accent=True).pack(side="right", padx=8)
        self._btn(fila, "Solo dar de baja", solo,
                  danger=True).pack(side="right", padx=8)

    def _quitar_slot(self, serial: int) -> bool:
        try:
            store = self.vault._v2store()
            from cofre import keys as keys_mod
            datos, ok = keys_mod.quitar_pendrive(store._vault, store._data,
                                                 serial)
        except Exception as exc:                   # noqa: BLE001
            self.set_foot(f"no se pudo quitar la ranura: {exc}")
            return False
        if not ok:
            self.set_foot("esa ranura ya no estaba")
            return False
        store._data = datos
        try:
            revoke_stick(self.vault_path, serial)
        except Exception:
            pass
        record(self.vault_path, "stick-revoke", self.gate, serial, name="-",
               ok=True)
        self.refresh_sticks()
        self.set_foot(f"ranura del serial {serial} quitada")
        return True

    def _rekey_gui(self, motivo: str) -> None:
        material = getattr(self.vault, "_material", {}) or {}
        stick = str(material.get("stick_path") or "")
        if not stick:
            self.set_foot("sin el pendrive actual no se puede cambiar la clave maestra")
            return
        self.set_foot("cambiando la clave maestra...")
        self.root.update_idletasks()
        comando = [sys.executable, "-m", "cofre.cli", "--gate", self.gate,
                   "--stick", stick, "--vault", self.vault_path,
                   "rekey", "--si", "--motivo", motivo]
        entorno = dict(os.environ, COFRE_VAULT=str(self.vault_path))
        if material.get("pin"):
            entorno["COFRE_PIN"] = str(material["pin"])
        try:
            proc = subprocess.run(comando, capture_output=True, text=True,
                                  env=entorno, timeout=300)
            salida = (proc.stdout or "") + (proc.stderr or "")
            exito = proc.returncode == 0
        except Exception as exc:                   # noqa: BLE001
            salida = f"no se pudo cambiar la clave maestra: {exc}"
            exito = False
        if exito:
            try:
                # el proceso cerro el tramo y cambio la maestra: se reabre con
                # la misma llave (su ranura se re-envolvio con el material actual)
                self.vault.reset_store()
                store = self.vault._v2store()
                if store.master is None:
                    raise RuntimeError("el cofre no se abrió con la llave nueva")
                audit_set_key(store.master)
                from cofre.audit import bind_store
                bind_store(store)
                self.refresh_sticks()
                self.refresh_list()
                self.refresh_detail()
                self._escribir_calendario()
                self.set_foot("clave maestra cambiada; el pendrive actual sigue abriendo")
            except Exception as exc:               # noqa: BLE001
                self.set_foot(f"clave maestra cambiada, pero no se pudo reabrir: {exc}. "
                              "Bloquea y abre de nuevo")
                self.lock(motivo="cambio de clave", detalle="reabrir con el pendrive",
                          sin_evento=True)
        else:
            self.set_foot("no se pudo cambiar la clave maestra; el cofre sigue como estaba")
        self._mostrar_salida("Cambiar la clave maestra", salida.strip())

    def _add_pendrive(self, win_keys) -> None:
        material = getattr(self.vault, "_material", {}) or {}
        stick = str(material.get("stick_path") or "")
        actual = stick[:3].upper() if len(stick) >= 2 and stick[1] == ":" else ""
        if not stick:
            self.set_foot("abre el cofre con un pendrive para poder añadir otro")
            return
        letras = [d for d in drive_letters()
                  if drive_kind(d) in (DRIVE_REMOVABLE, DRIVE_FIXED)
                  and d.upper() != actual]
        if not letras:
            self.set_foot("no hay otra unidad conectada")
            return
        win = self._sheet("Añadir un pendrive")
        win.geometry("660x440")
        tk.Label(win, text="Añadir un pendrive al cofre", fg=FG, bg=PANEL,
                 font=self.f_sub, anchor="w").pack(fill="x", padx=18,
                                                   pady=(16, 4))
        pasos = chr(10).join([
            "1. Se escribe COFRE.KEY.nuevo en la unidad elegida. El COFRE.KEY",
            "   que ya tenga ese pendrive no se toca.",
            "2. Se añade una ranura al cofre y se comprueba que la llave nueva",
            "   abre antes de darla por buena.",
            "3. Cuando confirmes, borra o renombra el COFRE.KEY viejo y renombra",
            "   COFRE.KEY.nuevo a COFRE.KEY. El viejo ya no sirve para este cofre.",
        ])
        tk.Label(win, text=pasos, fg=MUT, bg=PANEL, font=self.f_body,
                 anchor="w", justify="left").pack(fill="x", padx=18)
        lista = tk.Listbox(win, bg=CAMPO, fg=FG, font=self.f_mono,
                           relief="flat", bd=0, highlightthickness=0,
                           height=6)
        lista.pack(fill="x", padx=18, pady=10)
        for letra in letras:
            lista.insert("end", letra)
        lista.selection_set(0)
        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=18, pady=(0, 14))

        def crear() -> None:
            seleccion = lista.curselection()
            if not seleccion:
                return
            destino = letras[seleccion[0]]
            win.destroy()
            self._crear_llave_en(destino, win_keys)

        self._btn(fila, "Cancelar", win.destroy).pack(side="right")
        self._btn(fila, "Crear llave nueva", crear,
                  accent=True).pack(side="right", padx=8)

    def _crear_llave_en(self, drive: str, win_keys) -> None:
        material = getattr(self.vault, "_material", {}) or {}
        stick = str(material.get("stick_path") or "")
        destino = Path(drive) / "COFRE.KEY.nuevo"
        comando = [sys.executable, "-m", "cofre.cli", "--gate", self.gate,
                   "--stick", stick, "--vault", self.vault_path,
                   "stick-add-v2", str(destino)]
        entorno = dict(os.environ, COFRE_VAULT=str(self.vault_path))
        if material.get("pin"):
            entorno["COFRE_PIN"] = str(material["pin"])
        try:
            proc = subprocess.run(comando, capture_output=True, text=True,
                                  env=entorno, timeout=180)
            salida = ((proc.stdout or "") + (proc.stderr or "")).strip()
        except Exception as exc:                   # noqa: BLE001
            salida = f"no se pudo crear la llave: {exc}"
        try:
            self.vault.refresh()
            self.refresh_sticks()
        except Exception:
            pass
        try:
            win_keys.destroy()
        except Exception:
            pass
        self._mostrar_salida("Añadir pendrive", salida)
        self.open_keys()

    def _nuevo_codigo(self) -> None:
        if not self.session or not self.vault.is_v2():
            self.set_foot("abre un cofre v2 para generar el código")
            return
        aviso = ("Se va a reemplazar el código de recuperación. El anterior "
                 "dejará de abrir el cofre. Los pendrives no cambian.")
        if not self._confirmar_accion("Nuevo código de recuperación", aviso,
                                      "Generar"):
            return
        try:
            store = self.vault._v2store()
            from cofre import keys as keys_mod
            codigo, datos = keys_mod.generar_codigo(
                store._vault, store._data, store.master)
            store._data = datos
        except Exception as exc:                   # noqa: BLE001
            self.set_foot(f"no se pudo generar el código: {exc}")
            return
        record(self.vault_path, "recovery", self.gate, self.serial, name="-",
               ok=True, detail="código de recuperación renovado")
        self.set_foot("código nuevo generado; el anterior ya no abre")
        self._mostrar_codigo(codigo)

    def _mostrar_codigo(self, codigo: str) -> None:
        win = self._sheet("Código de recuperación nuevo")
        win.geometry("700x460")
        tk.Label(win, text="Apunta estas 25 palabras en papel",
                 fg=FG, bg=PANEL, font=self.f_title, anchor="w").pack(
            fill="x", padx=18, pady=(16, 2))
        tk.Label(win, text="Se muestran una sola vez. No se guardan en ningún "
                           "fichero y no hay botón de copiar: el portapapeles "
                           "guarda historial. El código anterior ya no abre.",
                 fg=MUT, bg=PANEL, font=self.f_small, anchor="w",
                 wraplength=660, justify="left").pack(fill="x", padx=18)
        from cofre import widgets as W
        W.CodeGrid(win, codigo, bg=PANEL).pack(fill="x", padx=18, pady=10)
        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=18, pady=(0, 14))
        self._btn(fila, "Cerrar", win.destroy).pack(side="right")

    def _probar_codigo(self) -> None:
        win = self._sheet("Probar el código de recuperación")
        win.geometry("680x380")
        tk.Label(win, text="Pega las 25 palabras. No se guarda nada.",
                 fg=FG, bg=PANEL, font=self.f_sub, anchor="w").pack(
            fill="x", padx=18, pady=(16, 4))
        caja = tk.Text(win, height=5, bg=CAMPO, fg=FG, font=self.f_mono,
                       bd=0, highlightthickness=0, wrap="word")
        caja.pack(fill="both", expand=True, padx=18, pady=8)
        resultado = tk.Label(win, text="", fg=MUT, bg=PANEL,
                             font=self.f_body, anchor="w", wraplength=620,
                             justify="left")
        resultado.pack(fill="x", padx=18)

        def probar() -> None:
            from cofre import keys as keys_mod
            ok, motivo = keys_mod.probar_codigo(
                self.vault.load(), caja.get("1.0", "end").strip())
            resultado.configure(text=("ABRE: " if ok else "NO ABRE: ") + motivo,
                                fg=OK if ok else WARN)

        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=18, pady=14)
        self._btn(fila, "Cerrar", win.destroy).pack(side="right")
        self._btn(fila, "Probar", probar, accent=True).pack(side="right",
                                                             padx=8)

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

    def open_shortcuts(self, event=None) -> None:
        win = self._sheet("COFRE - atajos de teclado")
        win.geometry("620x480")
        tk.Label(win, text="Atajos", fg=FG, bg=PANEL, font=self.f_title,
                 anchor="w").pack(fill="x", padx=18, pady=(14, 4))
        filas = [
            ("Ctrl+K", "Paleta de comandos y secretos"),
            ("Ctrl+F", "Buscar en la lista"),
            ("Ctrl+N", "Nuevo secreto"),
            ("Enter", "Copiar el secreto seleccionado"),
            ("Ctrl+Shift+C", "Copiar el nombre (no revela el valor)"),
            ("Ctrl+E", "Editar el secreto"),
            ("Supr", "Mover a la papelera (pide confirmación)"),
            ("Ctrl+L", "Bloquear el cofre"),
            ("Esc", "Ocultar el valor o cerrar el diálogo"),
            ("Ctrl+Q", "Salir"),
            ("F1", "Estos atajos"),
        ]
        for tecla, que in filas:
            fila = tk.Frame(win, bg=PANEL)
            fila.pack(fill="x", padx=18, pady=3)
            tk.Label(fila, text=tecla, fg=ACC, bg=PANEL, font=self.f_mono,
                     width=14, anchor="w").pack(side="left")
            tk.Label(fila, text=que, fg=FG, bg=PANEL, font=self.f_body,
                     anchor="w").pack(side="left")
        self._btn(win, "Cerrar", win.destroy).pack(pady=(10, 14))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_force()

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

    def _mostrar_salida(self, titulo: str, texto: str) -> None:
        win = self._sheet(titulo)
        win.geometry("720x440")
        tk.Label(win, text=titulo, fg=FG, bg=PANEL, font=self.f_h2,
                 anchor="w").pack(fill="x", padx=14, pady=(12, 6))
        marco = tk.Frame(win, bg=PANEL)
        marco.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        caja = tk.Text(marco, bg=PANEL2, fg=FG, font=self.f_mono, bd=0,
                       highlightthickness=0, wrap="word")
        barra = tk.Scrollbar(marco, command=caja.yview)
        caja.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        caja.pack(side="left", fill="both", expand=True)
        caja.insert("end", texto or "sin salida")
        caja.configure(state="disabled")
        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=14, pady=(0, 12))
        self._btn(fila, "Cerrar", win.destroy).pack(side="right")
        self._btn(fila, "Copiar detalle",
                  lambda: self._copiar_texto(texto)).pack(side="right", padx=8)

    def _copiar_texto(self, texto: str) -> None:
        try:
            from cofre.clipboard import copy_text
            copy_text(texto)
            self.set_foot("detalle copiado al portapapeles")
        except Exception as exc:                   # noqa: BLE001
            self.set_foot(f"no se pudo copiar: {exc}")

    def open_settings(self) -> None:
        """6.7: seguridad, generador, alertas, navegador, copias y Acerca de."""
        from cofre import alerts as alerts_mod
        from cofre import settings as st
        from cofre import widgets as W
        cfg = st.load(self.vault_path)
        alertas = alerts_mod.load_settings(self.vault_path)
        win = self._sheet("Ajustes")
        win.geometry("840x660")
        cab = tk.Frame(win, bg=PANEL)
        cab.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(cab, text="Ajustes", fg=FG, bg=PANEL, font=self.f_title,
                 anchor="w").pack(side="left")
        self._btn(cab, "Cerrar", win.destroy).pack(side="right")
        tk.Label(win, text="Todo esto se guarda en cofre-settings.json, junto "
                           "al cofre. No hay secretos ahí.",
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

        seccion(izq, "Seguridad")
        campo(izq, "Bloquear por inactividad (min)", v_idle)
        campo(izq, "Tiempo máximo de sesión (h)", v_max)
        campo(izq, "Vaciar el portapapeles (s; 0 = nunca)", v_clip)
        campo(izq, "Ocultar el valor revelado (s)", v_reveal)

        seccion(izq, "Generador")
        segmentado(izq, "Perfil por defecto", v_perfil,
                   ["machine", "human"], ["Para máquinas", "Palabras"])
        segmentado(izq, "Palabras", v_palabras, ["4", "6", "8"],
                   ["4", "6", "8"])
        segmentado(izq, "Idioma", v_idioma, ["es", "en"], ["es", "en"])

        seccion(izq, "Umbrales de alertas")
        campo(izq, "Lecturas para una ráfaga", v_burst)
        campo(izq, "Minutos de la ráfaga", v_bmin)
        campo(izq, "Horario inusual: desde", v_desde)
        campo(izq, "Horario inusual: hasta", v_hasta)
        campo(izq, "Pausa entre alertas (min)", v_pausa)
        campo(izq, "Fallos de apertura seguidos", v_fallos)
        campo(izq, "Horas para rotación colgada", v_rot)

        seccion(der, "Navegador")
        fila_puente = tk.Frame(der, bg=PANEL)
        fila_puente.pack(fill="x", pady=2)
        tk.Label(fila_puente, text="Conectar el puente al abrir el cofre",
                 fg=MUT, bg=PANEL, font=self.f_small, anchor="w").pack(
            side="left", fill="x", expand=True)
        W.Switch(fila_puente, v_bridge, bg=PANEL).pack(side="right")

        v_nav = tk.BooleanVar(value=bool(self.browser_on))
        fila_nav = tk.Frame(der, bg=PANEL)
        fila_nav.pack(fill="x", pady=(6, 2))
        punto = tk.Canvas(fila_nav, width=12, height=12, bg=PANEL,
                          highlightthickness=0)
        punto.pack(side="left", padx=(0, 6))
        estado_nav = tk.Label(fila_nav, text="", fg=MUT, bg=PANEL,
                              font=self.f_body, anchor="w")
        estado_nav.pack(side="left")
        self._btn(fila_nav, "Emparejar",
                  lambda e: self._emparejar_host()).pack(side="right",
                                                         padx=(8, 0))
        tk.Label(fila_nav, text="Conectar", fg=MUT, bg=PANEL,
                 font=self.f_small).pack(side="right", padx=(0, 4))
        W.Switch(fila_nav, v_nav, bg=PANEL).pack(side="right")

        def pintar_nav() -> None:
            conectado = bool(self.browser_on)
            punto.delete("all")
            punto.create_oval(2, 2, 10, 10,
                              fill=OK if conectado else LINE, outline="")
            estado_nav.configure(
                text="Conectado" if conectado else "Desconectado",
                fg=OK if conectado else MUT)

        def cambiar_nav(*_a) -> None:
            if bool(v_nav.get()) != bool(self.browser_on):
                self.toggle_browser()
            if bool(v_nav.get()) != bool(self.browser_on):
                v_nav.set(bool(self.browser_on))
            pintar_nav()

        v_nav.trace_add("write", cambiar_nav)
        pintar_nav()

        seccion(der, "Copias")
        fila_copia = tk.Frame(der, bg=PANEL)
        fila_copia.pack(fill="x", pady=2)
        tk.Entry(fila_copia, textvariable=v_carpeta, bg=CAMPO, fg=FG,
                 insertbackground=FG, relief="flat", highlightthickness=1,
                 highlightbackground=LINE, font=self.f_body).pack(
            side="left", fill="x", expand=True)
        self._btn(fila_copia, "Elegir",
                  lambda e: self._elegir_carpeta(v_carpeta)).pack(
            side="left", padx=6)
        self._btn(der, "Copiar el cofre ahora",
                  lambda e: self._copiar_copia(v_carpeta.get())).pack(
            anchor="w", pady=4)
        tk.Label(der, text="La copia es el cofre cifrado. La llave del pendrive "
                           "NO debe ir en la misma carpeta.",
                 fg=FAINT, bg=PANEL, font=self.f_small, anchor="w",
                 wraplength=360, justify="left").pack(fill="x")

        seccion(der, "Acerca de")
        formato = "v2 (índice y entradas cifrados)" if self.vault.is_v2() else "v1"
        tk.Label(der, text=f"COFRE {st.VERSION} · formato {formato}",
                 fg=FG, bg=PANEL, font=self.f_body, anchor="w").pack(fill="x")
        tk.Label(der, text=str(self.vault_path), fg=MUT, bg=PANEL,
                 font=self.f_small, anchor="w", wraplength=360,
                 justify="left").pack(fill="x")

        seccion(der, "Emergencia")
        self._btn(der, "Botón de pánico", self.open_panic,
                  danger=True).pack(anchor="w")

        def guardar() -> None:
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
        self._btn(cab, "Guardar", guardar, accent=True).pack(side="right",
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

    def open_panic(self) -> None:
        """5.10: la emergencia se ve aquí; la ejecucion va en una terminal."""
        win = self._sheet("COFRE - emergencia")
        win.geometry("660x500")
        tk.Label(win, text="Botón de pánico", fg=DANGER, bg=PANEL,
                 font=self.f_title, anchor="w").pack(fill="x", padx=18,
                                                     pady=(16, 4))
        texto = tk.Text(win, bg=PANEL, fg=FG, font=self.f_mono, bd=0,
                        highlightthickness=0, wrap="word", height=18)
        texto.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        cuerpo = chr(10).join([
            "El pánico, en este orden:",
            "  1. Cloudflare: roll de cada token; el administrador, el último.",
            "  2. GitHub PAT: revocación por valor.",
            "  3. GitHub App: regenerar la clave privada en la web.",
            "  4. Otros proveedores: URL para revocar a mano.",
            "  5. Señuelos: no se tocan.",
            "  6. Código nuevo y cambio de la clave maestra: este pendrive sigue;",
            "     los demás se quedan fuera y hay que volver a darles llave.",
            "",
            "El código nuevo se muestra UNA vez. Ten papel a mano.",
            "",
            "Este botón NO ejecuta el pánico: abre la emergencia, deja ver el",
            "plan y el comando. La ejecución se hace en una terminal, donde el",
            "código se ve y se apunta:",
            "",
            "  run.cmd panic --dry-run   (primero, sin tocar nada)",
            "  run.cmd panic             (pide teclear REVOCAR TODO)",
        ])
        texto.insert("end", cuerpo)
        texto.configure(state="disabled")
        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=18, pady=(0, 12))
        self._btn(fila, "Cerrar", win.destroy).pack(side="right")
        self._btn(fila, "Copiar comando", self._copiar_panico).pack(
            side="right", padx=8)
        self._btn(fila, "Ver el plan", lambda: self._plan_panico(texto)).pack(
            side="right", padx=8)

    def _copiar_panico(self) -> None:
        try:
            from cofre.clipboard import copy_text
            copy_text("run.cmd panic --dry-run")
            self.set_foot("copiado: primero el plan (dry-run), sin tocar nada")
        except Exception as exc:                       # noqa: BLE001
            self.set_foot(f"no se pudo copiar: {exc}")

    def _plan_panico(self, texto) -> None:
        """Ejecutar solo el dry-run del CLI y enseñar el plan, sin tocar nada."""
        material = getattr(self.vault, "_material", {}) or {}
        stick = str(material.get("stick_path") or "")
        if not stick:
            self._insertar_plan(texto, "sin pendrive no se puede abrir el cofre "
                                      "desde otra consola: ejecuta run.cmd panic "
                                      "en una terminal con la llave conectada")
            return
        comando = [sys.executable, "-m", "cofre.cli", "--gate", self.gate,
                   "--stick", stick, "--vault", self.vault_path,
                   "panic", "--dry-run"]
        entorno = dict(os.environ, COFRE_VAULT=str(self.vault_path))
        if material.get("pin"):
            entorno["COFRE_PIN"] = str(material["pin"])
        try:
            proc = subprocess.run(comando, capture_output=True, text=True,
                                  env=entorno, timeout=180)
            salida = (proc.stdout or "") + (proc.stderr or "")
        except Exception as exc:                       # noqa: BLE001
            salida = f"no se pudo ejecutar el plan: {exc}"
        self._insertar_plan(texto, salida.strip() or "(sin salida)")

    def _insertar_plan(self, texto, salida: str) -> None:
        texto.configure(state="normal")
        texto.insert("end", chr(10) + chr(10) + "PLAN (dry-run, no toca nada):"
                     + chr(10) + salida + chr(10))
        texto.see("end")
        texto.configure(state="disabled")

    def open_audit(self, event=None) -> None:
        """Verificar la cadena del registro y ensenar las ultimas entradas.

        El equivalente a 'python -m cofre.cli log verify', pero sin consola.
        """
        from cofre.audit import legacy_files, tail_human, verify_vault

        if not self.session:
            self.set_foot("abre el cofre para verificar las firmas del registro")
            return
        try:
            self.vault.refresh()
        except Exception:
            pass
        ok, detalle = verify_vault(self.vault)

        win = self._sheet("COFRE - registro de accesos")
        win.geometry("760x420")

        cabecera = tk.Frame(win, bg=PANEL)
        cabecera.pack(fill="x", padx=SM, pady=(SM, 0))
        tk.Label(cabecera, text="Registro de accesos", fg=FG, font=self.f_title,
                 bg=PANEL, anchor="w").pack(side="left")
        self._btn(cabecera, "Cerrar", win.destroy).pack(side="right")

        estado = "cadena y firmas correctas" if ok else "PROBLEMA: " + detalle
        tk.Label(win, text=estado, fg=OK if ok else WARN, bg=PANEL,
                 font=self.f_sub, anchor="w", wraplength=700,
                 justify="left").pack(fill="x", padx=SM, pady=(2, 0))
        tk.Label(win, text=detalle if ok else "", fg=MUT, bg=PANEL,
                 font=self.f_small, anchor="w", wraplength=700,
                 justify="left").pack(fill="x", padx=SM)

        viejos = [p.name for p in legacy_files(self.vault_path)
                  if p.name.startswith(".cofre-access-v1-")]
        if viejos:
            tk.Label(win, text=f"historico v1 (sin verificar): {viejos[0]}",
                     fg=FAINT, bg=PANEL, font=self.f_small, anchor="w").pack(
                fill="x", padx=SM, pady=(2, 0))

        marco = tk.Frame(win, bg=PANEL2)
        marco.pack(fill="both", expand=True, padx=SM, pady=SM)
        texto = tk.Text(marco, bg=PANEL2, fg=FG, font=self.f_mono, bd=0,
                        highlightthickness=0, wrap="word")
        barra = tk.Scrollbar(marco, command=texto.yview)
        texto.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        texto.pack(side="left", fill="both", expand=True, padx=XS, pady=XS)

        lineas = tail_human(self.vault_path, 40)
        cuerpo = chr(10).join(lineas) if lineas else "todavía no hay eventos"
        texto.insert("end", cuerpo)
        texto.configure(state="disabled")

        record(self.vault_path, "audit-verify", self.gate, self.serial, ok=ok,
               detail=detalle[:150])
        self.set_foot(("registro verificado: " if ok else "registro con problemas: ") + detalle)

    def open_guide(self, event=None) -> None:
        """Guía de uso paginada: un paso por pantalla, texto grande, sin tecnicismos."""
        win = self._sheet("COFRE - guía de uso")
        win.configure(bg=BG)
        win.geometry("620x520+140+90")
        win.minsize(520, 420)

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x")
        tk.Frame(head, bg=ACC, height=3).pack(fill="x")
        step_var = tk.StringVar()
        tk.Label(head, text=self.GUIDE_TITLE, fg=FG, font=self.f_h2,
                 bg=PANEL).pack(anchor="w", padx=LG, pady=(MD, 0))
        tk.Label(head, textvariable=step_var, fg=MUT, font=self.f_small,
                 bg=PANEL).pack(anchor="w", padx=LG, pady=(0, MD))

        card = tk.Frame(win, bg=PANEL2, highlightthickness=1, highlightbackground=LINE)
        card.pack(fill="both", expand=True, padx=LG, pady=LG)
        title_lbl = tk.Label(card, text="", fg=FG, font=self.f_h2, bg=PANEL2,
                             anchor="w", justify="left", wraplength=500)
        title_lbl.pack(fill="x", padx=LG, pady=(LG, MD))
        lines_box = tk.Frame(card, bg=PANEL2)
        lines_box.pack(fill="both", expand=True, padx=LG)

        state = {"i": 0}

        def render() -> None:
            for w in lines_box.winfo_children():
                w.destroy()
            title, lines = self.GUIDE[state["i"]]
            title_lbl.configure(text=title)
            step_var.set(f"paso {state['i'] + 1} de {len(self.GUIDE)}")
            for line in lines:
                row = tk.Frame(lines_box, bg=PANEL2)
                row.pack(fill="x", pady=XS)
                tk.Frame(row, bg=ACC, width=3, height=16).pack(side="left", pady=4)
                tk.Label(row, text=line, fg=FG, font=self.f_body, bg=PANEL2,
                         anchor="w", justify="left", wraplength=480).pack(
                    side="left", fill="x", padx=(MD, 0))
            prev_btn.set_enabled(state["i"] > 0)
            next_btn.label.configure(text="Cerrar" if state["i"] == len(self.GUIDE) - 1
                                     else "Siguiente")
            dots.delete("all")
            for k in range(len(self.GUIDE)):
                color = ACC if k == state["i"] else LINE2
                dots.create_oval(4 + k * 14, 4, 12 + k * 14, 12, fill=color, outline="")

        def go(delta: int):
            nxt = state["i"] + delta
            if nxt < 0:
                return
            if nxt >= len(self.GUIDE):
                win.destroy()
                return
            state["i"] = nxt
            render()

        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x")
        next_btn = self._btn(foot, "Siguiente", lambda _e: go(1), accent=True)
        next_btn.pack(side="right", padx=(SM, LG), pady=SM)
        prev_btn = self._btn(foot, "Anterior", lambda _e: go(-1))
        prev_btn.pack(side="right", padx=SM, pady=SM)
        dots = tk.Canvas(foot, bg=PANEL, width=14 * len(self.GUIDE) + 8, height=16,
                         highlightthickness=0, bd=0)
        dots.pack(side="left", padx=LG)

        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Right>", lambda _e: go(1))
        win.bind("<Left>", lambda _e: go(-1))
        render()
        win.focus_set()
        return win

    def toggle_help(self) -> None:
        if self.help_box.winfo_ismapped():
            self.help_box.pack_forget()
        else:
            self.help_box.pack(fill="x", padx=12, pady=(8, 12))

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

    def _update_strength(self, event=None) -> None:
        """Sin formulario fijo (E6): la fortaleza se calcula en la hoja."""
        return

    def _update_strength_antiguo(self, event=None) -> None:
        value = self.val_var.get()
        if not value:
            self.strength_var.set("fuerza: sin valor")
            return
        import math
        chars = set(value)
        bits = len(value) * math.log2(max(len(chars), 2))
        label = "debil" if bits < 40 else "aceptable" if bits < 60 else "fuerte"
        self.strength_var.set(f"fuerza: {label}  ({len(value)} caracteres, ~{bits:.0f} bits)")

    def copy_name(self, event=None) -> None:
        if not self.selected:
            self.set_foot("no hay selección")
            return
        try:
            from cofre.clipboard import copy_text
            copy_text(self.selected)
            record(self.vault_path, "copy-name", self.gate, self.serial, name=self.selected)
            self.set_foot(f"copiado el nombre '{self.selected}'. Copiar el nombre no "
                         "revela el valor.")
        except Exception as exc:
            self.set_foot(f"no se pudo copiar: {exc}")

    def copy_exec_command(self, event=None) -> None:
        if not self.selected:
            self.set_foot("no hay selección")
            return
        cmd = f"run.cmd exec --name {self.selected} -- python script.py"
        try:
            from cofre.clipboard import copy_text
            copy_text(cmd)
            record(self.vault_path, "copy-exec", self.gate, self.serial, name=self.selected)
            self.set_foot("copiado el comando. Sustituye 'python script.py' por tu "
                         "comando real.")
        except Exception as exc:
            self.set_foot(f"no se pudo copiar: {exc}")

    def rename_selected(self, event=None) -> None:
        new = self.name_var.get().strip()
        if not self.selected or not self.session:
            self.set_foot("no hay selección")
            return
        if self._is_canary(self.selected):
            self._canary_alert(self.selected, "copiar")
            return
        if not new:
            self.set_foot("escribe el nombre nuevo en el campo nombre y pulsa Renombrar")
            return
        if new == self.selected:
            self.set_foot("el nombre ya es ese")
            return
        try:
            ok = self.vault.rename(self.session, self.selected, new)
        except Exception as exc:
            self.set_foot(f"error al renombrar: {exc}")
            return
        if not ok:
            self.set_foot(f"no se pudo renombrar a '{new}' (quizas ya existe ese nombre)")
            return
        record(self.vault_path, "rename", self.gate, self.serial, name=new)
        old, self.selected = self.selected, new
        self.name_var.set("")
        self.detail_name.configure(text=new)
        self.refresh_list()
        self.set_foot(f"renombrado '{old}' a '{new}'. El valor no se tocó.")

    def edit_selected(self, event=None) -> None:
        if not self.selected or not self.session:
            self.set_foot("no hay selección")
            return
        from cofre.entry_sheet import EntrySheet
        self._sheet_nueva = EntrySheet(self, mode="edit", nombre=self.selected)
        record(self.vault_path, "edit-load", self.gate, self.serial, name=self.selected)

    def stick_label(self) -> str:
        used = next((s for s in self.stick_report() if s["serial"] == str(self.serial)), None)
        if used:
            return f"{used['drive']} ({used['role']})"
        return f"serial {self.serial}"

    def _refresh_actions(self) -> None:
        """Los botones del detalle solo tienen sentido con un secreto elegido y
        el cofre abierto."""
        usable = bool(self.selected) and self.session is not None
        for b in getattr(self, "action_btns", []):
            b.set_enabled(usable)

    def select(self, name: str):
        self.selected = name
        if getattr(self, "_salud_frame", None) is not None:
            self._salud_frame.destroy()
            self._salud_frame = None
        self.refresh_list()
        self.detail_name.configure(text=name)
        if self.session_obj:
            self.session_obj.touch()

        used = next((s for s in self.stick_report()
                     if s["serial"] == str(self.serial)), None)
        which = f"{used['drive']} ({used['role']})" if used else str(self.serial)
        meta = f"cifrado AES-256-GCM  |  abierta con la llave de {which}"
        tags = self.vault.meta(name).get("tags", [])
        if tags:
            meta += "  |  tags: " + ", ".join(tags)
        self.meta_var.set(meta)
        self.value_box.delete("1.0", "end")
        self.value_box.insert("1.0", MASK)
        self.refresh_detail()
        self._update_detail_visible()

    # ---------- detalle (E5) ----------

    def _update_detail_visible(self) -> None:
        """Con selección, el detalle; sin ella, el estado vacio."""
        hay = bool(self.selected) and bool(self.session)
        piezas = list(getattr(self, "_detail_piezas", []))
        for w in piezas:
            try:
                if hay:
                    if not w.winfo_ismapped():
                        w.pack(fill="x" if w is not self.chips_row else "x",
                               padx=16 if w not in (self.chips_row,) else 16)
                else:
                    w.pack_forget()
            except Exception:
                pass
        try:
            if hay:
                self.empty_detail.place_forget()
            elif not self.empty_detail.winfo_ismapped():
                self.empty_detail.place(relx=0.5, rely=0.42, anchor="center")
        except Exception:
            pass

    def refresh_detail(self) -> None:
        """Chips, sitios, consumidores y ciclo de vida del secreto elegido."""
        for caja in (self.chips_row, self.sites_box, self.consumers_box, self.life_box):
            for w in caja.winfo_children():
                w.destroy()
        if not self.selected or not self.session:
            return
        try:
            meta = dict(self.vault.meta(self.selected) or {})
            sitios = self.vault.urls(self.selected)
        except Exception:
            return

        tipo = str(meta.get("type") or "api_key")
        from cofre import policy as _policy
        pol = _policy.effective(meta)
        etiquetas = [(tipo, "neutral")]
        if sitios:
            etiquetas.append(("sitio asignado", "ok"))
        else:
            etiquetas.append(("sin sitio", "warn"))
        if pol.get("confirm"):
            etiquetas.append(("pide confirmación", "rot"))
        if not pol.get("browser"):
            etiquetas.append(("no sale al navegador", "neutral"))
        caduca = str(meta.get("expires_at") or "")
        if caduca:
            etiquetas.append((f"caduca {caduca}", "rot"))
        salud = str(meta.get("health") or "")
        if salud:
            from cofre import health as _salud
            etiquetas.append((_salud.ETIQUETAS.get(salud, salud),
                              "ok" if salud == "ok" else "rot"))
        for texto, kind in etiquetas:
            self._chip(self.chips_row, texto, kind).pack(side="left", padx=(0, 6))

        if not sitios:
            tk.Label(self.sites_box, text="ningúno: este secreto no se rellena en ningúna web",
                     fg=FAINT, font=self.f_small, bg=PANEL2, anchor="w").pack(fill="x")
        for sitio in sitios:
            fila = tk.Frame(self.sites_box, bg=CAMPO)
            fila.pack(fill="x", pady=1)
            tk.Label(fila, text=sitio, fg=FG, font=self.f_mono, bg=CAMPO,
                     anchor="w").pack(side="left")
            self._btn(fila, "Quitar",
                      lambda s=sitio: self.remove_site(s)).pack(side="right")

        consumidores = list(meta.get("consumers") or [])
        if not consumidores:
            tk.Label(self.consumers_box, text="nada desplegado", fg=FAINT,
                     font=self.f_small, bg=CAMPO, anchor="w").pack(fill="x")
        for c in consumidores:
            tk.Label(self.consumers_box, text=str(c), fg=MUT, font=self.f_small,
                     bg=CAMPO, anchor="w").pack(fill="x")

        lineas = []
        if meta.get("provider"):
            lineas.append(f"proveedor: {meta['provider']}")
        if caduca:
            lineas.append(f"caduca: {caduca}")
        if meta.get("rotate_every_days"):
            lineas.append(f"rotar cada {meta['rotate_every_days']} días")
        if meta.get("last_rotated"):
            lineas.append(f"última rotación: {meta['last_rotated']}")
        if salud:
            detalle_salud = str(meta.get("health_detail") or "")
            lineas.append("salud: " + salud +
                          (f" ({detalle_salud})" if detalle_salud else ""))
        if meta.get("last_verified"):
            lineas.append(f"comprobada: {str(meta['last_verified'])[:16]}")
        if not lineas:
            lineas.append("sin datos de ciclo de vida")
        for linea in lineas:
            tk.Label(self.life_box, text=linea, fg=MUT, font=self.f_small,
                     bg=CAMPO, anchor="w").pack(fill="x")

    def _chip(self, parent, texto: str, kind: str):
        """Chip pequeno sin depender del rediseño completo (E2 lo sustituye)."""
        color = {"ok": OK, "warn": WARN, "rot": ACC2 if False else WARN,
                 "neutral": MUT}.get(kind, MUT)
        return tk.Label(parent, text=texto, fg=color, bg=PANEL,
                        font=self.f_small, padx=6, pady=1)

    def _show_history(self) -> None:
        """Historial del secreto: eventos del log que lo mencionan."""
        if not self.selected:
            return
        from cofre.audit import _events
        eventos = [e for e in _events(self.vault_path)
                   if e.get("name") == self.selected]
        win = self._sheet(f"Historial de {self.selected}")
        win.geometry("620x420")
        texto = tk.Text(win, bg=PANEL, fg=FG, font=self.f_mono, bd=0,
                        highlightthickness=0, wrap="word")
        texto.pack(fill="both", expand=True, padx=12, pady=12)
        if not eventos:
            texto.insert("end", "sin eventos para este secreto")
        for e in eventos[-60:]:
            firma = "firmado" if e.get("mac") else "sin firma"
            linea = (f"{e.get('ts')}  {e.get('ev')}  "
                     + ('ok' if e.get('ok') else 'FALLO') + f"  {firma}" + chr(10))
            texto.insert("end", linea)
        texto.configure(state="disabled")
        self._btn(win, "Cerrar", win.destroy).pack(pady=(0, 12))

    def assign_site(self) -> None:
        """Asignar un dominio a ESTE secreto. Pasa por confirmación."""
        if not self.selected or not self.session:
            self.set_foot("selecciona un secreto con el cofre abierto")
            return
        from cofre.hosts import HostsError, clean_host
        valor = self._ask_text("Asignar un sitio",
                               f"Dominio donde se puede rellenar '{self.selected}'",
                               "ejemplo.com")
        if not valor:
            return
        try:
            host = clean_host(valor)
        except HostsError as exc:
            self.set_foot(f"dominio inválido: {exc}")
            return
        if self.request_confirm(f"Tu - asignar sitio", self.selected) == "deny":
            self.set_foot("asignacion cancelada")
            return
        try:
            actuales = list(self.vault.urls(self.selected))
            if host not in actuales:
                actuales.append(host)
            self.vault.set_urls(self.selected, actuales)
        except Exception as exc:                     # noqa: BLE001
            self.set_foot(f"no se pudo asignar: {exc}")
            return
        record(self.vault_path, "host-assign", self.gate, self.serial,
               name=self.selected, ok=True, detail=host)
        self.set_foot(f"'{host}' asignado a {self.selected}")
        self.refresh_detail()

    def remove_site(self, host: str) -> None:
        if not self.selected or not self.session:
            return
        try:
            actuales = [h for h in self.vault.urls(self.selected) if h != host]
            self.vault.set_urls(self.selected, actuales)
        except Exception as exc:                     # noqa: BLE001
            self.set_foot(f"no se pudo quitar: {exc}")
            return
        record(self.vault_path, "host-assign", self.gate, self.serial,
               name=self.selected, ok=True, detail=f"quitar {host}")
        self.set_foot(f"'{host}' ya no esta asignado a {self.selected}")
        self.refresh_detail()

    def _ask_text(self, titulo: str, etiqueta: str, ejemplo: str = "") -> str:
        """Hoja minima de una línea. Devuelve '' si se cancela."""
        from cofre.widgets import Field
        win = self._sheet(titulo)
        win.geometry("460x180")
        tk.Label(win, text=etiqueta, fg=FG, bg=PANEL, font=self.f_sub,
                 anchor="w", wraplength=420, justify="left").pack(
            fill="x", padx=16, pady=(14, 6))
        campo = Field(win, placeholder=ejemplo, width=420, bg=PANEL)
        campo.pack(anchor="w", padx=16)
        if ejemplo:
            campo.set("")
        salida = {"valor": ""}

        def aceptar():
            salida["valor"] = campo.get().strip()
            win.destroy()

        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=16, pady=10)
        self._btn(fila, "Cancelar", win.destroy).pack(side="right")
        self._btn(fila, "Guardar", aceptar, accent=True).pack(side="right", padx=8)
        win.bind("<Return>", lambda _e: aceptar())
        win.bind("<Escape>", lambda _e: win.destroy())
        campo.focus()
        self.root.wait_window(win)
        return salida["valor"]

    # ---------- acciones ----------

    def reveal(self, event=None):
        # Solo un click de raton real revela. Un script que llame a reveal()
        # sin evento de Tk, o con un evento que no venga del boton, no lo
        # consigue. No es una barrera contra código malicioso con acceso a la
        # maquina: es una barrera contra la revelacion involuntaria o automatizada.
        if not isinstance(event, tk.Event) or getattr(event, "num", None) != 1:
            self.set_foot("ver el valor exige un click de raton en el boton 'Ver'")
            return
        objetivos = set(self._ver_targets) | set(getattr(self, "_ver_targets_extra", []))
        if event.widget not in objetivos:
            self.set_foot("'Ver' solo funciona pulsando el boton Ver")
            return
        # un click real tiene coordenadas dentro del widget; un evento
        # sinteticos sin coordenadas no las tiene
        w = event.widget
        ex, ey = getattr(event, "x", -1), getattr(event, "y", -1)
        if not (0 < ex < w.winfo_width() and 0 < ey < w.winfo_height()):
            self.set_foot("'Ver' solo responde a un click dentro del boton")
            return
        if not self.selected or not self.session:
            self.set_foot("no hay selección o el gate no esta abierto")
            return
        try:
            value = self.vault.get(self.session, self.selected)
        except Exception as exc:
            self.set_foot(f"error al descifrar: {exc}")
            return
        self.value_box.delete("1.0", "end")
        self.value_box.insert("1.0", value)
        self.value_box.configure(fg=FG)
        if self.reveal_id is not None:
            try:
                self.root.after_cancel(self.reveal_id)
            except Exception:
                pass
        if not self.sticky:
            self.reveal_id = self.root.after(
                getattr(self, "reveal_ms", REVEAL_MS), self.hide)
        record(self.vault_path, "reveal", self.gate, self.serial, name=self.selected)
        self.set_foot("mostrando '%s'%s" % (self.selected,
                                            " (fijo, no se oculta)" if self.sticky
                                            else (": se oculta sola en "
                                                  f"{getattr(self, 'reveal_ms', REVEAL_MS) // 1000} segundos")))

    def toggle_sticky(self, event=None):
        if getattr(event, "num", None) != 1:
            return
        self.sticky = not self.sticky
        self.sticky_btn.label.configure(text="Fijado" if self.sticky else "Fijar")
        if self.sticky:
            if self.reveal_id is not None:
                try:
                    self.root.after_cancel(self.reveal_id)
                except Exception:
                    pass
                self.reveal_id = None
            self.set_foot("el valor no se ocultara solo; pulsa Ocultar al terminar")
        else:
            self.set_foot("auto-ocultacion activada (15 s)")

    def hide(self, event=None):
        self.value_box.delete("1.0", "end")
        self.value_box.insert("1.0", MASK)
        self.value_box.configure(fg=MUT)
        self.reveal_id = None
        self.set_foot("valor oculto")

    def _is_canary(self, name: str | None) -> bool:
        if not name:
            return False
        try:
            return str(self.vault.meta(name).get("type") or "") == "canary"
        except Exception:
            return False

    def _canary_alert(self, name: str, canal: str) -> None:
        """3.2: leer un senuelo es lo mas grave que puede pasar aquí."""
        record(self.vault_path, "canary-access", self.gate, self.serial,
               name=name, ok=False, detail=f"canal={canal}")
        self.set_status("ALERTA: alguien ha pedido un senuelo", warn=True)
        self.set_foot(f"ALERTA: '{name}' es un senuelo. No se entrega. "
                      f"Canal: {canal}. Queda anotado.")
        try:
            import ctypes
            texto = ("Alguien ha pedido el senuelo '" + str(name) + "' por el canal "
                     + str(canal) + ".\n\nNo se ha entregado nada. "
                     "Revisa el registro de accesos.")
            ctypes.windll.user32.MessageBoxW(
                None, texto, "COFRE - senuelo solicitado",
                0x00040000 | 0x00000030)
        except Exception:
            pass

    def copy_to_clipboard(self, event=None):
        if not self.selected or not self.session:
            self.set_foot("no hay selección")
            return
        # 2.3: la politica se aplica tambien al boton de la GUI y a la paleta
        from cofre import policy as _policy
        meta = dict(self.vault.meta(self.selected) or {})
        permitido, motivo = _policy.allowed(meta, "clipboard")
        if not permitido:
            self.set_foot(motivo)
            return
        if _policy.needs_confirm(meta):
            if not self._confirmar_accion(
                    "Confirmar copia",
                    f"'{self.selected}' esta marcado como sensible. Se va a "
                    "copiar el valor al portapapeles.",
                    "Copiar"):
                return
        try:
            value = self.vault.get(self.session, self.selected)
        except Exception as exc:
            self.set_foot(f"error: {exc}")
            return
        try:
            from cofre.clipboard import copy_text
            ok = copy_text(value)
        except Exception as exc:
            self.set_foot(f"no se pudo copiar: {exc}")
            return
        if not ok:
            self.set_foot("el portapapeles no se pudo escribir")
            return
        record(self.vault_path, "clipboard", self.gate, self.serial, name=self.selected)
        if self.clipboard_ttl:
            if self._clip_id is not None:
                try:
                    self.root.after_cancel(self._clip_id)
                except Exception:
                    pass
            def _clean():
                self._clip_id = None
                try:
                    from cofre.clipboard import clear_clipboard
                    clear_clipboard()
                    self.set_foot("portapapeles vaciado automaticamente")
                except Exception:
                    pass
            self._clip_id = self.root.after(self.clipboard_ttl * 1000, _clean)
            self.set_foot(f"copiado al portapapeles. Se vacia solo en {self.clipboard_ttl} s "
                         "(mientras esta ahi, cualquier proceso de la sesión puede leerlo).")
        else:
            self.set_foot("copiado al portapapeles de Windows y NO se limpia solo: "
                         "cualquier proceso de la sesión puede leerlo.")

    def toggle_show_value(self, event=None):
        if self._is_canary(self.selected):
            self._canary_alert(self.selected, "ver")
            return
        visible = self.val_entry.cget("show") == ""
        # Ojo: configure(show=None) NO cambia nada en tkinter (None = "no tocar");
        # para mostrar el texto hay que pasar cadena vacia.
        self.val_entry.configure(show="*" if visible else "")
        self.show_val_btn.label.configure(
            text="Mostrar al teclear" if visible else "Ocultar al teclear")
        self.set_foot("el campo valor se muestra o se oculta; esto no guarda nada en disco")

    def delete_selected(self, event=None):
        if not self.selected or not self.session:
            self.set_foot("no hay selección")
            return
        if not getattr(self, "_confirm_delete", False):
            self._confirm_delete = True
            self.del_btn.label.configure(text=f"Confirmar: borrar {self.selected}")
            self.set_foot("pulsa otra vez para borrar de verdad. El valor no se "
                          "recupera después de borrarlo.")
            self.root.after(6000, self._cancel_delete)
            return
        self._cancel_delete()
        try:
            ok = self.vault.delete(self.session, self.selected)
        except Exception as exc:
            self.set_foot(f"error: {exc}")
            return
        record(self.vault_path, "del", self.gate, self.serial, name=self.selected, ok=ok)
        self.set_foot("borrado" if ok else "no existe")
        if ok:
            self.selected = None
            self.detail_name.configure(text="sin selección")
            self.meta_var.set("")
            self.value_box.delete("1.0", "end")
        self.refresh_list()

    def _cancel_delete(self):
        self._confirm_delete = False
        try:
            self.del_btn.label.configure(text="Borrar")
        except Exception:
            pass

    def add_secret(self, event=None):
        """Compatibilidad: el boton Guardar antiguo ahora abre la hoja."""
        return self._focus_new(event)

    def _add_secret_antiguo(self, event=None):
        name = self.name_var.get().strip()
        value = self.val_var.get()
        if not name or not value:
            self.set_foot("nombre y valor son obligatorios")
            return
        if not self.session:
            self.set_foot("gate no abierto: conecta el pendrive")
            return
        try:
            tags = [t.strip() for t in self.tags_var.get().split(",") if t.strip()]
            self.vault.add(self.session, name, value, tags)
        except Exception as exc:
            self.set_foot(f"error al guardar: {exc}")
            return
        record(self.vault_path, "add", self.gate, self.serial, name=name)
        self.name_var.set("")
        self.val_var.set("")
        self.tags_var.set("")
        self._update_strength()
        self.select(name)
        self.set_foot(f"guardado '{name}'")

    def set_lang(self, code: str, event=None):
        """Guarda el idioma elegido. El texto de entropia lo pinta la hoja (E6)."""
        self.lang_var.set(code)
        try:
            words = int(self.words_var.get() or 5)
        except ValueError:
            words = 5
            self.words_var.set("5")
        self._entropy_texto = entropy(words=words, lang=code)

    def generate(self, kind: str, words: int = 5, event=None):
        if kind == "machine":
            value = machine_password()
            note = "48 bytes aleatorios: 384 bits. Nadie la teclea; copiarla y pegar."
        else:
            value = human_password(words=words, lang=self.lang_var.get())
            info = entropy(words=words, lang=self.lang_var.get())
            if info["lista"]:
                note = (f"{info['palabras']} palabras de {info['lista']} = "
                        f"{info['bits']} bits")
            else:
                note = (f"sin lista: password silabica de ~{info['bits']} bits. "
                        "Genera la lista con tools/build_wordlist.py")
        self.val_var.set(value)
        self.set_foot(note)
        record(self.vault_path, "gen", self.gate, self.serial)
        return value

    def show_log(self, lines: int = 4):
        entries = tail(self.vault_path, lines)
        texto = " | ".join(entries[-3:]) if entries else "sin registros"
        try:
            from cofre.audit import legacy_files
            viejos = [p for p in legacy_files(self.vault_path)
                      if p.name.startswith(".cofre-access-v1-")]
            if viejos:
                texto += f"  ||  historico v1 (sin verificar): {viejos[0].name}"
        except Exception:
            pass
        self.set_foot("último registro: " + texto)


def parse_args(argv: list[str]) -> dict:
    vault = str(default_vault())
    out = {"vault": vault, "gate": "usb", "stick": None, "allow_new": False}
    if "--vault" in argv:
        out["vault"] = argv[argv.index("--vault") + 1]
    if "--gate" in argv:
        out["gate"] = argv[argv.index("--gate") + 1]
    if "--stick" in argv:
        out["stick"] = argv[argv.index("--stick") + 1]
    out["allow_new"] = "--allow-new-stick" in argv
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Antes de crear Tk: sin esto Windows escala la ventana como una imagen y
    # el texto sale borroso a 125 % o 150 %.
    dpi = enable_dpi_awareness()
    cfg = parse_args(argv)
    app = CofreGUI(cfg["vault"], cfg["gate"], cfg["stick"], cfg["allow_new"])
    dpi["scaling"] = apply_tk_scaling(app.root, dpi["dpi"])
    dark_titlebar(app.root)
    app.build()
    if "--selftest" in argv:
        app.root.update_idletasks()
        app.root.update()
        print("gui construida sin error; entradas:", len(app.vault.names()))
        print("geometria:", app.root.winfo_geometry())
        print(f"dpi: modo={dpi['mode']} {dpi['dpi']} ppp, tk scaling={dpi['scaling']:.3f}")
        from cofre.gen import entropy as _ent
        _info = _ent(words=6, lang="es")
        if _info.get("lista"):
            print(f"wordlist: {_info['lista']} palabras, {_info['bits_por_palabra']} bits/palabra")
        else:
            print("wordlist: NO encontrada (se usara el fallback silabico)")
        app.root.destroy()
        return 0
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
