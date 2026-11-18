"""COFRE - widgets propios del rediseño «grafito y latón» (E2).

Nota de ubicacion: el plan decia `cofre/gui/widgets.py`, pero `cofre/gui.py` es
un modulo, no un paquete, así que el paquete `cofre.gui` no existe. Se deja en
`cofre/widgets.py` para no trocear gui.py a mitad del rediseño.

Tkinter no tiene esquinas redondeadas ni estados decentes por defecto. En vez de
usar ttk (que impone el aspecto del sistema), cada control se dibuja sobre un
Canvas con `round_rect`, y el texto va encima.

Reglas de la casa que estos widgets respetan:

  - el hover NO cambia el fondo: sube el borde (regla del 2026-11-10);
  - el acento latón se reserva a la acción primaria de la pantalla;
  - un control desactivado no responde ni al ratón ni al hover;
  - el foco se ve con un anillo de 2 px, no cambiando el color del texto;
  - sin emojis: los iconos son glifos de Segoe Fluent Icons.

Nada de aquí toca seguridad: son piezas de dibujo.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from cofre.theme import COLORS as C
from cofre.theme import RADIUS, SIZES, SPACE

BG = C["bg"]
SURFACE = C["surface"]
CARD = C["card"]
RAISED = C["raised"]
BORDER = C["border"]
BORDER_STRONG = C["border_strong"]
TEXT = C["text"]
MUTED = C["muted"]
MUT = MUTED      # alias usado por los widgets
FAINT = C["faint"]
DISABLED = C["disabled"]
DISABLED_BG = C["disabled_bg"]
ACCENT = C["accent"]
ACCENT_HOVER = C["accent_hover"]
ON_ACCENT = C["on_accent"]
DANGER = C["danger"]
OK = C["ok"]
WARN = C["warn"]


# ---------------------------------------------------------------- formas

def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
               r: float, **kw) -> int:
    """Rectangulo de esquinas redondeadas con un solo polygon suavizado."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    puntos = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(puntos, smooth=True, splinesteps=36, **kw)


PALETA_PROVEEDOR = ("#7AA7E8", "#5CBF8F", "#D9A955", "#C58BE0", "#E8964A",
                    "#6FC7C7", "#E07A9A", "#9FB05C")


CONOCIDOS = {
    "cloudflare": "#D9A955",   # ambar, como en el lienzo
    "github": "#C58BE0",
    "google": "#7AA7E8",
    "aws": "#E8964A",
    "amazon": "#E8964A",
    "azure": "#6FC7C7",
    "microsoft": "#6FC7C7",
    "openai": "#5CBF8F",
    "stripe": "#9FB05C",
}


def color_de_proveedor(nombre: str) -> str:
    """Color estable por proveedor. Los conocidos tienen tono fijo."""
    bajo = (nombre or "").lower()
    for clave, color in CONOCIDOS.items():
        if clave in bajo:
            return color
    if not bajo:
        return MUT
    total = sum(ord(c) for c in bajo)
    return PALETA_PROVEEDOR[total % len(PALETA_PROVEEDOR)]


def _font(root, role: str = "body") -> tkfont.Font:
    familia = {
        "body": ("Segoe UI Variable Text", "Segoe UI"),
        "label": ("Segoe UI Variable Text", "Segoe UI"),
        "title": ("Segoe UI Variable Text", "Segoe UI"),
        "mono": ("Cascadia Mono", "Consolas", "Courier New"),
        "icon": ("Segoe Fluent Icons", "Segoe MDL2 Assets"),
    }[role]
    disponible = set(tkfont.families(root))
    elegida = next((f for f in familia if f in disponible), familia[-1])
    tam = {"body": 10, "label": 9, "title": 13, "mono": 10, "icon": 12}[role]
    peso = "bold" if role == "title" else "normal"
    return tkfont.Font(root=root, family=elegida, size=tam, weight=peso)


# ---------------------------------------------------------------- boton

