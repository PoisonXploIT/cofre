"""COFRE - motor de rotacion con diario (paso 5.7).

Reparto de responsabilidades, que es lo que hace recuperable el proceso:

  - El **valor nuevo** vive dentro de la entrada cifrada del cofre, en el campo
    `pending`. Si solo estuviera en memoria, al morir el proceso no se podria ni
    continuar ni deshacer.
  - El **diario** vive dentro del indice cifrado (`settings.rotation`) y guarda
    solo estados: en que paso se quedo, que destinos ya estan hechos y las
    referencias del proveedor. Nunca valores.

Fases, en orden:

    comenzada -> pendiente_creada -> desplegando -> desplegada
              -> promovida -> revocada

Que hacer al reabrir depende de si el valor viejo sigue siendo valido:

    antes de promover            si  -> deshacer (por defecto)
    promovida, sin revocar       si  -> continuar (por defecto)
    revocada, o se uso el roll   no  -> continuar (la unica posible)

Nada se ejecuta solo: `plan_resume()` dice que paso, resalta la opcion por
defecto y espera confirmacion.

La credencial vieja no se olvida: al cerrar sin revocarla queda anotada en la
entrada (`old_unrevoked`, una lista: cada rotacion sin revocar deja la suya) con
su referencia y la fecha. Salud la muestra con un boton Revocar y, a los siete
dias, salta una alerta baja.
"""

from __future__ import annotations

import secrets
from datetime import datetime


# El diario vive dentro del indice cifrado, no en un fichero aparte: si alguien
# cambia el ID de la credencial nueva por el de otro token, el descifrado falla y
# resume se niega a actuar. Un fichero en claro permitia que COFRE borrase el
# token equivocado por orden de un tercero.
JOURNAL_KEY = "rotation"
MARGEN_ALERTA_HORAS = 24
DIAS_SIN_REVOCAR = 7
# El historial guarda 5 versiones normales. Las que estan pendientes de revocar
# se quedan fijadas y NO cuentan para ese tope: si salieran del historial, en
# GitHub (que revoca por valor) ya no se podrian revocar.
MAX_HISTORIAL = 5


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


# ---------------------------------------------------------------- metadatos

def _meta(store, master: bytes, nombre: str) -> dict:
    idx = store.index(store._data, master)
    return dict((idx.get("entries") or {}).get(nombre) or {})


def _actualizar_meta(store, master: bytes, nombre: str, cambios: dict) -> dict:
    idx = store.index(store._data, master)
    meta = (idx.get("entries") or {}).get(nombre)
    if not meta:
        raise KeyError(nombre)
    meta.update(cambios)
    meta["updated"] = _ahora()
    store._write_index(store._data, master, idx)
    store.save(store._data)
    return dict(meta)


def _antiguas(meta: dict) -> list[dict]:
    """Lista de credenciales viejas sin revocar de una entrada.

    Se admite la forma antigua (un solo dict) para no perder datos ya escritos.
    """
    dato = meta.get("old_unrevoked")
    if isinstance(dato, dict):
        return [dict(dato)]
    if isinstance(dato, list):
        return [dict(d) for d in dato if isinstance(d, dict)]
    return []


def _guardar_antiguas(store, master: bytes, nombre: str,
                      lista: list[dict]) -> None:
    idx = store.index(store._data, master)
    meta = (idx.get("entries") or {}).get(nombre)
    if not meta:
        raise KeyError(nombre)
    if lista:
        meta["old_unrevoked"] = lista
    else:
        meta.pop("old_unrevoked", None)
    meta["updated"] = _ahora()
    store._write_index(store._data, master, idx)
    store.save(store._data)


def pendientes_de_revocar(store, master: bytes) -> list[dict]:
    """Credenciales viejas que siguen vivas en el proveedor, de la mas vieja a
    la mas nueva. No descifra valores: solo el indice."""
    idx = store.index(store._data, master)
    salida: list[dict] = []
    for nombre, meta in (idx.get("entries") or {}).items():
        for dato in _antiguas(meta):
            salida.append({
                "nombre": nombre,
                "proveedor": str(meta.get("provider") or ""),
                "ref": dict(dato.get("ref") or {}),
                "desde": str(dato.get("desde") or ""),
                "hid": str(dato.get("hid") or ""),
                "history": dato.get("history"),
            })
    return sorted(salida, key=lambda p: p["desde"])


def dias_desde(desde: str) -> int:
    try:
        cuando = datetime.fromisoformat(str(desde))
    except (TypeError, ValueError):
        return 0
    return max(0, (datetime.now() - cuando).days)


