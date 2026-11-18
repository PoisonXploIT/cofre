"""COFRE - proveedor generico configurable (paso 5.5, hecho el 2026-11-18).

Hasta ahora Salud solo sabia comprobar Cloudflare y GitHub. Esto cubre el resto
(Tavily, OpenAI, Hugging Face, Anthropic, Stripe, cualquier API con un endpoint de
"quien soy") sin escribir un proveedor por servicio.

Dos maneras de usarlo:

  1. **Catalogo**: `run.cmd meta TAVILY_API_KEY --provider tavily` y listo. Los
     servicios conocidos llevan su comprobacion escrita aqui (`CATALOGO`).
  2. **A mano**: `--provider generic` y la comprobacion en el indice cifrado, con
     `run.cmd meta NOMBRE --verify '{...}'`. Las claves del JSON:

         method    GET (por defecto) o POST
         url       a donde se pregunta (obligatoria)
         header    cabecera que lleva el valor (por defecto Authorization)
         prefix    lo que va delante del valor ("Bearer " por defecto)
         ok        codigos HTTP que cuentan como valido (por defecto [200])
         json_ok   ruta en la respuesta que tiene que ser verdadera, con puntos
         expires   ruta en la respuesta con la fecha de caducidad
         manual_url  pagina del servicio para crear el valor a mano
         body      cuerpo JSON, si el endpoint lo pide

La configuracion vive en `meta["verify"]`, dentro del **indice cifrado**, y nunca
se escribe en el registro. El valor del secreto no se imprime ni se guarda: solo
viaja en la cabecera de la peticion.
"""

from __future__ import annotations

import os
import urllib.parse

from cofre.providers.base import Provider, VerifyResult, register
from cofre.providers.http import ProviderError, request


def _ruta(datos, camino: str):
    """Saca `a.b.c` de un diccionario; None si no esta."""
    actual = datos
    for parte in str(camino or "").split("."):
        if not parte:
            continue
        if isinstance(actual, dict):
            actual = actual.get(parte)
        elif isinstance(actual, list):
            try:
                actual = actual[int(parte)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if actual is None:
            return None
    return actual


# Comprobaciones conocidas. "whoami" es un endpoint que responde 200 (o 401) con
# el propio token: lo justo para saber si sigue vivo, sin pedir permisos de mas.
CATALOGO: dict[str, dict] = {
    "tavily": {
        "url": "https://api.tavily.com/search",
        "method": "POST",
        "header": "Authorization",
        "prefix": "Bearer ",
        "ok": [200],
        "body": {"query": "ping", "max_results": 1},
        "manual_url": "https://app.tavily.com/home",
    },
    "openai": {
        "url": "https://api.openai.com/v1/models",
        "header": "Authorization",
        "prefix": "Bearer ",
        "ok": [200],
        "manual_url": "https://platform.openai.com/api-keys",
    },
    "huggingface": {
        "url": "https://huggingface.co/api/whoami-v2",
        "header": "Authorization",
        "prefix": "Bearer ",
        "ok": [200],
        "json_ok": "name",
        "manual_url": "https://huggingface.co/settings/tokens",
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/models",
        "header": "x-api-key",
        "prefix": "",
        "ok": [200],
        "manual_url": "https://console.anthropic.com/settings/keys",
    },
    "stripe": {
        "url": "https://api.stripe.com/v1/balance",
        "header": "Authorization",
        "prefix": "Bearer ",
        "ok": [200],
        "manual_url": "https://dashboard.stripe.com/apikeys",
    },
}


def url_final(url: str) -> str:
    """La url a la que se pregunta.

    `COFRE_GENERIC_BASE` cambia solo el origen (esquema, host y puerto) y conserva
    el camino: asi las pruebas apuntan a un servidor falso sin reescribir cada
    configuracion, y en produccion no hay variable puesta.
    """
    base = os.environ.get("COFRE_GENERIC_BASE")
    if not base:
        return url
    partes = urllib.parse.urlsplit(url)
    camino = partes.path or ""
    if partes.query:
        camino += "?" + partes.query
    return base.rstrip("/") + camino


def _config(meta: dict, defecto: dict | None = None) -> dict:
    """Catalogo + lo que haya en `meta["verify"]`, con esto último mandando."""
    cfg = dict(defecto or {})
    extra = meta.get("verify")
    if isinstance(extra, dict):
        cfg.update({k: v for k, v in extra.items() if v not in ("", None)})
    return cfg


class Generic(Provider):
    """Comprobacion configurable. No sabe rotar: eso se hace a mano."""

    name = "generic"
    can_auto_rotate = False

    def __init__(self, nombre: str | None = None, defecto: dict | None = None):
        self.name = nombre or "generic"
        self.defecto = dict(defecto or {})

    # ------------------------------------------------------------- verify

    def verify(self, value: str, meta: dict) -> VerifyResult:
        cfg = _config(meta, self.defecto)
        url = str(cfg.get("url") or "")
        if not url:
            return VerifyResult(False, detail="falta la url de comprobación "
                                              "(run.cmd meta NOMBRE --verify ...)")
        if not value:
            return VerifyResult(False, detail="el secreto está vacío")

        cabecera = str(cfg.get("header") or "Authorization")
        prefijo = str(cfg.get("prefix", "Bearer "))
        cabeceras = {cabecera: f"{prefijo}{value}"}
        metodo = str(cfg.get("method") or "GET").upper()
        cuerpo = cfg.get("body") if isinstance(cfg.get("body"), dict) else None
        url = url_final(url)

        try:
            status, _h, datos = request(metodo, url, headers=cabeceras,
                                        json_body=cuerpo, timeout=20)
        except ProviderError as exc:
            return VerifyResult(False, detail=str(exc))

        validos = cfg.get("ok") or [200]
        try:
            validos = [int(c) for c in validos]
        except (TypeError, ValueError):
            validos = [200]

        if status not in validos:
            return VerifyResult(False, detail=f"el proveedor responde HTTP {status}")

        ruta_ok = str(cfg.get("json_ok") or "")
        if ruta_ok:
            encontrado = _ruta(datos, ruta_ok)
            if not encontrado:
                return VerifyResult(False, detail=f"la respuesta no trae '{ruta_ok}'")

        caduca = ""
        ruta_cad = str(cfg.get("expires") or "")
        if ruta_cad:
            caduca = str(_ruta(datos, ruta_cad) or "")[:10]

        return VerifyResult(True, caduca, "responde", "", "active")

    def manual_url(self, meta: dict) -> str:
        cfg = _config(meta, self.defecto)
        return str(cfg.get("manual_url") or "")

    # ------------------------------------------------------- no hay rotacion

    def roll_value(self, token_id: str, admin_value: str, meta: dict) -> str:
        raise ProviderError("este proveedor no rota solo: usa rotate --manual")

    def create_replacement(self, meta: dict, admin_value: str) -> tuple[str, dict]:
        raise ProviderError("este proveedor no rota solo: usa rotate --manual")

    def revoke(self, token_id: str, admin_value: str, meta: dict) -> None:
        raise ProviderError("este proveedor no revoca solo: hazlo en su web")


GENERICO = register(Generic())
for _nombre, _cfg in CATALOGO.items():
    register(Generic(_nombre, _cfg))


def conocido(nombre: str) -> bool:
    return nombre in CATALOGO
