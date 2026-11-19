"""COFRE - llaves, salud y ciclo de vida de la ventana (2026-11-19).

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

class LlavesGUI:
    """Se mezcla en CofreGUI; no se instancia sola."""

    def open_health(self, event=None) -> None:
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

    def _sellar_registro(self, event=None) -> None:
        """Sellar el registro desde la vista de salud."""
        try:
            from cofre.audit import auto_seal
            store = self.vault._v2store() if self.vault.is_v2() else None
            hecho = bool(store) and auto_seal(store, store.master, forzar=True)
        except Exception:
            hecho = False
        self.set_foot("registro sellado" if hecho else "no se pudo sellar")
        self._mostrar_vista("salud")

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

    def _comprobar_salud(self, event=None) -> None:
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

    def open_keys(self, event=None) -> None:
        """6.6: llaves del cofre, estado, último uso y acciones."""
        if not self.session:
            self.set_foot("abre el cofre para ver las llaves")
            return
        win = self._sheet(msg("llaves.titulo"))
        win.geometry("760x560")
        cab = tk.Frame(win, bg=PANEL)
        cab.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(cab, text=msg("llaves.cabecera"), fg=FG, bg=PANEL,
                 font=self.f_title, anchor="w").pack(side="left")
        self._btn(cab, msg("llaves.anadir"),
                  lambda e: self._add_pendrive(win)).pack(side="right")
        self._btn(cab, msg("llaves.nuevo_codigo"),
                  lambda e: self._nuevo_codigo()).pack(side="right", padx=6)

        self._btn(cab, msg("llaves.probar"),
                  lambda e: self._probar_codigo()).pack(side="right", padx=6)
        tk.Label(win, text=msg("llaves.intro"),
                 fg=MUT, bg=PANEL, font=self.f_small, anchor="w",
                 wraplength=720, justify="left").pack(fill="x", padx=14)
        filas = tk.Frame(win, bg=PANEL)
        filas.pack(fill="both", expand=True, padx=14, pady=(8, 4))
        try:
            llaves = self._llaves_datos()
        except Exception as exc:                   # noqa: BLE001
            llaves = []
            tk.Label(filas, text=msg("llaves.error_leer", error=exc),
                     fg=WARN, bg=PANEL, font=self.f_body).pack(anchor="w")
        for datos in llaves:
            self._fila_llave(filas, datos, win)
        tk.Label(win, text=msg("llaves.pie"),
                 fg=FAINT, bg=PANEL, font=self.f_small, anchor="w",
                 wraplength=720, justify="left").pack(fill="x", padx=14)
        self._btn(win, msg("comun.cerrar"), win.destroy).pack(pady=(8, 12))

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
            tk.Label(caja, text=msg("llaves.recovery"), fg=FG,
                     bg=CAMPO, font=self.f_body, anchor="w").pack(side="left")
            W.Chip(caja, msg("llaves.papel"), "neutral", bg=CAMPO).pack(side="right",
                                                            padx=8)
            return
        if kind == "huerfano":
            icono.create_text(17, 17, text="", fill=WARN,
                              font=(ICON_FONT, 15))
            tk.Label(caja, text=f"{datos.get('drive') or '?'} · {msg('llaves.huerfano')}",
                     fg=WARN, bg=CAMPO, font=self.f_body, anchor="w").pack(
                side="left")
            W.Chip(caja, msg("llaves.sin_ranura"), "warn", bg=CAMPO).pack(side="right",
                                                              padx=8)
            return
        serial = datos.get("serial")
        actual = str(serial) == str(self.serial)
        conectada = bool(datos.get("connected"))
        registrada = bool(datos.get("registered"))
        if actual:
            estado, tipo = msg("llaves.abierta"), "info"
        elif conectada:
            estado, tipo = msg("llaves.conectada"), "ok"
        elif not registrada:
            estado, tipo = msg("llaves.sin_registrar"), "warn"
        else:
            estado, tipo = msg("llaves.no_conectada"), "neutral"
        icono.create_text(17, 17, text="",
                          fill=ACC if (conectada or actual) else MUT,
                          font=(ICON_FONT, 15))
        W.Chip(caja, estado, tipo, bg=CAMPO).pack(side="right", padx=(8, 6))
        if not actual:
            # la llave abierta solo lleva su chip "Abierta ahora"; el texto
            # repetia la etiqueta
            self._text_btn(
                caja, msg("llaves.baja"),
                lambda s=serial, w=win: self._baja_pendrive(int(s), w),
                danger=True).pack(side="right", padx=8)
        texto = tk.Frame(caja, bg=CAMPO)
        texto.pack(side="left", fill="x", expand=True)
        titulo = (f"{datos.get('drive') or 'sin letra'} · "
                  f"{datos.get('role') or datos.get('label') or 'pendrive'}")
        tk.Label(texto, text=titulo, fg=FG, bg=CAMPO, font=self.f_body,
                 anchor="w").pack(fill="x")
        ultimo = str(datos.get("last") or "")
        pie = (msg("llaves.uso", fecha=self._fecha_humana(ultimo))
               if ultimo else msg("llaves.sin_uso"))
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
        donde = info.get("drive") or "ese pendrive"
        win = self._sheet(msg("llaves.baja_titulo"))
        win.geometry("640x360")
        tk.Label(win, text=msg("llaves.baja_pendrive", donde=donde),
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

        def solo(event=None) -> None:
            win.destroy()
            if self._quitar_slot(serial):
                win_keys.destroy()
                self.open_keys()

        def con_rekey(event=None) -> None:
            win.destroy()
            if not self._quitar_slot(serial):
                return
            win_keys.destroy()
            self._rekey_gui(f"baja de {donde}")

        self._btn(fila, "Cancelar", win.destroy).pack(side="right")
        self._btn(fila, msg("llaves.baja_rekey"), con_rekey,
                  accent=True).pack(side="right", padx=8)
        self._btn(fila, msg("llaves.solo_baja"), solo,
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
        self.set_foot("ranura del pendrive quitada")
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
        win = self._sheet(msg("llaves.anadir_titulo"))
        win.geometry("660x440")
        tk.Label(win, text=msg("llaves.anadir_cofre"), fg=FG, bg=PANEL,
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

        def crear(event=None) -> None:
            seleccion = lista.curselection()
            if not seleccion:
                return
            destino = letras[seleccion[0]]
            win.destroy()
            self._crear_llave_en(destino, win_keys)

        self._btn(fila, "Cancelar", win.destroy).pack(side="right")
        self._btn(fila, msg("llaves.anadir_crear"), crear,
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
