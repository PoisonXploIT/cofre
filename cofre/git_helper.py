"""COFRE - ayudante de credenciales para git (paso 7.2, corregido).

NO abre el cofre ni lee el pendrive. Habla por la tuberia con la GUI, que es la
unica que tiene la sesion. Con la GUI cerrada no devuelve nada: git pedira la
contraseña como siempre.

La GUI comprueba el cliente, consulta la politica del canal `git` y pide
confirmacion la primera vez por host (o "Permitir 5 minutos"). El valor solo
viaja por la tuberia local y sale por stdout; nunca al log.
"""

from __future__ import annotations

import os
import sys

from cofre.nmhost import forward

LARGO_CONFIRMACION_MS = 25_000


def _leer_stdin() -> dict[str, str]:
    datos: dict[str, str] = {}
    for linea in sys.stdin:
        linea = linea.rstrip("\r\n")
        if not linea:
            break
        if "=" in linea:
            clave, valor = linea.split("=", 1)
            datos[clave.strip()] = valor.strip()
    return datos


def _host(datos: dict[str, str]) -> str:
    host = datos.get("host", "")
    if host:
        return host.lower()
    url = datos.get("url", "")
    if "://" in url:
        return url.split("://", 1)[1].split("/", 1)[0].lower()
    return ""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    operacion = argv[0] if argv else "get"
    datos = _leer_stdin()
    if operacion != "get":
        return 0
    host = _host(datos)
    if not host:
        return 0
    # La tuberia es del proceso de la GUI. Si no esta, no hay nada que hacer:
    # este proceso no abre el cofre.
    respuesta = forward({"type": "git", "host": host},
                        reply_timeout_ms=LARGO_CONFIRMACION_MS)
    if not isinstance(respuesta, dict) or not respuesta.get("ok"):
        return 0
    usuario = str(respuesta.get("username") or "")
    valor = str(respuesta.get("password") or "")
    if not usuario or not valor:
        return 0
    sys.stdout.write(f"username={usuario}\npassword={valor}\n\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
