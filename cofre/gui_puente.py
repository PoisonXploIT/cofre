"""COFRE - puente con el navegador y permisos temporales (2026-11-19).

Sacado de `gui.py` (paso del plan: el fichero de la ventana era demasiado grande
para que un modelo pequeno lo leyera entero). Aqui vive lo que no es dibujo:

  - `ui_call` y `_pump_ui`: pintar desde otro hilo, siempre en el de Tkinter;
  - `set_status`: la pildora de la cabecera;
  - permisos temporales de 5 minutos: cuenta atras, y retirarlos a mano;
  - `request_confirm`: el dialogo, por cola si viene de otro hilo;
  - la tuberia: arrancarla, sondearla y pararla (navegador y git).

Todo se mezcla en `CofreGUI` por herencia: los metodos usan `self` y las mismas
constantes de color de `cofre/theme.py`.
"""

from __future__ import annotations

import os
import queue
import time
import tkinter as tk

from cofre import bridge_ops
from cofre.audit import record
from cofre.messages import msg
from cofre.pipe_server import BridgeController
from cofre.serve import SecretServer, allowed_origins_for
from cofre.theme import COLORS
from cofre.threads import assert_main, is_main

PANEL = COLORS["surface"]
PANEL2 = COLORS["card"]
MUT = COLORS["muted"]
OK = COLORS["ok"]


