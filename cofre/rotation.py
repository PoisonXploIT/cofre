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

JOURNAL_NAME = ".cofre-rotation.json"
MARGEN_ALERTA_HORAS = 24

FASES = ("comenzada", "pendiente_creada", "desplegando", "desplegada",
         "promovida", "revocada")


def journal_path(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / JOURNAL_NAME


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Journal:
    def __init__(self, vault_path: str | Path, datos: dict | None = None):
        self.path = journal_path(vault_path)
        self.datos = datos if datos is not None else (self.cargar() or {})

    @classmethod
    def cargar(cls, vault_path: str | Path) -> "Journal | None":
        p = journal_path(vault_path)
        if not p.exists():
            return None
        try:
            return cls(vault_path, json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------ estado

    def guardar(self) -> None:
        atomic_write(self.path, json.dumps(self.datos, indent=2, sort_keys=True))

    def borrar(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

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

def begin(vault_path: str | Path, nombre: str, proveedor: str,
          valor_pendiente: str, ref_nueva: dict | None = None,
          destinos: list[str] | None = None,
          old_value_still_valid: bool = True) -> Journal:
    diario = Journal(vault_path, {
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

def plan_resume(vault_path: str | Path) -> dict | None:
    """Que paso, que opciones hay y cual se recomienda. No ejecuta nada."""
    diario = Journal.cargar(vault_path)
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


def marcar_destino(vault_path: str | Path, destino: str, estado: str) -> None:
    diario = Journal.cargar(vault_path)
    if diario:
        diario.marcar_destino(destino, estado)


def promote(vault_path: str | Path) -> None:
    diario = Journal.cargar(vault_path)
    if diario:
        diario.set_fase("promovida")
        diario.marcar("promovida", "pendiente pasa a activo; viejo al historial")


def mark_revoked(vault_path: str | Path) -> None:
    diario = Journal.cargar(vault_path)
    if diario:
        diario.set_fase("revocada")
        diario.marcar("revocada", "viejo revocado en el proveedor")


def finish(vault_path: str | Path) -> None:
    """Cerrar el diario cuando ya no queda nada que hacer."""
    diario = Journal.cargar(vault_path)
    if diario:
        diario.borrar()


# ---------------------------------------------------------------- acciones

def deshacer(vault_path: str | Path, opcion_confirmada: bool = False,
             store=None) -> str:
    """Volver atras: reponer el valor viejo en los destinos ya cambiados,
    borrar la credencial nueva en el proveedor y descartar la pendiente."""
    if not opcion_confirmada:
        raise RuntimeError("deshacer exige confirmación explicita")
    diario = Journal.cargar(vault_path)
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


def continuar(vault_path: str | Path, opcion_confirmada: bool = False,
              store=None) -> str:
    """Terminar lo que falto: promover si no se hizo y revocar el viejo."""
    if not opcion_confirmada:
        raise RuntimeError("continuar exige confirmación explicita")
    diario = Journal.cargar(vault_path)
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
