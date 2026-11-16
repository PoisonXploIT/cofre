"""Borra los hosts de la sonda H23 del registro y los manifests generados.

  python tools/nm_probe/uninstall_hosts.py
"""

from __future__ import annotations

from pathlib import Path
import winreg

HERE = Path(__file__).resolve().parent
ROOTS = [
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
]


def main() -> int:
    removed = 0
    for root in ROOTS:
        for name in ("bat", "cmd", "python", "py"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{root}\com.cofre.{name}")
                print("borrada clave:", rf"{root}\com.cofre.{name}")
                removed += 1
            except FileNotFoundError:
                pass
    for f in HERE.glob("com.cofre.*.json"):
        f.unlink()
        print("borrado manifest:", f.name)
    print(f"\n{removed} claves eliminadas. La extension se quita desde brave://extensions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
