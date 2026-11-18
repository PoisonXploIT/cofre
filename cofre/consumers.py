"""COFRE - desplegar el valor nuevo donde se usa (paso 5.6).

`consumers` del indice usa cadenas con este formato:

    gha:propietario/repo:NOMBRE              secreto de repo en GitHub Actions
    gha-env:propietario/repo:entorno:NOMBRE  secreto de entorno en Actions
    cfw:cuenta:script:NOMBRE                 secreto de un Worker de Cloudflare
    exec                                     solo se usa con `cofre exec`
    manual:texto libre                       lo cambia la persona

GitHub cifra los secretos con libsodium (PyNaCl) usando la clave publica del
repo: aqui se cifra con caja sellada y se manda en base64. Cloudflare recibe el
texto y lo guarda como `secret_text`.

Rutas verificadas el 2026-11-17 en la referencia oficial:

  GitHub     GET  /repos/{owner}/{repo}/actions/secrets/public-key
             PUT  /repos/{owner}/{repo}/actions/secrets/{name}
             (entornos: /repos/{owner}/{repo}/environments/{env}/secrets/...)

  Cloudflare PUT  /accounts/{account_id}/workers/scripts/{script}/secrets
             PATCH .../secrets-bulk para varios
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cofre.providers.http import ProviderError, base_url, request

GITHUB_API = "https://api.github.com"
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"


@dataclass
class Consumer:
    kind: str                 # gha | gha-env | cfw | exec | manual
    raw: str
    owner: str = ""
    repo: str = ""
    entorno: str = ""
    cuenta: str = ""
    script: str = ""
    nombre: str = ""
    nota: str = ""

    def etiqueta(self) -> str:
        if self.kind in ("gha", "gha-env"):
            destino = f"{self.owner}/{self.repo}"
            if self.entorno:
                destino += f" ({self.entorno})"
            return f"GitHub Actions {destino} · {self.nombre}"
        if self.kind == "cfw":
            return f"Worker {self.script} · {self.nombre}"
        if self.kind == "manual":
            return f"manual · {self.nota}"
        return self.kind


def parse(cadena: str) -> Consumer:
    texto = str(cadena or "").strip()
    if texto == "exec":
        return Consumer("exec", texto)
    if texto.startswith("manual:"):
        return Consumer("manual", texto, nota=texto.split(":", 1)[1])
    if texto.startswith("gha:"):
        resto = texto[4:]
        repo, _, nombre = resto.rpartition(":")
        owner, _, nombre_repo = repo.partition("/")
        return Consumer("gha", texto, owner=owner, repo=nombre_repo, nombre=nombre)
    if texto.startswith("gha-env:"):
        resto = texto[8:]
        partes = resto.split(":")
        if len(partes) != 3:
            raise ProviderError(f"consumidor mal escrito: {texto}")
        repo, entorno, nombre = partes
        owner, _, nombre_repo = repo.partition("/")
        return Consumer("gha-env", texto, owner=owner, repo=nombre_repo,
                        entorno=entorno, nombre=nombre)
    if texto.startswith("cfw:"):
        partes = texto[4:].split(":")
        if len(partes) != 3:
            raise ProviderError(f"consumidor mal escrito: {texto}")
        cuenta, script, nombre = partes
        return Consumer("cfw", texto, cuenta=cuenta, script=script, nombre=nombre)
    raise ProviderError(f"consumidor desconocido: {texto}")


# ------------------------------------------------------------------ GitHub

def cifrar_para_github(valor: str, clave_publica_b64: str) -> str:
    """Caja sellada de libsodium y base64, como exige Actions."""
    try:
        from nacl import encoding, public
    except ImportError as exc:                          # pragma: no cover
        raise ProviderError(
            "falta PyNaCl para cifrar el secreto de Actions "
            "(pip install pynacl)") from exc
    clave = public.SealedBox(public.PublicKey(
        base64.b64decode(clave_publica_b64), encoder=encoding.RawEncoder))
    cifrado = clave.encrypt(valor.encode("utf-8"))
    return base64.b64encode(cifrado).decode("ascii")


def deploy_github(consumidor: Consumer, valor: str, token: str) -> None:
    api = base_url(GITHUB_API, "COFRE_GITHUB_API")
    cabeceras = {"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"}
    base = f"/repos/{consumidor.owner}/{consumidor.repo}"
    if consumidor.entorno:
        ruta = f"{base}/environments/{consumidor.entorno}/secrets"
    else:
        ruta = f"{base}/actions/secrets"
    status, _h, body = request("GET", f"{api}{ruta}/public-key", headers=cabeceras)
    if status != 200 or not isinstance(body, dict):
        raise ProviderError(f"no se pudo leer la clave publica del repo: HTTP {status}")
    clave_b64 = str(body.get("key") or "")
    key_id = str(body.get("key_id") or "")
    if not clave_b64 or not key_id:
        raise ProviderError("el repo no devolvio clave publica utilizable")
    cifrado = cifrar_para_github(valor, clave_b64)
    status, _h, body = request(
        "PUT", f"{api}{ruta}/{consumidor.nombre}", headers=cabeceras,
        json_body={"encrypted_value": cifrado, "key_id": key_id})
    if status not in (201, 204, 200):
        raise ProviderError(f"GitHub rechazo el secreto: HTTP {status}")


# ------------------------------------------------------------------ Cloudflare

def deploy_worker(consumidor: Consumer, valor: str, token: str) -> None:
    api = base_url(CLOUDFLARE_API, "COFRE_CLOUDFLARE_API")
    url = (f"{api}/accounts/{consumidor.cuenta}/workers/scripts/"
           f"{consumidor.script}/secrets")
    status, _h, body = request(
        "PUT", url, headers={"Authorization": f"Bearer {token}",
                             "Accept": "application/json"},
        json_body={"name": consumidor.nombre, "text": valor,
                   "type": "secret_text"})
    if not (200 <= status < 300):
        detalle = ""
        if isinstance(body, dict):
            errores = body.get("errors") or []
            detalle = "; ".join(str(e.get("message")) for e in errores
                                if isinstance(e, dict))
        raise ProviderError(f"Cloudflare rechazo el secreto: {detalle or status}")


# ------------------------------------------------------------------ lote

def deploy(consumidores: list[str], valor: str, *,
           github_token: str = "", cloudflare_token: str = "") -> list[tuple[str, bool, str]]:
    """Despliega el valor en cada consumidor. Devuelve (etiqueta, ok, detalle)."""
    resultados = []
    for cadena in consumidores:
        try:
            consumidor = parse(cadena)
        except ProviderError as exc:
            resultados.append((cadena, False, str(exc)))
            continue
        etiqueta = consumidor.etiqueta()
        try:
            if consumidor.kind == "gha" or consumidor.kind == "gha-env":
                if not github_token:
                    raise ProviderError("hace falta un token con permiso de secretos")
                deploy_github(consumidor, valor, github_token)
            elif consumidor.kind == "cfw":
                if not cloudflare_token:
                    raise ProviderError("hace falta el token administrador de Cloudflare")
                deploy_worker(consumidor, valor, cloudflare_token)
            else:
                resultados.append((etiqueta, True, "nada que desplegar"))
                continue
            resultados.append((etiqueta, True, "desplegado"))
        except ProviderError as exc:
            resultados.append((etiqueta, False, str(exc)))
    return resultados
