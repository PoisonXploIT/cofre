"""Despacho de mensajes del puente del navegador (comun a tuberia y TCP).

Las reglas son las mismas que ya aplica serve.py y no se duplican aqui:

  - status: dice si el cofre esta abierto y cuantos secretos hay, sin valores;
  - list:   nombres, etiquetas y tipo, sin valores;
  - get:    exige que el host de la pestana este asignado a ESE secreto (R1),
            y deja constancia en el log con el dominio y sin el valor;
  - match:  nombres cuyos dominios encajan con el host de la pestana (4.6), para
            que el aviso del navegador los ponga primero. Sin valores;
  - assign: anadir el host actual a los dominios de un secreto (4.6). Pide
            confirmacion en la GUI: una pagina no puede autorizarse sola.

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

    if tipo == "git":
        # El ayudante de git pasa por aqui, no abre el cofre. Primera vez por
        # host: confirmacion en pantalla; "Permitir 5 minutos" se cachea por
        # host. El cliente de la tuberia ya lo identifico el servidor.
        if not app.session:
            return {"ok": False, "error": "cofre cerrado"}
        host = _domain({"domain": message.get("host", "")})
        if not host:
            return {"ok": False, "error": "falta el host"}
        from cofre import git_cred
        encontrado = git_cred.buscar(app.vault, host)
        if encontrado is None:
            record(app.vault_path, "git-get", app.gate, app.serial, name="-",
                   ok=False, detail=f"git:{host} sin coincidencia")
            return {"ok": False, "error": "no hay credencial para ese host"}
        nombre, meta = encontrado
        permitido, motivo = git_cred.permitido(meta)
        if not permitido:
            record(app.vault_path, "git-get", app.gate, app.serial, name=nombre,
                   ok=False, detail=f"git:{host} politica")
            return {"ok": False, "error": motivo}
        otorgado = app.request_confirm(f"git - {host}", nombre,
                                       contexto=f"git:{host}")
        if otorgado == "deny":
            record(app.vault_path, "git-get", app.gate, app.serial, name=nombre,
                   ok=False, detail=f"git:{host} confirmación denegada")
            return {"ok": False, "error": "confirmación denegada en COFRE"}
        try:
            valor = app.vault.get(app.session, nombre)
        except Exception:                              # noqa: BLE001
            record(app.vault_path, "git-get", app.gate, app.serial, name=nombre,
                   ok=False, detail=f"git:{host} no se pudo leer")
            return {"ok": False, "error": "no se pudo leer la credencial"}
        usuario = git_cred.usuario(app.vault, nombre, host)
        cliente = message.get("_client") if isinstance(message.get("_client"), dict) else {}
        extra = f" pid={cliente.get('pid')}" if cliente.get("pid") else ""
        record(app.vault_path, "git-get", app.gate, app.serial, name=nombre,
               ok=True, detail=f"git:{host}{extra}")
        from cofre.audit import stamp_vault
        stamp_vault(app.vault)
        return {"ok": True, "username": usuario, "password": valor}

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

    if tipo == "match":
        # 4.6: que secretos valen para esta pestana, para ponerlos primero.
        domain = _domain(message)
        if not domain:
            return {"ok": False, "error": "falta el dominio"}
        items = []
        for nombre in app.vault.names():
            try:
                patrones = list(app.vault.urls(nombre) or [])
            except Exception:                        # noqa: BLE001
                continue
            if patrones and host_matches(domain, patrones):
                meta = dict(app.vault.meta(nombre) or {})
                items.append({"name": nombre,
                              "kind": meta.get("type") or "secret",
                              "tags": list(meta.get("tags") or []),
                              "exact": domain in [str(p).lower() for p in patrones]})
        record(app.vault_path, "browser-list", app.gate, app.serial,
               name=f"{len(items)} para {domain}", ok=True, detail="match")
        return {"ok": True, "host": domain, "items": items}

    if tipo == "assign":
        # 4.6: asignar el sitio desde el aviso del navegador, con confirmacion en
        # la ventana. Solo el host exacto: nada de comodines desde una pagina.
        nombre = str(message.get("name", "")).strip()
        domain = _domain(message)
        if not nombre:
            return {"ok": False, "error": "falta el nombre"}
        if not domain or any(c in domain for c in "/*:? "):
            record(app.vault_path, "host-assign", app.gate, app.serial, name=nombre,
                   ok=False, detail=f"host inválido: {domain[:40] or '(vacio)'}")
            return {"ok": False, "error": "el host de la pagina no vale para asignar"}
        if nombre not in set(app.vault.names()):
            return {"ok": False, "error": "no existe ese secreto"}
        actuales = list(app.vault.urls(nombre) or [])
        if domain in [str(u).lower() for u in actuales]:
            return {"ok": True, "name": nombre, "urls": actuales, "changed": False}
        otorgado = app.request_confirm(f"Navegador - {domain}",
                                       f"asignar '{nombre}' a este sitio",
                                       contexto=f"assign:{nombre}:{domain}")
        if otorgado == "deny":
            record(app.vault_path, "host-assign", app.gate, app.serial, name=nombre,
                   ok=False, detail=f"{domain} confirmación denegada")
            return {"ok": False, "error": "confirmación denegada en COFRE"}
        nuevos = actuales + [domain]
        try:
            app.vault.set_urls(nombre, nuevos)
        except Exception as exc:                     # noqa: BLE001
            record(app.vault_path, "host-assign", app.gate, app.serial, name=nombre,
                   ok=False, detail=f"no se pudo guardar: {type(exc).__name__}")
            return {"ok": False, "error": "no se pudieron guardar los dominios"}
        record(app.vault_path, "host-assign", app.gate, app.serial, name=nombre,
               ok=True, detail=f"desde el navegador: +{domain}")
        from cofre.audit import stamp_vault
        stamp_vault(app.vault)
        return {"ok": True, "name": nombre, "urls": nuevos, "changed": True}

    return {"ok": False, "error": f"tipo desconocido: {tipo or '(vacio)'}"}
