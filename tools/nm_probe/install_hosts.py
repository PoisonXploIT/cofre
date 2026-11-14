"""Escribe los manifests de host de mensajeria nativa para la sonda H23.

Los coloca en las rutas que busca Chromium en Windows (Chrome y Brave) y usa
el ID determinista de la extension de prueba (el mismo que da su campo 'key').

  python tools/nm_probe/install_hosts.py
  python tools/nm_probe/install_hosts.py --show
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
PY = sys.executable

CANDIDATES = [
    LOCALAPPDATA / "Google" / "Chrome" / "Application" / "Chrome",
    LOCALAPPDATA / "BraveSoftware" / "Brave-Browser" / "Application" / "Brave",
    LOCALAPPDATA / "BraveSoftware" / "Brave-Browser",
    LOCALAPPDATA,
]

HOSTS = {
    "bat": HERE / "host.bat",
    "cmd": HERE / "host.cmd",
    "python": Path(PY),
    "py": HERE / "host.py",
}


def ext_id() -> str:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    der = base64.b64decode(manifest["key"])
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join("abcdefghijklmnop"[int(c, 16)] for c in digest)


def main() -> int:
    if not (HERE / "manifest.json").exists():
        print("Primero hay que generar el manifest de la prueba. Ejecuta el probe o crea manifest.json a mano.")
        return 1
    ident = ext_id()
    origin = f"chrome-extension://{ident}"
    written = []
    for base in CANDIDATES:
        d = base / "nativeMessaging"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for name, path in HOSTS.items():
            f = d / f"com.cofre.{name}.json"
            f.write_text(json.dumps({
                "name": f"com.cofre.{name}",
                "path": str(path),
                "type": "stdio",
                "allowed_origins": [origin],
            }, indent=2), encoding="utf-8")
            written.append(str(f))
    print("id de la extension de prueba:", ident)
    print("origen autorizado:", origin)
    for w in written:
        print("  host escrito:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