def _recortar_historial(contenido: dict) -> bool:
    """Dejar 5 versiones normales; las fijadas no cuentan ni se tiran."""
    historia = contenido.get("history")
    if not isinstance(historia, list):
        return False
    libres = [i for i, entrada in enumerate(historia)
              if isinstance(entrada, dict) and not entrada.get("pinned")]
    sobran = set(libres[:-MAX_HISTORIAL]) if len(libres) > MAX_HISTORIAL else set()
    if not sobran:
        return False
    contenido["history"] = [entrada for i, entrada in enumerate(historia)
                            if i not in sobran]
    return True


def _desfijar_historial(store, master: bytes, nombre: str, hid: str) -> None:
    """La credencial ya no esta pendiente: su versión vuelve a contar normal."""
    if not hid:
        return
    contenido = store._vault.blob(store._data, master, nombre)
    cambiado = False
    for entrada in contenido.get("history") or []:
        if (isinstance(entrada, dict) and entrada.get("hid") == hid
                and entrada.get("pinned")):
            entrada["pinned"] = False
            cambiado = True
    if not cambiado:
        return
    _recortar_historial(contenido)
    store._vault.set_blob(store._data, master, nombre, contenido)
    store.save(store._data)


def _valor_de_la_antigua(store, master: bytes, nombre: str,
                         dato: dict) -> str:
    """Valor viejo para los proveedores que revocan por valor (GitHub).

    Se busca por `hid` (estable aunque el historial se recorte); se admite el
    indice antiguo por compatibilidad.
    """
    hid = str(dato.get("hid") or "")
    indice = dato.get("history")
    if not hid and indice is None:
        return ""
    contenido = store._vault.blob(store._data, master, nombre)
    historia = list(contenido.get("history") or [])
    if hid:
        for entrada in historia:
            if isinstance(entrada, dict) and entrada.get("hid") == hid:
                return str(entrada.get("value") or "")
        return ""
    try:
        if 0 <= int(indice) < len(historia):
            return str(historia[int(indice)].get("value") or "")
    except (TypeError, ValueError):
        pass
    return ""


def revocar_antigua(store, master: bytes, nombre: str, admin_value: str = "",
                    desde: str | None = None) -> str:
    """Revocar en el proveedor una credencial vieja que se quedo viva.

    Cloudflare se revoca por id; GitHub, por valor (va en el historial cifrado de
    la entrada). Nunca se escribe el valor en el log ni en el indice.
    """
    from cofre.providers.http import ProviderError

    meta = _meta(store, master, nombre)
    antiguas = _antiguas(meta)
    if not antiguas:
        return "no hay credencial antigua pendiente"
    if desde:
        elegida = next((a for a in antiguas if str(a.get("desde") or "") == desde),
                       None)
        if elegida is None:
            return "no hay credencial antigua pendiente con esa fecha"
    else:
        elegida = antiguas[0]

    ref = dict(elegida.get("ref") or {})
    objetivo = str(ref.get("token_id") or "")
    if not objetivo:
        objetivo = _valor_de_la_antigua(store, master, nombre, elegida)
    if not objetivo:
        raise ProviderError("no se sabe que credencial antigua revocar")

    from cofre.providers import get as provider_get
    proveedor = provider_get(str(meta.get("provider") or ""))
    proveedor.revoke(objetivo, admin_value, meta)

    # primero se quita la fijacion y luego la nota; si desfijar fallara, la nota
    # se iria igual: el proveedor ya la revoco
    try:
        _desfijar_historial(store, master, nombre, str(elegida.get("hid") or ""))
    except Exception:                              # noqa: BLE001
        pass
    resto = [a for a in antiguas if a is not elegida]
    _guardar_antiguas(store, master, nombre, resto)
    return "credencial antigua revocada"


def descartar_antigua(store, master: bytes, nombre: str,
                      desde: str | None = None) -> str:
    """Quitar la nota sin tocar el proveedor.

    Para cuando la credencial ya se revoco a mano en el panel del proveedor: no
    se puede volver a revocar (daria 404) y la nota quedaria para siempre.
    """
    antiguas = _antiguas(_meta(store, master, nombre))
    if not antiguas:
        return "no hay credencial antigua pendiente"
    if desde:
        elegida = next((a for a in antiguas if str(a.get("desde") or "") == desde),
                       None)
        if elegida is None:
            return "no hay credencial antigua pendiente con esa fecha"
    else:
        elegida = antiguas[0]
    try:
        _desfijar_historial(store, master, nombre, str(elegida.get("hid") or ""))
    except Exception:                              # noqa: BLE001
        pass
    resto = [a for a in antiguas if a is not elegida]
    _guardar_antiguas(store, master, nombre, resto)
    return "aviso descartado (no se toco el proveedor)"


