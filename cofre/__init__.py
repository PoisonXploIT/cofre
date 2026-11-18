"""COFRE - bóveda local de secretos.

La version vive aqui y solo aqui: `run.cmd --version` la lee de este fichero.

Se queda en 0.9.x mientras el usuario no cierre las tareas manuales M1-M11; al
terminarlas pasa a 1.0.0 (decision del 2026-11-18). No hay ejecutable: el
PyInstaller queda descartado por ahora (D17); la mensajeria nativa funciona con el
.bat y la ventana arranca con pythonw.
"""

from __future__ import annotations

__version__ = "0.9.0"
