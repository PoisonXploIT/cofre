"""COFRE - calendario de recordatorios (paso 5.8).

El cofre esta cerrado la mayor parte del tiempo, asi que sus fechas (caducidad,
rotacion, credenciales sin revocar) no se pueden leer sin el pendrive. Al cerrar
se deja un resumen **sin nombres y sin valores** en `cofre-schedule.json`, junto
al cofre:

    {"next_due": "2026-11-24", "vencidas": 0, "caducan": 1,
     "sin_revocar": 1, "rotacion_abierta": 0}

`due --notify` lo lee sin llave. Si la fecha ya llego, avisa con un MessageBoxW
en su propio hilo. Si alguien manipula el fichero, solo cambia el recordatorio:
no abre nada ni revela que secreto es.

Reglas de las fechas:

  - caducidad: el aviso empieza 14 dias antes (`caducan`); ya pasada cuenta como
    vencida.
  - rotacion: el dia en que toca (`last_rotated` o `created` + dias).
  - sin revocar: a los 7 dias de dejar la credencial vieja viva (el mismo plazo
    que la alerta de 3.2).
  - rotacion a medias: cuenta como pendiente desde ya.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from cofre.paths import atomic_write
from cofre.rotation import DIAS_SIN_REVOCAR, _antiguas

NOMBRE = "cofre-schedule.json"
DIAS_CADUCA = 14


def ruta(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / NOMBRE


def _fecha(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor or "")[:10])
    except ValueError:
        return None


def calcular(entradas: list[dict], diario_abierto: bool,
             hoy: date | None = None) -> dict:
    """Resumen del calendario a partir de los metadatos del indice.

    No lee valores ni nombres: solo fechas y contadores.
    """
    hoy = hoy or date.today()
    vencidas = caducan = sin_revocar = 0
    avisos: list[date] = []
    sin_revocar_vencidas = 0

    for meta in entradas:
        expira = _fecha(meta.get("expires_at"))
        if expira is not None:
            inicio = expira - timedelta(days=DIAS_CADUCA)
            if expira < hoy:
                vencidas += 1                  # ya caducada
            elif inicio <= hoy:
                caducan += 1
            else:
                avisos.append(inicio)

        cada = meta.get("rotate_every_days")
        base = _fecha(meta.get("last_rotated") or meta.get("created"))
        if cada and base:
            toca = base + timedelta(days=int(cada))
            if toca <= hoy:
                vencidas += 1
            else:
                avisos.append(toca)

        for antigua in _antiguas(meta):
            sin_revocar += 1
            desde = _fecha(antigua.get("desde"))
            if desde is None:
                continue
            aviso = desde + timedelta(days=DIAS_SIN_REVOCAR)
            if aviso <= hoy:
                sin_revocar_vencidas += 1
            else:
                avisos.append(aviso)

    if vencidas or caducan or diario_abierto or sin_revocar_vencidas:
        siguiente: date | None = hoy
    else:
        siguiente = min(avisos) if avisos else None

    return {
        "next_due": siguiente,
        "vencidas": vencidas,
        "caducan": caducan,
        "sin_revocar": sin_revocar,
        "rotacion_abierta": 1 if diario_abierto else 0,
    }


def serializar(datos: dict) -> dict:
    copia = dict(datos)
    cuando = datos.get("next_due")
    copia["next_due"] = cuando.isoformat() if isinstance(cuando, date) else ""
    return copia


def escribir(store) -> Path | None:
    """Escribir el resumen junto al cofre. Nunca lanza (es un recordatorio)."""
    try:
        if store is None or getattr(store, "master", None) is None:
            return None
        idx = store.index(store._data, store.master)
        entradas = list((idx.get("entries") or {}).values())
        abierto = bool((idx.get("settings") or {}).get("rotation"))
        datos = serializar(calcular(entradas, abierto))
        texto = json.dumps(datos, indent=2, sort_keys=True)
        return atomic_write(ruta(store.path), texto)
    except Exception:                              # noqa: BLE001
        return None


def leer(vault_path: str | Path) -> dict | None:
    p = ruta(vault_path)
    if not p.exists():
        return None
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def toca(datos: dict | None, hoy: date | None = None) -> bool:
    if not datos:
        return False
    cuando = _fecha(datos.get("next_due"))
    return cuando is not None and cuando <= (hoy or date.today())


def describe(datos: dict | None) -> str:
    if not datos:
        return "no hay calendario: abre COFRE una vez para generarlo"
    return (f"próxima fecha: {datos.get('next_due') or 'ninguna'}\n"
            f"vencidas: {int(datos.get('vencidas') or 0)} · "
            f"caducan pronto: {int(datos.get('caducan') or 0)} · "
            f"sin revocar: {int(datos.get('sin_revocar') or 0)} · "
            f"rotación a medias: {int(datos.get('rotacion_abierta') or 0)}")


def mensaje(datos: dict | None) -> str:
    if not datos:
        return ""
    total = sum(int(datos.get(clave) or 0) for clave in
                ("vencidas", "caducan", "sin_revocar", "rotacion_abierta"))
    detalle = (f"{int(datos.get('vencidas') or 0)} vencidas, "
               f"{int(datos.get('caducan') or 0)} caducan pronto, "
               f"{int(datos.get('sin_revocar') or 0)} sin revocar, "
               f"{int(datos.get('rotacion_abierta') or 0)} a medias")
    return (f"COFRE: {total} pendientes ({detalle}).\n"
            "Conecta el pendrive y abre COFRE.")
