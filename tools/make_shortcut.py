"""Crea el acceso directo COFRE en el escritorio.

Usa pythonw.exe del venv para que no aparezca ninguna ventana de consola.
El icono sale de assets/cofre.ico.

Uso: python tools/make_shortcut.py [--name COFRE]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHONW = REPO / ".venv" / "Scripts" / "pythonw.exe"
ICON = REPO / "assets" / "cofre.ico"


def desktop_dir() -> Path:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True, check=True)
        path = Path(out.stdout.strip())
        if path.is_dir():
            return path
    except Exception:
        pass
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def main() -> int:
    name = "COFRE"
    if "--name" in sys.argv:
        name = sys.argv[sys.argv.index("--name") + 1]

    for need, label in ((PYTHONW, "pythonw.exe del venv"), (ICON, "assets/cofre.ico")):
        if not need.exists():
            print(f"falta {label}: {need}")
            return 1

    desktop = desktop_dir()
    lnk = desktop / f"{name}.lnk"
    ps = f"""
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut('{lnk}')
$s.TargetPath = '{PYTHONW}'
$s.Arguments = '-m cofre.cli gui'
$s.WorkingDirectory = '{REPO}'
$s.IconLocation = '{ICON},0'
$s.Description = 'COFRE - boveda de secretos'
$s.WindowStyle = 1
$s.Save()
Write-Output ('creado ' + '{lnk}')
"""
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                            capture_output=True, text=True)
    print(result.stdout.strip() or result.stderr.strip())
    if not lnk.exists():
        return 1
    print("tamano:", lnk.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
