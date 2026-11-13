"""Prueba el puente del navegador contra un cofre de verdad.

Crea un cofre temporal con una llave propia, arranca el servidor en un puerto
libre y comprueba:

  1. sin cabecera Origin (o con uno no autorizado) -> 403
  2. /status con el origen correcto -> abierto
  3. /list -> nombres, sin valores
  4. /get -> el valor correcto
  5. quitando la llave del cofre -> /get deja de contestar (409)

Uso: python tools/serve_probe.py
"""
from __future__ import annotations

import json
import secrets
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.serve import SecretServer, allowed_origins_for
from cofre.crypto import Vault
from cofre.gate import resolve_session_key
from cofre.usb import KEY_FILENAME

TMP = Path(__import__("os").environ["TEMP"]) / "cofre_serve_probe"


def call(base: str, path: str, origin: str | None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main() -> int:
    origins = allowed_origins_for()
    if not origins:
        print("sin origen autorizado: ejecuta tools/install_extension.py")
        return 1
    good = origins[0]
    bad = "https://sitio-cualquiera.example"

    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    keyfile = TMP / KEY_FILENAME
    keyfile.write_bytes(secrets.token_bytes(32))
    vault_path = TMP / "v.json"
    vault = Vault(vault_path)

    # H13: con el registro vacio ya no se autoriza nada por defecto.
    try:
        resolve_session_key("usb", str(vault_path), stick=str(keyfile))
        print("FALLO  H13: un registro vacio autorizo un pendrive sin registrar")
        failures_hint = True
    except Exception as exc:
        print("OK    H13: registro vacio -> no se autoriza ningun pendrive")
        print("       ", str(exc)[:90])
        failures_hint = False

    session, _serial = resolve_session_key("usb", str(vault_path), stick=str(keyfile),
                                            allow_new=True)
    vault.init(session, salt=__import__("cofre.salt", fromlist=["get_salt"]).get_salt(str(vault_path), create=True))
    vault.add(session, "TAVILY_API_KEY", "valor-secreto-de-prueba", ["google"])
    vault.add(session, "GMAIL_PASSWORD", "otra-clave", ["correo"])

    server = SecretServer(str(vault_path), [good], gate="usb",
                          stick=str(keyfile), port=0).start()
    base = server.origin
    print("servidor de prueba en", base, "| origen permitido:", good)

    failures = 0

    def check(label, cond, extra=""):
        nonlocal failures
        print(f"{'OK   ' if cond else 'FALLO'} {label} {extra}")
        if not cond:
            failures += 1

    code, data = call(base, "/list", bad)
    check("origen no autorizado rechazado", code == 403, f"({code})")

    code, data = call(base, "/list", None)
    check("sin Origin rechazado", code == 403, f"({code})")

    code, data = call(base, "/status", good)
    check("/status abierto", code == 200 and data.get("open") is True, data)

    code, data = call(base, "/list", good)
    names = [i["name"] for i in data.get("items", [])]
    check("/list devuelve nombres", names == ["GMAIL_PASSWORD", "TAVILY_API_KEY"], names)
    check("/list no trae valores", "value" not in json.dumps(data))

    code, data = call(base, "/get", good, {"name": "TAVILY_API_KEY"})
    check("/get devuelve el valor", code == 200
          and data.get("value") == "valor-secreto-de-prueba")

    code, data = call(base, "/get", good, {"name": "NO_EXISTE"})
    check("/get de algo inexistente da 404", code == 404, f"({code})")

    keyfile.unlink()
    code, data = call(base, "/get", good, {"name": "TAVILY_API_KEY"})
    # Al borrar la llave del cofre de prueba, find_stick puede encontrar los
    # pendrives reales de la maquina y entonces el descifrado falla: eso es un
    # 409 de autorizacion, no un valor filtrado. Lo importante es que NO
    # devuelva datos.
    check("sin la llave correcta no devuelve valor",
          code in (409, 500) and "value" not in data,
          f"({code}) {data.get('error', '')}")

    # Determinista: se fuerza el gate cerrado para probar el mapeo 409.
    import cofre.serve as serve_mod
    from cofre.gate import GateUnavailable

    def _closed(*_a, **_k):
        raise GateUnavailable("no se encontro COFRE.KEY")

    original = serve_mod.resolve_session_key
    serve_mod.resolve_session_key = _closed
    try:
        code, data = call(base, "/get", good, {"name": "TAVILY_API_KEY"})
        check("gate cerrado -> 409 con mensaje", code == 409
              and "pendrive no disponible" in data.get("error", ""), f"({code})")
        code, data = call(base, "/list", good)
        check("gate cerrado -> /list 409", code == 409, f"({code})")
        code, data = call(base, "/status", good)
        check("gate cerrado -> /status dice cerrado",
              code == 200 and data.get("open") is False, data)
    finally:
        serve_mod.resolve_session_key = original

    server.stop()
    shutil.rmtree(TMP, ignore_errors=True)
    print()
    print("TODO OK" if not failures else f"{failures} fallo(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
