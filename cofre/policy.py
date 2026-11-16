"""COFRE - politica de entrega por secreto (paso 2.3).

Una sola funcion decide si un secreto puede salir y por que canal:

    allowed(meta, "browser")  -> (bool, motivo)
    allowed(meta, "exec")
    allowed(meta, "clipboard")
    allowed(meta, "reveal")

Canales:
  browser    el puente del navegador
  exec       inyeccion como variable de entorno
  clipboard  boton Copiar
  reveal     boton Ver en pantalla

Politica por defecto segun el tipo y las etiquetas, salvo que el indice lleve
una `policy` explicita:

  private_key, o tags con "admin"   -> confirm: True,  browser: False, exec: False
  password                          -> confirm: False, browser: True,  exec: False
  api_key / api_token               -> confirm: False, browser: False, exec: True
  note / canary                     -> todo False (canary ademas dispara alerta)
"""

from __future__ import annotations

CHANNELS = ("browser", "exec", "clipboard", "reveal")


def _defaults(meta: dict) -> dict:
    tipo = str(meta.get("type") or "api_key")
    tags = [str(t).lower() for t in meta.get("tags", [])]
    if tipo == "canary":
        return {"confirm": True, "browser": False, "exec": False,
                "clipboard": False, "reveal": False}
    if tipo == "private_key" or "admin" in tags:
        return {"confirm": True, "browser": False, "exec": False,
                "clipboard": True, "reveal": True}
    if tipo == "password":
        return {"confirm": False, "browser": True, "exec": False,
                "clipboard": True, "reveal": True}
    if tipo in ("api_key", "api_token", "oauth_app"):
        return {"confirm": False, "browser": False, "exec": True,
                "clipboard": True, "reveal": True}
    if tipo == "note":
        return {"confirm": False, "browser": False, "exec": False,
                "clipboard": True, "reveal": True}
    return {"confirm": False, "browser": False, "exec": True,
            "clipboard": True, "reveal": True}


def effective(meta: dict) -> dict:
    """Politica que se aplica: la del indice si existe, si no la del tipo."""
    base = _defaults(meta)
    extra = meta.get("policy") or {}
    if isinstance(extra, dict):
        for clave in ("confirm", "browser", "exec", "clipboard", "reveal"):
            if clave in extra:
                base[clave] = bool(extra[clave])
    return base


def allowed(meta: dict, channel: str) -> tuple[bool, str]:
    if channel not in CHANNELS:
        return False, f"canal desconocido: {channel}"
    pol = effective(meta)
    if not pol.get(channel, False):
        nombre = meta.get("name") or "este secreto"
        if channel == "browser":
            return False, f"'{nombre}' no se puede rellenar en el navegador (politica)"
        if channel == "exec":
            return False, f"'{nombre}' no se puede inyectar en un comando (politica)"
        if channel == "clipboard":
            return False, f"'{nombre}' no se puede copiar (politica)"
        if channel == "reveal":
            return False, f"'{nombre}' no se puede mostrar (politica)"
    return True, ""


def needs_confirm(meta: dict) -> bool:
    return bool(effective(meta).get("confirm"))
