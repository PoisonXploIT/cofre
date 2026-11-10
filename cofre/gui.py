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
from cofre.usb import KEY_FILENAME, drive_letters, load_registry, volume_serial

BG = "#0d1117"
PANEL = "#141a22"
PANEL2 = "#1b232e"
INPUT = "#232c38"
FG = "#e6edf3"
MUT = "#94a2b1"
ACC = "#3f8f74"
ACC2 = "#275746"
WARN = "#d0755c"
LINE = "#2b3542"

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

        self.root = root or tk.Tk()
        self.root.title("COFRE - boveda de secretos")
        self.root.configure(bg=BG)
        self.root.geometry("980x620+30+30")
        self.root.minsize(820, 540)

        self.f_title = tkfont.Font(family="Segoe UI", size=17, weight="bold")
        self.f_h2 = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.f_sub = tkfont.Font(family="Segoe UI", size=10)
        self.f_body = tkfont.Font(family="Segoe UI", size=11)
        self.f_mono = tkfont.Font(family="Consolas", size=11)
        self.f_small = tkfont.Font(family="Segoe UI", size=9)

    # ---------- piezas de estilo ----------

    def _btn(self, parent, text, command, accent=False):
        """Boton plano: Tk tiene un aspecto de los 90; un frame con etiqueta
        dentro queda mas limpio y permite hover."""
        bg = ACC2 if accent else PANEL2
        frame = tk.Frame(parent, bg=LINE, highlightthickness=1)
        inner = tk.Frame(frame, bg=bg)
        lab = tk.Label(inner, text=text, fg=FG, font=self.f_body, bg=bg)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        lab.pack(fill="both", expand=True, padx=13, pady=8)
        frame.label = lab
        def hover(_e, b=bg):
            for f in (frame, inner, lab):
                f.configure(bg=ACC)
            lab.configure(fg=BG)
        def unhover(_e, b=bg):
            frame.configure(bg=LINE)
            inner.configure(bg=b)
            lab.configure(bg=b, fg=FG)
        frame.bind("<Enter>", hover)
        frame.bind("<Leave>", unhover)
        frame.bind("<Button-1>", lambda e: command(e))
        lab.bind("<Button-1>", lambda e: command(e))
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
        top.pack(fill="x", padx=18, pady=13)
        tk.Label(top, text="COFRE", fg=FG, font=self.f_title, bg=PANEL).pack(side="left")
        tk.Label(top, text="  boveda local  |  la llave vive en el pendrive",
                 fg=MUT, font=self.f_sub, bg=PANEL).pack(side="left")

        self.status_var = tk.StringVar(value="pendrive no detectado")
        self.status_label = tk.Label(top, textvariable=self.status_var, fg=WARN,
                                     bg=PANEL2, font=self.f_sub, padx=10, pady=6)
        self.status_label.pack(side="right")
        self._btn(top, "Reconectar", self.unlock).pack(side="right", padx=(0, 10))

        # ---------- cuerpo ----------
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        # izquierda: pendrives, lista, ayuda
        left = tk.Frame(body, bg=PANEL, width=340)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        sticks_box = tk.Frame(left, bg=PANEL2)
        sticks_box.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(sticks_box, text="Pendrives que abren este cofre",
                 fg=FG, font=self.f_sub, bg=PANEL2).pack(anchor="w", pady=(4, 2))
        self.stick_rows = []
        for _ in range(4):
            lab = tk.Label(sticks_box, text="", fg=MUT, font=self.f_small, bg=PANEL2,
                           anchor="w")
            lab.pack(fill="x")
            self.stick_rows.append(lab)
        tk.Label(sticks_box, text="Basta con conectar UNO cualquiera. No hace falta "
                                 "conectar los dos.", fg=MUT, font=self.f_small,
                 bg=PANEL2).pack(anchor="w", pady=(4, 6))

        tk.Label(left, text="Secretos", fg=FG, font=self.f_sub, bg=PANEL).pack(
            anchor="w", padx=14, pady=(12, 6))
        self.query_var = tk.StringVar()
        self._entry(left, self.query_var).pack(fill="x", padx=14, pady=6)
        tk.Label(left, text="buscar", fg=MUT, font=self.f_small, bg=PANEL).pack(anchor="w", padx=14)
        self.list_frame = tk.Frame(left, bg=PANEL)
        self.list_frame.pack(fill="both", expand=True, padx=14)
        self.count_var = tk.StringVar(value="0 entradas")
        tk.Label(left, textvariable=self.count_var, fg=MUT, font=self.f_small,
                 bg=PANEL).pack(anchor="w", padx=14, pady=(10, 8))

        help_box = tk.Frame(left, bg=PANEL2)
        help_box.pack(fill="x", padx=14, pady=(8, 12))
        tk.Label(help_box, text="Como se usa, en 4 pasos", fg=FG, font=self.f_sub,
                 bg=PANEL2).pack(anchor="w", pady=(4, 2))
        for line in (
            "1. Conecta el pendrive (cualquiera de los autorizados).",
            "2. Pulsa Reconectar: arriba aparece cual esta abierto.",
            "3. Escribe nombre y valor, pulsa Guardar. El nombre es lo que "
            "buscaras luego (p. ej. TAVILY_API_KEY).",
            "4. Para usarla: Copiar y pegar, o en terminal",
            "   run.cmd exec --name TAVILY_API_KEY -- python script.py",
        ):
            tk.Label(help_box, text=line, fg=MUT, font=self.f_small, bg=PANEL2,
                     anchor="w").pack(fill="x")

        # derecha: detalle + alta
        right = tk.Frame(body, bg=PANEL2)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))

        self.detail_name = tk.Label(right, text="sin seleccion", fg=FG,
                                    font=self.f_h2, bg=PANEL2)
        self.detail_name.pack(anchor="w", padx=16, pady=(14, 2))
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

        row = tk.Frame(right, bg=PANEL2)
        row.pack(fill="x", padx=16, pady=6)
        self._ver_targets = set()
        ver = self._btn(row, "Ver", self.reveal, accent=True)
        ver.pack(side="left", padx=8)
        for w in (ver, *ver.winfo_children(), *[c for w in ver.winfo_children() for c in w.winfo_children()]):
            self._ver_targets.add(w)
        self._ver_frame = ver
        for b in (self._btn(row, "Ocultar", self.hide),
                  self._btn(row, "Copiar al portapapeles", self.copy_to_clipboard)):
            b.pack(side="left", padx=8)
        self.sticky_btn = self._btn(row, "Fijar", self.toggle_sticky)
        self.sticky_btn.pack(side="left", padx=8)
        self.del_btn = self._btn(row, "Borrar", self.delete_selected)
        self.del_btn.pack(side="left", padx=8)

        tk.Frame(right, bg=LINE, height=1).pack(fill="x", padx=16, pady=12)

        add = tk.Frame(right, bg=PANEL)
        add.pack(fill="x", padx=16, pady=6)
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
        tk.Label(langrow, text="palabras", fg=MUT, font=self.f_small, bg=PANEL).pack(side="left", padx=(10, 4))
        wentry = self._entry(langrow, self.words_var)
        wentry.configure(width=4)
        wentry.pack(side="left")
        tk.Label(add, text="nombre (sin espacios), p. ej. TAVILY_API_KEY", fg=MUT,
                 font=self.f_small, bg=PANEL).pack(anchor="w")
        self.name_entry = self._entry(add, self.name_var)
        self.name_entry.pack(fill="x", pady=(2, 6))
        tk.Label(add, text="valor: la contraseña, la clave API o el token",
                 fg=MUT, font=self.f_small, bg=PANEL).pack(anchor="w")
        self.val_entry = self._entry(add, self.val_var, mono=True, show="*")
        self.val_entry.pack(fill="x", pady=(2, 6))
        self.name_entry.bind("<Return>", lambda _e: self.add_secret())
        self.val_entry.bind("<Return>", lambda _e: self.add_secret())
        genrow = tk.Frame(add, bg=PANEL)
        genrow.pack(fill="x", pady=10)
        self._btn(genrow, "Generar para maquina (384 bits)",
                  lambda e: self.generate("machine", event=e)).pack(side="left", padx=8)
        self._btn(genrow, "4 palabras",
                  lambda e: self.generate("words", 4, event=e)).pack(side="left", padx=8)
        self._btn(genrow, "6 palabras",
                  lambda e: self.generate("words", 6, event=e)).pack(side="left", padx=8)
        self.show_val_btn = self._btn(genrow, "Mostrar lo escrito",
                                      lambda e: self.toggle_show_value(event=e))
        self.show_val_btn.pack(side="left", padx=8)
        self._btn(genrow, "Guardar", self.add_secret, accent=True).pack(side="right")
        self.entropy_var = tk.StringVar(value="")
        self.set_lang("es")
        tk.Label(add, textvariable=self.entropy_var, fg=MUT, font=self.f_small,
                 bg=PANEL).pack(anchor="w")
        tk.Label(add, text="La sugerencia se escribe en el campo valor; hay que pulsar "
                            "Guardar para que quede dentro del cofre.", fg=MUT,
                 font=self.f_small, bg=PANEL).pack(anchor="w", pady=(4, 0))

        pinrow = tk.Frame(right, bg=PANEL)
        pinrow.pack(fill="x", padx=16, pady=(6, 4))
        tk.Label(pinrow, text="PIN (solo si el gate es usb-pin)", fg=MUT, font=self.f_sub,
                 bg=PANEL).pack(side="left")
        self._entry(pinrow, self.pin_var, show="*").pack(side="left", fill="x", expand=True, padx=8)

        logbox = tk.Frame(right, bg=PANEL)
        logbox.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(logbox, text="Actividad reciente", fg=MUT, font=self.f_sub, bg=PANEL).pack(
            anchor="w", pady=(6, 2))
        self.log_labels = []
        for _ in range(3):
            lab = tk.Label(logbox, text="", fg=MUT, font=self.f_small, bg=PANEL, anchor="w")
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
        tk.Label(foot, textvariable=self.foot_var, fg=MUT, font=self.f_small,
                 bg=PANEL, anchor="w").pack(fill="x", padx=18, pady=10)

        self.root.bind("<Escape>", lambda _e: self.root.destroy())
        self.unlock()

    # ---------- estado ----------

    def set_status(self, text, warn=False):
        self.status_var.set(text)
        self.status_label.configure(fg=WARN if warn else FG,
                                    bg=PANEL2)

    def refresh_log(self):
        entries = tail(self.vault_path, 3)
        for i, lab in enumerate(self.log_labels):
            lab.configure(text=entries[-(i + 1)] if len(entries) > i else "")

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
        if not report:
            text = "ninguno registrado. Ejecuta: run.cmd stick-init E:\\COFRE.KEY"
        else:
            parts = []
            for s in report:
                parts.append(f"{s['drive']}  {s['label'] or 'USB'}  {s['role']}  "
                             f"{'conectado' if s['connected'] else 'NO conectado'}")
            text = "  |  ".join(parts)
        for i, lab in enumerate(self.stick_rows):
            lab.configure(text=parts[i] if report and i < len(parts) else "")
        if not report:
            self.stick_rows[0].configure(text=text)
        self._stick_text = text

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
            self.refresh_list()
            return False

        if not self.vault.load().get("wrapper"):
            self.session = None
            self.set_status("cofre vacio: hay que inicializarlo", warn=True)
            self.set_foot("cofre no inicializado. En una terminal: run.cmd init "
                          "(con el pendrive conectado) y luego run.cmd add TAVILY_API_KEY")
            self.refresh_sticks()
            self.refresh_list()
            return False

        used = next((s for s in self.stick_report()
                     if s["serial"] == str(self.serial)), None)
        which = f"{used['drive']} ({used['role']})" if used else str(self.serial)
        self.set_status(f"abierto  |  llave usada: {which}", warn=False)
        self.refresh_sticks()
        self.refresh_list()
        return True

    def refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not self.session:
            self.count_var.set("gate cerrado")
            return
        q = self.query_var.get().strip().lower()
        names = [n for n in self.vault.names() if not q or q in n.lower()]
        self.count_var.set(f"{len(names)} entrada(s)")
        if not names:
            tk.Label(self.list_frame, text="no hay secretos (o ninguno coincide)",
                     fg=MUT, font=self.f_small, bg=PANEL).pack(anchor="w", pady=8)
            return
        for n in names:
            sel = (n == self.selected)
            outer = tk.Frame(self.list_frame, bg=ACC if sel else LINE, highlightthickness=1)
            inner = tk.Frame(outer, bg=ACC2 if sel else PANEL)
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            lab = tk.Label(inner, text=n, fg=FG, font=self.f_body, bg=ACC2 if sel else PANEL,
                           anchor="w")
            lab.pack(fill="x", padx=12, pady=9)
            lab.bind("<Button-1>", lambda _e, name=n: self.select(name))
            outer.bind("<Button-1>", lambda _e, name=n: self.select(name))

    def stick_label(self) -> str:
        used = next((s for s in self.stick_report() if s["serial"] == str(self.serial)), None)
        if used:
            return f"{used['drive']} ({used['role']})"
        return f"serial {self.serial}"

    def select(self, name: str):
        self.selected = name
        self.refresh_list()
        self.detail_name.configure(text=name)
        self.meta_var.set(f"cifrado AES-256-GCM  |  abierta con la llave de {self.stick_label()}")
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
        self.set_foot("copiado al portapapeles de Windows. Cualquier proceso de la sesion "
                      "puede leerlo: limpiarlo al terminar.")

    def toggle_show_value(self, event=None):
        showing = self.val_entry.cget("show") == ""
        self.val_entry.configure(show=None if showing else "*")
        self.show_val_btn.label.configure(text="Ocultar lo escrito" if showing else "Mostrar lo escrito")
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
            self.vault.add(self.session, name, value)
        except Exception as exc:
            self.set_foot(f"error al guardar: {exc}")
            return
        record(self.vault_path, "add", self.gate, self.serial, name=name)
        self.name_var.set("")
        self.val_var.set("")
        self.select(name)
        self.set_foot(f"guardado '{name}'")

    def set_lang(self, code: str, event=None):
        self.lang_var.set(code)
        info = entropy(words=int(self.words_var.get() or 5), lang=code)
        self.entropy_var.set(f"{info['palabras']} palabras x {info['bits_por_palabra']} bits "
                            f"= {info['bits']} bits ({info['lista']} palabras en la lista)")

    def generate(self, kind: str, words: int = 5, event=None):
        if kind == "machine":
            value = machine_password()
            note = "48 bytes aleatorios: 384 bits. Nadie la teclea; copiarla y pegar."
        else:
            value = human_password(words=words, lang=self.lang_var.get())
            info = entropy(words=words, lang=self.lang_var.get())
            note = (f"{info['palabras']} palabras de {info['lista']} = {info['bits']} bits. "
                    f"{info['aviso']}") if info['aviso'] else \
                f"{info['palabras']} palabras de {info['lista']} = {info['bits']} bits"
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
    cfg = parse_args(argv)
    app = CofreGUI(cfg["vault"], cfg["gate"], cfg["stick"], cfg["allow_new"])
    app.build()
    if "--selftest" in argv:
        app.root.update_idletasks()
        app.root.update()
        print("gui construida sin error; entradas:", len(app.vault.names()))
        print("geometria:", app.root.winfo_geometry())
        app.root.destroy()
        return 0
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