def _olvidar_antigua(store, master: bytes, nombre: str, desde: str = "") -> None:
    """Quitar la nota de una credencial que ya se revoco fuera de aquí."""
    antiguas = _antiguas(_meta(store, master, nombre))
    if not antiguas:
        return
    if desde:
        elegida = next((a for a in antiguas if str(a.get("desde") or "") == desde),
                       None)
        resto = [a for a in antiguas if str(a.get("desde") or "") != desde]
    else:
        elegida, resto = antiguas[0], antiguas[1:]
    if elegida is not None:
        try:
            _desfijar_historial(store, master, nombre,
                                str(elegida.get("hid") or ""))
        except Exception:                          # noqa: BLE001
            pass
    _guardar_antiguas(store, master, nombre, resto)


# ---------------------------------------------------------------- inicio

def begin(store, master: bytes, nombre: str, proveedor: str,
          valor_pendiente: str, ref_nueva: dict | None = None,
          destinos: list[str] | None = None,
          old_value_still_valid: bool = True,
          ref_old: dict | None = None) -> Journal:
    diario = Journal(store, master, {
        "nombre": nombre,
        "proveedor": proveedor,
        "iniciada": _ahora(),
        "fase": "pendiente_creada",
        "ref_nueva": ref_nueva or {},
        "ref_old": ref_old or {},
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
        opciones = ["deshacer", "continuar"]
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


def _promover(store, master: bytes, diario: Journal) -> str:
    """El pendiente pasa a activo y el viejo al historial.

    Devuelve la fecha con la que se anoto la credencial vieja (cadena vacia si
    ya estaba promovida: en ese caso no se duplica la anotacion).
    """
    nombre = str(diario.datos.get("nombre"))
    contenido = store._vault.blob(store._data, master, nombre)
    pendiente = contenido.pop("pending", None)
    indice_historial = None
    if pendiente is not None:
        historia = contenido.setdefault("history", [])
        hid = secrets.token_hex(8)
        historia.append({"value": str(contenido.get("value") or ""),
                         "replaced": _ahora(), "hid": hid, "pinned": True})
        indice_historial = len(historia) - 1
        contenido["value"] = str(pendiente.get("value") or "")
        # el valor que hay que poder revocar no se tira aunque el historial
        # crezca: queda fijado hasta que se revoque o se descarte
        _recortar_historial(contenido)
        store._vault.set_blob(store._data, master, nombre, contenido)
        store.save(store._data)

    desde = ""
    cambios = {"last_rotated": datetime.now().date().isoformat()}
    ref_nueva = dict(diario.datos.get("ref_nueva") or {})
    if ref_nueva:
        cambios["provider_ref"] = ref_nueva
    if indice_historial is not None:
        desde = _ahora()
        nueva = {"ref": dict(diario.datos.get("ref_old") or {}),
                 "desde": desde, "hid": hid}
        nueva["history"] = indice_historial
        cambios["old_unrevoked"] = _antiguas(_meta(store, master, nombre)) + [nueva]
        diario.datos["promovida_desde"] = desde
    _actualizar_meta(store, master, nombre, cambios)
    diario.set_fase("promovida")
    diario.marcar("promovida", "pendiente pasa a activo; viejo al historial")
    return desde


def promote(store, master: bytes) -> None:
    diario = Journal.cargar(store, master)
    if diario:
        _promover(store, master, diario)


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

def deshacer(store, master: bytes, opcion_confirmada: bool = False,
             admin_value: str = "", github_token: str = "") -> str:
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
        nombre = str(diario.datos.get("nombre"))
        contenido = store._vault.blob(store._data, master, nombre)
        viejo = str(contenido.get("value") or "")
        pendiente = (contenido.get("pending") or {})
        ref_nueva = pendiente.get("ref") or diario.datos.get("ref_nueva") or {}
        if hechos and viejo:
            from cofre.consumers import deploy
            from cofre.providers.http import ProviderError
            resultados = deploy(hechos, viejo, cloudflare_token=admin_value,
                                github_token=github_token)
            fallos = [f"{et}: {det}" for et, ok, det in resultados if not ok]
            if fallos:
                raise ProviderError("no se pudo reponer el viejo: "
                                    + "; ".join(fallos)[:180])
        # borrar la credencial nueva si el proveedor lo permite
        token_id = str(ref_nueva.get("token_id") or "")
        valor_nueva = str(pendiente.get("value") or "")
        try:
            from cofre.providers import get as provider_get
            proveedor = provider_get(str(diario.datos.get("proveedor")))
            objetivo = token_id or (valor_nueva
                                    if getattr(proveedor, "name", "") == "github"
                                    else "")
            if objetivo:
                proveedor.revoke(objetivo, admin_value, {})
        except Exception:
            pass
        contenido.pop("pending", None)
        store._vault.set_blob(store._data, master, nombre, contenido)
        store.save(store._data)
    diario.borrar()
    return "deshecho"


def continuar(store, master: bytes, opcion_confirmada: bool = False,
              admin_value: str = "") -> str:
    """Terminar lo que falto: promover si no se hizo y revocar el viejo."""
    if not opcion_confirmada:
        raise RuntimeError("continuar exige confirmación explicita")
    diario = Journal.cargar(store, master)
    if diario is None:
        return "no hay nada que continuar"
    nombre = str(diario.datos.get("nombre"))
    if diario.fase != "revocada":
        desde = _promover(store, master, diario)
        if not desde:
            desde = str(diario.datos.get("promovida_desde") or "")
        try:
            revocar_antigua(store, master, nombre, admin_value,
                            desde=desde or None)
        except Exception as exc:                   # noqa: BLE001
            # el diario NO se cierra: quedaria una credencial vieja viva sin
            # que nadie lo recuerde
            diario.marcar("fallo_revocar", str(exc)[:120])
            return f"interrumpida: no se pudo revocar la antigua ({exc})"
        diario.set_fase("revocada")
        diario.marcar("revocada", "viejo revocado en el proveedor")
    diario.borrar()
    return "continuado"


# ---------------------------------------------------------------- motor

def run_rotation(store, master: bytes, nombre: str, proveedor: str,
                 valor_nuevo: str = "", ref_nueva: dict | None = None,
                 destinos: list[str] | None = None, desplegar=None,
                 revocar=None, revocar_viejo: bool = False,
                 old_value_still_valid: bool = True, *,
                 crear=None, verificar=None, ref_old: dict | None = None):
    """Ciclo completo: crear -> pendiente -> desplegar -> promover -> revocar.

    `crear()` devuelve (valor, ref) y se ejecuta ANTES de escribir nada: si
    falla, no queda diario, ni pendiente, ni destino tocado.

    `desplegar(destinos, valor)`, `verificar(valor)` y `revocar()` son callables
    para poder probar fallos en cada paso; lanzan al fallar. Si algo falla, el
    diario queda en la fase en la que murio y el valor viejo sigue siendo el
    activo (hasta promover).
    """
    if crear is not None:
        try:
            valor_nuevo, ref_nueva = crear()
        except Exception as exc:                   # noqa: BLE001
            return f"no-creada: {exc}"
    if not valor_nuevo:
        return "no-creada: sin valor nuevo"

    contenido = store._vault.blob(store._data, master, nombre)
    contenido["pending"] = {"value": valor_nuevo, "ref": ref_nueva or {},
                            "desde": _ahora()}
    store._vault.set_blob(store._data, master, nombre, contenido)
    store.save(store._data)

    diario = begin(store, master, nombre, proveedor, valor_nuevo, ref_nueva,
                   destinos, old_value_still_valid, ref_old=ref_old)
    try:
        diario.set_fase("desplegando")
        for destino in destinos or []:
            if desplegar is None:
                raise RuntimeError("no hay forma de desplegar")
            desplegar([destino], valor_nuevo)
            diario.marcar_destino(destino, "hecho")
        diario.set_fase("desplegada")

        # verificar DESPUES de desplegar: si el proveedor no acepta el valor
        # nuevo, se queda en "desplegada" y lo recomendado es deshacer
        if verificar is not None:
            verificar(valor_nuevo)

        _promover(store, master, diario)

        if revocar_viejo:
            if revocar is None:
                raise RuntimeError("falta la forma de revocar el viejo")
            revocar()
            # la credencial ya no existe en el proveedor: solo se quita la nota
            # (volver a llamar a revoke aqui seria pedir dos veces lo mismo)
            _olvidar_antigua(store, master, nombre,
                             str(diario.datos.get("promovida_desde") or ""))
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
