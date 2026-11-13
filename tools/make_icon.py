"""Genera el icono del cofre (assets/cofre.ico) sin dependencias externas.

Dibujo por funciones de distancia (SDF) con antialias analitico: no hace falta
PIL ni supersampling. Escribe un ICO multi-tamano con payload PNG (soportado
desde Windows Vista).

Uso: python tools/make_icon.py [salida.ico]
"""
from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

# paleta (los mismos tokens que cofre/theme.py)
CARD = (0x16, 0x1D, 0x28)
CARD_TOP = (0x1F, 0x28, 0x36)
BORDER = (0x33, 0x42, 0x58)
ACCENT = (0x3E, 0x9C, 0x7A)
ACCENT_DARK = (0x2F, 0x7D, 0x61)
HOLE = (0x04, 0x12, 0x0C)
STEEL = (0xC9, 0xD6, 0xE4)

SIZES = (16, 24, 32, 48, 64, 128, 256)


# ---------- SDF ----------

def sd_round_rect(px, py, cx, cy, hw, hh, r):
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    ax, ay = max(qx, 0.0), max(qy, 0.0)
    return math.hypot(ax, ay) + min(max(qx, qy), 0.0) - r


def sd_circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


def sd_ring(px, py, cx, cy, r, w):
    return abs(math.hypot(px - cx, py - cy) - r) - w / 2.0


def coverage(d):
    return min(1.0, max(0.0, 0.5 - d))


def blend(dst, src, a):
    return tuple(int(dst[i] + (src[i] - dst[i]) * a) for i in range(3))


# ---------- pieza ----------

def render(size: int) -> list[list[tuple[int, int, int, int]]]:
    """Dibuja el icono a `size` px. Devuelve filas de RGBA."""
    s = float(size)
    cx = cy = s / 2.0
    img = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]

    # geometria relativa: se adapta a cualquier tamano
    card_r = s * 0.22
    hw = hh = s * 0.46
    body_w = s * 0.20
    body_h = s * 0.16
    body_cy = cy + s * 0.13
    shackle_r = s * 0.105
    shackle_w = max(1.0, s * 0.055)
    shackle_cy = body_cy - body_h - shackle_r * 0.45
    hole_r = s * 0.045

    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            col = (0, 0, 0)
            alpha = 0.0

            # tarjeta redondeada con borde
            d_card = sd_round_rect(px, py, cx, cy, hw, hh, card_r)
            a_card = coverage(d_card)
            if a_card > 0:
                t = (py - (cy - hh)) / (2 * hh)
                t = min(1.0, max(0.0, t))
                base = tuple(int(CARD_TOP[i] + (CARD[i] - CARD_TOP[i]) * t) for i in range(3))
                col = base
                alpha = a_card
                d_border = abs(d_card + max(1.0, s * 0.012)) - max(1.0, s * 0.012)
                a_border = coverage(d_border) * a_card
                if a_border > 0:
                    col = blend(col, BORDER, a_border)

            # cuerpo del candado
            d_body = sd_round_rect(px, py, cx, body_cy, body_w, body_h, max(1.0, s * 0.05))
            a_body = coverage(d_body)
            if a_body > 0:
                t = (py - (body_cy - body_h)) / (2 * body_h)
                t = min(1.0, max(0.0, t))
                grad = tuple(int(ACCENT[i] + (ACCENT_DARK[i] - ACCENT[i]) * t) for i in range(3))
                col = blend(col, grad, a_body)
                alpha = max(alpha, a_body)

            # arco del candado
            ang = math.atan2(py - shackle_cy, px - cx)
            in_arc = ang <= 0.0 or abs(px - cx) > shackle_r * 0.98
            d_arc = sd_ring(px, py, cx, shackle_cy, shackle_r, shackle_w)
            a_arc = coverage(d_arc)
            if a_arc > 0 and in_arc:
                col = blend(col, STEEL, a_arc)
                alpha = max(alpha, a_arc)

            # ojo de la cerradura
            d_hole = sd_circle(px, py, cx, body_cy - body_h * 0.15, hole_r)
            a_hole = coverage(d_hole)
            if a_hole > 0:
                col = blend(col, HOLE, a_hole)
                alpha = max(alpha, a_hole)
            d_slot = sd_round_rect(px, py, cx, body_cy + body_h * 0.32,
                                   hole_r * 0.42, body_h * 0.42, hole_r * 0.42)
            a_slot = coverage(d_slot)
            if a_slot > 0:
                col = blend(col, HOLE, a_slot)
                alpha = max(alpha, a_slot)

            img[y][x] = (col[0], col[1], col[2], int(round(alpha * 255)))
    return img


# ---------- PNG / ICO ----------

def write_png(rows: list[list[tuple[int, int, int, int]]], size: int) -> bytes:
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filtro 0 (none)
        for x in range(size):
            r, g, b, a = rows[y][x]
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    blobs = b""
    for size, png in images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        blobs += png
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + blobs)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent.parent / "assets" / "cofre.ico")
    images = []
    for size in SIZES:
        pixels = render(size)
        images.append((size, write_png(pixels, size)))
        print(f"  {size}x{size} listo")
    write_ico(out, images)
    print("escrito", out, out.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
