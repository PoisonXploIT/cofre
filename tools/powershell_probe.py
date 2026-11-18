"""Sonda de las funciones de PowerShell (paso 7.4).

Usa -ExecutionPolicy Bypass solo para no depender de la politica de esta
maquina. La configuracion recomendada del usuario es RemoteSigned una vez (M10).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "cofre.ps1"


def main() -> int:
    comando = (
        f". '{SCRIPT}'; "
        "(Get-Command cofre, cofre-run, cofre-copy | Measure-Object).Count")
    proc = subprocess.run(
        ["powershell.exe", "-ExecutionPolicy", "Bypass", "-NoProfile",
         "-Command", comando], capture_output=True, text=True, timeout=60)
    salida = (proc.stdout or "").strip()
    ok = proc.returncode == 0 and salida.endswith("3")
    print(f"{'OK   ' if ok else 'FALLO'}  funciones cofre, cofre-run y "
          f"cofre-copy  (salida {salida or 'vacia'})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