class Button(tk.Frame):
    """Boton plano con esquinas redondeadas.

    kind: primary (laton) | secondary (borde) | text (sin borde) | danger | icon
    """

    PAD = {"primary": 18, "secondary": 14, "text": 10, "danger": 14, "icon": 8}

    def __init__(self, parent, text: str = "", command=None, kind: str = "secondary",
                 icon: str | None = None, height: int | None = None,
                 bg: str | None = None):
        self._bg = bg or str(parent.cget("bg"))
        super().__init__(parent, bg=self._bg, bd=0, highlightthickness=0)
        self.command = command
        self.kind = kind
        self.icon = icon
        self.text = text
        self._estado = "normal"
        self._hover = False
        self._foco = False
        self._f_body = _font(self, "icon" if kind == "icon" else "body")
        self._f_text = _font(self, "body")
        alto = height or SIZES["btn"]
        ancho = self._ancho()
        self.canvas = tk.Canvas(self, width=ancho, height=alto, bg=self._bg,
                                bd=0, highlightthickness=0, takefocus=1)
        self.canvas.pack()
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<FocusIn>", self._on_focus_in)
        self.canvas.bind("<FocusOut>", self._on_focus_out)
        self.canvas.bind("<Return>", lambda _e: self.invoke())
        self.canvas.bind("<space>", lambda _e: self.invoke())
        self._dibujar()

    # ------------------------------------------------------------ medidas

    def _ancho(self) -> int:
        if self.kind == "icon":
            return SIZES["icon_btn"] + 8
        texto = self.text
        if self.icon:
            texto = self.icon + "  " + texto
        medida = self._f_body.measure(texto) if self.icon else self._f_text.measure(texto)
        return medida + self.PAD.get(self.kind, 14) * 2

    # ------------------------------------------------------------ dibujo

    def _colores(self):
        if self._estado == "disabled":
            return DISABLED_BG, DISABLED, BORDER
        if self.kind == "primary":
            fondo = ACCENT_HOVER if self._hover else ACCENT
            return fondo, ON_ACCENT, fondo
        if self.kind == "danger":
            return CARD, DANGER, (DANGER if self._hover else BORDER)
        if self.kind == "text":
            return self._bg, (ACCENT_HOVER if self._hover else MUTED), self._bg
        borde = ACCENT if self._hover else BORDER
        return CARD, TEXT, borde

    def _dibujar(self) -> None:
        self.canvas.delete("all")
        ancho = int(self.canvas.cget("width"))
        alto = int(self.canvas.cget("height"))
        fondo, color_texto, borde = self._colores()
        radio = RADIUS["btn"]
        if self.kind != "text":
            round_rect(self.canvas, 1, 1, ancho - 1, alto - 1, radio,
                       fill=fondo, outline=borde, width=1)
        if self._foco:
            _anillo(self.canvas, 1, 1, ancho - 1, alto - 1, radio, ACCENT)
        texto = self.text
        if self.icon:
            texto = self.icon + ("  " + self.text if self.text else "")
            fuente = self._f_body
        else:
            fuente = self._f_text
        self.canvas.create_text(ancho / 2, alto / 2, text=texto, fill=color_texto,
                                font=fuente)

    # ------------------------------------------------------------ estado

    def set_enabled(self, habilitado: bool) -> None:
        self._estado = "normal" if habilitado else "disabled"
        self._dibujar()

    def set_text(self, texto: str) -> None:
        self.text = texto
        self.canvas.configure(width=self._ancho())
        self._dibujar()

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self._dibujar()

    # ------------------------------------------------------------ eventos

    def _on_enter(self, _e=None):
        if self._estado == "disabled":
            return
        self._hover = True
        self.canvas.configure(cursor="hand2")
        self._dibujar()

    def _on_leave(self, _e=None):
        self._hover = False
        self.canvas.configure(cursor="")
        self._dibujar()

    def _on_press(self, _e=None):
        if self._estado == "disabled":
            return
        self.canvas.focus_set()

    def _on_release(self, _e=None):
        if self._estado == "disabled":
            return
        self.invoke()

    def _on_focus_in(self, _e=None):
        self._foco = True
        self._dibujar()

    def _on_focus_out(self, _e=None):
        self._foco = False
        self._dibujar()

    def invoke(self):
        if self._estado == "disabled":
            return
        if callable(self.command):
            self.command()


