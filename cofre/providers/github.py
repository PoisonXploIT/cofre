"""Proveedor GitHub (paso 5.4).

GitHub no permite rotar un PAT por API: hay que crearlo a mano en la web. Por eso
aqui la rotacion es **asistida**:

  - `verify(valor)`            GET /user con el PAT: valida y da login y scopes
  - `manual_url(meta)`         pagina donde se crea el token nuevo
  - `create_replacement(...)`  no soportado: se llama a `manual_url` y el usuario
                               pega el valor nuevo

Y para lo automatizado esta la **GitHub App** (decision D4): COFRE guarda la
clave privada y fabrica tokens de instalacion que caducan en una hora. No hay
nada que rotar: un token robado sirve como mucho 60 minutos.

  - `app_jwt(app_id, clave_pem)`         JWT RS256 firmado con la clave privada
  - `installation_token(jwt, instal_id)` POST /app/installations/{id}/access_tokens
"""

from __future__ import annotations

import base64
import json
import time

from cofre.providers.base import Provider, VerifyResult, register
from cofre.providers.http import ProviderError, base_url, request

API = "https://api.github.com"


def _api() -> str:
    return base_url(API, "COFRE_GITHUB_API")


def _headers(token: str | None = None, accept: str = "application/vnd.github+json") -> dict:
    cabeceras = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    return cabeceras


class GitHub(Provider):
    name = "github"
    can_auto_rotate = False        # el PAT se crea a mano en la web

    def manual_url(self, meta: dict) -> str:
        ref = meta.get("provider_ref") or {}
        # tokens clasicos o fine-grained, segun lo que se haya guardado
        if ref.get("fine_grained"):
            return "https://github.com/settings/personal-access-tokens/new"
        return "https://github.com/settings/tokens/new"

    # -------------------------------------------------------------- verify

    def verify(self, value: str, meta: dict) -> VerifyResult:
        status, cabeceras, body = request("GET", f"{_api()}/user", headers=_headers(value))
        if status == 401:
            return VerifyResult(False, detail="token rechazado por GitHub (401)")
        if not isinstance(body, dict):
            return VerifyResult(False, detail=f"respuesta ilegible (HTTP {status})")
        if status != 200:
            return VerifyResult(False, detail=str(body.get("message") or f"HTTP {status}"))
        login = str(body.get("login") or "")
        scopes = str(cabeceras.get("X-OAuth-Scopes") or "")
        detalle = f"usuario {login}" + (f", scopes: {scopes}" if scopes else "")
        caduca = str(body.get("expires_at") or "")[:10]
        return VerifyResult(True, caduca, detalle)

    # -------------------------------------------------------------- manual

    def create_replacement(self, meta: dict, admin_value: str) -> tuple[str, dict]:
        raise ProviderError(
            "GitHub no permite crear un PAT por API: crea el token en "
            f"{self.manual_url(meta)} y pegalo con 'rotate --manual'")

    def revoke(self, token_id: str, admin_value: str, meta: dict) -> None:
        """Solo fine-grained tokens se pueden revocar por API; lo clasico, a mano."""
        if not token_id:
            raise ProviderError("falta el id del token; en tokens clasicos se borra a mano")
        status, _h, body = request(
            "DELETE", f"{_api()}/user/personal-access-tokens/{token_id}",
            headers=_headers(admin_value))
        if status not in (204, 200):
            raise ProviderError(f"no se pudo revocar: {_errores(body) or status}")


# ------------------------------------------------------------------- App

def app_jwt(app_id: str, clave_pem: str | bytes, ahora: int | None = None) -> str:
    """JWT RS256 para autenticarse como la GitHub App (válido 10 minutos)."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:                          # pragma: no cover
        raise ProviderError("falta 'cryptography' para firmar el JWT de la App") from exc

    def b64(datos: bytes) -> str:
        return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")

    momento = int(time.time() if ahora is None else ahora)
    cabecera = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    cuerpo = b64(json.dumps({"iat": momento - 60, "exp": momento + 540,
                             "iss": str(app_id)}).encode())
    mensaje = f"{cabecera}.{cuerpo}".encode()
    privada = (serialization.load_pem_private_key(clave_pem.encode() if isinstance(clave_pem, str)
                                                  else clave_pem, password=None))
    firma = privada.sign(mensaje, padding.PKCS1v15(), hashes.SHA256())
    return f"{cabecera}.{cuerpo}.{b64(firma)}"


def installation_token(jwt: str, installation_id: str) -> tuple[str, str]:
    """Token de instalacion (caduca en 1 h). Devuelve (valor, caduca_iso)."""
    status, _h, body = request(
        "POST", f"{_api()}/app/installations/{installation_id}/access_tokens",
        headers=_headers(jwt))
    if status not in (200, 201) or not isinstance(body, dict):
        raise ProviderError(f"no se pudo crear el token de instalacion: "
                            f"{_errores(body) or status}")
    valor = str(body.get("token") or "")
    if not valor:
        raise ProviderError("GitHub no devolvio el token de instalacion")
    return valor, str(body.get("expires_at") or "")


def _errores(body) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or "")[:160]
    return ""


GITHUB = register(GitHub())
