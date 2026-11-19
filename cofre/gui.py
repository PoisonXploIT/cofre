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
import time
from pathlib import Path

import tkinter as tk
from tkinter import font as tkfont

from cofre.audit import clave_ligada as audit_clave_ligada
from cofre.audit import clear_key as audit_clear_key
from cofre.audit import record, set_key as audit_set_key, tail
from cofre.crypto import Vault
from cofre.gate import GateUnavailable, material_for, resolve_session_key
from cofre.gen import entropy, human_password, machine_password
from cofre.gui_ajustes import AjustesGUI
from cofre.gui_detalle import DetalleGUI
from cofre.gui_hojas import HojasGUI
from cofre.gui_llaves import LlavesGUI
from cofre.gui_lista import ListaGUI
from cofre.gui_paleta import PaletaGUI
from cofre.gui_puente import PuenteGUI
from cofre.messages import msg
from cofre.paths import default_vault
from cofre.threads import assert_main, is_main
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


class CofreGUI(PuenteGUI, HojasGUI, LlavesGUI, ListaGUI, DetalleGUI,
               AjustesGUI, PaletaGUI):
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
        # llamadas a Tk desde otros hilos: se encolan y las pinta el sondeo
        self._ui_cola: queue.Queue = queue.Queue()
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

        # ojo: se guarda el metodo original ANTES de sustituirlo. Antes se llamaba
        # a `boton.set_enabled(on)` dentro del propio envoltorio, que ya era el
        # envoltorio: recursion infinita al pulsar cualquier boton deshabilitado
        # (salio con la guia, 2026-11-19).
        original_set_enabled = boton.set_enabled

        def set_enabled(on: bool):
            boton._enabled = on
            original_set_enabled(on)

        boton.set_enabled = set_enabled
        return boton

    def _draw_pill(self) -> None:
        """Pildora redondeada: fondo ok_bg, texto corto y punto de estado."""
        assert_main("_draw_pill")
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

        # ---------- permisos temporales (2026-11-18) ----------
        # La tuberia esta abierta siempre que el cofre lo esta. Mientras dura un
        # "Permitir 5 minutos", se ve aqui y se puede retirar con un clic.
        self.grants_row = tk.Frame(header, bg=PANEL)
        self._grants_widgets: list = []
        self._grants_firma: tuple | None = None


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
        self.root.after(50, self._pump_ui)
        self.root.after(1000, self._pump_grants)
        from cofre.lock_screen import LockScreen
        self.lock_screen = LockScreen(self.root, self)
        self.lock_screen.mostrar("abriendo el cofre...")

        self.refresh_wizard()
        self.unlock()
        self._key_cache = self._key_drives()
        self.root.after(2000, self._poll)

    # ---------- estado ----------


    def refresh_log(self):
        from cofre.audit import tail_human
        entries = tail_human(self.vault_path, len(self.log_labels))
        for i, lab in enumerate(self.log_labels):
            lab.configure(text=entries[i] if i < len(entries) else "")

    def set_foot(self, text, ttl: int = 8000):
        """Aviso breve en el pie. Se borra solo, o al cambiar de estado."""
        assert_main("set_foot")
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

    # ---------- permisos temporales a la vista ----------


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

    def _bind_material(self) -> bool:
        """v2 necesita la llave del pendrive, no solo la sesión derivada.

        Devuelve False si el cofre no se pudo abrir de verdad con esa llave. Paso el
        2026-11-19: el volumen contestaba a `resolve_session_key` pero no a
        `material_for`, asi que la ventana decia "abierto" con la sesion puesta y el
        cofre sin clave: 0 secretos y "cofre v2 abierto sin sesión" al guardar.
        """
        if not self.vault.is_v2():
            return True
        material = material_for(self.gate, str(self.vault_path), self.stick,
                                self.allow_new)
        self.vault.bind_material(material)
        try:
            if self.vault._v2store().master is not None:
                return True
        except Exception:
            return False
        # segundo intento: un volumen lento puede fallar una vez
        try:
            import time as _time
            _time.sleep(0.4)
            self.vault.reset_store()
            material = material_for(self.gate, str(self.vault_path), self.stick,
                                    self.allow_new)
            self.vault.bind_material(material)
            return self.vault._v2store().master is not None
        except Exception:
            return False

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

        if not self._bind_material():
            # la llave no abre el indice: mejor cerrar que quedarse a medias
            self.session = None
            self.serial = None
            self.vault.reset_store()
            self._pill_texto = msg("comun.cerrado")
            self.set_status(msg("comun.cerrado"), warn=True)
            message = ("el pendrive responde, pero el cofre no se abre con su llave. "
                       "Quita y vuelve a conectar el pendrive y pulsa Reconectar.")
            self.set_foot(message, ttl=0)
            record(self.vault_path, "gui-gate", self.gate, None, ok=False,
                   detail="material sin llave util")
            self.refresh_list()
            if getattr(self, "lock_screen", None):
                self.lock_screen.mostrar(message)
            return False

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
        # La tuberia sirve al navegador y al ayudante de git: se levanta con
        # el cofre abierto. El interruptor de Ajustes la puede parar.
        if self.bridge_ctl is None and self.bridge is None:
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
        self._grants_firma = None
        try:
            self._refrescar_grants()          # la barra de permisos se vacia ya
        except Exception:
            pass
        # el evento se firma ANTES de tirar la clave: un 'lock' sin firma no
        # existe si el cofre estaba abierto. Y si no habia sesión no se escribe
        # nada: bloquear un cofre ya cerrado no es un evento.
        # solo se anota si hay clave de auditoria: un `lock` sin firma no deberia
        # existir, y la GUI puede bloquear cuando el cofre no llego a abrirse
        # (pendrive retirado justo al abrir). Paso el 2026-11-17: 17 locks sin
        # firma que parecian manipulacion.
        if self.session and not sin_evento and audit_clave_ligada():
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


    def open_new_for_site(self, sitio: str, usuario: str = "") -> None:
        """4.8: el navegador pide guardar este sitio. Se abre la hoja con el
        dominio puesto y el valor se escribe aqui, no en la extension."""
        assert_main("open_new_for_site")
        if not self.session:
            self.set_foot(msg("nuevo.abre"))
            return
        from cofre.entry_sheet import EntrySheet
        actual = getattr(self, "_sheet_nueva", None)
        try:
            if actual is not None and actual.win.winfo_exists() and not actual.guardado:
                if sitio:
                    actual.campo_sitios.set(sitio)
                actual.win.lift()
                actual.campo_nombre.entry.focus_set()
                self.set_foot(msg("nuevo.hoja_abierta", sitio=sitio))
                return
        except Exception:
            pass
        self._sheet_nueva = EntrySheet(self, mode="new", sitio=sitio, usuario=usuario)
        self.set_foot(msg("nuevo.sitio_preparado", sitio=sitio))
        record(self.vault_path, "browser-save", self.gate, self.serial,
               name=f"desde el navegador: {sitio}"[:60], ok=True)

    def _focus_new(self, event=None):
        """Abrir la hoja de alta (E6)."""
        if not self.session:
            self.set_foot(msg("nuevo.abre"))
            return
        from cofre.entry_sheet import EntrySheet
        self._sheet_nueva = EntrySheet(self, mode="new")
        self.canvas.yview_moveto(1.0)
        self.set_foot("escribe el nombre (p. ej. TAVILY_API_KEY), el valor, y pulsa Guardar")

    # ---------- errores ----------

    def _on_tk_error(self, exc_type, exc_value, tb) -> None:
        """Un fallo en un callback no puede quedarse mudo ni tumbar la ventana.

        Con pythonw, `sys.stderr` es None: escribir ahi lanzaba otra excepcion
        dentro del propio manejador, se escapaba del `mainloop` y la ventana se
        cerraba "sola" (paso el 2026-11-19 con el boton Probar).
        """
        import traceback
        text = traceback.format_exception(exc_type, exc_value, tb)
        try:
            if sys.stderr is not None:
                sys.stderr.write("".join(text))
        except Exception:
            pass
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


    # ---------- detalle (E5) ----------


    # ---------- acciones ----------


    def _canary_alert(self, name: str, canal: str) -> None:
        """3.2: leer un senuelo es lo mas grave que puede pasar aquí.

        Puede llegar desde el hilo de la tuberia o del TCP: el registro si se
        escribe aqui (con su cerrojo) y lo que pinta se encola al hilo de Tk.
        """
        record(self.vault_path, "canary-access", self.gate, self.serial,
               name=name, ok=False, detail=f"canal={canal}")
        self.ui_call(self._canary_alert_ui, name, canal)

    def _canary_alert_ui(self, name: str, canal: str) -> None:
        assert_main("_canary_alert_ui")
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
