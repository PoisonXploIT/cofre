"""Quita el host de mensajeria nativa de COFRE.

  python tools/uninstall_host.py
"""

from __future__ import annotations

import winreg
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOST_NAME = "com.cofre.host"
ROOTS = [
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
]


def main() -> int:
    for root in ROOTS:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{root}\{HOST_NAME}")
            print("clave borrada:", rf"HKCU\{root}\{HOST_NAME}")
        except FileNotFoundError:
            pass
    manifest = REPO / "nmhost" / f"{HOST_NAME}.json"
    if manifest.exists():
        manifest.unlink()
        print("manifiesto borrado:", manifest)
    print("")
    print("La extension se quita desde la pagina de extensiones del navegador.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
