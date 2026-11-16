"""Despacho de mensajes del puente del navegador (comun a tuberia y TCP).

Las reglas son las mismas que ya aplica serve.py y no se duplican aqui:

  - status: dice si el cofre esta abierto y cuantos secretos hay, sin valores;
  - list:   nombres, etiquetas y tipo, sin valores;
  - get:    exige que el host de la pestana este asignado a ESE secreto (R1),
            y deja constancia en el log con el dominio y sin el valor.

Se usa desde el hilo de la GUI (BridgeController.poll), asi que aqui si se puede
leer el cofre con la sesion de la ventana.
"""

from __future__ import annotations

from cofre.audit import record
from cofre.hosts import HostsError, allows, host_matches


def _domain(payload: dict) -> str:
    return str(payload.get("domain", "")).strip().lower()


def dispatch(app, message: dict) -> dict:
    """Ejecuta una peticion del navegador. `app` es la CofreGUI."""
    tipo = str(message.get("type", "")).strip()

    if tipo == "status":
        if not app.session:
            return {"ok": True, "open": False}
        return {"ok": True, "open": True, "serial": app.serial,
                "count": len(app.vault.names())}

    if not app.session:
        return {"ok": False, "error": "cofre cerrado"}

    if tipo == "list":
        nombres = app.vault.names()
        items = []
        for nombre in nombres:
            meta = app.vault.meta(nombre)
            items.append({"name": nombre, "tags": meta.get("tags", []),
                          "kind": meta.get("type", "secret")})
        record(app.vault_path, "browser-list", app.gate, app.serial,
               name=f"{len(items)} nombres", ok=True)
        return {"ok": True, "items": items}

    if tipo == "get":
        nombre = str(message.get("name", "")).strip()
        if not nombre:
            return {"ok": False, "error": "falta el nombre"}
        domain = _domain(message)
        if app.vault.is_v2():
            patrones = app.vault.urls(nombre)
            if not patrones:
                permitido, motivo = False, f"'{nombre}' no tiene ningun sitio asignado"
            elif not host_matches(domain, patrones):
                permitido, motivo = False, f"'{domain}' no esta asignado a '{nombre}'"
            else:
                permitido, motivo = True, ""
        else:
            try:
                permitido, motivo = allows(app.vault_path, nombre, domain)
            except HostsError:
                permitido, motivo = False, "no se pueden leer los dominios asignados"
        if not permitido:
            record(app.vault_path, "browser-get", app.gate, app.serial, name=nombre,
                   ok=False, detail=f"dominio rechazado: {domain or 'sin dominio'}")
            return {"ok": False, "error": motivo}
        try:
            valor = app.vault.get(app.session, nombre)
        except KeyError:
            record(app.vault_path, "browser-get", app.gate, app.serial, name=nombre,
                   ok=False, detail="no existe")
            return {"ok": False, "error": "no existe ese secreto"}
        except Exception as exc:                     # noqa: BLE001
            record(app.vault_path, "browser-get", app.gate, app.serial, name=nombre,
                   ok=False, detail=type(exc).__name__)
            return {"ok": False, "error": "el pendrive no corresponde a este cofre"}
        record(app.vault_path, "browser-get", app.gate, app.serial, name=nombre,
               ok=True, detail=f"dominio={domain or 'sin dominio'}")
        return {"ok": True, "name": nombre, "value": valor}

    return {"ok": False, "error": f"tipo desconocido: {tipo or '(vacio)'}"}
