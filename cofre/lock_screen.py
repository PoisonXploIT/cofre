"""COFRE - pantalla de bloqueo (E3 del rediseño).

Sustituye la sensacion de "cerrado y abierto se ven casi igual": al bloquear, un
panel cubre la ventana con el candado, el estado de las llaves, el PIN si el gate
lo pide y el boton de abrir. El pie se queda visible, porque ahi va el motivo del
bloqueo (Session.describe).

No decide nada de seguridad: llama a los mismos metodos que la cabecera
(`unlock`, `lock`) y lee el mismo `stick_report`.
"""

from __future__ import annotations

import tkinter as tk

from cofre.theme import COLORS as C
from cofre.theme import SPACE
from cofre import widgets as W

GLIFO_CANDADO = "\ue72e"
GLIFO_LLAVE = "\ue8d7"


class LockScreen(tk.Frame):
    """Capa a pantalla completa que se eleva al bloquear."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"], bd=0, highlightthickness=0)
        self.app = app
        self._construir()

    # ------------------------------------------------------------ dibujo

    def _construir(self) -> None:
        # Sin altura fija: con `usb-pin` el campo PIN y el aviso empujan el
        # contenido y, con el height=430 de antes, se cortaba por abajo (el campo
        # PIN y el boton quedaban fuera del marco). Ahora el marco mide lo que
        # mide su contenido y se centra en la capa.
        centro = tk.Frame(self, bg=C["bg"], width=460)
        centro.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(centro, text=GLIFO_CANDADO, fg=C["accent"], bg=C["bg"],
                 font=(self._icon_family(), 46)).pack()
        tk.Label(centro, text="COFRE", fg=C["text"], bg=C["bg"],
                 font=self._font("display")).pack(pady=(SPACE["md"], 0))
        self.motivo = tk.Label(centro, text="la llave no esta en memoria",
                               fg=C["muted"], bg=C["bg"], font=self._font("label"))
        self.motivo.pack(pady=(2, SPACE["xl"]))

        caja = tk.Frame(centro, bg=C["surface"], highlightthickness=1,
                        highlightbackground=C["border"])
        caja.pack(fill="x")
        tk.Label(caja, text="LLAVES QUE ABREN ESTE COFRE", fg=C["faint"],
                 bg=C["surface"], font=self._font("label"),
                 anchor="w").pack(fill="x", padx=SPACE["lg"], pady=(SPACE["md"], 6))
        self.llaves = tk.Frame(caja, bg=C["surface"])
        self.llaves.pack(fill="x", padx=SPACE["lg"])
        self.sin_llave = tk.Label(caja, text="conecta un pendrive del cofre",
                                  fg=C["muted"], bg=C["surface"],
                                  font=self._font("label"), anchor="w")
        self.sin_llave.pack(fill="x", padx=SPACE["lg"], pady=(0, SPACE["md"]))

        # PIN: solo si el gate lo pide
        self.pin_box = tk.Frame(centro, bg=C["bg"])
        tk.Label(self.pin_box, text="PIN", fg=C["faint"], bg=C["bg"],
                 font=self._font("label"), anchor="w").pack(fill="x",
                                                            pady=(SPACE["md"], 2))
        self.pin_field = W.Field(self.pin_box, placeholder="PIN del cofre",
                                 show="*", width=320, bg=C["bg"])
        self.pin_field.pack(anchor="w")

        acciones = tk.Frame(centro, bg=C["bg"])
        acciones.pack(fill="x", pady=(SPACE["xl"], 0))
        # el PIN va justo debajo de las llaves y ANTES de los botones; antes se
        # empaquetaba al final (despues del texto de recuperacion) y quedaba
        # abajo del todo, cortado y sin poder confirmar (2026-11-20)
        self.acciones = acciones
        self.b_abrir = W.Button(acciones, "Abrir el cofre", kind="primary",
                                command=self._abrir, bg=C["bg"])
        self.b_abrir.pack(side="left")
        self.b_reconectar = W.Button(acciones, "Reconectar", kind="secondary",
                                     command=self._reconectar, bg=C["bg"])
        self.b_reconectar.pack(side="left", padx=(SPACE["sm"], 0))

        self.recuperacion = tk.Label(
            centro, text="¿Perdiste los pendrives? El código de recuperacion\n"
                         "se usa desde la consola: run.cmd get NOMBRE --recovery",
            fg=C["faint"], bg=C["bg"], font=self._font("label"), justify="left")
        self.recuperacion.pack(pady=(SPACE["lg"], 0), anchor="w")

        self.bind("<Return>", lambda _e: self._abrir())

    # ------------------------------------------------------------ ayudas

    def _font(self, role: str):
        if role == "display":
            return self.app.f_title        # 13 pt bold: el rol display del tema
        if role == "title":
            return self.app.f_sub
        return self.app.f_small

    def _icon_family(self) -> str:
        return "Segoe Fluent Icons"

    def _abrir(self):
        if getattr(self.app, "pin_field", None) is not None:
            self.app.pin_var.set(self.pin_field.get())
        self.app.unlock()

    def _reconectar(self):
        self.app.refresh_sticks()
        self.app.refresh_wizard()
        self.app.set_foot("buscando el pendrive otra vez...")
        self.app.unlock()

    # ------------------------------------------------------------ estado

    def refrescar(self, motivo: str = "") -> None:
        """Repinta llaves y motivo.

        Se llama al bloquear y **en cada sondeo** (cada 2 s). Antes destruia y
        volvia a crear las filas siempre: la pantalla de bloqueo titilaba todo el
        rato. Ahora solo se repinta si cambia algo de verdad (una llave que entra
        o sale, o el gate); el motivo se toca solo si es otro texto.
        """
        if motivo and self.motivo.cget("text") != motivo:
            self.motivo.configure(text=motivo)
        filas = self.app.stick_report()
        firma = (tuple((str(d.get("drive")), str(d.get("role")),
                        bool(d.get("present"))) for d in filas[:3]), self.app.gate)
        if firma == getattr(self, "_firma", None):
            return
        self._firma = firma
        for w in self.llaves.winfo_children():
            w.destroy()
        if not filas:
            self.sin_llave.pack(fill="x", padx=SPACE["lg"], pady=(0, SPACE["md"]))
        else:
            self.sin_llave.pack_forget()
            for datos in filas[:3]:
                conectada = datos.get("present")
                texto = (f"{GLIFO_LLAVE}  {datos.get('drive') or datos.get('serial')}  "
                         f"· {datos.get('role', '')}  · ")
                fila = tk.Frame(self.llaves, bg=C["surface"])
                fila.pack(fill="x", pady=2)
                tk.Label(fila, text=texto, fg=C["text"], bg=C["surface"],
                         font=self._font("label"), anchor="w").pack(side="left")
                tk.Label(fila, text="conectada" if conectada else "no conectada",
                         fg=C["ok"] if conectada else C["faint"], bg=C["surface"],
                         font=self._font("label")).pack(side="left")
        if self.app.gate == "usb-pin":
            if not self.pin_box.winfo_ismapped():
                self.pin_box.pack(fill="x", pady=(SPACE["md"], 0),
                                  before=self.acciones)
        elif self.pin_box.winfo_ismapped():
            self.pin_box.pack_forget()
        if self.b_abrir._estado != ("normal" if filas else "disabled"):
            self.b_abrir.set_enabled(bool(filas))
        texto_sin = "conecta un pendrive del cofre" if not filas else ""
        if self.sin_llave.cget("text") != texto_sin:
            self.sin_llave.configure(text=texto_sin)

    def mostrar(self, motivo: str = "") -> None:
        self.refrescar(motivo)
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lift()

    def ocultar(self) -> None:
        self.place_forget()
