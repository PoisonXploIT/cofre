"""Dialogo de confirmacion para secretos sensibles (paso 2.4).

Ventana modal, siempre encima, con Denegar por defecto y cierre automatico a los
20 s. Nunca muestra el valor: solo quien lo pide, para que y durante cuanto.

Se construye desde el hilo de Tkinter. Si se llama desde otro hilo (el puente),
se usa `ask_async`, que encola y espera, igual que BridgeController.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk

from cofre.theme import COLORS, SPACE, build_fonts, dark_titlebar

# nombres del tema (COLORS usa surface/text, no panel/fg)
BG = COLORS["surface"]
FG = COLORS["text"]
MUT = COLORS["muted"]
ACC = COLORS["accent"]
WARN = COLORS["warn"]
CARD = COLORS["card"]
PAD = SPACE["lg"]

TIMEOUT_MS = 20_000
GRANT_MS = 5 * 60 * 1000
ARM_MS = 700        # retardo antes de poder pulsar Permitir


class ConfirmDialog:
    """'Denegar' (por defecto) / 'Permitir una vez' / 'Permitir 5 minutos'."""

    def __init__(self, root, who: str, what: str, timeout_ms: int = TIMEOUT_MS):
        self.result: str | None = None        # "once" | "grant" | "deny"
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title("COFRE - confirmar entrega")
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.transient(root)
        dark_titlebar(self.win)

        cuerpo = build_fonts(root)["body"]

        tk.Label(self.win, text="Alguien pide un secreto", fg=FG,
                 bg=BG, font=cuerpo, anchor="w").pack(
            fill="x", padx=PAD, pady=(14, 4))
        tk.Label(self.win, text=who, fg=ACC, bg=BG,
                 font=cuerpo, anchor="w").pack(fill="x", padx=PAD)
        tk.Label(self.win, text=what, fg=FG, bg=BG,
                 font=cuerpo, anchor="w").pack(fill="x", padx=PAD, pady=(2, 10))
        self.msg = tk.Label(self.win, text=f"si no contestas en {timeout_ms // 1000} s se deniega",
                            fg=MUT, bg=BG, anchor="w")
        self.msg.pack(fill="x", padx=PAD, pady=(0, 8))

        fila = tk.Frame(self.win, bg=BG)
        fila.pack(fill="x", padx=PAD, pady=(0, 14))
        self._btn(fila, "Denegar", "deny", WARN).pack(side="left")
        self.b_grant = self._btn(fila, "Permitir 5 minutos", "grant", MUT)
        self.b_grant.pack(side="right")
        self.b_once = self._btn(fila, "Permitir una vez", "once", ACC)
        self.b_once.pack(side="right", padx=8)
        # como los navegadores: Permitir no esta activo al abrir. Un clic o un
        # Enter que iba a otra ventana no puede autorizar nada.
        for b in (self.b_once, self.b_grant):
            b.configure(state="disabled", fg=MUT)
        self.win.after(ARM_MS, self._arm)

        self._after = self.win.after(timeout_ms, lambda: self._close("deny"))
        self.win.protocol("WM_DELETE_WINDOW", lambda: self._close("deny"))
        self.win.bind("<Escape>", lambda _e: self._close("deny"))
        self.win.update_idletasks()
        self._center(root)
        self.win.deiconify()
        self.win.grab_set()
        self.win.focus_force()
        self.win.focus_set()

    def _btn(self, parent, texto: str, valor: str, color: str):
        b = tk.Button(parent, text=texto, command=lambda: self._close(valor),
                      bg=CARD, fg=color, activebackground=CARD,
                      activeforeground=color, relief="flat", bd=0,
                      padx=12, pady=6, cursor="hand2", highlightthickness=0)
        return b

    def _arm(self) -> None:
        try:
            self.b_once.configure(state="normal", fg=ACC)
            self.b_grant.configure(state="normal", fg=MUT)
        except Exception:
            pass

    def _center(self, root) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = root.winfo_rootx() + (root.winfo_width() - w) // 2
        y = root.winfo_rooty() + (root.winfo_height() - h) // 3
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _close(self, valor: str) -> None:
        if self.result is not None:
            return
        self.result = valor
        try:
            self.win.after_cancel(self._after)
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
    """Puente entre el hilo que pide y el hilo de Tkinter.

    El que pide llama a `ask(...)` y se queda esperando en `event`. El hilo de la
    GUI ejecuta `poll()` desde `after`, muestra el dialogo y despierta.
    """

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
        """Devuelve True si atendio algo (para programar otro poll)."""
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
