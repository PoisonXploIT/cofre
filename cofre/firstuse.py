"""COFRE - primer uso (paso 6.8): llave, cofre, codigo y reserva.

La creacion es una funcion pura (sin Tk) para poder probarla con un cofre
temporal vacio: `crear_cofre` escribe la llave en la unidad, crea el cofre v2 con
su ranura y un codigo de recuperacion, y registra el pendrive. Nunca pisa un
cofre ni una llave que ya existan.

`Wizard` es la ventana de cinco pasos (bienvenida, pendrive, codigo con
confirmacion, reserva y extension). El codigo se genera antes de crear nada, se
muestra como cuadricula numerada 5x5 y no se puede copiar al portapapeles: solo
imprimir o apuntarlo a mano.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import tkinter as tk
from pathlib import Path

from cofre import widgets as W
from cofre.messages import msg
from cofre.theme import COLORS as C
from cofre.usb import KEY_FILENAME, register_stick, volume_serial
from cofre.v2 import VaultV2, new_recovery_slot, new_usb_slot
from cofre.v2.recovery import new_code, normalize
from cofre.v2.slots import try_open_slot

ICON_FONT = "Segoe Fluent Icons"
GLIFO_CANDADO = "\ue72e"
GLIFO_LLAVE = "\ue8d7"

TEXTO_BIENVENIDA = msg("primer_uso.bienvenida_texto")


def crear_cofre(vault_path, drive: str, clave: str | Path | None = None,
                etiqueta: str = "principal",
                recovery_code: str | None = None) -> dict:
    """Crear llave y cofre v2 nuevos. Devuelve el estado (incluye el código)."""
    vault = Path(vault_path)
    if vault.exists() and vault.stat().st_size > 0:
        raise FileExistsError("ya existe un cofre en esa ruta")
    llave_path = Path(clave) if clave else Path(drive) / KEY_FILENAME
    if llave_path.exists():
        raise FileExistsError(f"ya hay una llave en {llave_path}")
    serial = volume_serial(str(drive))
    if serial is None:
        raise ValueError("no se puede leer el serial de esa unidad")
    llave = secrets.token_bytes(32)
    llave_path.parent.mkdir(parents=True, exist_ok=True)
    llave_path.write_bytes(llave)
    master = secrets.token_bytes(32)
    v2 = VaultV2(vault)
    datos = v2.create(master, new_usb_slot(master, llave, serial, etiqueta, ""))
    codigo = recovery_code or new_code()
    datos["slots"].append(new_recovery_slot(master, codigo, "recuperacion"))
    v2.save(datos)
    if try_open_slot(datos["slots"][0], llave) != master:
        raise RuntimeError("la llave nueva no abre la ranura; no se ha guardado")
    register_stick(str(vault), serial, str(drive))
    return {"vault": str(vault), "llave": str(llave_path), "serial": serial,
            "código": codigo, "master": master, "data": datos,
            "drive": str(drive)}


def agregar_reserva(vault_path, datos: dict, master: bytes, drive: str,
                    clave: str | Path | None = None) -> dict:
    """Añadir una llave de reserva al cofre recien creado, probándola antes."""
    llave_path = Path(clave) if clave else Path(drive) / KEY_FILENAME
    if llave_path.exists():
        raise FileExistsError(f"ya hay una llave en {llave_path}")
    serial = volume_serial(str(drive))
    if serial is None:
        raise ValueError("no se puede leer el serial de esa unidad")
    llave = secrets.token_bytes(32)
    llave_path.parent.mkdir(parents=True, exist_ok=True)
    llave_path.write_bytes(llave)
    slot = new_usb_slot(master, llave, serial, "reserva", "")
    if try_open_slot(slot, llave) != master:
        llave_path.unlink(missing_ok=True)
        raise RuntimeError("la llave de reserva no abre; no se ha añadido")
    datos["slots"].append(slot)
    VaultV2(vault_path).save(datos)
    register_stick(str(vault_path), serial, str(drive), role="reserva")
    return {"llave": str(llave_path), "serial": serial, "slot": slot}


def confirmar_palabras(codigo: str, respuestas: dict[int, str]) -> bool:
    """Comprobar las palabras pedidas (1..24), sin distinguir tildes ni caja."""
    partes = normalize(codigo).split()
    for indice, texto in respuestas.items():
        if not 1 <= int(indice) <= len(partes) - 1:
            return False
        if normalize(texto or "") != partes[int(indice) - 1]:
            return False
    return True


class Wizard:
    """Ventana de primer uso. Modal, cinco pasos y sin dependencias."""

    PASOS = 5

    def __init__(self, app):
        self.app = app
        self.win = app._sheet(msg("primer_uso.titulo"))
        self.win.geometry("780x620")
        self.win.minsize(680, 520)
        self.cuerpo = None
        self.datos = None
        self.codigo = ""
        self.master = None
        self.llave = ""
        self.drive = ""
        self.preguntas: list[int] = []
        self.win.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.win.bind("<Escape>", lambda _e: self.cerrar())
        try:
            self.win.grab_set()
        except Exception:
            pass
        self._paso_bienvenida()

    # ------------------------------------------------------------ pintura

    def _limpiar(self) -> None:
        if self.cuerpo is not None:
            self.cuerpo.destroy()
        self.cuerpo = tk.Frame(self.win, bg=C["surface"])
        self.cuerpo.pack(fill="both", expand=True, padx=22, pady=16)

    def _indicador(self, paso: int, nota: str = "") -> None:
        fila = tk.Frame(self.cuerpo, bg=C["surface"])
        fila.pack(fill="x", pady=(0, 10))
        texto = msg("primer_uso.paso", paso=paso, total=self.PASOS) + (
            f" · {nota}" if nota else "")
        tk.Label(fila, text=texto, fg=C["muted"], bg=C["surface"],
                 font=self.app.f_small, anchor="w").pack(side="left")
        puntos = tk.Frame(fila, bg=C["surface"])
        puntos.pack(side="left", padx=(10, 0))
        for numero in range(1, self.PASOS + 1):
            punto = tk.Canvas(puntos, width=10, height=10, bg=C["surface"],
                              highlightthickness=0)
            punto.create_oval(2, 2, 8, 8,
                              fill=C["accent"] if numero <= paso else C["border"],
                              outline="")
            # de izquierda a derecha: el paso 1 enciende el primer punto
            punto.pack(side="left", padx=(0, 4))

    def _titulo(self, texto: str) -> None:
        tk.Label(self.cuerpo, text=texto, fg=C["text"], bg=C["surface"],
                 font=self.app.f_title, anchor="w", wraplength=720,
                 justify="left").pack(fill="x")

    def _texto(self, texto: str) -> None:
        tk.Label(self.cuerpo, text=texto, fg=C["muted"], bg=C["surface"],
                 font=self.app.f_body, anchor="w", wraplength=720,
                 justify="left").pack(fill="x", pady=(8, 0))

    def _botonera(self, atras=None, siguiente=None,
                  texto_sig: str | None = None):
        fila = tk.Frame(self.cuerpo, bg=C["surface"])
        fila.pack(fill="x", side="bottom", pady=(16, 0))
        if atras is not None:
            self.app._btn(fila, msg("comun.atras"), atras).pack(side="left")
        if siguiente is not None:
            self.app._btn(fila, texto_sig or msg("comun.siguiente"), siguiente,
                          accent=True).pack(side="right")
        return fila

    # ------------------------------------------------------------ pasos

    def _paso_bienvenida(self, event=None) -> None:
        self._limpiar()
        self._indicador(1)
        centro = tk.Frame(self.cuerpo, bg=C["surface"])
        centro.pack(expand=True)
        tk.Label(centro, text=GLIFO_CANDADO, fg=C["accent"],
                 bg=C["surface"], font=(ICON_FONT, 48)).pack()
        tk.Label(centro, text=msg("primer_uso.bienvenida"), fg=C["text"],
                 bg=C["surface"], font=self.app.f_title, pady=10).pack()
        tk.Label(centro, text=TEXTO_BIENVENIDA, fg=C["muted"],
                 bg=C["surface"], font=self.app.f_body, wraplength=600,
                 justify="center").pack()
        self.app._btn(centro, msg("primer_uso.empezar"),
                      lambda _e=None: self._paso_pendrive(),
                      accent=True).pack(pady=(20, 0))

    def _paso_pendrive(self, event=None) -> None:
        from cofre.usb import DRIVE_FIXED, DRIVE_REMOVABLE, drive_kind, drive_letters
        self._limpiar()
        self._indicador(2)
        self._titulo(msg("primer_uso.pendrive"))
        self._texto(msg("primer_uso.pendrive_texto"))
        sistema = (os.environ.get("SystemDrive", "C:") + "\\").upper()
        letras = [d for d in drive_letters()
                  if drive_kind(d) in (DRIVE_REMOVABLE, DRIVE_FIXED)
                  and d.upper() != sistema]
        if not letras:
            self._texto(msg("primer_uso.sin_unidades"))
            self._botonera(atras=self._paso_bienvenida)
            return
        lista = tk.Listbox(self.cuerpo, bg=C["card"], fg=C["text"],
                           font=self.app.f_mono, relief="flat", bd=0,
                           highlightthickness=0, height=min(6, len(letras)))
        lista.pack(fill="x", pady=10)
        for letra in letras:
            lista.insert("end", letra)
        lista.selection_set(0)
        aviso = tk.Label(self.cuerpo, text="", fg=C["warn"],
                         bg=C["surface"], font=self.app.f_small, anchor="w")
        aviso.pack(fill="x")

        def seguir() -> None:
            sel = lista.curselection()
            if not sel:
                return
            self.drive = letras[sel[0]]
            self.codigo = new_code()
            self._paso_codigo()

        self._botonera(atras=self._paso_bienvenida,
                       siguiente=lambda _e=None: seguir(),
                       texto_sig=msg("primer_uso.generar"))

    def _paso_codigo(self, event=None) -> None:
        self._limpiar()
        self._indicador(3, msg("primer_uso.paso_codigo"))
        self._titulo("Código de recuperación")
        self._texto(msg("primer_uso.codigo_texto"))
        # pie fijo abajo: se empaqueta antes que la cuadricula para que nunca
        # quede fuera (el boton de seguir se perdia en ventanas bajas)
        pie = tk.Frame(self.cuerpo, bg=C["surface"])
        pie.pack(side="bottom", fill="x", pady=(10, 0))
        if self.datos is None:
            self.app._btn(pie, msg("comun.atras"),
                          self._volver_al_pendrive).pack(side="left")
        self.app._btn(pie, msg("primer_uso.imprimir"),
                      self._imprimir).pack(side="left", padx=(8, 0))
        self.app._btn(pie, msg("primer_uso.apuntado"),
                      self._paso_confirmar,
                      accent=True).pack(side="right")
        W.CodeGrid(self.cuerpo, self.codigo).pack(fill="x", pady=8)

    def _volver_al_pendrive(self, event=None) -> None:
        """Volver antes de crear: el código anterior deja de valer."""
        self.codigo = ""
        self.preguntas = []
        self._paso_pendrive()

    def _imprimir(self, event=None) -> None:
        """TXT temporal numerado, dialogo de impresion y borrado posterior."""
        try:
            ruta = Path(tempfile.gettempdir()) / "cofre-código-recuperacion.txt"
            partes = self.codigo.split()
            lineas = []
            for inicio in range(0, len(partes), 5):
                trozo = partes[inicio:inicio + 5]
                lineas.append("   ".join(f"{inicio + i + 1}. {palabra}"
                                         for i, palabra in enumerate(trozo)))
            ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
            os.startfile(str(ruta), "print")       # noqa: S606
            self.win.after(60000, lambda: ruta.unlink(missing_ok=True))
            self.app.set_foot(msg("primer_uso.impreso"))
        except Exception as exc:                   # noqa: BLE001
            self.app.set_foot(msg("primer_uso.error_imprimir", error=exc))

    def _paso_confirmar(self, event=None) -> None:
        self._limpiar()
        self._indicador(3, msg("primer_uso.paso_confirmar"))
        self._titulo("Confirma que lo tienes")
        self._texto(msg("primer_uso.confirmar_texto"))
        if not self.preguntas:
            self.preguntas = sorted(secrets.SystemRandom().sample(range(1, 25), 2))
        self.campos = []
        for indice in self.preguntas:
            fila = tk.Frame(self.cuerpo, bg=C["surface"])
            fila.pack(fill="x", pady=4)
            tk.Label(fila, text=msg("primer_uso.palabra", numero=indice),
                     fg=C["muted"], bg=C["surface"], font=self.app.f_small,
                     width=14, anchor="w").pack(side="left")
            var = tk.StringVar()
            entrada = tk.Entry(fila, textvariable=var, bg=C["card"],
                               fg=C["text"], insertbackground=C["text"],
                               relief="flat", highlightthickness=1,
                               highlightbackground=C["border"],
                               font=self.app.f_body)
            entrada.pack(side="left", fill="x", expand=True)
            self.campos.append((indice, var))
        self.aviso = tk.Label(self.cuerpo, text="", fg=C["warn"],
                              bg=C["surface"], font=self.app.f_small, anchor="w")
        self.aviso.pack(fill="x")

        def comprobar() -> None:
            respuestas = {indice: var.get() for indice, var in self.campos}
            if not confirmar_palabras(self.codigo, respuestas):
                self.aviso.configure(text=msg("comun.no_coincide"))
                return
            if self.datos is None:
                try:
                    estado = crear_cofre(self.app.vault_path, self.drive,
                                         recovery_code=self.codigo)
                except Exception as exc:           # noqa: BLE001
                    self.aviso.configure(
                        text=msg("primer_uso.error_crear", error=exc))
                    return
                self.datos = estado["data"]
                self.master = estado["master"]
                self.llave = estado["llave"]
            self._paso_reserva()

        self._botonera(atras=self._paso_codigo,
                       siguiente=lambda _e=None: comprobar(),
                       texto_sig=msg("primer_uso.confirmar_boton"))

    def _paso_reserva(self, event=None) -> None:
        from cofre.usb import DRIVE_FIXED, DRIVE_REMOVABLE, drive_kind, drive_letters
        self._limpiar()
        self._indicador(4)
        self._titulo(msg("primer_uso.reserva"))
        self._texto(msg("primer_uso.reserva_texto"))
        actual = str(self.drive)[:3].upper()
        letras = [d for d in drive_letters()
                  if drive_kind(d) in (DRIVE_REMOVABLE, DRIVE_FIXED)
                  and d.upper() != actual]
        aviso = tk.Label(self.cuerpo, text="", fg=C["warn"],
                         bg=C["surface"], font=self.app.f_small, anchor="w")
        aviso.pack(fill="x")
        if not letras:
            aviso.configure(text=msg("primer_uso.sin_reserva"))
            self._botonera(atras=self._paso_confirmar,
                           siguiente=self._paso_extension,
                           texto_sig=msg("primer_uso.saltar"))
            return
        lista = tk.Listbox(self.cuerpo, bg=C["card"], fg=C["text"],
                           font=self.app.f_mono, relief="flat", bd=0,
                           highlightthickness=0, height=min(6, len(letras)))
        lista.pack(fill="x", pady=8)
        for letra in letras:
            lista.insert("end", letra)
        lista.selection_set(0)

        def agregar() -> None:
            sel = lista.curselection()
            if not sel:
                return
            try:
                agregar_reserva(self.app.vault_path, self.datos, self.master,
                                letras[sel[0]])
            except Exception as exc:               # noqa: BLE001
                aviso.configure(text=msg("primer_uso.error_reserva",
                                         error=exc))
                return
            self._paso_extension()

        fila = self._botonera(atras=self._paso_confirmar,
                              siguiente=lambda _e=None: agregar(),
                              texto_sig=msg("primer_uso.anadir_reserva"))
        self.app._btn(fila, msg("primer_uso.saltar"),
                      self._paso_extension).pack(side="right", padx=8)

    def _paso_extension(self, event=None) -> None:
        self._limpiar()
        self._indicador(5)
        self._titulo(msg("primer_uso.extension"))
        self._texto(msg("primer_uso.extension_texto"))
        fila = self._botonera(siguiente=self._terminar,
                              texto_sig=msg("primer_uso.terminar"))
        self.app._btn(fila, msg("primer_uso.abrir_guia"),
                      self.app.open_guide).pack(side="left", padx=8)

    def _terminar(self, event=None) -> None:
        llave = self.llave
        self.codigo = ""
        self.master = None
        self.datos = None
        self.cerrar()
        try:
            self.app.stick = str(llave)
            self.app.vault.reset_store()
            self.app.unlock()
        except Exception as exc:                   # noqa: BLE001
            self.app.set_foot(msg("primer_uso.error_abrir", error=exc))

    def cerrar(self) -> None:
        self.codigo = ""
        self.master = None
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
