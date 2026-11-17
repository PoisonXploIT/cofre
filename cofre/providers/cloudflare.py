"""COFRE - proveedor Cloudflare (paso 5.3).

Tres operaciones, todas con la API oficial de tokens:

  verify(valor)                  GET  /client/v4/user/tokens/verify
  roll_value(id, admin)          PUT  /client/v4/user/tokens/{id}/value
  create_replacement(meta, admin) POST /client/v4/user/tokens   (copia politicas)
  revoke(id, admin)              DELETE /client/v4/user/tokens/{id}

El token ADMINISTRADOR es el unico que puede gestionar tokens: por eso vive en el
cofre con la etiqueta `admin`, que obliga a confirmar y lo cierra al navegador y a
`exec`.

Nada de esto se registra con el valor dentro: `http.request` no escribe cabeceras
ni cuerpos en ningun sitio.
"""

from __future__ import annotations

from datetime import date, timedelta

from cofre.providers.base import Provider, VerifyResult, register
from cofre.providers.http import ProviderError, base_url, request

API = "https://api.cloudflare.com/client/v4"


def _api() -> str:
    return base_url(API, "COFRE_CLOUDFLARE_API")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _ok(status: int, body) -> bool:
    if not isinstance(body, dict):
        return False
    return 200 <= status < 300 and bool(body.get("success", True))


class Cloudflare(Provider):
    name = "cloudflare"
    can_auto_rotate = True

    def manual_url(self, meta: dict) -> str:
        return "https://dash.cloudflare.com/profile/api-tokens"

    # -------------------------------------------------------------- verify

    def verify(self, value: str, meta: dict) -> VerifyResult:
        status, _h, body = request("GET", f"{_api()}/user/tokens/verify",
                                   headers=_headers(value))
        if not isinstance(body, dict):
            return VerifyResult(False, detail="respuesta ilegible del proveedor")
        if not _ok(status, body):
            detalle = _errores(body) or f"HTTP {status}"
            return VerifyResult(False, detail=detalle)
        result = body.get("result") or {}
        estado = str(result.get("status", ""))
        caduca = str(result.get("expires_on", ""))[:10]
        ident = str(result.get("id", ""))
        if estado and estado != "active":
            return VerifyResult(False, caduca, f"el token esta en estado '{estado}'",
                                ident, estado)
        return VerifyResult(True, caduca, "activo", ident, estado or "active")

    # -------------------------------------------------------------- roll

    def roll_value(self, token_id: str, admin_value: str, meta: dict) -> str:
        """Variante A: mismo token, valor nuevo. El viejo deja de valer."""
        if not token_id:
            raise ProviderError("falta el id del token (meta --token-id)")
        ref = meta.get("provider_ref") or {}
        cuenta = ref.get("account_id")
        if cuenta:
            url = f"{_api()}/accounts/{cuenta}/tokens/{token_id}/value"
        else:
            url = f"{_api()}/user/tokens/{token_id}/value"
        status, _h, body = request("PUT", url, headers=_headers(admin_value),
                                   json_body={})
        if not _ok(status, body):
            raise ProviderError(f"el proveedor rechazo el roll: {_errores(body) or status}")
        nuevo = (body.get("result") or {})
        if isinstance(nuevo, dict):
            nuevo = nuevo.get("value", "")
        if not nuevo:
            raise ProviderError("el proveedor no devolvio el valor nuevo")
        return str(nuevo)

    # -------------------------------------------------------------- B

    def create_replacement(self, meta: dict, admin_value: str) -> tuple[str, dict]:
        """Variante B: token nuevo copiando politicas y condicion."""
        ref = meta.get("provider_ref") or {}
        token_id = ref.get("token_id")
        if not token_id:
            raise ProviderError("falta el id del token para copiar sus politicas")
        status, _h, body = request("GET", f"{_api()}/user/tokens/{token_id}",
                                   headers=_headers(admin_value))
        if not _ok(status, body):
            raise ProviderError(f"no se pudo leer el token: {_errores(body) or status}")
        actual = body.get("result") or {}

        dias = int(meta.get("rotate_every_days") or 90) + 14
        caduca = (date.today() + timedelta(days=dias)).isoformat()
        nombre = str(actual.get("name") or meta.get("name") or "token")
        nuevo_nombre = f"{nombre} (rotado {date.today().isoformat()})"

        carga = {"name": nuevo_nombre, "policies": actual.get("policies") or [],
                 "expires_on": caduca}
        if actual.get("condition"):
            carga["condition"] = actual["condition"]
        status, _h, body = request("POST", f"{_api()}/user/tokens",
                                   headers=_headers(admin_value), json_body=carga)
        if not _ok(status, body):
            raise ProviderError(f"no se pudo crear el token nuevo: {_errores(body) or status}")
        creado = body.get("result") or {}
        valor = str(creado.get("value", ""))
        if not valor:
            raise ProviderError("el proveedor no devolvio el valor del token nuevo")
        ref_nuevo = dict(ref)
        ref_nuevo["token_id"] = str(creado.get("id", ""))
        return valor, ref_nuevo

    def revoke(self, token_id: str, admin_value: str, meta: dict) -> None:
        if not token_id:
            raise ProviderError("falta el id del token a revocar")
        status, _h, body = request("DELETE", f"{_api()}/user/tokens/{token_id}",
                                   headers=_headers(admin_value))
        if not _ok(status, body):
            raise ProviderError(f"no se pudo revocar el token viejo: {_errores(body) or status}")


def _errores(body) -> str:
    if not isinstance(body, dict):
        return ""
    errores = body.get("errors") or []
    textos = [str(e.get("message") or e) for e in errores if isinstance(e, dict)]
    return "; ".join(textos)[:200]


CLOUDFLARE = register(Cloudflare())
