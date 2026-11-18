"""COFRE - comprobacion de hilo para Tkinter (2026-11-18).

Tkinter no es seguro entre hilos: tocar un widget desde otro hilo funciona casi
siempre y falla a veces, con cuelgues o cierres sin traza. La regla es una:
**todo lo que pinta ocurre en el hilo principal**; los demas hilos solo encolan
(ConfirmQueue, CofreGUI.ui_call) y, si acaso, esperan su respuesta.

Las funciones que pintan llaman a `assert_main(...)` al entrar. Asi un fallo de
orden se ve en la primera prueba en vez de aparecer cada mil ejecuciones.
"""

from __future__ import annotations

import threading


class WrongThread(RuntimeError):
    """Se ha llamado a Tkinter desde un hilo que no es el principal."""


def is_main() -> bool:
    return threading.current_thread() is threading.main_thread()


def nombre_hilo() -> str:
    return threading.current_thread().name


def assert_main(where: str) -> None:
    """Falla si no estamos en el hilo principal (el de Tkinter)."""
    if not is_main():
        raise WrongThread(
            f"{where} debe ejecutarse en el hilo de Tkinter; "
            f"se ha llamado desde '{nombre_hilo()}'")
