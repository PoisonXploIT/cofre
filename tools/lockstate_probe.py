"""Sonda del bloqueo al bloquear Windows (paso 2.2).

La ejecuta el USUARIO: imprime una linea por segundo mientras pulsa Win+L, espera
y vuelve. Si OpenInputDesktop distingue los dos estados, se usa en Session.check;
si no, se apunta y se salta (no es bloqueante).

  python tools/lockstate_probe.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.windll.user32
DESKTOP_SWITCHDESKTOP = 0x0100


def input_desktop_locked() -> bool | None:
    """True si el escritorio de entrada no se puede abrir (sesion bloqueada)."""
    handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if handle:
        user32.CloseDesktop(handle)
        return False
    error = ctypes.get_last_error()
    # 5 = acceso denegado: es el caso normal cuando la sesion esta bloqueada
    if error in (5, 0):
        return True
    return None


def main() -> int:
    print("pulsa Win+L para bloquear Windows, espera unos segundos y vuelve.")
    print("Ctrl+C para terminar.")
    print("")
    ultimo = None
    cambios = 0
    try:
        while True:
            estado = input_desktop_locked()
            texto = {True: "BLOQUEADO", False: "activo", None: "desconocido"}[estado]
            marca = ""
            if estado != ultimo:
                cambios += 1
                marca = "  <- cambio"
                ultimo = estado
            print(time.strftime("%H:%M:%S"), texto, f"(cambios: {cambios})", marca, flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("")
        if cambios >= 2:
            print("RESULTADO: la sonda distingue los dos estados. Se puede usar en Session.check.")
        else:
            print("RESULTADO: no se han visto cambios; no se usa (no es bloqueante).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
