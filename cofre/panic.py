"""COFRE - boton de panico (paso 5.10).

Primero se enseña el plan y no se toca nada (`--dry-run`). El plan no lleva
valores. Al ejecutar, en este orden:

  1. Cloudflare: roll (variante A) de cada token registrado; el token
     administrador va el ULTIMO, porque hace falta para los demas.
  2. GitHub PAT: revocacion por valor, en lotes de 1000.
  3. GitHub App: aviso para regenerar la clave privada en la web (no hay API).
  4. Otros proveedores: URL para revocar a mano.
  5. Señuelos: no se tocan.
  6. Codigo de recuperacion nuevo y rekey (lo hace el CLI con `v2.rekey`).

El panic deja el cofre con una clave maestra nueva; los pendrives que no esten
conectados se quedan fuera y hay que volver a darles llave.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from cofre.providers.http import ProviderError


@dataclass
class Accion:
    tipo: str                  # roll | revoke | app | manual
    nombre: str
    detalle: str
    proveedor: str = ""
    token_id: str = ""
    valor: str = field(default="", repr=False)   # nunca se imprime
    admin: bool = False
    url: str = ""


@dataclass
class Plan:
    acciones: list[Accion] = field(default_factory=list)
    canarios: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def cuenta(self, tipo: str) -> int:
        return sum(1 for a in self.acciones if a.tipo == tipo)


def _etiquetas(meta: dict) -> list[str]:
    return [str(t).lower() for t in (meta.get("tags") or [])]


def planificar(store, master: bytes, admin_disponible: bool) -> Plan:
    """Leer el cofre y proponer las acciones. No toca el proveedor."""
    from cofre.providers import get as provider_get
    from cofre.rotation import pendientes_de_revocar

    idx = store.index(store._data, master)
    entradas = idx.get("entries") or {}
    plan = Plan()
    rolls: list[Accion] = []
    revokes: list[Accion] = []
    otros: list[Accion] = []

    for nombre, meta in entradas.items():
        tipo = str(meta.get("type") or "")
        if tipo == "canary":
            plan.canarios.append(nombre)
            continue
        if tipo == "note":
            continue
        if tipo == "private_key":
            if "admin" in _etiquetas(meta):
                otros.append(Accion(
                    "app", nombre,
                    "regenerar la clave privada de la GitHub App en la web",
                    proveedor="github"))
            else:
                plan.avisos.append(
                    f"{nombre}: clave privada que no es de la App; no se toca")
            continue
        proveedor_nombre = str(meta.get("provider") or "")
        ref = dict(meta.get("provider_ref") or {})
        token_id = str(ref.get("token_id") or "")
        if proveedor_nombre == "cloudflare" and token_id:
            admin = "admin" in _etiquetas(meta)
            rolls.append(Accion(
                "roll", nombre,
                "roll del token administrador (el último)" if admin
                else "roll del token",
                proveedor="cloudflare", token_id=token_id, admin=admin))
            continue
        if proveedor_nombre == "github":
            try:
                valor = store._vault.get(store._data, master, nombre)
            except Exception:                      # noqa: BLE001
                valor = ""
            revokes.append(Accion(
                "revoke", nombre, "revocar el PAT por valor",
                proveedor="github", valor=valor))
            continue
        if proveedor_nombre:
            url = ""
            try:
                url = provider_get(proveedor_nombre).manual_url(meta)
            except Exception:                      # noqa: BLE001
                url = ""
            otros.append(Accion(
                "manual", nombre, "revocar a mano", proveedor=proveedor_nombre,
                url=url))
            continue
        plan.avisos.append(f"{nombre}: sin proveedor; no se toca")

    rolls.sort(key=lambda a: (a.admin, a.nombre))
    plan.acciones = rolls + revokes + otros
    if rolls and not admin_disponible:
        plan.avisos.append(
            "falta el token administrador de Cloudflare: los roll no se pueden hacer")
    viejas = pendientes_de_revocar(store, master)
    if viejas:
        plan.avisos.append(
            f"{len(viejas)} credenciales antiguas sin revocar; el panico no las "
            "toca: revocalas desde Salud")
    return plan


def _guardar_valor(store, master: bytes, nombre: str, nuevo: str) -> None:
    contenido = store._vault.blob(store._data, master, nombre)
    contenido["value"] = nuevo
    contenido.pop("pending", None)
    store._vault.set_blob(store._data, master, nombre, contenido)
    store.save(store._data)
    _marcar(store, master, nombre, "ok", "rotado por panico", extra={
        "last_rotated": date.today().isoformat()})


def _marcar(store, master: bytes, nombre: str, estado: str, detalle: str,
            extra: dict | None = None) -> None:
    idx = store.index(store._data, master)
    meta = (idx.get("entries") or {}).get(nombre)
    if meta is None:
        return
    meta["health"] = estado
    meta["health_detail"] = detalle[:160]
    meta.update(extra or {})
    store._write_index(store._data, master, idx)
    store.save(store._data)


def ejecutar(store, master: bytes, plan: Plan, admin_valor: str = "",
             token_gh: str = "") -> list[tuple[Accion, bool, str]]:
    """Ejecutar los roll y las revocaciones. El rekey lo hace el CLI despues."""
    from cofre.providers import get as provider_get

    resultados: list[tuple[Accion, bool, str]] = []

    for accion in plan.acciones:
        if accion.tipo != "roll":
            continue
        try:
            if not admin_valor:
                raise ProviderError("falta el token administrador de Cloudflare")
            meta = dict(store.meta(accion.nombre) or {})
            nuevo = provider_get("cloudflare").roll_value(
                accion.token_id, admin_valor, meta)
            _guardar_valor(store, master, accion.nombre, nuevo)
            if accion.admin:
                # el token viejo acaba de morir: los despliegues del propio
                # administrador usan el valor nuevo
                admin_valor = nuevo
            detalle = "valor nuevo guardado"
            consumidores = [str(c) for c in (meta.get("consumers") or [])]
            if consumidores:
                # el roll invalida el valor viejo en el acto: se intenta dejar
                # los destinos al dia una vez, sin bloquear el resto del panico
                try:
                    from cofre.consumers import deploy
                    despliegue = deploy(consumidores, nuevo,
                                        github_token=token_gh,
                                        cloudflare_token=admin_valor)
                    hechos = [et for et, ok, det in despliegue
                              if ok and det == "desplegado"]
                    fallos = [f"{et}: {det}" for et, ok, det in despliegue
                              if not ok]
                    manuales = [c for c in consumidores
                                if c.startswith("manual:")]
                    detalle = (f"desplegado en {len(hechos)}/"
                               f"{len(consumidores)} consumidores")
                    if manuales:
                        detalle += f"; a mano: {len(manuales)}"
                    if fallos:
                        detalle += "; FALLA " + "; ".join(fallos)[:110]
                except Exception as exc:           # noqa: BLE001
                    detalle += f"; no se pudo desplegar: {exc}"
            resultados.append((accion, True, detalle))
        except Exception as exc:                   # noqa: BLE001
            resultados.append((accion, False, str(exc)))

    valores = [a.valor for a in plan.acciones
               if a.tipo == "revoke" and a.valor]
    if valores:
        try:
            from cofre.providers.github import revoke_credentials
            for inicio in range(0, len(valores), 1000):
                revoke_credentials(valores[inicio:inicio + 1000])
            for accion in plan.acciones:
                if accion.tipo == "revoke" and accion.valor:
                    _marcar(store, master, accion.nombre, "invalida",
                            "revocada por panico")
            resultados.append((Accion("revoke", f"{len(valores)} PAT",
                                      "revocación en lote"), True,
                               f"{len(valores)} revocados"))
        except Exception as exc:                   # noqa: BLE001
            resultados.append((Accion("revoke", f"{len(valores)} PAT",
                                      "revocación en lote"), False, str(exc)))
    for accion in plan.acciones:
        if accion.tipo == "revoke" and not accion.valor:
            resultados.append((accion, False,
                               "no se pudo leer el valor del PAT"))

    for accion in plan.acciones:
        if accion.tipo == "app":
            resultados.append((accion, True,
                               "regenerala en la web; COFRE no puede hacerlo"))
        elif accion.tipo == "manual":
            resultados.append((accion, True,
                               accion.url or "sin URL: hazlo en el panel"))
    return resultados
