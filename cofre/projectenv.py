"""COFRE - `.cofre-env.json` por proyecto (paso 7.1).

El fichero no lleva valores: solo referencias.

    {"TAVILY_API_KEY": "cofre://TAVILY_API_KEY",
     "GITHUB_TOKEN": "cofre://GITHUB_APP@app",
     "DB_USER": "cofre://POSTGRES_LOCAL#username"}

`run` resuelve las referencias, respeta la politica `exec` y pide confirmacion
para los secretos sensibles. Los valores solo viven en la memoria del proceso y
en el entorno del hijo. Nunca se imprimen ni se registran.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cofre import policy

NOMBRE = ".cofre-env.json"
PREFIJO = "cofre://"


class ProjectEnvError(RuntimeError):
    pass


@dataclass
class Ref:
    destino: str
    nombre: str
    campo: str = ""
    app: bool = False

    @property
    def etiqueta(self) -> str:
        extra = "#" + self.campo if self.campo else ("@app" if self.app else "")
        return self.nombre + extra


def buscar(desde: str | Path) -> Path | None:
    base = Path(desde).resolve()
    for carpeta in (base, *base.parents):
        ruta = carpeta / NOMBRE
        if ruta.is_file():
            return ruta
    return None


def cargar(ruta: str | Path) -> list[Ref]:
    p = Path(ruta)
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectEnvError(f"no se puede leer {p.name}: {exc}") from exc
    if not isinstance(datos, dict) or not datos:
        raise ProjectEnvError(f"{p.name} debe ser un objeto con variables")
    refs = []
    for destino, valor in datos.items():
        if not isinstance(destino, str) or not destino.isidentifier():
            raise ProjectEnvError(f"nombre de variable inválido: {destino!r}")
        if not isinstance(valor, str) or not valor.startswith(PREFIJO):
            raise ProjectEnvError(
                f"{destino}: el fichero no puede llevar valores; usa "
                "cofre://NOMBRE")
        resto = valor[len(PREFIJO):]
        campo = ""
        app = False
        if "#" in resto:
            resto, campo = resto.split("#", 1)
        if resto.endswith("@app"):
            resto = resto[:-4]
            app = True
        if not resto:
            raise ProjectEnvError(f"{destino}: referencia vacía")
        refs.append(Ref(destino, resto, campo, app))
    return refs


def _campo(vault, nombre: str, campo: str) -> str:
    if not vault.is_v2():
        raise ProjectEnvError("los campos # solo existen en cofre v2")
    store = vault._v2store()
    if store.master is None:
        raise ProjectEnvError("el cofre esta cerrado")
    contenido = store._vault.blob(store._data, store.master, nombre)
    campos = contenido.get("fields") or {}
    if campo not in campos:
        raise ProjectEnvError(f"{nombre} no tiene el campo '{campo}'")
    return str(campos[campo])


def _app(vault, session, nombre: str, meta: dict) -> str:
    app_id = str(meta.get("app_id") or "")
    instalacion = str(meta.get("installation_id") or "")
    if not app_id or not instalacion:
        raise ProjectEnvError(
            f"{nombre}: falta app_id/installation_id (meta --app-id --installation)")
    from cofre.providers.github import app_jwt, installation_token
    try:
        pem = vault.get(session, nombre)
        jwt = app_jwt(app_id, pem)
        valor, _caduca = installation_token(jwt, instalacion)
        return valor
    except Exception as exc:                       # noqa: BLE001
        raise ProjectEnvError(f"{nombre}: no se pudo crear el token de la App: "
                              f"{exc}") from exc


def revisar(vault, session, refs: list[Ref]) -> list[dict]:
    """Estado de cada referencia, sin devolver valores."""
    salida = []
    for ref in refs:
        meta = dict(vault.meta(ref.nombre) or {})
        if not meta:
            salida.append({"ref": ref, "estado": "falta",
                           "detalle": "no existe el secreto"})
            continue
        if ref.campo:
            try:
                _campo(vault, ref.nombre, ref.campo)
            except Exception as exc:               # noqa: BLE001
                salida.append({"ref": ref, "estado": "campo",
                               "detalle": str(exc)})
                continue
        if ref.app:
            if not meta.get("app_id") or not meta.get("installation_id"):
                salida.append({"ref": ref, "estado": "app",
                               "detalle": "faltan app_id/installation_id"})
                continue
            salida.append({"ref": ref, "estado": "ok", "detalle": "token de App"})
            continue
        permitido, motivo = policy.allowed(meta, "exec")
        if not permitido:
            salida.append({"ref": ref, "estado": "politica", "detalle": motivo})
            continue
        salida.append({"ref": ref, "estado": "ok", "detalle": ""})
    return salida


def resolver(vault, session, refs: list[Ref]) -> dict[str, str]:
    """Valores para el proceso hijo. Lanza ProjectEnvError con el primer fallo."""
    estados = revisar(vault, session, refs)
    malos = [e for e in estados if e["estado"] != "ok"]
    if malos:
        primero = malos[0]
        raise ProjectEnvError(f"{primero['ref'].destino}: {primero['detalle']}")
    env = {}
    for ref in refs:
        meta = dict(vault.meta(ref.nombre) or {})
        if ref.app:
            env[ref.destino] = _app(vault, session, ref.nombre, meta)
        elif ref.campo:
            env[ref.destino] = _campo(vault, ref.nombre, ref.campo)
        else:
            env[ref.destino] = vault.get(session, ref.nombre)
    return env


def sensibles(vault, refs: list[Ref]) -> list[str]:
    nombres = []
    for ref in refs:
        meta = dict(vault.meta(ref.nombre) or {})
        if ref.app or policy.needs_confirm(meta):
            nombres.append(ref.destino)
    return nombres
