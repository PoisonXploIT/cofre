"""Genera la clave de la extension y fija su ID en extension/manifest.json.

Por que una clave: sin 'key' en el manifest, Chrome asigna un ID distinto a cada
instalacion y el servidor no puede tener una lista de origenes exacta. Con la
clave publica incrustada, el ID es determinista (SHA-256 de la clave DER, 16
bytes, base32 con alfabeto a-p) y el servidor puede exigir exactamente ese
origen.

Uso:
  python tools/install_extension.py            # crea o reutiliza la clave
  python tools/install_extension.py --show     # solo muestra el ID actual
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "extension"
KEY_FILE = EXT / ".extension-key.pem"
MANIFEST = EXT / "manifest.json"


def id_from_public_der(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest()[:32]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[int(ch, 16)] for ch in digest)


def ensure_key() -> bytes:
    """Devuelve la clave publica DER, creando el par si no existe."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if KEY_FILE.exists():
        private = serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    else:
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEY_FILE.write_bytes(private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()))
        print("clave creada:", KEY_FILE)
    return private.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)


def main() -> int:
    if not MANIFEST.exists():
        print("falta extension/manifest.json")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    if "--show" in sys.argv:
        print("extension id:", id_from_public_der(base64.b64decode(manifest["key"]))
              if manifest.get("key") else "(sin clave: ID aleatorio)")
        return 0

    der = ensure_key()
    manifest["key"] = base64.b64encode(der).decode("ascii")
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    ext_id = id_from_public_der(der)

    print("clave publica escrita en", MANIFEST.name)
    print("extension id:", ext_id)
    print("origen permitido: chrome-extension://" + ext_id)
    print()
    print("Pasos en Chrome/Edge:")
    print("  1. chrome://extensions  (o edge://extensions)")
    print("  2. activar 'Modo de desarrollador'")
    print("  3. 'Cargar descomprimida' y elegir", EXT)
    print("  4. comprobar que el ID coincide con el de arriba")
    print()
    print("El servidor del cofre ya acepta ese origen automaticamente:")
    print("  run.cmd serve --port 47653")
    return 0


if __name__ == "__main__":
    sys.exit(main())
