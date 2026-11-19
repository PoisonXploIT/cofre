"""COFRE - hojas y dialogos de la ventana (2026-11-19).

Sacado de `gui.py` para que el fichero de la ventana se pueda leer entero. Se mezcla
en `CofreGUI` por herencia: los metodos usan `self` y las mismas constantes de color
de `cofre/theme.py`.
"""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path

from cofre.audit import record
from cofre.messages import msg
from cofre.theme import COLORS, SIZES, SPACE
from cofre.threads import assert_main

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
ACC = COLORS["accent"]
DIS = COLORS["disabled"]
ICON_FONT = "Segoe Fluent Icons"
SM = SPACE["sm"]
XS = SPACE["xs"]
MD = SPACE["md"]
LG = SPACE["lg"]
XL = SPACE["xl"]
BG = COLORS["bg"]
ONACC = COLORS["on_accent"]
ACC2 = COLORS["card"]
DANGER = COLORS["danger"]
LINE2 = COLORS["border_strong"]
MASK = "•" * 16

from cofre import widgets as W  # noqa: E402
from cofre.gen import entropy, human_password, machine_password  # noqa: E402,F401
from cofre.usb import (create_key_on, copy_key_to, find_stick,  # noqa: E402,F401
                       key_drives, load_registry, revoke_stick,
                       volume_serial)

class HojasGUI:
    """Se mezcla en CofreGUI; no se instancia sola."""

    def _confirmar_accion(self, titulo: str, texto: str, etiqueta: str) -> bool:
        """Confirmacion explicita para una accion destructiva de la GUI."""
        win = self._sheet(titulo)
        win.geometry("500x220")
        tk.Label(win, text=texto, fg=FG, bg=PANEL, font=self.f_body,
                 wraplength=450, justify="left", anchor="w").pack(
            fill="x", padx=18, pady=(18, 12))
        salida = {"ok": False}

        def aceptar(event=None):
            salida["ok"] = True
            win.destroy()

        fila = tk.Frame(win, bg=PANEL)
        fila.pack(fill="x", padx=18, pady=8)
        self._btn(fila, msg("comun.cancelar"), win.destroy).pack(side="right")
        self._btn(fila, etiqueta, aceptar, accent=True).pack(side="right", padx=8)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_force()
        self.root.wait_window(win)
        return salida["ok"]

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

        def aceptar(event=None):
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
        self._btn(fila, msg("llaves.imprimir"),
                  lambda e: self._imprimir_codigo(win, codigo)).pack(side="left")
        self._btn(fila, "Cerrar", win.destroy).pack(side="right")

    def _imprimir_codigo(self, win, codigo: str) -> None:
        """TXT temporal numerado, dialogo de impresion y borrado posterior."""
        import os as _os
        import tempfile
        try:
            ruta = Path(tempfile.gettempdir()) / "cofre-codigo-recuperacion.txt"  # no-tildes
            partes = codigo.split()
            lineas = []
            for inicio in range(0, len(partes), 5):
                trozo = partes[inicio:inicio + 5]
                lineas.append("   ".join(f"{inicio + i + 1}. {palabra}"
                                         for i, palabra in enumerate(trozo)))
            ruta.write_text("\n".join(lineas) + "\n",
                                 encoding="utf-8")
            _os.startfile(str(ruta), "print")       # noqa: S606
            win.after(60000, lambda: ruta.unlink(missing_ok=True))
            self.set_foot(msg("primer_uso.impreso"))
        except Exception as exc:                   # noqa: BLE001
            self.set_foot(msg("primer_uso.error_imprimir", error=exc))

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

        def probar(event=None) -> None:
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

    def open_panic(self, event=None) -> None:
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

    def _copiar_panico(self, event=None) -> None:
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
