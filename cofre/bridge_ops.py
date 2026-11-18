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
from cofre.policy import allowed as policy_allowed, needs_confirm


def _domain(payload: dict) -> str:
    return str(payload.get("domain", "")).strip().lower()


def dispatch(app, message: dict) -> dict:
    """Ejecuta una peticion del navegador. `app` es la CofreGUI."""
    try:
        # los dominios o los secretos pueden haberse cambiado desde la CLI
        # mientras la GUI estaba abierta: se relee antes de decidir nada
        app.vault.refresh()
    except Exception:
        pass
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
                permitido, motivo = False, f"'{nombre}' no tiene ningún sitio asignado"
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
        # 2.3: la politica del secreto decide si puede salir por el navegador
        meta = dict(app.vault.meta(nombre) or {})
        meta.setdefault("name", nombre)
        permitido_pol, motivo_pol = policy_allowed(meta, "browser")
        if not permitido_pol:
            if str(meta.get("type") or "") == "canary":
                record(app.vault_path, "canary-access", app.gate, app.serial,
                       name=nombre, ok=False, detail=f"canal=browser:{domain}")
                try:
                    app._canary_alert(nombre, f"navegador:{domain}")
                except Exception:
                    pass
            else:
                record(app.vault_path, "browser-get", app.gate, app.serial, name=nombre,
                       ok=False, detail="politica: navegador")
            return {"ok": False, "error": motivo_pol}

        # 2.4: si el secreto es sensible, confirmacion en pantalla
        if needs_confirm(meta):
            otorgado = app.request_confirm(f"Navegador - {domain or 'sin dominio'}", nombre)
            if otorgado == "deny":
                record(app.vault_path, "browser-get", app.gate, app.serial, name=nombre,
                       ok=False, detail="confirmación denegada")
                return {"ok": False, "error": "confirmación denegada en COFRE"}

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
        from cofre.audit import stamp_vault
        stamp_vault(app.vault)
        return {"ok": True, "name": nombre, "value": valor}

    return {"ok": False, "error": f"tipo desconocido: {tipo or '(vacio)'}"}
