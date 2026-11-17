"""COFRE - dialogo de confirmación (paso 2.4, aspecto E7).

Ventana modal, siempre encima, con la accion segura por defecto:

  Denegar (con foco, en laton porque es la accion recomendada)
  Permitir una vez
  Permitir 5 minutos

Nunca muestra el valor: solo quien lo pide, para que y una cuenta atras de 20 s.
Los botones de permitir no se pueden pulsar hasta pasados 700 ms, para que un
clic o un Enter destinado a otra ventana no autorice nada.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk

from cofre.theme import COLORS as C
from cofre.theme import SPACE, dark_titlebar
from cofre import widgets as W

TIMEOUT_MS = 20_000
GRANT_MS = 5 * 60 * 1000
ARM_MS = 700        # retardo antes de poder pulsar Permitir

GLIFO_ESCUDO = "\uea18"


class ConfirmDialog:
    """Devuelve 'once' | 'grant' | 'deny' en `result`."""

    def __init__(self, root, who: str, what: str, timeout_ms: int = TIMEOUT_MS):
        self.result: str | None = None
        self._timeout_ms = timeout_ms
        self._restante = max(1, timeout_ms // 1000)

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title("COFRE - confirmar entrega")
        self.win.configure(bg=C["surface"])
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.transient(root)
        dark_titlebar(self.win)

        cuerpo = tk.Frame(self.win, bg=C["surface"])
        cuerpo.pack(fill="both", expand=True, padx=SPACE["xl"], pady=SPACE["lg"])

        cab = tk.Frame(cuerpo, bg=C["surface"])
        cab.pack(fill="x")
        tk.Label(cab, text=GLIFO_ESCUDO, fg=C["accent"], bg=C["surface"],
                 font=("Segoe Fluent Icons", 22)).pack(side="left", padx=(0, 10))
        textos = tk.Frame(cab, bg=C["surface"])
        textos.pack(side="left", fill="x", expand=True)
        tk.Label(textos, text="Alguien pide un secreto", fg=C["text"],
                 bg=C["surface"], font=("Segoe UI Variable Text", 13, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(textos, text=who, fg=C["accent"], bg=C["surface"],
                 font=("Segoe UI Variable Text", 10), anchor="w").pack(fill="x")

        tk.Label(cuerpo, text=what, fg=C["text"], bg=C["surface"],
                 font=("Cascadia Mono", 10), anchor="w").pack(
            fill="x", pady=(SPACE["md"], 4))

        self.msg = tk.Label(cuerpo, text="", fg=C["muted"], bg=C["surface"],
                            font=("Segoe UI Variable Text", 9), anchor="w")
        self.msg.pack(fill="x")
        self._actualizar_cuenta()

        acciones = tk.Frame(cuerpo, bg=C["surface"])
        acciones.pack(fill="x", pady=(SPACE["lg"], 0))
        self.b_deny = W.Button(acciones, "Denegar", kind="primary", bg=C["surface"],
                               command=lambda: self._close("deny"))
        self.b_deny.pack(side="left")
        self.b_grant = W.Button(acciones, "Permitir 5 minutos", kind="text",
                                bg=C["surface"],
                                command=lambda: self._close("grant"))
        self.b_grant.pack(side="right")
        self.b_once = W.Button(acciones, "Permitir una vez", kind="secondary",
                               bg=C["surface"],
                               command=lambda: self._close("once"))
        self.b_once.pack(side="right", padx=(0, 8))

        # como los navegadores: permitir no esta activo al abrir
        self.b_once.set_enabled(False)
        self.b_grant.set_enabled(False)
        self.win.after(ARM_MS, self._arm)
        self._after = self.win.after(timeout_ms, lambda: self._close("deny"))
        self._tick = self.win.after(1000, self._cuenta_atras)

        self.win.protocol("WM_DELETE_WINDOW", lambda: self._close("deny"))
        self.win.bind("<Escape>", lambda _e: self._close("deny"))
        self.win.bind("<Return>", lambda _e: self._close("deny"))

        self.win.update_idletasks()
        self._center(root)
        self.win.deiconify()
        try:
            self.win.grab_set()
        except Exception:
            pass
        self.win.focus_force()
        self.b_deny.canvas.focus_set()

    # ------------------------------------------------------------ dibujo

    def _center(self, root) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = root.winfo_rootx() + (root.winfo_width() - w) // 2
        y = root.winfo_rooty() + (root.winfo_height() - h) // 3
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ------------------------------------------------------------ estado

    def _arm(self) -> None:
        try:
            self.b_once.set_enabled(True)
            self.b_grant.set_enabled(True)
        except Exception:
            pass

    def _actualizar_cuenta(self) -> None:
        self.msg.configure(text=f"si no contestas, se deniega en {self._restante} s")

    def _cuenta_atras(self) -> None:
        self._restante -= 1
        if self._restante <= 0:
            return
        self._actualizar_cuenta()
        try:
            self._tick = self.win.after(1000, self._cuenta_atras)
        except Exception:
            pass

    def _close(self, valor: str) -> None:
        if self.result is not None:
            return
        self.result = valor
        for ident in (getattr(self, "_after", None), getattr(self, "_tick", None)):
            try:
                if ident:
                    self.win.after_cancel(ident)
            except Exception:
                pass
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass

    def wait(self) -> str:
        self.win.wait_window()
        return self.result or "deny"


class ConfirmQueue:
    """Puente entre el hilo que pide y el hilo de Tkinter."""

    def __init__(self, root):
        self.root = root
        self.requests: queue.Queue = queue.Queue()

    def ask(self, who: str, what: str, timeout: int = 30) -> str:
        box: dict = {}
        done = threading.Event()
        self.requests.put((who, what, box, done))
        if not done.wait(timeout=timeout):
            return "deny"
        return box.get("result", "deny")

    def poll(self) -> bool:
        try:
            who, what, box, done = self.requests.get_nowait()
        except queue.Empty:
            return False
        try:
            dialogo = ConfirmDialog(self.root, who, what)
            box["result"] = dialogo.wait()
        except Exception:
            box["result"] = "deny"
        finally:
            done.set()
        return True
