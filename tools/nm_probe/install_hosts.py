"""Instala los hosts de mensajeria nativa de la sonda H23 (Windows).

Lo que se aprendio el 2026-11-16 probandolo en Brave:

  1. En Windows el host NO se descubre por carpetas: se descubre por el REGISTRO.
     Las carpetas `nativeMessaging` son cosa de Linux y macOS.
  2. Brave lee `HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts` (la clave de
     Chrome). Tambien se escribe la de Brave y la de Chromium por si acaso.
  3. El valor que importa es el PREDETERMINADO (sin nombre) de la subclave que se
     llama igual que el host. Un valor con nombre no sirve.
  4. El 'path' del manifest debe ser ABSOLUTO. Con ruta relativa: "host not found".
  5. El manifest DEBE llevar el campo "description". Sin el, Brave responde
     "Specified native messaging host not found" aunque todo lo demas este bien.
  6. allowed_origins necesita la barra final: chrome-extension://<id>/
  7. Sin BOM.

  python tools/nm_probe/install_hosts.py
  python tools/nm_probe/uninstall_hosts.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path
import winreg

HERE = Path(__file__).resolve().parent
PY = sys.executable

ROOTS = [
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
]

HOSTS = {
    "bat": (HERE / "host.bat", "Sonda H23: envoltorio .bat -> python host.py"),
    "cmd": (HERE / "host.cmd", "Sonda H23: envoltorio .cmd -> python host.py"),
    "python": (Path(PY), "Sonda H23: python.exe directo (sin script)"),
    "py": (HERE / "host.py", "Sonda H23: script .py (no es ejecutable Win32)"),
}


def ext_id() -> str:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    der = base64.b64decode(manifest["key"])
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join("abcdefghijklmnop"[int(c, 16)] for c in digest)


def main() -> int:
    ident = ext_id()
    origin = f"chrome-extension://{ident}/"
    print("extension de prueba:", ident)
    print("origen autorizado:  ", origin)
    for name, (path, desc) in HOSTS.items():
        host = f"com.cofre.{name}"
        manifest = HERE / f"{host}.json"
        manifest.write_text(json.dumps({
            "name": host,
            "description": desc,
            "path": str(path),          # absoluta: obligatorio
            "type": "stdio",
            "allowed_origins": [origin],
        }, indent=2), encoding="utf-8")   # sin BOM
        for root in ROOTS:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\{host}",
                                    0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest))
        print(f"  {host:18} -> {path}")
    print("\nListo. Recarga la extension en el navegador y abre probe.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
