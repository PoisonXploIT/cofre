"""Instala el host de mensajeria nativa real de COFRE (Windows).

Escribe el manifiesto del host y lo registra en las claves que lee Brave/Chrome,
con las siete condiciones verificadas el 2026-11-16:

  1. se descubre por registro, no por carpetas;
  2. Brave lee HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts (se escriben
     tambien la de Chromium y la de Brave por si cambia);
  3. el valor es el PREDETERMINADO de la subclave, no un valor con nombre;
  4. la subclave se llama igual que el campo "name" del manifiesto;
  5. "path" absoluta;
  6. "description" presente (sin el: "host not found");
  7. allowed_origins con barra final y JSON sin BOM.

  python tools/install_host.py            # instala
  python tools/install_host.py --show     # solo muestra lo que haria
  python tools/uninstall_host.py          # quita registro y manifiesto
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import winreg
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "extension"
MANIFEST = EXT / "manifest.json"
HOST_NAME = "com.cofre.host"
LAUNCHER = REPO / "nmhost" / "cofre-host.bat"

ROOTS = [
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
]


def extension_id() -> str:
    key = json.loads(MANIFEST.read_text(encoding="utf-8")).get("key")
    if not key:
        raise SystemExit("extension/manifest.json no tiene 'key': ejecuta install_extension.py")
    der = base64.b64decode(key)
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join("abcdefghijklmnop"[int(c, 16)] for c in digest)


def host_manifest_path() -> Path:
    return REPO / "nmhost" / f"{HOST_NAME}.json"


def write_manifest() -> Path:
    ident = extension_id()
    data = {
        "name": HOST_NAME,
        # Sin description, Brave responde "Specified native messaging host not
        # found" y parece un problema de rutas. Costo horas el 2026-11-16.
        "description": "COFRE: puente entre la extension y la GUI local (tuberia con nombre)",
        "path": str(LAUNCHER.resolve()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ident}/"],
    }
    target = host_manifest_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def register(manifest: Path) -> list[str]:
    hechas = []
    for root in ROOTS:
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{root}\{HOST_NAME}",
                                    0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest))
            hechas.append(root)
        except OSError as exc:
            print(f"aviso: no se pudo escribir {root}: {exc}")
    return hechas


def main() -> int:
    if not LAUNCHER.exists():
        print(f"falta {LAUNCHER}")
        return 1
    manifest = write_manifest()
    ident = extension_id()
    print("extension id:", ident)
    print("manifiesto del host:", manifest)
    print(json.dumps(json.loads(manifest.read_text(encoding="utf-8")), indent=2,
                     ensure_ascii=False))
    if "--show" in sys.argv:
        print("(solo muestra: no se ha escrito el registro)")
        return 0
    for root in register(manifest):
        print("registrado en HKCU\\" + root)
    print("")
    print("Siguiente: recarga la extension en el navegador y activa 'Navegador' en COFRE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
