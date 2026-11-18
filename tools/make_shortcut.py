"""Crea los accesos directos del cofre en el escritorio.

  COFRE              -> pythonw.exe, sin consola (uso normal)
  COFRE (diagnostico)-> run-diag.cmd, con consola (para leer errores)

Uso: python tools/make_shortcut.py [--name COFRE] [--only normal|diag]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHONW = REPO / ".venv" / "Scripts" / "pythonw.exe"
ICON = REPO / "assets" / "cofre.ico"
DIAG = REPO / "run-diag.cmd"


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


def make(lnk: Path, target: Path, args: str, workdir: Path,
         description: str, style: int = 1) -> bool:
    ps = f"""
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut('{lnk}')
$s.TargetPath = '{target}'
$s.Arguments = '{args}'
$s.WorkingDirectory = '{workdir}'
$s.IconLocation = '{ICON},0'
$s.Description = '{description}'
$s.WindowStyle = {style}
$s.Save()
"""
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("error:", result.stderr.strip())
        return False
    return lnk.exists()


def main() -> int:
    name = "COFRE"
    if "--name" in sys.argv:
        name = sys.argv[sys.argv.index("--name") + 1]
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None

    for need, label in ((PYTHONW, "pythonw.exe del venv"), (ICON, "assets/cofre.ico"),
                        (DIAG, "run-diag.cmd")):
        if not need.exists():
            print(f"falta {label}: {need}")
            return 1

    desktop = desktop_dir()
    ok = True
    if only in (None, "normal"):
        lnk = desktop / f"{name}.lnk"
        ok &= make(lnk, PYTHONW, "-m cofre.cli gui", REPO,
                   "COFRE - bóveda de secretos")
        print("normal     :", lnk, "(", lnk.stat().st_size if lnk.exists() else 0, "bytes )")
    if only in (None, "diag"):
        lnk = desktop / f"{name} (diagnostico).lnk"
        ok &= make(lnk, DIAG, "", REPO,
                   "COFRE - modo diagnostico (con consola)")
        print("diagnostico:", lnk, "(", lnk.stat().st_size if lnk.exists() else 0, "bytes )")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