class PuenteGUI:
    """Se mezcla en CofreGUI; no se instancia sola."""

    def ui_call(self, fn, *args, **kwargs) -> None:
        """Pintar desde cualquier hilo: aqui, o encolado al hilo de Tkinter.

        Tkinter no es seguro entre hilos. Los hilos de la tuberia y del TCP
        nunca tocan widgets: encolan y el sondeo los ejecuta en el principal.
        """
        if is_main():
            fn(*args, **kwargs)
            return
        self._ui_cola.put((fn, args, kwargs))

    def _pump_ui(self) -> None:
        """Vaciar la cola de pintado. Solo en el hilo de Tkinter."""
        assert_main("_pump_ui")
        for _ in range(50):
            try:
                fn, args, kwargs = self._ui_cola.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args, **kwargs)
            except Exception:
                pass
        try:
            self.root.after(50, self._pump_ui)
        except Exception:
            pass

    def set_status(self, text, warn=False):
        assert_main("set_status")
        self.status_var.set(text)
        self._draw_pill()
        try:
            if warn:
                self.pill.configure(bg=PANEL)
        except Exception:
            pass

    def _grants_activos(self) -> list[tuple[tuple[str, str], float]]:
        """Los permisos de 5 minutos que siguen vivos, de mas antiguo a mas nuevo."""
        ahora = time.time()
        vivos: dict[tuple[str, str], float] = {}
        for clave, hasta in list(self.confirm_grants.items()):
            try:
                restante = float(hasta) - ahora
            except (TypeError, ValueError):
                continue
            if restante > 0:
                vivos[clave] = float(hasta)
        self.confirm_grants = vivos
        return sorted(vivos.items(), key=lambda kv: kv[1])

    @staticmethod
    def _grant_texto(clave) -> str:
        """'git: github.com' o 'navegador: NOMBRE' a partir de la clave."""
        contexto, quien = (clave if isinstance(clave, tuple) else (clave, ""))
        contexto, quien = str(contexto), str(quien)
        if contexto.lower().startswith("git:"):
            return f"git: {contexto[4:]}"
        if quien.lower().startswith("navegador"):
            return f"navegador: {contexto}"
        return f"{quien.lower()}: {contexto}" if quien else contexto

    def _pump_grants(self) -> None:
        """Cada segundo: cuenta atras y limpieza de permisos caducados."""
        assert_main("_pump_grants")
        self._refrescar_grants()
        try:
            self.root.after(1000, self._pump_grants)
        except Exception:
            pass

    def _refrescar_grants(self) -> None:
        assert_main("_refrescar_grants")
        filas = []
        for clave, hasta in self._grants_activos():
            resta = max(0, int(round(hasta - time.time())))
            filas.append((clave, f"{self._grant_texto(clave)} permitido "
                                 f"{resta // 60}:{resta % 60:02d}"))
        firma = tuple(texto for _clave, texto in filas)
        if firma == self._grants_firma:
            return
        self._grants_firma = firma
        self._dibujar_grants(filas)

    def _dibujar_grants(self, filas: list) -> None:
        for widget in self._grants_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self._grants_widgets = []
        if not filas:
            try:
                self.grants_row.pack_forget()
            except Exception:
                pass
            return
        try:
            self.grants_row.pack(fill="x", padx=16, pady=(0, 6))
        except Exception:
            pass
        etiqueta = tk.Label(self.grants_row, text=msg("permisos.titulo"),
                            fg=MUT, bg=PANEL, font=self.f_small)
        etiqueta.pack(side="left")
        self._grants_widgets.append(etiqueta)
        for clave, texto in filas:
            caja = tk.Frame(self.grants_row, bg=PANEL2)
            caja.pack(side="left", padx=(8, 0))
            lab = tk.Label(caja, text=texto, fg=OK, bg=PANEL2, font=self.f_small)
            lab.pack(side="left", padx=(8, 4), pady=2)
            boton = self._text_btn(caja, msg("permisos.retirar"),
                                   lambda c=clave: self.revocar_permiso(c))
            boton.pack(side="left", padx=(0, 6))
            self._grants_widgets.extend([caja, lab, boton])

    def revocar_permiso(self, clave) -> None:
        """Retirar un permiso temporal antes de que caduque."""
        assert_main("revocar_permiso")
        if self.confirm_grants.pop(clave, None) is None:
            return
        texto = self._grant_texto(clave)
        nombre = str(clave[0] if isinstance(clave, tuple) else clave)[:60]
        record(self.vault_path, "grant-revoke", self.gate, self.serial,
               name=nombre, ok=True, detail=f"permiso retirado a mano: {texto}"[:150])
        self._grants_firma = None
        self._refrescar_grants()
        self.set_foot(msg("permisos.retirado", texto=texto))

    def request_confirm(self, who: str, what: str, contexto: str | None = None,
                        cachear: bool = True) -> str:
        """Pregunta a la persona (2.4).

        Dos caminos, y solo dos:

          - hilo de la GUI (una accion de la ventana): dialogo modal directo,
            como el resto de hojas; `wait_window` corre su propio bucle de Tk;
          - cualquier otro hilo (tuberia, TCP): se encola y **espera aqui**;
            el sondeo abre el dialogo sin bloquearse y le pasa la respuesta.

        `contexto` permite que el permiso de 5 minutos sea por host en git; el
        navegador sigue usando el secreto seleccionado. `cachear=False` (D20) no
        consulta ni guarda ese permiso: lo pide un agente y se confirma siempre.
        """
        if not self.confirm_queue:
            return "deny"
        clave = (contexto or self.selected or what, who.split(" - ")[0])
        if cachear:
            self._grants_activos()      # limpia caducados antes de mirar
            hasta = self.confirm_grants.get(clave)
            if hasta and hasta > time.time():
                return "grant"
        if is_main():
            try:
                from cofre.gui_confirm import ConfirmDialog
                resultado = ConfirmDialog(self.root, who, what).wait()
            except Exception:
                resultado = "deny"
        else:
            resultado = self.confirm_queue.ask(who, what, timeout=30)
        if resultado == "grant" and cachear:
            self.confirm_grants[clave] = time.time() + 300
        return resultado

    def _pump_confirm(self) -> None:
        if not self.confirm_queue:
            return
        assert_main("_pump_confirm")
        try:
            if self.confirm_queue.pump():
                self.root.after(10, self._pump_confirm)
                return
        except Exception:
            pass
        self.root.after(100, self._pump_confirm)

    def toggle_browser(self) -> None:
        if self.bridge or self.bridge_ctl:
            self.stop_bridge()
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

        # La misma tuberia sirve al navegador y al ayudante de git. No se exige
        # la extension: git tambien la usa, y sin ella el navegador simplemente
        # no tiene cliente.
        if self.bridge_ctl is None:
            self.bridge_ctl = BridgeController(
                self.root,
                lambda msg: bridge_ops.dispatch(self, msg),
                # el despacho ya no corre en el hilo de Tk: lo que se pinte,
                # a la cola del hilo principal
                log=lambda m: self.ui_call(self.set_foot, f"puente: {m}"))
        try:
            self.bridge_ctl.start()
        except Exception as exc:                      # noqa: BLE001
            self.set_foot(f"no se pudo crear la tuberia: {exc}")
            self.bridge_ctl = None
            return
        self.browser_on = True
        self.set_foot("tubería local lista (navegador y git)")
        record(self.vault_path, "bridge-start", self.gate, self.serial, ok=True,
               detail="tuberia")

    def _pump_bridge(self) -> None:
        """Se conserva por compatibilidad: el despacho pasa por los hilos de la
        tuberia; aqui solo se comprueba que el servidor sigue vivo."""
        if not self.bridge_ctl:
            return
        try:
            self.bridge_ctl.poll()
        except Exception:
            pass
        self.root.after(2000, self._pump_bridge)

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
        # al cerrar el puente no queda nadie que conteste: se deniega lo
        # pendiente y se cierra el dialogo, si habia uno abierto
        if self.confirm_queue:
            try:
                self.confirm_queue.cancelar()
            except Exception:
                pass
        self.browser_on = False
        self.set_foot("tubería local cerrada (navegador y git)")
