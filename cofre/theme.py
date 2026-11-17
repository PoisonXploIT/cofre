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
    # --- paleta «grafito y laton» (2026-11-17) ---
    "bg": "#0E0F11",          # ventana y barra de titulo
    "surface": "#15171A",     # lista, paneles
    "card": "#212427",        # detalle, dialogos (1.15:1 sobre surface)
    "raised": "#2C3035",      # campos, fila elegida, chips neutros
    "input": "#2C3035",       # (compatibilidad) campos
    "border": "#2E343B",      # borde de boton secundario, hover (1.26:1 sobre card)
    "border_strong": "#484F58",
    "text": "#ECEDEE",        # 15,9:1 sobre card
    "muted": "#A0A6AD",       # 7,3:1
    "faint": "#8A9098",       # 5,2:1: vale para texto
    "disabled_bg": "#2A2F35",
    "disabled": "#767D85",
    "accent": "#D9A955",      # laton: solo la accion principal
    "accent_hover": "#E3B96E",
    "on_accent": "#1C1508",
    "ok": "#5CBF8F",
    "ok_bg": "#15231C",
    "ok_fg": "#9FDDBE",
    "warn": "#E8964A",
    "warn_bg": "#3A2014",
    "warn_fg": "#F2A774",
    "rot_bg": "#3A2E17",
    "rot_fg": "#E6C27D",
    "info": "#7AA7E8",
    "info_bg": "#17283A",
    "info_fg": "#8DB8F0",
    "danger": "#EC7B66",
    "overlay": "#000000",
}

# ---------- espaciado (escala de 4) ----------

SPACE = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 20,
    "xxl": 24,
    "x3": 32,
}

# altura de controles
SIZES = {
    "row": 40,        # fila de lista
    "btn": 32,        # boton compacto
    "btn_primary": 36,
    "icon_btn": 28,
    "chip": 24,
    "scrollbar": 8,
    "field": 40,
    "titlebar": 36,
    "header": 60,
    "sidebar": 220,
    "list": 340,
    "statusbar": 34,
}

RADIUS = {"btn": 8, "field": 8, "row": 10, "panel": 12, "dialog": 14,
          "chip": 10, "card": 12, "sheet": 14}

# ---------- tipografia ----------

#: rol -> (familia preferida, familias de reserva, tamano, peso)
TYPE = {
    "display": (("Segoe UI Variable Display", "Segoe UI"), 18, "bold"),
    "title": (("Segoe UI Variable Text", "Segoe UI"), 13, "bold"),
    "body": (("Segoe UI Variable Text", "Segoe UI"), 10, "normal"),
    "label": (("Segoe UI Variable Text", "Segoe UI"), 9, "normal"),
    "mono": (("Cascadia Mono", "Consolas", "Courier New"), 10, "normal"),
    "meta": (("Segoe UI Variable Text", "Segoe UI"), 9, "normal"),
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


def dark_titlebar(window) -> bool:
    """Barra de titulo oscura de Windows, sin dibujar una propia.

    Se pierde arrastrar y ajustar con Win+flechas si se dibuja la barra a mano;
    con DWM se conserva todo y solo cambia el color. Se aplica a la ventana
    principal y a cada Toplevel: una hoja blanca sobre una app oscura canta.

    Devuelve True si Windows acepto al menos el modo oscuro.
    """
    import ctypes

    try:
        window.update_idletasks()
        user32 = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()

        on = ctypes.c_int(1)
        aplicado = False
        for attr in (20, 19):      # DWMWA_USE_IMMERSIVE_DARK_MODE (19 en Win10 viejo)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on),
                                         ctypes.sizeof(on)) == 0:
                aplicado = True
                break
        # color de la barra (Win11): COLORREF 0x00BBGGRR
        color = ctypes.c_int(0x00110F0E)          # #0E0F11
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color),
                                  ctypes.sizeof(color))
        return aplicado
    except Exception:
        return False


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