def _anillo(canvas: tk.Canvas, x1, y1, x2, y2, r, color) -> None:
    round_rect(canvas, x1, y1, x2, y2, r, fill="", outline=color, width=2)


class IconButton(Button):
    """Boton cuadrado con un glifo. text es el glifo."""

    def __init__(self, parent, glyph: str, command=None, bg: str | None = None):
        super().__init__(parent, text="", command=command, kind="icon", icon=glyph, bg=bg)


# ---------------------------------------------------------------- chip

class Chip(tk.Canvas):
    """Etiqueta pequeña de estado: abierto, caduca, rotar, sin asignar."""

    ESTILOS = {
        "ok": ("ok_bg", "ok_fg"),
        "warn": ("warn_bg", "warn_fg"),
        "rot": ("rot_bg", "rot_fg"),
        "info": ("info_bg", "info_fg"),
        "neutral": ("raised", "muted"),
    }

    def __init__(self, parent, texto: str, kind: str = "neutral",
                 bg: str | None = None):
        self._bg = bg or str(parent.cget("bg"))
        # la fuente se mide con el padre: el propio widget aun no tiene `tk`
        self._f = _font(parent, "label")
        alto = SIZES["chip"]
        ancho = self._f.measure(texto) + 20
        super().__init__(parent, width=ancho, height=alto, bg=self._bg,
                         bd=0, highlightthickness=0)
        fondo, color = self.ESTILOS.get(kind, self.ESTILOS["neutral"])
        round_rect(self, 1, 1, ancho - 1, alto - 1, RADIUS["chip"],
                   fill=C[fondo], outline="")
        self.create_text(ancho / 2, alto / 2, text=texto, fill=C[color], font=self._f)


# ---------------------------------------------------------------- campo

class Field(tk.Frame):
    """Entrada de texto con marco redondeado y anillo al enfocar."""

    def __init__(self, parent, placeholder: str = "", show: str = "",
                 width: int = 240, bg: str | None = None, on_change=None):
        self._bg = bg or str(parent.cget("bg"))
        super().__init__(parent, bg=self._bg, bd=0, highlightthickness=0)
        self._f = _font(parent, "body")
        alto = SIZES["field"]
        self.canvas = tk.Canvas(self, width=width, height=alto, bg=self._bg,
                                bd=0, highlightthickness=0)
        self.canvas.pack()
        self.var = tk.StringVar()
        self.entry = tk.Entry(self.canvas, textvariable=self.var, bd=0,
                              relief="flat", bg=RAISED, fg=TEXT,
                              insertbackground=TEXT, font=self._f,
                              highlightthickness=0)
        if show:
            self.entry.configure(show=show)
        self._placeholder = placeholder
        self.canvas.create_window(12, alto / 2, window=self.entry, anchor="w",
                                  width=width - 24, height=alto - 12)
        self.entry.bind("<FocusIn>", lambda _e: self._dibujar(foco=True))
        self.entry.bind("<FocusOut>", lambda _e: self._dibujar(foco=False))
        if on_change:
            self.var.trace_add("write", lambda *_: on_change(self.var.get()))
        self._dibujar(foco=False)

    def _dibujar(self, foco: bool) -> None:
        self.canvas.delete("marco")
        ancho = int(self.canvas.cget("width"))
        alto = int(self.canvas.cget("height"))
        borde = C["accent"] if foco else BORDER_STRONG
        round_rect(self.canvas, 1, 1, ancho - 1, alto - 1, RADIUS["field"],
                   fill=RAISED, outline=borde, width=2 if foco else 1,
                   tags="marco")
        self.canvas.tag_lower("marco")

    def get(self) -> str:
        return self.var.get()

    def set(self, valor: str) -> None:
        self.var.set(valor)

    def focus(self) -> None:
        self.entry.focus_set()


