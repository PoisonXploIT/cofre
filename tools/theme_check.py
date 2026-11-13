"""Comprueba los tokens de cofre/theme.py contra objetivos de contraste.

Uso: python tools/theme_check.py
Devuelve exit 1 si algun objetivo no se cumple (sirve de puerta en CI).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.theme import COLORS, RADIUS, SIZES, SPACE, TYPE


def _lin(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = luminance(COLORS[a]), luminance(COLORS[b])
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


TARGETS = [
    ("text", "surface", 4.5, "texto principal"),
    ("text", "card", 4.5, "texto en tarjeta"),
    ("muted", "surface", 4.5, "texto secundario"),
    ("muted", "card", 4.5, "secundario en tarjeta"),
    ("faint", "card", 3.0, "metadatos"),
    ("on_accent", "accent", 4.5, "texto sobre accion primaria"),
    ("danger", "surface", 4.5, "borrar"),
    ("warn", "surface", 4.5, "atencion"),
    ("border", "card", 1.2, "separador visible"),
    ("border_strong", "card", 1.8, "borde de campo enfocado"),
    ("card", "surface", 1.15, "separacion de superficies"),
    ("input", "card", 1.15, "campo distinguible"),
]

failures = 0
for a, b, target, label in TARGETS:
    value = ratio(a, b)
    ok = value >= target
    failures += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FALLO'} {a:14s}/{b:14s} {value:5.2f}:1  "
          f"objetivo >= {target}  ({label})")

print()
print("escala de espaciado:", list(SPACE.values()))
print("tipografia:", {k: f"{v[1]}pt {v[2]}" for k, v in TYPE.items()})
print("radios:", RADIUS, "| tamanos:", SIZES)
print()
print("TOKENS OK" if not failures else f"{failures} fallo(s) de contraste")
sys.exit(0 if not failures else 1)
