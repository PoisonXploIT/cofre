"""COFRE - copiar al portapapeles de Windows sin dependencias.

Tkinter mantiene su propio portapapeles: root.clipboard_append() no escribe en
el clipboard real de Windows, asi que pegar fuera de la ventana no funciona.
Esta capa usa WinAPI (OpenClipboard + CF_UNICODETEXT) con ctypes.

No se pasa el secreto por la linea de comando de ningún proceso: se escribe
directamente en la memoria del clipboard.
"""

from __future__ import annotations

import ctypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def copy_text(text: str) -> bool:
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    payload = text.encode("utf-16-le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
    if not handle:
        return False
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return False
    ctypes.memmove(ptr, payload, len(payload))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(0):
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
    finally:
        user32.CloseClipboard()
    return True
