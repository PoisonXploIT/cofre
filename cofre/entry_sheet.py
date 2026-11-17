"""COFRE - hoja de alta y edicion de secretos (E6 del rediseño).

Sustituye el formulario que vivia siempre abierto en el detalle. Una hoja modal
con lo necesario y por tipo:

  nombre · tipo · valor · etiquetas · sitios donde se puede rellenar

Generadores y fortaleza viven aquí, no en la ventana principal. Esc cancela,
Ctrl+Enter guarda. No cambia ninguna regla de seguridad: escribe con
`vault.add` y `vault.set_urls`, los mismos metodos que antes.
"""

from __future__ import annotations

import tkinter as tk

from cofre.audit import record
from cofre.gen import entropy, human_password, machine_password
from cofre.hosts import HostsError, clean_host
from cofre.theme import COLORS as C
from cofre.theme import SPACE
from cofre import widgets as W

TIPOS = ("password", "api_key", "api_token", "private_key", "note")


class EntrySheet:
    """mode: 'new' | 'edit'. En edit se precarga el valor y se mantiene el nombre."""

    def __init__(self, app, mode: str = "new", nombre: str | None = None):
        self.app = app
        self.mode = mode
        self.nombre = nombre
        self.guardado = False

        self.win = app._sheet("Nuevo secreto" if mode == "new" else f"Editar {nombre}")
        self.win.geometry("560x520")
        self.win.minsize(480, 440)
        self.win.bind("<Escape>", lambda _e: self.win.destroy())
        self.win.bind("<Control-Return>", lambda _e: self.guardar())

        cuerpo = tk.Frame(self.win, bg=C["surface"])
        cuerpo.pack(fill="both", expand=True, padx=SPACE["lg"], pady=SPACE["lg"])

        tk.Label(cuerpo, text="Nuevo secreto" if mode == "new" else f"Editar {nombre}",
                 fg=C["text"], bg=C["surface"], font=app.f_title,
                 anchor="w").pack(fill="x")
        self.aviso = tk.Label(cuerpo, text="", fg=C["warn"], bg=C["surface"],
                              font=app.f_small, anchor="w")
        self.aviso.pack(fill="x", pady=(2, 8))

        # nombre
        tk.Label(cuerpo, text="nombre (sin espacios, p. ej. TAVILY_API_KEY)",
                 fg=C["faint"], bg=C["surface"], font=app.f_small,
                 anchor="w").pack(fill="x")
        self.campo_nombre = W.Field(cuerpo, width=500, bg=C["surface"])
        self.campo_nombre.pack(anchor="w", pady=(2, 8))
        if nombre:
            self.campo_nombre.set(nombre)
            self.campo_nombre.entry.configure(state="readonly")

        # tipo
        tk.Label(cuerpo, text="tipo (decide por donde puede salir)",
                 fg=C["faint"], bg=C["surface"], font=app.f_small,
                 anchor="w").pack(fill="x")
        self.tipo_var = tk.StringVar(value=self._tipo_actual())
        fila_tipo = tk.Frame(cuerpo, bg=C["surface"])
        fila_tipo.pack(anchor="w", pady=(2, 8))
        for tipo in TIPOS:
            tk.Radiobutton(fila_tipo, text=tipo, value=tipo, variable=self.tipo_var,
                           bg=C["surface"], fg=C["text"], selectcolor=C["card"],
                           activebackground=C["surface"], activeforeground=C["text"],
                           font=app.f_small, bd=0, highlightthickness=0).pack(
                side="left", padx=(0, 8))

        # valor
        tk.Label(cuerpo, text="valor: la contraseña, la clave o el token",
                 fg=C["faint"], bg=C["surface"], font=app.f_small,
                 anchor="w").pack(fill="x")
        fila_valor = tk.Frame(cuerpo, bg=C["surface"])
        fila_valor.pack(fill="x", pady=(2, 4))
        self.campo_valor = W.Field(fila_valor, show="*", width=420, bg=C["surface"],
                                   on_change=self._fortaleza)
        self.campo_valor.pack(side="left")
        self.b_ver = W.Button(fila_valor, "ver", kind="text", bg=C["surface"],
                              command=self._alternar_ver)
        self.b_ver.pack(side="left", padx=(6, 0))
        self.fuerza = tk.Label(cuerpo, text="fuerza: sin valor", fg=C["faint"],
                               bg=C["surface"], font=app.f_small, anchor="w")
        self.fuerza.pack(fill="x")

        generadores = tk.Frame(cuerpo, bg=C["surface"])
        generadores.pack(fill="x", pady=(6, 8))
        for texto, comando in (("Para maquina", lambda: self._generar("machine")),
                               ("4 palabras", lambda: self._generar("words", 4)),
                               ("6 palabras", lambda: self._generar("words", 6))):
            W.Button(generadores, texto, kind="secondary", bg=C["surface"],
                     command=comando).pack(side="left", padx=(0, 6))

        # etiquetas y sitios
        tk.Label(cuerpo, text="etiquetas (separadas por coma)", fg=C["faint"],
                 bg=C["surface"], font=app.f_small, anchor="w").pack(fill="x")
        self.campo_tags = W.Field(cuerpo, width=500, bg=C["surface"])
        self.campo_tags.pack(anchor="w", pady=(2, 8))
        tk.Label(cuerpo, text="sitios donde se puede rellenar (separados por coma, "
                              "opcional)", fg=C["faint"], bg=C["surface"],
                 font=app.f_small, anchor="w").pack(fill="x")
        self.campo_sitios = W.Field(cuerpo, width=500, bg=C["surface"])
        self.campo_sitios.pack(anchor="w", pady=(2, 10))

        pie = tk.Frame(cuerpo, bg=C["surface"])
        pie.pack(fill="x")
        if mode == "edit":
            W.Button(pie, "Copiar nombre", kind="text", bg=C["surface"],
                     command=lambda: app.copy_name()).pack(side="left")
            W.Button(pie, "Renombrar...", kind="text", bg=C["surface"],
                     command=self._renombrar).pack(side="left", padx=(8, 0))
        W.Button(pie, "Cancelar", kind="secondary", bg=C["surface"],
                 command=self.win.destroy).pack(side="right")
        W.Button(pie, "Guardar", kind="primary", bg=C["surface"],
                 command=self.guardar).pack(side="right", padx=(0, 8))

        self._precargar()
        self.campo_valor.focus()
        try:
            self.win.grab_set()
        except Exception:
            pass

    # ------------------------------------------------------------ datos

    def _meta(self) -> dict:
        if not self.nombre:
            return {}
        try:
            return dict(self.app.vault.meta(self.nombre) or {})
        except Exception:
            return {}

    def _tipo_actual(self) -> str:
        tipo = str(self._meta().get("type") or "")
        return tipo if tipo in TIPOS else ("password" if self.mode == "edit" else "api_key")

    def _precargar(self) -> None:
        if self.mode != "edit" or not self.nombre:
            return
        meta = self._meta()
        self.campo_tags.set(", ".join(meta.get("tags") or []))
        try:
            self.campo_sitios.set(", ".join(self.app.vault.urls(self.nombre)))
        except Exception:
            pass
        try:
            valor = self.app.vault.get(self.app.session, self.nombre)
            self.campo_valor.set(valor)
            self._fortaleza(valor)
        except Exception as exc:                      # noqa: BLE001
            self.aviso.configure(text=f"no se pudo leer el valor: {exc}")

    def _renombrar(self) -> None:
        """Renombrar desde la hoja. El valor no se toca."""
        app = self.app
        nuevo = app._ask_text("Renombrar", f"Nuevo nombre para '{self.nombre}'",
                              "NUEVO_NOMBRE")
        if not nuevo or nuevo == self.nombre:
            return
        try:
            ok = app.vault.rename(app.session, self.nombre, nuevo)
        except Exception as exc:                      # noqa: BLE001
            self.aviso.configure(text=f"no se pudo renombrar: {exc}")
            return
        if not ok:
            self.aviso.configure(text="no se pudo renombrar (ese nombre ya existe)")
            return
        record(app.vault_path, "rename", app.gate, app.serial, name=nuevo)
        app.selected = nuevo
        app.refresh_list()
        app.select(nuevo)
        app.set_foot(f"renombrado a '{nuevo}'")
        self.win.destroy()

    # ------------------------------------------------------------ acciones

    def _alternar_ver(self) -> None:
        if str(self.campo_valor.entry.cget("show")) == "*":
            self.campo_valor.entry.configure(show="")
            self.b_ver.set_text("ocultar")
        else:
            self.campo_valor.entry.configure(show="*")
            self.b_ver.set_text("ver")

    def _generar(self, kind: str, palabras: int = 5) -> None:
        if kind == "machine":
            valor = machine_password()
        else:
            valor = human_password(words=palabras, lang="es")
        self.campo_valor.set(valor)
        self._fortaleza(valor)
        info = entropy(words=palabras, lang="es") if kind != "machine" else {}
        self.fuerza.configure(
            text=("384 bits (48 bytes aleatorios)" if kind == "machine"
                  else f"{info.get('bits', '?')} bits con {info.get('lista', '?')} palabras"))

    def _fortaleza(self, valor: str) -> None:
        if not valor:
            self.fuerza.configure(text="fuerza: sin valor")
            return
        import math
        chars = set(valor)
        bits = len(valor) * math.log2(max(len(chars), 2))
        etiqueta = "debil" if bits < 40 else "aceptable" if bits < 60 else "fuerte"
        self.fuerza.configure(text=f"fuerza: {etiqueta}  ({len(valor)} caracteres, "
                                   f"~{bits:.0f} bits)")

    def guardar(self) -> None:
        app = self.app
        nombre = (self.nombre if self.mode == "edit"
                  else self.campo_nombre.get().strip())
        valor = self.campo_valor.get()
        if not nombre:
            self.aviso.configure(text="falta el nombre")
            return
        if not valor:
            self.aviso.configure(text="falta el valor")
            return
        tags = [t.strip() for t in self.campo_tags.get().split(",") if t.strip()]
        sitios = []
        for parte in self.campo_sitios.get().split(","):
            parte = parte.strip()
            if not parte:
                continue
            try:
                sitios.append(clean_host(parte))
            except HostsError as exc:
                self.aviso.configure(text=f"sitio invalido: {exc}")
                return
        tipo = self.tipo_var.get()
        try:
            if app.vault.is_v2():
                app.vault.add(app.session, nombre, valor, tags, sitios)
                app.vault._v2store()._data["entries"]  # noqa: B018  (fuerza el refresco)
            else:
                app.vault.add(app.session, nombre, valor, tags)
                if sitios:
                    app.vault.set_urls(nombre, sitios)
            if app.vault.is_v2():
                store = app.vault._v2store()
                idx = store.index(store._data, store.master)
                entrada = (idx.get("entries") or {}).get(nombre)
                if entrada is not None:
                    entrada["type"] = tipo
                    store._write_index(store._data, store.master, idx)
                    store.save(store._data)
        except Exception as exc:                      # noqa: BLE001
            self.aviso.configure(text=f"no se pudo guardar: {exc}")
            return
        record(app.vault_path, "add" if self.mode == "new" else "edit",
               app.gate, app.serial, name=nombre, ok=True)
        self.guardado = True
        app.selected = nombre
        app.refresh_list()
        try:
            app.select(nombre)
        except Exception:
            pass
        app.set_foot(f"guardado '{nombre}'")
        self.win.destroy()
