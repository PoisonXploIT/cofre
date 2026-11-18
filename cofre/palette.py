"""COFRE - paleta de comandos (paso 6.4).

Ctrl+K abre una lista que busca **secretos y acciones**. Enter ejecuta la
elegida. No salta ninguna politica: copiar pasa por `copy_to_clipboard`, que
comprueba el canal `clipboard`, y rotar pide confirmacion y usa el CLI (que
respeta el diario, el administrador y los destinos).

El catalogo y el filtro son funciones puras para poder probarlos sin abrir una
ventana: `catalogo(app)` y `filtrar(items, texto)`.
"""

from __future__ import annotations

import tkinter as tk

from cofre.theme import COLORS as C
from cofre.theme import dark_titlebar
from cofre.v2.recovery import normalize


def _puede_rotar(meta: dict) -> bool:
    proveedor = str(meta.get("provider") or "")
    if not proveedor:
        return False
    try:
        from cofre.providers import get as provider_get
        return bool(getattr(provider_get(proveedor), "can_auto_rotate", False))
    except Exception:                              # noqa: BLE001
        return False


def catalogo(app) -> list[tuple[str, object]]:
    """Lista de (texto, accion). Las acciones se ejecutan en el hilo de Tk."""
    items: list[tuple[str, object]] = []
    items.append(("Bloquear el cofre", app.lock))
    items.append(("Comprobar salud de las credenciales",
                  lambda: (app.open_health(), app._comprobar_salud())))
    items.append(("Nuevo secreto", app._focus_new))
    items.append(("Ajustes", app.open_settings))
    items.append(("Llaves y recuperación", app.open_keys))
    items.append(("Registro de accesos", app.open_audit))
    items.append(("Guía de uso", app.open_guide))
    items.append(("Atajos de teclado", app.open_shortcuts))
    items.append(("Buscar en la lista", lambda: app.query_entry.focus_set()))
    if getattr(app, "session", None):
        for nombre in app.vault.names():
            meta = dict(app.vault.meta(nombre) or {})
            items.append((f"Abrir {nombre}", lambda n=nombre: app.select(n)))
            items.append((f"Copiar {nombre}",
                          lambda n=nombre: _copiar(app, n)))
            if _puede_rotar(meta):
                items.append((f"Rotar {nombre}",
                              lambda n=nombre: app._rotar_para_paleta(n)))
    return items


def filtrar(items: list[tuple[str, object]], texto: str) -> list[tuple[str, object]]:
    consulta = normalize(texto or "")
    if not consulta:
        return list(items)
    return [item for item in items if consulta in normalize(item[0])]


def _copiar(app, nombre: str) -> None:
    app.select(nombre)
    app.copy_to_clipboard()


class Palette:
    """Ventana modal pequena: campo, lista y Enter. Sin dependencias."""

    def __init__(self, app):
        self.app = app
        self.items = catalogo(app)
        self.visibles = list(self.items)
        self.win = tk.Toplevel(app.root)
        self.win.title("COFRE - comandos")
        self.win.configure(bg=C["surface"])
        self.win.geometry("660x440")
        self.win.transient(app.root)
        try:
            dark_titlebar(self.win)
        except Exception:
            pass

        cabecera = tk.Frame(self.win, bg=C["surface"])
        cabecera.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(cabecera, text="Buscar secretos y acciones", fg=C["muted"],
                 bg=C["surface"], font=app.f_small, anchor="w").pack(fill="x")
        self.entrada = tk.Entry(cabecera, bg=C["card"], fg=C["text"],
                                font=app.f_body, relief="flat", bd=0,
                                insertbackground=C["text"],
                                highlightthickness=1,
                                highlightbackground=C["border"],
                                highlightcolor=C["accent"])
        self.entrada.pack(fill="x", pady=(4, 0), ipady=6)

        marco = tk.Frame(self.win, bg=C["surface"])
        marco.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        self.lista = tk.Listbox(marco, bg=C["card"], fg=C["text"],
                                selectbackground=C["accent"],
                                selectforeground=C["on_accent"],
                                font=app.f_mono, relief="flat", bd=0,
                                highlightthickness=0, activestyle="none")
        barra = tk.Scrollbar(marco, command=self.lista.yview)
        self.lista.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.lista.pack(side="left", fill="both", expand=True)

        self.aviso = tk.Label(self.win, text="", fg=C["muted"],
                              bg=C["surface"], font=app.f_small, anchor="w")
        self.aviso.pack(fill="x", padx=14)
        tk.Label(self.win, text="Enter ejecuta  ·  flechas mueven  ·  Esc cierra",
                 fg=C["faint"], bg=C["surface"], font=app.f_small,
                 anchor="w").pack(fill="x", padx=14, pady=(0, 10))

        self.entrada.bind("<KeyRelease>", self._refrescar)
        self.entrada.bind("<Down>", lambda _e: self._mover(1))
        self.entrada.bind("<Up>", lambda _e: self._mover(-1))
        self.entrada.bind("<Return>", self.ejecutar)
        self.entrada.bind("<Escape>", lambda _e: self.cerrar())
        self.lista.bind("<Return>", self.ejecutar)
        self.lista.bind("<Double-Button-1>", self.ejecutar)
        self.lista.bind("<Escape>", lambda _e: self.cerrar())
        self.win.bind("<Escape>", lambda _e: self.cerrar())
        self.win.protocol("WM_DELETE_WINDOW", self.cerrar)

        self._refrescar()
        self.win.update_idletasks()
        self._centrar()
        try:
            self.win.grab_set()
        except Exception:
            pass
        self.entrada.focus_force()

    # ------------------------------------------------------------ dibujo

    def _centrar(self) -> None:
        raiz = self.app.root
        ancho, alto = 660, 440
        x = raiz.winfo_rootx() + max(0, (raiz.winfo_width() - ancho) // 2)
        y = raiz.winfo_rooty() + max(0, (raiz.winfo_height() - alto) // 3)
        self.win.geometry(f"{ancho}x{alto}+{x}+{y}")

    def _refrescar(self, event=None) -> None:
        self.visibles = filtrar(self.items, self.entrada.get())
        self.lista.delete(0, "end")
        for texto, _accion in self.visibles:
            self.lista.insert("end", texto)
        if self.visibles:
            self.lista.selection_set(0)
            self.lista.activate(0)
            self.lista.see(0)
        self.aviso.configure(text="" if self.visibles else "sin resultados")

    def _mover(self, delta: int) -> str:
        if not self.visibles:
            return "break"
        seleccion = self.lista.curselection()
        indice = (seleccion[0] if seleccion else -1) + delta
        indice = max(0, min(indice, len(self.visibles) - 1))
        self.lista.selection_clear(0, "end")
        self.lista.selection_set(indice)
        self.lista.activate(indice)
        self.lista.see(indice)
        return "break"

    # ------------------------------------------------------------ acciones

    def ejecutar(self, event=None) -> str:
        seleccion = self.lista.curselection()
        if not seleccion:
            return "break"
        _texto, accion = self.visibles[seleccion[0]]
        self.cerrar()
        try:
            accion()
        except Exception as exc:                   # noqa: BLE001
            self.app.set_foot(f"no se pudo ejecutar: {exc}")
        return "break"

    def cerrar(self) -> None:
        if getattr(self.app, "_palette", None) is self:
            self.app._palette = None
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
