"""COFRE - detalle del secreto y acciones (2026-11-19).

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

class DetalleGUI:
    """Se mezcla en CofreGUI; no se instancia sola."""

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
        meta = f"guardado cifrado en este equipo  |  abierta con la llave de {which}"
        tags = self.vault.meta(name).get("tags", [])
        if tags:
            meta += "  |  tags: " + ", ".join(tags)
        self.meta_var.set(meta)
        self.value_box.delete("1.0", "end")
        self.value_box.insert("1.0", MASK)
        self.refresh_detail()
        self._update_detail_visible()

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

    def assign_site(self, event=None) -> None:
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

    def _refresh_actions(self) -> None:
        """Los botones del detalle solo tienen sentido con un secreto elegido y
        el cofre abierto."""
        usable = bool(self.selected) and self.session is not None
        for b in getattr(self, "action_btns", []):
            b.set_enabled(usable)

    def stick_label(self) -> str:
        used = next((s for s in self.stick_report() if s["serial"] == str(self.serial)), None)
        if used:
            return f"{used['drive']} ({used['role']})"
        return f"serial {self.serial}"

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
