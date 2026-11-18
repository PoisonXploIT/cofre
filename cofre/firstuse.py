"""COFRE - primer uso (paso 6.8): llave, cofre, codigo y reserva.

La creacion es una funcion pura (sin Tk) para poder probarla con un cofre
temporal vacio: `crear_cofre` escribe la llave en la unidad, crea el cofre v2 con
su ranura y un codigo de recuperacion, y registra el pendrive. Nunca pisa un
cofre ni una llave que ya existan.

`Wizard` es la ventana de cinco pasos. El codigo se muestra una sola vez y se
confirma tecleando dos palabras al azar antes de seguir.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import tkinter as tk
from pathlib import Path

from cofre.theme import COLORS as C
from cofre.usb import KEY_FILENAME, register_stick, volume_serial
from cofre.v2 import VaultV2, new_recovery_slot, new_usb_slot
from cofre.v2.recovery import new_code, normalize
from cofre.v2.slots import try_open_slot


def crear_cofre(vault_path, drive: str, clave: str | Path | None = None,
                etiqueta: str = "principal") -> dict:
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
    codigo = new_code()
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
        self.win = app._sheet("COFRE - primera vez")
        self.win.geometry("760x580")
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
        self.cuerpo.pack(fill="both", expand=True, padx=22, pady=18)

    def _titulo(self, texto: str) -> None:
        import tkinter as tk
        tk.Label(self.cuerpo, text=texto, fg=C["text"], bg=C["surface"],
                 font=self.app.f_title, anchor="w",
                 wraplength=700, justify="left").pack(fill="x")

    def _texto(self, texto: str) -> None:
        import tkinter as tk
        tk.Label(self.cuerpo, text=texto, fg=C["muted"], bg=C["surface"],
                 font=self.app.f_body, anchor="w", wraplength=700,
                 justify="left").pack(fill="x", pady=(8, 0))

    def _botonera(self, atras=None, siguiente=None, texto_sig="Siguiente",
                  danger=False):
        import tkinter as tk
        fila = tk.Frame(self.cuerpo, bg=C["surface"])
        fila.pack(fill="x", side="bottom", pady=(16, 0))
        if atras is not None:
            self.app._btn(fila, "Atrás", atras).pack(side="left")
        if siguiente is not None:
            self.app._btn(fila, texto_sig, siguiente,
                          accent=not danger).pack(side="right")
        return fila

    def _paso_bienvenida(self, event=None) -> None:
        self._limpiar()
        self._titulo("COFRE: tu bóveda local")
        self._texto(
            "COFRE guarda tus contraseñas y claves en un fichero cifrado que "
            "vive en este equipo. Nadie puede abrirlo sin tu pendrive o el "
            "código de recuperación de papel.\n\n"
            "Nada sale a internet por abrir el cofre. El navegador solo pide "
            "un valor concreto cuando tú lo pides, y solo en los sitios que "
            "asignes.\n\n"
            "Vamos a preparar la llave del pendrive, el cofre, el código de "
            "recuperación y, si quieres, una reserva.")
        self._botonera(siguiente=self._paso_pendrive, texto_sig="Empezar")

    def _paso_pendrive(self, event=None) -> None:
        import tkinter as tk
        from cofre.usb import DRIVE_FIXED, DRIVE_REMOVABLE, drive_kind, drive_letters
        self._limpiar()
        self._titulo("1. Elige el pendrive principal")
        self._texto("Se escribirá COFRE.KEY en esa unidad y se creará el cofre "
                    "allí donde apunta COFRE_VAULT. Si ya hay una llave o un "
                    "cofre, no se toca nada.")
        sistema = (os.environ.get("SystemDrive", "C:") + "\\").upper()
        letras = [d for d in drive_letters()
                  if drive_kind(d) in (DRIVE_REMOVABLE, DRIVE_FIXED)
                  and d.upper() != sistema]
        if not letras:
            self._texto("No hay ninguna unidad conectada. Enchufa el pendrive "
                        "y vuelve a abrir este asistente.")
            self._botonera(atras=self._paso_bienvenida)
            return
        lista = tk.Listbox(self.cuerpo, bg=C["card"],
                           fg=C["text"], font=self.app.f_mono,
                           relief="flat", bd=0, highlightthickness=0,
                           height=min(6, len(letras)))
        lista.pack(fill="x", pady=10)
        for letra in letras:
            lista.insert("end", letra)
        lista.selection_set(0)
        aviso = tk.Label(self.cuerpo, text="", fg=C["warn"],
                         bg=C["surface"], font=self.app.f_small, anchor="w")
        aviso.pack(fill="x")

        def crear() -> None:
            sel = lista.curselection()
            if not sel:
                return
            drive = letras[sel[0]]
            try:
                estado = crear_cofre(self.app.vault_path, drive)
            except Exception as exc:               # noqa: BLE001
                aviso.configure(text=f"no se pudo crear: {exc}")
                return
            self.datos = estado["data"]
            self.codigo = estado["código"]
            self.master = estado["master"]
            self.llave = estado["llave"]
            self.drive = estado["drive"]
            self._paso_codigo()

        self._botonera(atras=self._paso_bienvenida,
                       siguiente=lambda _e=None: crear(),
                       texto_sig="Crear llave y cofre")

    def _paso_codigo(self, event=None) -> None:
        import tkinter as tk
        self._limpiar()
        self._titulo("2. El código de recuperación")
        self._texto("Estas 25 palabras son la única forma de abrir el cofre si "
                    "pierdes el pendrive. Se muestran UNA vez. Apúntalas en "
                    "papel; no las guardes en el mismo equipo ni en una foto.")
        caja = tk.Text(self.cuerpo, height=5, bg=C["card"],
                       fg=C["text"], font=self.app.f_mono, bd=0,
                       highlightthickness=0, wrap="word")
        caja.pack(fill="x", pady=8)
        caja.insert("end", self.codigo)
        caja.configure(state="disabled")
        fila = tk.Frame(self.cuerpo, bg=C["surface"])
        fila.pack(fill="x")
        self.app._btn(fila, "Imprimir",
                      self._imprimir).pack(side="left")
        self.app._btn(fila, "Copiar",
                      lambda _e=None: self.app._copiar_texto(self.codigo)).pack(
            side="left", padx=8)
        self._botonera(siguiente=self._paso_confirmar,
                       texto_sig="Ya lo he apuntado")

    def _imprimir(self, event=None) -> None:
        """TXT temporal, dialogo de impresion y borrado posterior."""
        try:
            ruta = Path(tempfile.gettempdir()) / "cofre-código-recuperacion.txt"
            ruta.write_text(self.codigo + "\n", encoding="utf-8")
            os.startfile(str(ruta), "print")       # noqa: S606
            self.win.after(60000, lambda: ruta.unlink(missing_ok=True))
            self.app.set_foot("código enviado a imprimir; el temporal se borra en un minuto")
        except Exception as exc:                   # noqa: BLE001
            self.app.set_foot(f"no se pudo imprimir: {exc}")

    def _paso_confirmar(self, event=None) -> None:
        import tkinter as tk
        self._limpiar()
        self._titulo("3. Confirma que lo tienes")
        self._texto("Escribe las dos palabras que se piden, tal como las has "
                    "apuntado.")
        if not self.preguntas:
            self.preguntas = sorted(secrets.SystemRandom().sample(range(1, 25), 2))
        self.campos = []
        for indice in self.preguntas:
            fila = tk.Frame(self.cuerpo, bg=C["surface"])
            fila.pack(fill="x", pady=4)
            tk.Label(fila, text=f"palabra {indice}", fg=C["muted"],
                     bg=C["surface"], font=self.app.f_small,
                     width=12, anchor="w").pack(side="left")
            var = tk.StringVar()
            entrada = tk.Entry(fila, textvariable=var, bg=C["card"],
                               fg=C["text"], insertbackground=C["text"],
                               relief="flat", highlightthickness=1,
                               highlightbackground=C["border"],
                               font=self.app.f_body)
            entrada.pack(side="left", fill="x", expand=True)
            self.campos.append((indice, var))
        self.aviso = tk.Label(self.cuerpo, text="", fg=C["warn"],
                              bg=C["surface"], font=self.app.f_small,
                              anchor="w")
        self.aviso.pack(fill="x")

        def comprobar() -> None:
            respuestas = {indice: var.get() for indice, var in self.campos}
            if not confirmar_palabras(self.codigo, respuestas):
                self.aviso.configure(text="no coincide. Revisa las palabras y "
                                           "vuelve a probar.")
                return
            self._paso_reserva()

        self._botonera(atras=self._paso_codigo,
                       siguiente=lambda _e=None: comprobar(),
                       texto_sig="Confirmar")

    def _paso_reserva(self, event=None) -> None:
        import tkinter as tk
        from cofre.usb import DRIVE_FIXED, DRIVE_REMOVABLE, drive_kind, drive_letters
        self._limpiar()
        self._titulo("4. Pendrive de reserva (recomendado)")
        self._texto("Una segunda llave evita quedarte fuera si falla el "
                    "principal. Se escribe en otra unidad; el cofre recibirá "
                    "una ranura nueva probada antes de guardarse.")
        actual = str(self.drive)[:3].upper()
        letras = [d for d in drive_letters()
                  if drive_kind(d) in (DRIVE_REMOVABLE, DRIVE_FIXED)
                  and d.upper() != actual]
        aviso = tk.Label(self.cuerpo, text="", fg=C["warn"],
                         bg=C["surface"], font=self.app.f_small, anchor="w")
        aviso.pack(fill="x")
        if not letras:
            aviso.configure(text="No hay otra unidad conectada; puedes saltar "
                                 "este paso y añadirla después en Llaves.")
            self._botonera(atras=self._paso_confirmar, siguiente=self._paso_extension,
                           texto_sig="Saltar")
            return
        lista = tk.Listbox(self.cuerpo, bg=C["card"],
                           fg=C["text"], font=self.app.f_mono,
                           relief="flat", bd=0, highlightthickness=0,
                           height=min(6, len(letras)))
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
                aviso.configure(text=f"no se pudo añadir la reserva: {exc}")
                return
            self._paso_extension()

        fila = self._botonera(atras=self._paso_confirmar, siguiente=agregar,
                              texto_sig="Añadir reserva")
        self.app._btn(fila, "Saltar", self._paso_extension).pack(side="right",
                                                                 padx=8)

    def _paso_extension(self, event=None) -> None:
        self._limpiar()
        self._titulo("5. La extensión del navegador (opcional)")
        self._texto("La extensión solo rellena cuando tú pulsas su botón y solo "
                    "en los dominios asignados a cada secreto. Se instala desde "
                    "la carpeta 'extension' del repositorio; la guía explica "
                    "cómo cargarla en el navegador.\n\n"
                    "Puedes terminar ahora y hacerlo cuando quieras.")
        fila = self._botonera(siguiente=self._terminar, texto_sig="Terminar")
        self.app._btn(fila, "Abrir la guía",
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
            self.app.set_foot(f"el cofre está creado, pero no se pudo abrir: {exc}")

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
