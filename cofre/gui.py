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
    proceso de la sesion puede leerlo);
  - los secretos no se escriben en ningun fichero de la interfaz;
  - cada accion queda en .cofre-access.log (nombre y gate, nunca el valor).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import tkinter as tk
from tkinter import font as tkfont

from cofre.audit import record, tail
from cofre.crypto import Vault
from cofre.gate import GateUnavailable, resolve_session_key
from cofre.gen import entropy, human_password, machine_password
from cofre.theme import (COLORS, SIZES, SPACE, apply_tk_scaling, build_fonts,
                         enable_dpi_awareness)
from cofre.usb import (KEY_FILENAME, copy_key_to, create_key_on, drive_letters,
                       find_stick, load_registry, read_key, register_stick,
                       revoke_stick, volume_serial)

# Nombres cortos sobre los tokens de cofre/theme.py. Un color que no este en
# COLORS no se usa en esta interfaz.
BG = COLORS["bg"]
PANEL = COLORS["surface"]
PANEL2 = COLORS["card"]
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

MASK = "*" * 18
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
        self.browser_on = False
        self.clipboard_ttl = 30
        self._clip_id = None
        self._key_cache: set[str] = set()

        self.root = root or tk.Tk()
        self.root.title("COFRE - boveda de secretos")
        self._set_icon()
        self.root.configure(bg=BG)
        self.root.geometry("980x620+30+30")
        # Medido el 2026-11-10: por debajo de 920 px los botones de la fila 2
        # (Renombrar, Borrar) quedan por debajo de su ancho y se recorta el
        # texto. La Fase B (layout responsivo) bajara este minimo.
        self.root.minsize(920, 560)

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


    def _btn(self, parent, text, command, accent=False, danger=False):
        """Boton plano: Tk tiene un aspecto de los 90; un frame con etiqueta
        dentro queda mas limpio y permite hover. Admite estado deshabilitado:
        un boton apagado no responde ni al raton ni al hover.

        Regla de la casa (2026-11-10): el hover NO cambia el fondo. Solo sube
        el borde. El acento se reserva a la accion primaria.
        """
        if accent:
            bg, fg, hover_fg = ACC, ONACC, ONACC
        elif danger:
            bg, fg, hover_fg = PANEL2, DANGER, DANGER
        else:
            bg, fg, hover_fg = PANEL2, FG, ACC
        frame = tk.Frame(parent, bg=LINE, highlightthickness=1)
        inner = tk.Frame(frame, bg=bg)
        lab = tk.Label(inner, text=text, fg=fg, font=self.f_body, bg=bg)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        lab.pack(fill="both", expand=True, padx=12, pady=8)
        frame.label = lab
        frame._enabled = True
        frame._bg = bg

        def click(_e):
            if not frame._enabled:
                return
            command(_e)

        def hover(_e):
            if not frame._enabled:
                return
            frame.configure(bg=LINE2)
            lab.configure(fg=hover_fg)

        def unhover(_e):
            if not frame._enabled:
                return
            frame.configure(bg=LINE)
            lab.configure(fg=fg)

        def set_enabled(on: bool):
            frame._enabled = on
            if on:
                frame.configure(bg=LINE)
                inner.configure(bg=bg)
                lab.configure(bg=bg, fg=fg)
            else:
                frame.configure(bg=LINE)
                inner.configure(bg=PANEL)
                lab.configure(bg=PANEL, fg=DIS)


        frame.set_enabled = set_enabled
        frame.bind("<Enter>", hover)
        frame.bind("<Leave>", unhover)
        frame.bind("<Button-1>", click)
        lab.bind("<Button-1>", click)
        return frame

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
        tk.Frame(header, bg=ACC, height=3).pack(fill="x")

        top = tk.Frame(header, bg=PANEL)
        top.pack(fill="x", padx=16, pady=12)
        tk.Label(top, text="COFRE", fg=FG, font=self.f_title, bg=PANEL).pack(side="left")
        tk.Label(top, text="  boveda local", fg=MUT, font=self.f_sub,
                 bg=PANEL).pack(side="left")

        self.status_var = tk.StringVar(value="pendrive no detectado")
        pill = tk.Frame(top, bg=PANEL2, highlightthickness=1, highlightbackground=LINE)
        pill.pack(side="right", padx=(0, 8))
        self.pill_dot = tk.Canvas(pill, width=10, height=10, bg=PANEL2,
                                  highlightthickness=0, bd=0)
        self.pill_dot.pack(side="left", padx=(12, 0))
        self._dot = self.pill_dot.create_oval(2, 2, 9, 9, fill=WARN, outline="")
        self.status_label = tk.Label(pill, textvariable=self.status_var, fg=FG,
                                     bg=PANEL2, font=self.f_sub)
        self.status_label.pack(side="left", padx=(8, 12), pady=6)
        self._btn(top, "Bloquear", self.lock).pack(side="right", padx=(0, 8))
        self._btn(top, "Abrir", self.unlock, accent=True).pack(side="right", padx=(0, 8))

        # ---------- cuerpo ----------
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=16)

        # izquierda: pendrives, lista, ayuda
        left = tk.Frame(body, bg=PANEL, width=300)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        sticks_box = tk.Frame(left, bg=PANEL2)
        sticks_box.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(sticks_box, text="Pendrives que abren este cofre",
                 fg=FG, font=self.f_sub, bg=PANEL2).pack(anchor="w", pady=(4, 4))
        self.stick_rows = []
        self.stick_revokes = []
        for _ in range(3):
            rrow = tk.Frame(sticks_box, bg=PANEL2)
            rrow.pack(fill="x")
            lab = tk.Label(rrow, text="", fg=MUT, font=self.f_small, bg=PANEL2, anchor="w")
            lab.pack(side="left", fill="x", expand=True)
            btn = self._btn(rrow, "Revocar", lambda e, l=lab: self.revoke_from_gui(l))
            btn.pack(side="right")
            btn.pack_forget()
            self.stick_rows.append(lab)
            self.stick_revokes.append(btn)
        tk.Label(sticks_box, text="Basta con conectar UNO cualquiera. No hace falta "
                                 "conectar los dos.", fg=MUT, font=self.f_small,
                 bg=PANEL2).pack(anchor="w", pady=(4, 4))

        tk.Label(left, text="Secretos", fg=FG, font=self.f_sub, bg=PANEL).pack(
            anchor="w", padx=12, pady=(12, 4))
        self.query_var = tk.StringVar()
        self.query_entry = self._entry(left, self.query_var)
        self.query_entry.configure(width=1)
        self.query_entry.pack(fill="x", padx=12, pady=4)
        tk.Label(left, text="buscar", fg=MUT, font=self.f_small, bg=PANEL).pack(anchor="w", padx=12)
        self.list_frame = tk.Frame(left, bg=PANEL)
        self.list_frame.pack(fill="both", expand=True, padx=12)
        self.count_var = tk.StringVar(value="0 entradas")
        tk.Label(left, textvariable=self.count_var, fg=MUT, font=self.f_small,
                 bg=PANEL).pack(anchor="w", padx=12, pady=(8, 8))

        self.help_box = tk.Frame(left, bg=PANEL2)
        tk.Label(self.help_box, text="Como funciona (F1 para ocultar)", fg=FG,
                 font=self.f_sub, bg=PANEL2).pack(anchor="w", pady=(4, 4))
        for line in (
            "El pendrive guarda la llave (32 bytes en COFRE.KEY). Sin el pendrive, "
            "cofre.json es ruido: no se descifra.",
            "Basta con conectar UNO de los autorizados. La reserva abre el mismo cofre.",
            "Guardar: nombre + valor + Guardar. Ver: solo con click de raton.",
            "Bloquear (Ctrl+L) tira la llave de la RAM. Copiar pone el valor en el "
            "portapapeles y lo limpia a los 30 s.",
            "Atajos: Ctrl+F buscar, Ctrl+N nombre, Ctrl+C copiar, flechas navegar, F1 ayuda.",
        ):
            tk.Label(self.help_box, text=line, fg=MUT, font=self.f_small, bg=PANEL2,
                     anchor="w").pack(fill="x")
        self.help_box.pack(fill="x", padx=12, pady=(8, 12))

        # derecha: wizard + detalle + alta
        # Columna derecha desplazable: medido el 2026-11-10, el formulario de
        # alta no cabia a 620 px de alto y sus campos quedaban con ancho 1.
        right_outer = tk.Frame(body, bg=PANEL2)
        right_outer.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.canvas = tk.Canvas(right_outer, bg=PANEL2, highlightthickness=0, bd=0)
        self.vbar = tk.Scrollbar(right_outer, orient="vertical",
                                 command=self.canvas.yview,
                                 width=SIZES["scrollbar"], bg=PANEL, troughcolor=BG,
                                 activebackground=LINE2, relief="flat", bd=0,
                                 highlightthickness=0)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        right = tk.Frame(self.canvas, bg=PANEL2)
        self._right_win = self.canvas.create_window((0, 0), window=right, anchor="nw")

        def _sync_scroll(_e=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self.canvas.itemconfigure(self._right_win, width=self.canvas.winfo_width())

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
        self.dest_var = tk.StringVar(value="F:\\")
        wrow = tk.Frame(self.wizard, bg=PANEL)
        wrow.pack(fill="x", padx=16, pady=(4, 4))
        tk.Label(wrow, text="unidad destino", fg=MUT, font=self.f_small,
                 bg=PANEL).pack(side="left")
        dent = self._entry(wrow, self.dest_var, mono=True)
        dent.configure(width=6)
        dent.pack(side="left", padx=4)
        self._btn(wrow, "Crear llave", lambda e: self.wizard_create_key(event=e)).pack(
            side="left", padx=4)
        wrow2 = tk.Frame(self.wizard, bg=PANEL)
        wrow2.pack(fill="x", padx=16, pady=(0, 8))
        self._btn(wrow2, "Inicializar cofre", lambda e: self.wizard_init(event=e),
                  accent=True).pack(side="left", padx=4)
        self._btn(wrow2, "Copiar la llave (reserva)",
                  lambda e: self.wizard_backup(event=e)).pack(side="left", padx=4)

        self.detail_name = tk.Label(right, text="sin seleccion", fg=FG,
                                    font=self.f_h2, bg=PANEL2)
        self.detail_name.pack(anchor="w", padx=16, pady=(12, 4))
        self.meta_var = tk.StringVar(value="selecciona un secreto de la lista")
        tk.Label(right, textvariable=self.meta_var, fg=MUT, font=self.f_sub,
                 bg=PANEL2).pack(anchor="w", padx=16, pady=(0, 8))

        self.value_box = tk.Text(right, height=3, bg=PANEL, fg=MUT, font=self.f_mono,
                                 relief="flat", borderwidth=0,
                                 highlightbackground=LINE, highlightthickness=1,
                                 wrap="word")
        self.value_box.pack(fill="x", padx=16, pady=8)
        self.value_box.insert("1.0", MASK)
        self.value_box.configure(fg=MUT)

        # Dos filas, no una. Regla medida: con etiquetas largas, nueve botones
        # en una fila no caben ni a 980 px (los ultimos quedaban con ancho 1).
        # Fila 1: acciones sobre el valor. Fila 2: acciones sobre la entrada.
        row = tk.Frame(right, bg=PANEL2)
        row.pack(fill="x", padx=16, pady=(4, 4))
        self._ver_targets = set()
        self.action_btns = []
        ver = self._btn(row, "Ver", self.reveal, accent=True)
        ver.pack(side="left", padx=SM)
        self._ver_frame = ver
        for w in (ver, *ver.winfo_children(),
                  *[c for w in ver.winfo_children() for c in w.winfo_children()]):
            self._ver_targets.add(w)
        self.action_btns.append(ver)
        for b in (self._btn(row, "Ocultar", self.hide),
                  self._btn(row, "Copiar valor", self.copy_to_clipboard)):
            b.pack(side="left", padx=SM)
            self.action_btns.append(b)
        self.sticky_btn = self._btn(row, "Fijar", self.toggle_sticky)
        self.sticky_btn.pack(side="left", padx=SM)
        self.action_btns.append(self.sticky_btn)

        self.del_btn = self._btn(row, "Borrar", self.delete_selected, danger=True)
        self.del_btn.pack(side="right", padx=SM)
        self.action_btns.append(self.del_btn)

        row2 = tk.Frame(right, bg=PANEL2)
        row2.pack(fill="x", padx=16, pady=(0, 8))
        for b in (self._btn(row2, "Copiar nombre", self.copy_name),
                  self._btn(row2, "Comando exec", self.copy_exec_command),
                  self._btn(row2, "Editar", self.edit_selected),
                  self._btn(row2, "Renombrar", self.rename_selected)):
            b.pack(side="left", padx=SM)
            self.action_btns.append(b)
        self.edit_btn = self.action_btns[6]
        self.rename_btn = self.action_btns[7]

        tk.Frame(right, bg=LINE, height=1).pack(fill="x", padx=16, pady=12)

        add = tk.Frame(right, bg=PANEL)
        add.pack(fill="x", padx=16, pady=4)
        tk.Label(add, text="Guardar un secreto nuevo (si el nombre ya existe, "
                            "se actualiza su valor)", fg=FG, font=self.f_sub,
                 bg=PANEL).pack(anchor="w", pady=(8, 4))
        self.name_var = tk.StringVar()
        self.val_var = tk.StringVar()
        self.pin_var = tk.StringVar()
        self.lang_var = tk.StringVar(value="es")
        self.words_var = tk.StringVar(value="5")
        tk.Label(add, text="sugerencias de password (se escriben en el campo de valor, "
                             "no se guardan solas)", fg=MUT, font=self.f_sub, bg=PANEL).pack(anchor="w", pady=(8, 4))
        langrow = tk.Frame(add, bg=PANEL)
        langrow.pack(fill="x", pady=4)
        tk.Label(langrow, text="lista", fg=MUT, font=self.f_small, bg=PANEL).pack(side="left")
        for code in ("es", "en"):
            self._btn(langrow, code, lambda c=code: self.set_lang(c)).pack(side="left", padx=4)
        tk.Label(langrow, text="palabras", fg=MUT, font=self.f_small, bg=PANEL).pack(side="left", padx=(8, 4))
        wentry = self._entry(langrow, self.words_var)
        wentry.configure(width=4)
        wentry.pack(side="left")
        tk.Label(add, text="nombre (sin espacios), p. ej. TAVILY_API_KEY", fg=MUT,
                 font=self.f_small, bg=PANEL).pack(anchor="w")
        self.tags_var = tk.StringVar(value="")
        tk.Label(add, text="tags (opcional, separados por coma). Ej: google, trabajo",
                 fg=MUT, font=self.f_small, bg=PANEL).pack(anchor="w")
        tags_entry = self._entry(add, self.tags_var)
        tags_entry.configure(width=1)
        tags_entry.pack(fill="x", pady=(4, 4))
        self.name_entry = self._entry(add, self.name_var)
        self.name_entry.configure(width=1)
        self.name_entry.pack(fill="x", pady=(4, 4))
        tk.Label(add, text="valor: la contraseña, la clave API o el token",
                 fg=MUT, font=self.f_small, bg=PANEL).pack(anchor="w")
        self.val_entry = self._entry(add, self.val_var, mono=True, show="*")
        self.val_entry.configure(width=1)
        self.val_entry.pack(fill="x", pady=(4, 4))
        self.strength_var = tk.StringVar(value="fuerza: sin valor")
        tk.Label(add, textvariable=self.strength_var, fg=MUT, font=self.f_small,
                 bg=PANEL).pack(anchor="w")
        self.val_entry.bind("<Key>", self._update_strength)
        self.name_entry.bind("<Return>", lambda _e: self.add_secret())
        self.val_entry.bind("<Return>", lambda _e: self.add_secret())
        # Generadores en su propia fila y "Mostrar al teclear" + Guardar en otra:
        # medido el 2026-11-10, cinco botones en una fila dejaban "Guardar" con
        # ancho 1 (invisible) incluso a 980 px.
        genrow = tk.Frame(add, bg=PANEL)
        genrow.pack(fill="x", pady=(8, 4))
        self._btn(genrow, "Para maquina (384 bits)",
                  lambda e: self.generate("machine", event=e)).pack(side="left", padx=SM)
        self._btn(genrow, "4 palabras",
                  lambda e: self.generate("words", 4, event=e)).pack(side="left", padx=SM)
        self._btn(genrow, "6 palabras",
                  lambda e: self.generate("words", 6, event=e)).pack(side="left", padx=SM)

        saverow = tk.Frame(add, bg=PANEL)
        saverow.pack(fill="x", pady=(0, 8))
        self.show_val_btn = self._btn(saverow, "Mostrar al teclear",
                                      lambda e: self.toggle_show_value(event=e))
        self.show_val_btn.pack(side="left", padx=SM)
        self._btn(saverow, "Guardar", self.add_secret, accent=True).pack(side="right", padx=SM)
        self.entropy_var = tk.StringVar(value="")
        self.set_lang("es")
        tk.Label(add, textvariable=self.entropy_var, fg=MUT, font=self.f_small,
                 bg=PANEL).pack(anchor="w")
        tk.Label(add, text="La sugerencia se escribe en el campo valor; hay que pulsar "
                            "Guardar para que quede dentro del cofre.", fg=MUT,
                 font=self.f_small, bg=PANEL).pack(anchor="w", pady=(4, 0))

        self.pinrow = tk.Frame(right, bg=PANEL)
        tk.Label(self.pinrow, text="PIN del cofre", fg=MUT, font=self.f_sub,
                 bg=PANEL).pack(side="left")
        pin_entry = self._entry(self.pinrow, self.pin_var, show="*")
        pin_entry.configure(width=1)
        pin_entry.pack(side="left", fill="x", expand=True, padx=8)
        if self.gate == "usb-pin":
            self.pinrow.pack(fill="x", padx=16, pady=(4, 4))

        logbox = tk.Frame(right, bg=PANEL)
        logbox.pack(fill="x", padx=16, pady=(8, 16))
        self.log_labels = []
        for _ in range(3):
            lab = tk.Label(logbox, text="", fg=FAINT, font=self.f_small, bg=PANEL, anchor="w")
            lab.pack(fill="x")
            self.log_labels.append(lab)
        self.refresh_log()

        # ---------- pie ----------
        foot = tk.Frame(self.root, bg=PANEL)
        foot.pack(fill="x")
        tk.Frame(foot, bg=LINE, height=1).pack(fill="x")
        self.foot_var = tk.StringVar(
            value="El pendrive GUARDA la clave (32 bytes en COFRE.KEY), no la deriva. "
                  "Sin pendrive el cofre no se abre. Cada accion queda en "
                  ".cofre-access.log (el nombre, nunca el valor).")
        footrow = tk.Frame(foot, bg=PANEL)
        footrow.pack(fill="x", padx=16, pady=6)
        tk.Label(footrow, textvariable=self.foot_var, fg=MUT, font=self.f_small,
                 bg=PANEL, anchor="w", justify="left",
                 wraplength=640).pack(side="left", fill="x", expand=True)
        self.browser_btn = self._btn(footrow, "Navegador: off",
                                     lambda _e: self.toggle_browser())
        self.browser_btn.pack(side="right", padx=(SM, 0))
        self._btn(footrow, "Guia", self.open_guide).pack(side="right", padx=SM)

        # Con pythonw no hay consola: si un callback lanza, Tk imprime el
        # traceback en un stderr invisible y la ventana sigue como si nada.
        # Se captura y se muestra en el pie, que es donde el usuario mira.
        self.root.report_callback_exception = self._on_tk_error

        self.root.bind("<Escape>", lambda _e: self._on_close())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-l>", lambda _e: self.lock())
        self.root.bind("<Control-f>", lambda _e: self.query_entry.focus_set())
        self.root.bind("<Control-n>", lambda _e: self.name_entry.focus_set())
        self.root.bind("<Control-c>", lambda _e: self.copy_to_clipboard())
        self.root.bind("<Prior>", lambda _e: self.move_selection(-1))
        self.root.bind("<Next>", lambda _e: self.move_selection(1))
        self.root.bind("<F1>", lambda _e: self.toggle_help())
        self.refresh_wizard()
        self.unlock()
        self._key_cache = self._key_drives()
        self.root.after(2000, self._poll)

    # ---------- estado ----------

    def set_status(self, text, warn=False):
        self.status_var.set(text)
        self.status_label.configure(fg=FG)
        try:
            self.pill_dot.itemconfigure(self._dot, fill=WARN if warn else OK)
        except Exception:
            pass

    def refresh_log(self):
        from cofre.audit import tail_human
        entries = tail_human(self.vault_path, len(self.log_labels))
        for i, lab in enumerate(self.log_labels):
            lab.configure(text=entries[i] if i < len(entries) else "")

    def set_foot(self, text):
        self.foot_var.set(text)
        self.refresh_log()

    def stick_report(self) -> list[dict]:
        """Pendrives autorizados, con letra, rol y si estan conectados ahora."""
        reg = load_registry(self.vault_path)
        sticks = list(reg.get("sticks", {}).values())
        sticks.sort(key=lambda s: s.get("registered", ""))
        present = {}
        for drive in drive_letters():
            if (Path(drive) / KEY_FILENAME).is_file():
                serial = volume_serial(drive)
                if serial is not None:
                    present[str(serial)] = drive
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
            })
        return out

    def refresh_sticks(self) -> None:
        report = self.stick_report()
        for i, lab in enumerate(self.stick_rows):
            if i < len(report):
                s = report[i]
                lab.configure(text=f"serial {s['serial']}  {s['drive']}  {s['label'] or 'USB'}  "
                                  f"{s['role']}  {'conectado' if s['connected'] else 'NO conectado'}")
                if len(report) > 1:
                    self.stick_revokes[i].pack(side="right")
                else:
                    self.stick_revokes[i].pack_forget()
            else:
                lab.configure(text="")
                self.stick_revokes[i].pack_forget()
        if not report:
            self.stick_rows[0].configure(text="ninguno registrado: usa 'Crear llave' "
                                        "en el panel de Puesta en marcha")
        self._stick_text = " | ".join(r.cget("text") for r in self.stick_rows if r.cget("text"))

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
            self.set_status("cerrado: conecta el pendrive y pulsa Reconectar", warn=True)
            self.set_foot("gate cerrado: " + (str(exc) if str(exc) else "no se ha encontrado COFRE.KEY"))
            record(self.vault_path, "gui-gate", self.gate, None, ok=False, detail=str(exc))
            self.refresh_sticks()
            self.refresh_wizard()
            self.refresh_list()
            return False

        if not self.vault.load().get("wrapper"):
            self.needs_init = True
            self.set_status("hay llave, pero el cofre no esta inicializado", warn=True)
            self.set_foot("cofre no inicializado: usa 'Inicializar cofre' en el "
                          "panel de Puesta en marcha")
            self.refresh_sticks()
            self.refresh_wizard()
            self.refresh_list()
            return False

        used = next((s for s in self.stick_report()
                     if s["serial"] == str(self.serial)), None)
        which = f"{used['drive']} ({used['role']})" if used else str(self.serial)
        n = len(self.vault.names())
        self.set_status(f"abierto  |  llave: {which}  |  {n} secreto(s)", warn=False)
        self.refresh_sticks()
        self.refresh_wizard()
        self.refresh_list()
        return True

    def lock(self, event=None):
        """Bloquear: se tira la clave de sesion de la RAM. Hace falta el
        pendrive otra vez para abrir."""
        self.session = None
        self.serial = None
        self.selected = None
        self.stop_bridge()
        if self.gate == "usb-pin":
            self.pin_var.set("")
        self.hide()
        self.detail_name.configure(text="sin seleccion")
        self.meta_var.set("cofre bloqueado")
        self.refresh_list()
        self.refresh_wizard()
        self.set_status("bloqueado  |  la llave ya no esta en memoria", warn=True)
        record(self.vault_path, "lock", self.gate, None, ok=True)

    def refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not self.session:
            self.count_var.set("gate cerrado")
            self._names = []
            self._refresh_actions()
            return
        q = self.query_var.get().strip().lower()
        tags = []
        if q.startswith("tag:"):
            tags = [t for t in q[4:].split(",") if t]
            q = ""
        names = []
        for n in self.vault.names():
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
            self.detail_name.configure(text="sin seleccion")
            self.meta_var.set("selecciona un secreto de la lista")
        self._refresh_actions()
        self.count_var.set(f"{len(names)} entrada(s)")
        if not names:
            empty = tk.Frame(self.list_frame, bg=PANEL)
            empty.pack(fill="x", pady=LG)
            tk.Label(empty, text="Todavia no hay secretos" if not self.vault.names()
                     else "Ninguno coincide con la busqueda",
                     fg=MUT, font=self.f_sub, bg=PANEL, anchor="w").pack(fill="x")
            tk.Label(empty, text="El nombre es como lo llamaras luego: TAVILY_API_KEY, "
                                 "GMAIL_PASSWORD...",
                     fg=FAINT, font=self.f_small, bg=PANEL, anchor="w",
                     wraplength=250, justify="left").pack(fill="x", pady=(XS, SM))
            if not self.vault.names():
                self._btn(empty, "Guardar el primero", self._focus_new,
                          accent=True).pack(anchor="w")
            return
        for n in names:
            sel = (n == self.selected)
            rowbg = PANEL2 if sel else PANEL
            outer = tk.Frame(self.list_frame, bg=rowbg)
            outer.pack(fill="x", pady=1)
            bar = tk.Frame(outer, bg=ACC if sel else rowbg, width=3)
            bar.pack(side="left", fill="y")
            lab = tk.Label(outer, text=n, fg=FG, font=self.f_body, bg=rowbg,
                           anchor="w", height=1)
            lab.pack(side="left", fill="x", expand=True, padx=(SM, SM), pady=SM)
            kind = tk.Label(outer, text=self._kind_of(n), fg=FAINT, font=self.f_small,
                            bg=rowbg)
            kind.pack(side="right", padx=(0, SM))

            def _hover(_e, w=(outer, lab, kind)):
                if n == self.selected:
                    return
                for x in w:
                    x.configure(bg=LINE)
            def _unhover(_e, w=(outer, lab, kind)):
                if n == self.selected:
                    return
                for x in w:
                    x.configure(bg=PANEL)
            for widget in (outer, lab, kind):
                widget.bind("<Button-1>", lambda _e, name=n: self.select(name))
                widget.bind("<Enter>", _hover)
                widget.bind("<Leave>", _unhover)

    def _kind_of(self, name: str) -> str:
        """Etiqueta corta a la derecha de la fila, sin llamar al cifrado."""
        tags = self.vault.meta(name).get("tags", [])
        if tags:
            return tags[0]
        low = name.lower()
        if any(k in low for k in ("api", "key", "token", "secret", "hec")):
            return "clave"
        if any(k in low for k in ("pass", "pwd", "contras")):
            return "contrasena"
        return ""

    def _focus_new(self, event=None):
        self.name_entry.focus_set()
        self.name_entry.icursor("end")
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
        from cofre.serve import SecretServer, allowed_origins_for

        origins = allowed_origins_for()
        if not origins:
            self.set_foot("el navegador necesita la extension: ejecuta "
                          "tools/install_extension.py una vez")
            return
        if not self.session:
            self.set_foot("abre el cofre con el pendrive antes de activar el navegador")
            return
        try:
            self.bridge = SecretServer(self.vault_path, origins, gate=self.gate,
                                       stick=self.stick).start()
        except OSError as exc:
            self.set_foot(f"no se pudo abrir el puerto 47653: {exc}")
            self.bridge = None
            return
        self.browser_on = True
        self.browser_btn.label.configure(text="Navegador: on", fg=OK)
        record(self.vault_path, "bridge-start", self.gate, self.serial, ok=True)
        self.set_foot(f"navegador conectado en {self.bridge.origin} "
                      f"(solo mientras el cofre este abierto)")

    def stop_bridge(self) -> None:
        if self.bridge:
            try:
                self.bridge.stop()
            except Exception:
                pass
            self.bridge = None
        self.browser_on = False
        self.browser_btn.label.configure(text="Navegador: off", fg=FG)

    def _on_close(self) -> None:
        self.stop_bridge()
        self.root.destroy()

    def _key_drives(self) -> set[str]:
        return {d for d in drive_letters() if (Path(d) / KEY_FILENAME).is_file()}

    def state(self) -> str:
        if self.session and self.vault.load().get("wrapper"):
            return "empty" if not self.vault.names() else "open"
        if not self._key_drives() and not self.stick:
            return "no-key"
        if not self.vault.load().get("wrapper"):
            return "key-no-vault"
        return "closed"

    def refresh_wizard(self) -> None:
        st = self.state()
        drives = sorted(self._key_drives())
        if st == "no-key":
            self.wizard_msg.set(
                "No hay COFRE.KEY en ningun volumen. Conecta el pendrive y "
                "pulsa 'Crear llave' (se escriben 32 bytes aleatorios en el USB).")
            self.wizard.pack(fill="x", padx=16, pady=(12, 4), before=self.detail_name)
        elif st == "key-no-vault":
            self.wizard_msg.set(
                f"La llave esta en {', '.join(drives)} pero el cofre no esta "
                "inicializado. Pulsa 'Inicializar cofre'.")
            self.wizard.pack(fill="x", padx=16, pady=(12, 4), before=self.detail_name)
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
            self.vault.init(self.session)
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

    def _poll(self) -> None:
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
        # Auto-bloqueo: si desaparece el pendrive que abrio la sesion, la llave
        # no debe seguir viva en RAM. Reabrir es un click con el otro pendrive.
        if self.session and self.serial is not None:
            used = next((s for s in self.stick_report()
                         if s["serial"] == str(self.serial)), None)
            if used is not None and not used["connected"]:
                label = f"{used['drive']} ({used['role']})"
                self.lock()
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

    # ---------- guia de uso ----------

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
            "Queda asi: run.cmd exec --name TAVILY_API_KEY -- python script.py",
            "La clave va dentro de ese proceso, no a ningun fichero.",
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

    def open_guide(self, event=None) -> None:
        """Guia de uso paginada: un paso por pantalla, texto grande, sin tecnicismos."""
        win = tk.Toplevel(self.root)
        win.title("COFRE - guia de uso")
        win.configure(bg=BG)
        win.geometry("620x520+140+90")
        win.transient(self.root)
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
            self.set_foot("no hay seleccion")
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
            self.set_foot("no hay seleccion")
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
            self.set_foot("no hay seleccion")
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
            self.set_foot("no hay seleccion")
            return
        try:
            value = self.vault.get(self.session, self.selected)
        except Exception as exc:
            self.set_foot(f"error al leer: {exc}")
            return
        self.name_var.set(self.selected)
        self.val_var.set(value)
        self.val_entry.configure(show="")
        self.show_val_btn.label.configure(text="Ocultar al teclear")
        self.set_foot(f"valor de '{self.selected}' cargado en el campo. Cambialo y "
                     "pulsa Guardar para re-cifrarlo.")
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
        self.refresh_list()
        self.detail_name.configure(text=name)
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

    # ---------- acciones ----------

    def reveal(self, event=None):
        # Solo un click de raton real revela. Un script que llame a reveal()
        # sin evento de Tk, o con un evento que no venga del boton, no lo
        # consigue. No es una barrera contra codigo malicioso con acceso a la
        # maquina: es una barrera contra la revelacion involuntaria o automatizada.
        if not isinstance(event, tk.Event) or getattr(event, "num", None) != 1:
            self.set_foot("ver el valor exige un click de raton en el boton 'Ver'")
            return
        if event.widget not in self._ver_targets:
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
            self.set_foot("no hay seleccion o el gate no esta abierto")
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
            self.reveal_id = self.root.after(REVEAL_MS, self.hide)
        record(self.vault_path, "reveal", self.gate, self.serial, name=self.selected)
        self.set_foot("mostrando '%s'%s" % (self.selected,
                                            " (fijo, no se oculta)" if self.sticky
                                            else ": se oculta sola en 15 segundos"))

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

    def copy_to_clipboard(self, event=None):
        if not self.selected or not self.session:
            self.set_foot("no hay seleccion")
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
                         "(mientras esta ahi, cualquier proceso de la sesion puede leerlo).")
        else:
            self.set_foot("copiado al portapapeles de Windows y NO se limpia solo: "
                         "cualquier proceso de la sesion puede leerlo.")

    def toggle_show_value(self, event=None):
        visible = self.val_entry.cget("show") == ""
        # Ojo: configure(show=None) NO cambia nada en tkinter (None = "no tocar");
        # para mostrar el texto hay que pasar cadena vacia.
        self.val_entry.configure(show="*" if visible else "")
        self.show_val_btn.label.configure(
            text="Mostrar al teclear" if visible else "Ocultar al teclear")
        self.set_foot("el campo valor se muestra o se oculta; esto no guarda nada en disco")

    def delete_selected(self, event=None):
        if not self.selected or not self.session:
            self.set_foot("no hay seleccion")
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
            self.detail_name.configure(text="sin seleccion")
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
        self.lang_var.set(code)
        try:
            words = int(self.words_var.get() or 5)
        except ValueError:
            words = 5
            self.words_var.set("5")
        info = entropy(words=words, lang=code)
        if not info.get("lista"):
            self.entropy_var.set(
                f"sin lista de palabras: password silabica de ~{info['bits']} bits "
                "(no depende del numero de palabras). Genera la lista con "
                "tools/build_wordlist.py")
            return
        self.entropy_var.set(
            f"{info['palabras']} palabras x {info.get('bits_por_palabra', 0)} bits "
            f"= {info['bits']} bits ({info['lista']} palabras en la lista)")

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
        self.set_foot("ultimo registro: " + " | ".join(entries[-3:]) if entries else "sin registros")


def parse_args(argv: list[str]) -> dict:
    vault = os.environ.get("COFRE_VAULT", str(Path.home() / "AI" / "cofre" / "cofre.json"))
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
