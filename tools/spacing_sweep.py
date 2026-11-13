"""Barrido de espaciado: lleva todo padx/pady a la escala de 4.

Uso: python tools/spacing_sweep.py [--apply]
Sin --apply solo informa. Respeta 0 y 1 (0 = pegado, 1 = borde de 1 px que da
el aspecto de boton).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCALE = [4, 8, 12, 16, 24, 32]


def snap(n: int) -> int:
    if n in (0, 1):
        return n
    return min(SCALE, key=lambda s: (abs(s - n), s))


TUPLE = re.compile(r"\bpad([xy])=\(\s*(\d+)\s*,\s*(\d+)\s*\)")
SINGLE = re.compile(r"\bpad([xy])=(\d+)(?![\d(])")


def sweep(text: str) -> tuple[str, list[tuple[int, int]]]:
    changes: list[tuple[int, int]] = []

    def sub_tuple(m: re.Match) -> str:
        a, b = int(m.group(2)), int(m.group(3))
        if (snap(a), snap(b)) != (a, b):
            changes.append((a, snap(a)))
            changes.append((b, snap(b)))
        return f"pad{m.group(1)}=({snap(a)}, {snap(b)})"

    def sub_single(m: re.Match) -> str:
        n = int(m.group(2))
        if snap(n) != n:
            changes.append((n, snap(n)))
        return f"pad{m.group(1)}={snap(n)}"

    text = TUPLE.sub(sub_tuple, text)
    text = SINGLE.sub(sub_single, text)
    return text, changes


def main() -> int:
    apply = "--apply" in sys.argv
    path = Path(__file__).resolve().parent.parent / "cofre" / "gui.py"
    text = path.read_text(encoding="utf-8")
    new, changes = sweep(text)

    before_vals = sorted({int(v) for v in re.findall(r"\bpad[xy]=(?:\(\s*\d+\s*,\s*)?(\d+)", text)})
    after_vals = sorted({int(v) for v in re.findall(r"\bpad[xy]=(?:\(\s*\d+\s*,\s*)?(\d+)", new)})
    print("antes:", before_vals)
    print("despues:", after_vals)
    print("cambios:", len(changes), sorted(set(changes)))

    if apply and new != text:
        path.write_text(new, encoding="utf-8")
        print("escrito", path)
    out_of_scale = [v for v in after_vals if v not in SCALE and v not in (0, 1)]
    print("fuera de escala:", out_of_scale or "ninguno")
    return 0


if __name__ == "__main__":
    sys.exit(main())
