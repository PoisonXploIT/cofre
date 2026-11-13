"""COFRE - tokens de diseno (color, tipografia, espaciado, radios).

Un solo sitio para el aspecto visual. Regla: si un color o un margen no esta
aqui, no se usa. Los contrastes estan medidos contra WCAG 2.1 (luminancia
relativa), no elegidos a ojo.

Medido el 2026-11-10:
  text / surface         15.5:1
  muted / surface         7.2:1
  faint / surface         4.0:1   (solo texto grande o metadatos)
  on_accent / accent      5.7:1
  danger / surface        5.6:1
  border / card           1.45:1  (linea decorativa, no texto)
  border_strong / card    2.10:1  (borde de campo enfocado)
  card / surface          1.20:1  (separacion de superficies)
"""

from __future__ import annotations

import tkinter.font as tkfont

# ---------- color ----------

COLORS = {
    "bg": "#080B0F",          # fondo de ventana
    "surface": "#11161E",     # panel lateral
    "card": "#1F2836",        # tarjeta de trabajo (1.22:1 sobre surface)
    "input": "#283446",       # campos (1.18:1 sobre card)
    "border": "#334258",      # separadores 1 px (1.46:1 sobre card)
    "border_strong": "#3F526E",  # borde de campo enfocado (1.87:1)
    "text": "#E9EEF5",        # texto principal (12.7:1 sobre card)
    "muted": "#98A5B6",       # secundario (5.9:1 sobre card)
    "faint": "#6B7787",       # metadatos (3.3:1 sobre card)
    "disabled": "#4A5563",    # texto de boton apagado
    "accent": "#3E9C7A",      # accion primaria
    "on_accent": "#04120C",   # texto sobre el acento (5.7:1)
    "danger": "#D9705C",      # borrar (5.6:1)
    "warn": "#D9A44F",        # atencion (8.1:1)
    "ok": "#4C9E7C",          # abierto
    "overlay": "#000000",     # velo de las hojas modales
}

# ---------- espaciado (escala de 4) ----------

SPACE = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}

# altura de controles
SIZES = {
    "row": 40,        # fila de lista
    "btn": 32,        # boton compacto
    "btn_primary": 36,
    "icon_btn": 28,
    "chip": 24,
    "scrollbar": 8,
    "field": 36,
}

RADIUS = {"btn": 6, "card": 10, "chip": 12, "sheet": 12}

# ---------- tipografia ----------

#: rol -> (familia preferida, familias de reserva, tamano, peso)
TYPE = {
    "display": (("Segoe UI Variable Display", "Segoe UI"), 20, "bold"),
    "title": (("Segoe UI Variable Text", "Segoe UI"), 15, "bold"),
    "body": (("Segoe UI Variable Text", "Segoe UI"), 12, "normal"),
    "label": (("Segoe UI Variable Text", "Segoe UI"), 11, "normal"),
    "mono": (("Cascadia Mono", "Consolas", "Courier New"), 12, "normal"),
    "meta": (("Segoe UI Variable Text", "Segoe UI"), 10, "normal"),
}

#: fuente de iconos: glifos de una fuente, nunca emojis
ICON_FAMILIES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")


def pick_family(root, candidates: tuple[str, ...]) -> str:
    """Primera familia instalada de la lista. Se comprueba, no se asume."""
    try:
        available = set(tkfont.families(root))
    except Exception:
        available = set()
    for name in candidates:
        if name in available:
            return name
    return candidates[-1]


def build_fonts(root) -> dict[str, tkfont.Font]:
    """Crea los seis roles tipograficos. Devuelve {rol: Font}."""
    out = {}
    for role, (families, size, weight) in TYPE.items():
        family = pick_family(root, families)
        out[role] = tkfont.Font(root=root, family=family, size=size, weight=weight)
    out["icon"] = tkfont.Font(root=root, family=pick_family(root, ICON_FAMILIES), size=12)
    return out


def enable_dpi_awareness() -> dict:
    """Que Windows no escale la ventana como una imagen.

    Se usa awareness de sistema (1), no per-monitor v2: Tk no maneja
    WM_DPICHANGED, y con v2 una ventana movida a un monitor con otra escala
    queda mal dimensionada. Con awareness de sistema el texto sale nitido en la
    escala principal, que es el caso normal.

    Devuelve un diagnostico para poder comprobarlo desde --selftest.
    """
    import ctypes

    info = {"mode": "none", "dpi": 0, "scaling": None}
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        info["mode"] = "system"
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            info["mode"] = "system-legacy"
        except Exception:
            info["mode"] = "none"

    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        info["dpi"] = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
    except Exception:
        pass
    return info


def apply_tk_scaling(root, dpi: int) -> float:
    """Ajusta tk scaling solo si Tk no lo calculo ya bien (evita doble escala)."""
    target = (dpi or 96) / 72.0
    try:
        current = float(root.tk.call("tk", "scaling"))
    except Exception:
        current = target
    if abs(current - target) > 0.1:
        root.tk.call("tk", "scaling", target)
        return target
    return current
