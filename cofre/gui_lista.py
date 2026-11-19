"""COFRE - lista, filtros y navegacion (2026-11-19).

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

class ListaGUI:
    """Se mezcla en CofreGUI; no se instancia sola."""

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

    def move_selection(self, delta: int) -> None:
        names = getattr(self, "_names", [])
        if not names:
            return
        try:
            i = names.index(self.selected) if self.selected in names else 0
        except ValueError:
            i = 0
        self.select(names[(i + delta) % len(names)])

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

    def dismiss_alerts(self, event=None) -> None:
        self._alerts_visibles = []
        self.alert_band.pack_forget()

    def _mostrar_vista(self, vista: str) -> None:
        """Cambia entre el detalle normal y las vistas (salud)."""
        self.vista = vista
        if vista == "salud":
            for w in getattr(self, "_detail_piezas", []):
                try:
                    w.pack_forget()
                except Exception:
                    pass
            try:
                self.empty_detail.place_forget()
            except Exception:
                pass          # el widget ya no existe (ventana cerrada a medias)
            self._salud_panel()
            return
        if getattr(self, "_salud_frame", None) is not None:
            try:
                self._salud_frame.destroy()
            except Exception:
                pass
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
