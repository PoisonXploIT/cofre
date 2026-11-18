"""COFRE - motor de rotacion con diario (paso 5.7).

Reparto de responsabilidades, que es lo que hace recuperable el proceso:

  - El **valor nuevo** vive dentro de la entrada cifrada del cofre, en el campo
    `pending`. Si solo estuviera en memoria, al morir el proceso no se podria ni
    continuar ni deshacer.
  - El **diario** (`.cofre-rotation.json`) guarda solo estados: en que paso se
    quedo, que destinos ya estan hechos y las referencias del proveedor. Nunca
    valores.

Fases, en orden:

    comenzada -> pendiente_creada -> desplegando -> desplegada
              -> promovida -> revocada

Que hacer al reabrir depende de si el valor viejo sigue siendo valido:

    antes de promover            si  -> deshacer (por defecto)
    promovida, sin revocar       si  -> continuar (por defecto)
    revocada, o se uso el roll   no  -> continuar (la unica posible)

Nada se ejecuta solo: `plan_resume()` dice que paso, resalta la opcion por
defecto y espera confirmacion.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from cofre.paths import atomic_write

# El diario vive dentro del indice cifrado, no en un fichero aparte: si alguien
# cambia el ID de la credencial nueva por el de otro token, el descifrado falla y
# resume se niega a actuar. Un fichero en claro permitia que COFRE borrase el
# token equivocado por orden de un tercero.
JOURNAL_KEY = "rotation"
MARGEN_ALERTA_HORAS = 24

FASES = ("comenzada", "pendiente_creada", "desplegando", "desplegada",
         "promovida", "revocada")


class JournalError(RuntimeError):
    """El diario no se puede leer o no cuadra: no se actua."""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Journal:
    """Diario de rotación guardado en el indice cifrado del cofre."""

    def __init__(self, store, master: bytes, datos: dict):
        # store: el cofre abierto; master: la clave en memoria solo mientras dura
        self.store = store
        self.master = master
        self.datos = datos
        self.path = store.path

    # ------------------------------------------------------------ lectura

    @classmethod
    def cargar(cls, store, master: bytes) -> "Journal | None":
        try:
            idx = store.index(store._data, master)
        except Exception as exc:                       # noqa: BLE001
            raise JournalError(
                "el indice del cofre no se puede descifrar: no se actua") from exc
        datos = (idx.get("settings") or {}).get(JOURNAL_KEY)
        if not datos:
            return None
        if not isinstance(datos, dict):
            raise JournalError("el diario de rotación tiene forma inesperada")
        return cls(store, master, datos)

    # ------------------------------------------------------------ escritura

    def guardar(self) -> None:
        idx = self.store.index(self.store._data, self.master)
        idx.setdefault("settings", {})[JOURNAL_KEY] = self.datos
        self.store._write_index(self.store._data, self.master, idx)
        self.store.save(self.store._data)

    def borrar(self) -> None:
        idx = self.store.index(self.store._data, self.master)
        settings = idx.get("settings") or {}
        settings.pop(JOURNAL_KEY, None)
        idx["settings"] = settings
        self.store._write_index(self.store._data, self.master, idx)
        self.store.save(self.store._data)

    # ------------------------------------------------------------ estado

    @property
    def fase(self) -> str:
        return str(self.datos.get("fase") or "comenzada")

    def set_fase(self, fase: str) -> None:
        if fase not in FASES:
            raise ValueError(f"fase desconocida: {fase}")
        self.datos["fase"] = fase
        self.guardar()

    def marcar(self, paso: str, detalle: str = "") -> None:
        self.datos.setdefault("pasos", {})[paso] = {"ts": _ahora(),
                                                    "detalle": detalle[:160]}
        self.guardar()

    def marcar_destino(self, destino: str, estado: str) -> None:
        self.datos.setdefault("destinos", {})[destino] = estado
        self.guardar()

    def abierto_horas(self) -> float:
        inicio = str(self.datos.get("iniciada") or "")
        try:
            cuando = datetime.fromisoformat(inicio)
        except ValueError:
            return 0.0
        return (datetime.now() - cuando).total_seconds() / 3600

    def aviso_antiguo(self) -> str:
        horas = self.abierto_horas()
        if horas >= MARGEN_ALERTA_HORAS:
            return (f"rotación abierta hace {horas:.0f} h (mas de "
                    f"{MARGEN_ALERTA_HORAS}): revisala")
        return ""


# ---------------------------------------------------------------- inicio

def begin(store, master: bytes, nombre: str, proveedor: str,
          valor_pendiente: str, ref_nueva: dict | None = None,
          destinos: list[str] | None = None,
          old_value_still_valid: bool = True) -> Journal:
    diario = Journal(store, master, {
        "nombre": nombre,
        "proveedor": proveedor,
        "iniciada": _ahora(),
        "fase": "pendiente_creada",
        "ref_nueva": ref_nueva or {},
        "destinos": {d: "pendiente" for d in (destinos or [])},
        "viejo_valido": bool(old_value_still_valid),
        "pasos": {},
    })
    diario.marcar("pendiente_creada", "valor nuevo guardado como pendiente")
    diario.guardar()
    return diario


# ---------------------------------------------------------------- reanudar

def plan_resume(store, master: bytes) -> dict | None:
    """Que paso, que opciones hay y cual se recomienda. No ejecuta nada."""
    diario = Journal.cargar(store, master)
    if diario is None:
        return None
    fase = diario.fase
    viejo_valido = bool(diario.datos.get("viejo_valido", True))

    if fase in ("comenzada", "pendiente_creada", "desplegando", "desplegada"):
        opciones = ["deshacer"] + (["continuar"] if True else [])
        recomendada = "deshacer"
        explicacion = ("el valor viejo sigue valiendo: se puede volver atras "
                       "sin dejar nada roto")
    elif fase == "promovida":
        opciones = ["continuar", "deshacer"]
        recomendada = "continuar"
        explicacion = ("ya se promovio y solo falta revocar el viejo: deshacer "
                       "aquí seria ir hacia atras sin motivo")
    else:  # revocada
        opciones = ["continuar"]
        recomendada = "continuar"
        explicacion = "el viejo ya no vale: continuar es la unica opcion"

    if not viejo_valido or fase == "revocada":
        opciones = ["continuar"]
        recomendada = "continuar"
        explicacion = ("el valor viejo ya no es válido (revocado o roll): "
                       "solo se puede continuar")

    return {
        "nombre": diario.datos.get("nombre"),
        "proveedor": diario.datos.get("proveedor"),
        "fase": fase,
        "opciones": opciones,
        "recomendada": recomendada,
        "explicación": explicacion,
        "destinos": dict(diario.datos.get("destinos") or {}),
        "aviso": diario.aviso_antiguo(),
    }


def marcar_destino(store, master: bytes, destino: str, estado: str) -> None:
    diario = Journal.cargar(store, master)
    if diario:
        diario.marcar_destino(destino, estado)


def promote(store, master: bytes) -> None:
    diario = Journal.cargar(store, master)
    if diario:
        diario.set_fase("promovida")
        diario.marcar("promovida", "pendiente pasa a activo; viejo al historial")


def mark_revoked(store, master: bytes) -> None:
    diario = Journal.cargar(store, master)
    if diario:
        diario.set_fase("revocada")
        diario.marcar("revocada", "viejo revocado en el proveedor")


def finish(store, master: bytes) -> None:
    """Cerrar el diario cuando ya no queda nada que hacer."""
    diario = Journal.cargar(store, master)
    if diario:
        diario.borrar()


# ---------------------------------------------------------------- acciones

def deshacer(store, master: bytes, opcion_confirmada: bool = False) -> str:
    """Volver atras: reponer el valor viejo en los destinos ya cambiados,
    borrar la credencial nueva en el proveedor y descartar la pendiente."""
    if not opcion_confirmada:
        raise RuntimeError("deshacer exige confirmación explicita")
    diario = Journal.cargar(store, master)
    if diario is None:
        return "no hay nada que deshacer"
    if diario.fase not in ("comenzada", "pendiente_creada", "desplegando",
                           "desplegada"):
        return "deshacer no es posible en la fase " + diario.fase
    hechos = [d for d, estado in (diario.datos.get("destinos") or {}).items()
              if estado == "hecho"]
    if store is not None:
        contenido = store._vault.blob(store._data, store.master,
                                      str(diario.datos.get("nombre")))
        viejo = str(contenido.get("value") or "")
        pendiente = (contenido.get("pending") or {})
        ref_nueva = pendiente.get("ref") or diario.datos.get("ref_nueva") or {}
        if hechos and viejo:
            from cofre.consumers import deploy
            deploy(hechos, viejo, cloudflare_token="", github_token="")
        # borrar la credencial nueva si el proveedor lo permite
        token_id = str(ref_nueva.get("token_id") or "")
        if token_id:
            try:
                from cofre.providers import get as provider_get
                provider_get(str(diario.datos.get("proveedor"))).revoke(
                    token_id, "", {})
            except Exception:
                pass
        contenido.pop("pending", None)
        store._vault.set_blob(store._data, store.master,
                              str(diario.datos.get("nombre")), contenido)
        store.save(store._data)
    diario.borrar()
    return "deshecho"


def continuar(store, master: bytes, opcion_confirmada: bool = False) -> str:
    """Terminar lo que falto: promover si no se hizo y revocar el viejo."""
    if not opcion_confirmada:
        raise RuntimeError("continuar exige confirmación explicita")
    diario = Journal.cargar(store, master)
    if diario is None:
        return "no hay nada que continuar"
    nombre = str(diario.datos.get("nombre"))
    if store is not None and diario.fase != "revocada":
        contenido = store._vault.blob(store._data, store.master, nombre)
        pendiente = contenido.pop("pending", None)
        if pendiente and diario.fase != "promovida":
            contenido.setdefault("history", []).append(
                {"value": contenido.get("value", ""), "replaced": _ahora()})
            contenido["value"] = pendiente.get("value", "")
            store._vault.set_blob(store._data, store.master, nombre, contenido)
            store.save(store._data)
            diario.set_fase("promovida")
        token_id = str((diario.datos.get("ref_old") or {}).get("token_id") or "")
        if token_id:
            try:
                from cofre.providers import get as provider_get
                provider_get(str(diario.datos.get("proveedor"))).revoke(
                    token_id, "", {})
            except Exception:
                pass
        diario.set_fase("revocada")
    diario.borrar()
    return "continuado"


# ---------------------------------------------------------------- motor

def run_rotation(store, master: bytes, nombre: str, proveedor: str,
                 valor_nuevo: str, ref_nueva: dict | None,
                 destinos: list[str], desplegar, revocar=None,
                 revocar_viejo: bool = False, old_value_still_valid: bool = True):
    """Ciclo completo: pendiente -> desplegar -> promover -> revocar.

    `desplegar(destinos, valor)` y `revocar(ref)` son callables para poder
    probar fallos en cada paso. Si algo falla, el diario queda en la fase en la
    que murio y el valor viejo sigue siendo el activo.
    """
    from cofre.v2.vault import Vault2Error      # noqa: F401  (claridad)

    contenido = store._vault.blob(store._data, master, nombre)
    contenido["pending"] = {"value": valor_nuevo, "ref": ref_nueva or {},
                            "desde": _ahora()}
    store._vault.set_blob(store._data, master, nombre, contenido)
    store.save(store._data)

    diario = begin(store, master, nombre, proveedor, valor_nuevo, ref_nueva,
                   destinos, old_value_still_valid)
    try:
        diario.set_fase("desplegando")
        for destino in destinos:
            desplegar([destino], valor_nuevo)
            diario.marcar_destino(destino, "hecho")
        diario.set_fase("desplegada")

        contenido = store._vault.blob(store._data, master, nombre)
        pendiente = contenido.pop("pending", {})
        contenido.setdefault("history", []).append(
            {"value": contenido.get("value", ""), "replaced": _ahora()})
        contenido["value"] = pendiente.get("value", valor_nuevo)
        store._vault.set_blob(store._data, master, nombre, contenido)
        store.save(store._data)
        promote(store, master)

        if revocar_viejo and revocar is not None:
            revocar()
            mark_revoked(store, master)
        finish(store, master)
        return "completada"
    except Exception as exc:                      # noqa: BLE001
        # el objeto `diario` puede estar viejo (promote() escribe desde otro):
        # se recarga para no sobrescribir la fase con datos antiguos
        actual = Journal.cargar(store, master)
        if actual is not None:
            actual.marcar("fallo", type(exc).__name__)
        return f"interrumpida: {exc}"
