"""COFRE - estado de bloqueo de la sesion de Windows (paso 2.2).

Comprobado en esta maquina el 2026-11-17 con `tools/lockstate_probe.py`: al pulsar
Win+L, `OpenInputDesktop` falla con acceso denegado. Es decir, Windows si sabe
decirnos cuando la sesion esta bloqueada.

`is_locked()` devuelve:
    True   la sesion esta bloqueada
    False  hay escritorio de entrada
    None   no se puede saber (otro error, o no es Windows)

Con None no se bloquea nada: preferimos no adivinar.
"""

from __future__ import annotations

import sys

DESKTOP_SWITCHDESKTOP = 0x0100
ACCESS_DENIED = 5


def is_locked() -> bool | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if handle:
            user32.CloseDesktop(handle)
            return False
        error = ctypes.get_last_error()
        if error in (ACCESS_DENIED, 0):
            return True
        return None
    except Exception:
        return None
