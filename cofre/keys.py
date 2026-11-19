"""COFRE - llaves y recuperacion (paso 6.6), sin Tk para poder probarlo.

`reporte` arma la lista de llaves (ranuras del cofre) con su estado y ultimo
uso. `generar_codigo` cambia la ranura de recuperacion por una nueva con la
MISMA clave maestra (el codigo viejo deja de abrir; no hace falta rekey).
`probar_codigo` valida las 25 palabras sin tocar nada. `quitar_pendrive` quita
la ranura de un serial; nunca deja el cofre sin ninguna llave.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from cofre.v2.recovery import check_code, new_code
from cofre.v2.slots import SlotError, new_recovery_slot, open_with_recovery


def fecha_humana(texto, ahora: datetime | None = None) -> str:
    """Fecha del log en lenguaje normal: hoy 18:49, ayer, hace 3 días..."""
    ahora = ahora or datetime.now()
    try:
        cuando = datetime.fromisoformat(str(texto))
    except (TypeError, ValueError):
        return str(texto or "")
    hoy = ahora.date()
    if cuando.date() == hoy:
        return f"hoy {cuando:%H:%M}"
    if cuando.date() == hoy - timedelta(days=1):
        return f"ayer {cuando:%H:%M}"
    dias = (hoy - cuando.date()).days
    if 0 < dias < 7:
        return f"hace {dias} días"
    return cuando.strftime("%d/%m/%Y %H:%M")


def reporte(data: dict, registry: dict, presentes: dict,
            eventos: list[dict]) -> list[dict]:
    """Lista de llaves. `presentes`: {serial: {drive, connected}}."""
    sticks = {str(s.get("serial")): s
              for s in (registry.get("sticks") or {}).values()}
    ultimo: dict[str, dict] = {}
    for ev in eventos:
        serial = str(ev.get("stick") or "-")
        if serial not in ("-", "None", "none", ""):
            ultimo[serial] = ev
    salida: list[dict] = []
    vistas: set[str] = set()
    for slot in data.get("slots") or []:
        kind = str(slot.get("kind") or "")
        serial = str(slot.get("serial")) if kind == "usb" else ""
        info = sticks.get(serial) or {}
        presente = presentes.get(serial) or {}
        vistas.add(serial)
        salida.append({
            "kind": kind,
            "serial": slot.get("serial"),
            "label": str(slot.get("label") or ""),
            "drive": str(info.get("drive") or presente.get("drive") or ""),
            "role": str(info.get("role") or ""),
            "registered": bool(info) if kind == "usb" else True,
            "connected": bool(presente.get("connected")) if kind == "usb" else False,
            "pin": bool(slot.get("pin")),
            "last": str((ultimo.get(serial) or {}).get("ts") or "")[:16],
        })
    for serial, info in sticks.items():
        if serial in vistas:
            continue
        salida.append({
            "kind": "huerfano",
            "serial": int(serial) if serial.isdigit() else serial,
            "label": "",
            "drive": str(info.get("drive") or ""),
            "role": str(info.get("role") or ""),
            "registered": True,
            "connected": bool((presentes.get(serial) or {}).get("connected")),
            "pin": False,
            "last": str((ultimo.get(serial) or {}).get("ts") or "")[:16],
        })
    return salida


def generar_codigo(v2, data: dict, master: bytes,
                   label: str = "recuperacion") -> tuple[str, dict]:
    """Cambiar la ranura de recuperacion por una nueva con la misma maestra.

    La copia se escribe solo si todo va bien; el cofre en memoria no se toca
    hasta que el llamante use el `data` devuelto.
    """
    nuevo = json.loads(json.dumps(data))
    nuevo["slots"] = [s for s in (nuevo.get("slots") or [])
                      if s.get("kind") != "recovery"]
    # A3 de la revision (2026-11-19): el codigo SIEMPRE se genera al azar. Las 24
    # palabras elegidas a mano tienen mucha menos entropia y la ranura se ataca sin
    # conexion sobre cualquier copia; se quito la opcion "Mis palabras".
    codigo = new_code()
    nuevo["slots"].append(new_recovery_slot(master, codigo, label))
    v2.save(nuevo)
    return codigo, nuevo


def probar_codigo(data: dict, codigo: str) -> tuple[bool, str]:
    """Comprobar las 25 palabras contra este cofre. No cambia nada.

    Orden a proposito (2026-11-19): **primero se intenta abrir** y la palabra de
    control queda como pista. La verdad es si la ranura se abre; si algun dia el
    algoritmo de la palabra de control cambia, un codigo valido no se rechaza por
    una comprobacion previa. Si no abre, el mensaje dice por que.
    """
    codigo = (codigo or "").strip()
    if not codigo:
        return False, "escribe las 25 palabras"
    ok, motivo = check_code(codigo)
    try:
        open_with_recovery(data, codigo)
        return True, "el código abre este cofre"
    except SlotError as exc:
        if not ok:
            return False, f"{exc}. Además: {motivo}"
        return False, str(exc)
    except Exception as exc:                       # noqa: BLE001
        return False, f"no se pudo comprobar: {exc}"


def quitar_pendrive(v2, data: dict, serial: int) -> tuple[dict, bool]:
    """Quitar la ranura del pendrive. No deja el cofre sin ninguna llave."""
    nuevo = json.loads(json.dumps(data))
    antes = len(nuevo.get("slots") or [])
    nuevo["slots"] = [s for s in (nuevo.get("slots") or [])
                      if not (s.get("kind") == "usb"
                              and int(s.get("serial", -1)) == int(serial))]
    if len(nuevo["slots"]) == antes:
        return data, False
    if not nuevo["slots"]:
        raise ValueError("no quedaria ninguna llave para abrir el cofre")
    v2.save(nuevo)
    return nuevo, True
