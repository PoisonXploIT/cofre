"""COFRE - cliente HTTP minimo para proveedores (paso 5.2).

Una sola funcion, con urllib y sin dependencias. Reglas que no se rompen:

  - nunca se registran cabeceras ni cuerpos: llevan el token;
  - un error de red se convierte en ProviderError con mensaje en espanol y sin
    el valor;
  - la URL base es configurable para poder probar contra un servidor falso.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class ProviderError(RuntimeError):
    """Fallo al hablar con el proveedor. Nunca lleva el valor del secreto."""


def base_url(default: str, env: str = "COFRE_HTTP_BASE") -> str:
    """Permite apuntar a un servidor falso en las pruebas."""
    return os.environ.get(env, default).rstrip("/")


def request(method: str, url: str, headers: dict | None = None,
            json_body: dict | None = None, timeout: int = 20,
            form_body: dict | None = None) -> tuple[int, dict, object]:
    data = None
    cabeceras = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        cabeceras.setdefault("Content-Type", "application/json")
    elif form_body is not None:
        data = urllib.parse.urlencode(form_body).encode("utf-8")
        cabeceras.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = urllib.request.Request(url, data=data, headers=cabeceras, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cuerpo = resp.read().decode("utf-8", "replace")
            return resp.status, dict(resp.headers), _parse(cuerpo)
    except urllib.error.HTTPError as exc:
        cuerpo = exc.read().decode("utf-8", "replace")
        return exc.code, dict(exc.headers or {}), _parse(cuerpo)
    except urllib.error.URLError as exc:
        raise ProviderError(f"no se pudo conectar con el proveedor ({exc.reason})") from exc
    except OSError as exc:
        raise ProviderError(f"error de red: {type(exc).__name__}") from exc


def _parse(cuerpo: str):
    if not cuerpo:
        return {}
    try:
        return json.loads(cuerpo)
    except json.JSONDecodeError:
        return cuerpo