# ---------------------------------------------------------------- fila

class ListRow(tk.Frame):
    """Fila de la lista: cuadro con la inicial, nombre en mono, meta y chip."""

    ALTO = 56

    def __init__(self, parent, titulo: str, subtitulo: str = "", inicial: str = "",
                 chip: tuple[str, str] | None = None, on_click=None,
                 bg: str | None = None, color: str | None = None,
                 on_move=None):
        self._bg = bg or SURFACE
        super().__init__(parent, bg=self._bg, bd=0, highlightthickness=0)
        self.on_click = on_click
        self.on_move = on_move
        self.seleccionada = False
        self._foco = False
        self._f_titulo = _font(self, "mono")
        self._f_meta = _font(self, "label")

        self.canvas = tk.Canvas(self, height=self.ALTO, bg=self._bg, bd=0,
                                highlightthickness=0, takefocus=1)
        self.canvas.pack(fill="x", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._dibujar())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Return>", self._click)
        self.canvas.bind("<space>", self._click)
        self.canvas.bind("<Up>", lambda _e: self._mover(-1))
        self.canvas.bind("<Down>", lambda _e: self._mover(1))
        self.canvas.bind("<FocusIn>", self._focus_in)
        self.canvas.bind("<FocusOut>", self._focus_out)
        self._titulo = titulo
        self._subtitulo = subtitulo
        self._inicial = (inicial or titulo[:1] or "?").upper()
        self._color = color or MUT
        self._chip = chip
        self.canvas.bind("<Enter>", lambda _e: self._hover(True))
        self.canvas.bind("<Leave>", lambda _e: self._hover(False))
        self._encima = False

    def _click(self, _e=None):
        if callable(self.on_click):
            self.on_click(self._titulo)

    def _mover(self, delta: int):
        if callable(self.on_move):
            self.on_move(delta)

    def _focus_in(self, _e=None):
        self._foco = True
        self._dibujar()

    def _focus_out(self, _e=None):
        self._foco = False
        self._dibujar()

    def _hover(self, dentro: bool):
        self._encima = dentro
        self.canvas.configure(cursor="hand2" if dentro else "")
        self._dibujar()

    def set_seleccionada(self, valor: bool) -> None:
        self.seleccionada = valor
        self._dibujar()

    def _dibujar(self) -> None:
        self.canvas.delete("all")
        ancho = self.canvas.winfo_width() or 320
        alto = self.ALTO
        fondo = RAISED if (self.seleccionada or self._encima) else self._bg
        round_rect(self.canvas, 2, 2, ancho - 2, alto - 2, RADIUS["row"],
                   fill=fondo, outline=ACCENT if self._foco else "",
                   width=2 if self._foco else 0)
        # cuadro del proveedor
        self.canvas.create_rectangle(14, 12, 46, 44, fill=C["card"], outline="")
        self.canvas.create_text(30, 28, text=self._inicial, fill=MUTED,
                                font=self._f_titulo)
        self.canvas.create_text(58, 20, text=self._titulo, fill=TEXT, anchor="w",
                                font=self._f_titulo)
        if self._subtitulo:
            self.canvas.create_text(58, 37, text=self._subtitulo, fill=FAINT,
                                    anchor="w", font=self._f_meta)
        if self._chip:
            texto, kind = self._chip
            fondo_chip, color = Chip.ESTILOS.get(kind, Chip.ESTILOS["neutral"])
            ancho_chip = self._f_meta.measure(texto) + 18
            x2 = ancho - 12
            round_rect(self.canvas, x2 - ancho_chip, 18, x2, 38, RADIUS["chip"],
                       fill=C[fondo_chip], outline="")
            self.canvas.create_text(x2 - ancho_chip / 2, 28, text=texto,
                                    fill=C[color], font=self._f_meta)
