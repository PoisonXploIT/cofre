"""El token de la App no debe quedar en disco ni en el log (punto 4).

Se ejecuta con un servidor falso y se comprueba que el valor del token de
instalacion no aparece en ningun fichero de la carpeta del cofre.
"""

from __future__ import annotations

import os
import pathlib
import secrets
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre.usb import register_stick, volume_serial
from cofre.v2 import VaultV2, new_usb_slot
from fake_github import FakeGitHub

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    HAY_CRYPTO = True
except ImportError:                                    # pragma: no cover
    HAY_CRYPTO = False


@unittest.skipUnless(HAY_CRYPTO, "hace falta cryptography")
class TestTokenNoPersiste(unittest.TestCase):
    def test_el_token_de_la_app_no_toca_disco(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="cofre-apptoken-"))
        vault = tmp / "cofre.json"
        llave = tmp / "COFRE.KEY"
        llave.write_bytes(secrets.token_bytes(32))
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()).decode()
        master = secrets.token_bytes(32)
        serial = volume_serial(str(tmp.drive) + "\\")
        v2 = VaultV2(vault)
        datos = v2.create(master, new_usb_slot(master, llave.read_bytes(), serial, "t", ""))
        v2.put(datos, master, "GH_APP_PRIVATE_KEY", pem, ["admin"], [], kind="private_key")
        v2.save(datos)
        register_stick(str(vault), serial, str(tmp.drive) + "\\")

        fake = FakeGitHub()
        base = fake.start()
        fake.installation_token = "ghs_SECRETO_QUE_NO_DEBE_QUEDAR"
        env = dict(os.environ, COFRE_GITHUB_API=base, COFRE_VAULT=str(vault))
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "cofre.cli", "--gate", "usb",
                 "--vault", str(vault), "--stick", str(llave),
                 "app-exec", "--app-id", "123", "--installation", "12345",
                 "--var", "TOKEN_PRUEBA",
                 "--", sys.executable, "-c",
                 "import os;print('inyectado' if os.environ.get('TOKEN_PRUEBA') else 'vacio')"],
                capture_output=True, text=True, env=env, timeout=120)
            self.assertIn("inyectado", proc.stdout)
            # ni en el log ni en ningun fichero de la carpeta del cofre
            for fichero in tmp.rglob("*"):
                if fichero.is_file():
                    datos_leidos = fichero.read_text(encoding="utf-8", errors="ignore")
                    self.assertNotIn("ghs_SECRETO_QUE_NO_DEBE_QUEDAR", datos_leidos,
                                     f"el token aparecio en {fichero}")
        finally:
            fake.stop()
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
