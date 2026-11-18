"""COFRE - rekey de la clave maestra (paso 1.6, usado por el pánico 5.10).

Cambia K por K' y re-cifra el índice y todas las entradas. Los slots se rehacen
solo con el material que se puede abrir **ahora**: el pendrive con el que se ha
abierto el cofre y un código de recuperación nuevo. Los demás slots se eliminan
y se avisa: hay que volver a dar llave a esos pendrives con `stick-add-v2`.

Se trabaja sobre una copia del cofre y se valida antes de escribir: si algo no
cuadra, el fichero no se toca. La escritura es atómica.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cofre.v2.recovery import normalize, new_code
from cofre.v2.slots import new_recovery_slot, new_usb_slot, try_open_slot


class RekeyError(RuntimeError):
    pass


@dataclass
class RekeyPreparado:
    master: bytes
    data: dict
    usb_slot: dict | None
    codigo: str
    perdidos: list[dict] = field(default_factory=list)


def preparar(v2, data: dict, old_master: bytes, *, stick_key: bytes | None = None,
             serial: int | None = None, label: str = "", pin: str = "",
             recovery_code: str | None = None,
             kdf: dict | None = None) -> RekeyPreparado:
    """Re-cifrar una copia y validarla. No escribe nada."""
    import secrets

    try:
        idx = v2.index(data, old_master)
    except Exception as exc:                       # noqa: BLE001
        raise RekeyError(f"la clave actual no abre el indice: {exc}") from exc
    if not isinstance(idx, dict) or "entries" not in idx:
        raise RekeyError("el indice no tiene la forma esperada")

    copia = json.loads(json.dumps(data))
    nuevo = secrets.token_bytes(32)
    originales: dict[str, str] = {}

    for nombre, meta in (idx.get("entries") or {}).items():
        try:
            contenido = v2.blob(data, old_master, nombre)
        except Exception as exc:                   # noqa: BLE001
            raise RekeyError(f"no se pudo leer '{nombre}': {exc}") from exc
        valor = str(contenido.get("value") or "")
        originales[nombre] = valor
        extra = {k: v for k, v in contenido.items() if k != "value"}
        v2._put_value(copia, nuevo, str(meta.get("id")), valor, extra)

    # los blobs huerfanos (sin entrada en el indice) no se pueden re-cifrar:
    # se quedan fuera del cofre nuevo en vez de dejar datos con la clave vieja
    ids = {str(meta.get("id")) for meta in (idx.get("entries") or {}).values()}
    copia["entries"] = {ident: blob for ident, blob in
                        (copia.get("entries") or {}).items() if ident in ids}
    v2._write_index(copia, nuevo, idx)

    previos = list(copia.get("slots") or [])
    usb_slot = None
    if stick_key is not None and serial is not None:
        etiqueta = label or next(
            (str(s.get("label") or "") for s in previos
             if s.get("kind") == "usb" and int(s.get("serial", -1)) == int(serial)),
            "principal")
        usb_slot = new_usb_slot(nuevo, stick_key, int(serial), etiqueta, pin, kdf)

    codigo = recovery_code or new_code()
    recuperacion = new_recovery_slot(nuevo, codigo, "recuperacion", kdf)
    nuevos = [s for s in (usb_slot, recuperacion) if s is not None]
    perdidos = []
    for slot in previos:
        if usb_slot is not None and slot.get("id") == usb_slot.get("id"):
            continue
        if slot.get("kind") == "usb" and serial is not None \
                and int(slot.get("serial", -1)) == int(serial):
            continue
        perdidos.append({"kind": str(slot.get("kind") or ""),
                         "label": str(slot.get("label") or ""),
                         "serial": slot.get("serial")})
    copia["slots"] = nuevos

    # validar antes de escribir: indice, valores y cada slot nuevo
    try:
        idx2 = v2.index(copia, nuevo)
        if set(idx2.get("entries") or {}) != set(originales):
            raise RekeyError("el indice nuevo no tiene las mismas entradas")
        for nombre, valor in originales.items():
            if v2.get(copia, nuevo, nombre) != valor:
                raise RekeyError(f"la entrada '{nombre}' no sobrevive al rekey")
        if usb_slot is not None:
            if try_open_slot(usb_slot, stick_key + pin.encode("utf-8"), kdf) != nuevo:
                raise RekeyError("el slot del pendrive nuevo no abre")
        if try_open_slot(recuperacion, normalize(codigo).encode("utf-8"), kdf) != nuevo:
            raise RekeyError("el slot de recuperacion nuevo no abre")
    except RekeyError:
        raise
    except Exception as exc:                       # noqa: BLE001
        raise RekeyError(f"la comprobacion del rekey fallo: {exc}") from exc

    return RekeyPreparado(master=nuevo, data=copia, usb_slot=usb_slot,
                          codigo=codigo, perdidos=perdidos)


def guardar(v2, preparado: RekeyPreparado) -> None:
    """Escribir el cofre ya re-cifrado (una sola escritura atómica)."""
    v2.save(preparado.data)
