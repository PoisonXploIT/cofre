"""COFRE - salud de las credenciales (paso 5.9).

Comprueba cada credencial contra su proveedor de verdad y la clasifica sin
mostrar nunca el valor:

  invalida       el proveedor la rechaza                     rojo
  caduca         caduca en menos de 14 dias                  ambar
  rotacion       toca rotarla (last_rotated + rotate_every)  ambar
  duplicada      el mismo valor esta en dos entradas         ambar
  debil          contrasena de menos de 60 bits estimados    ambar
  sin_verificar  hace mas de 30 dias que no se comprueba     gris
  ok             lo demas

El resultado se guarda en el indice cifrado (`health`, `health_detail`,
`last_verified`, `expires_at`). El valor no se escribe en ningun sitio.

La revision se separa de la escritura a proposito: `revisar()` solo lee y llama
a los proveedores (puede tardar), asi la GUI puede lanzarla en un hilo y aplicar
el resultado en el hilo de Tkinter con `aplicar()`.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DIAS_CADUCA = 14
DIAS_SIN_VERIFICAR = 30
BITS_MINIMOS = 60

# de peor a mejor: el primer motivo es el estado que se muestra
ESTADOS = ("invalida", "caduca", "rotación", "sin_verificar", "duplicada",
           "debil", "ok")

SIN_VALOR = {"note", "canary"}

ETIQUETAS = {
    "invalida": "inválida",
    "caduca": "caduca pronto",
    "rotación": "toca rotar",
    "duplicada": "duplicada",
    "debil": "débil",
    "sin_verificar": "sin verificar",
    "ok": "correcta",
}


@dataclass
class Resultado:
    nombre: str
    estado: str
    detalle: str
    caduca: str = ""
    comprobado: str = ""


def _fecha(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor or "")[:10])
    except ValueError:
        return None


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fingerprint(master: bytes, valor: str) -> str:
    """Huella con clave para detectar duplicados sin guardar el valor."""
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"cofre/v2/fingerprint").derive(master)
    return hmac.new(key, valor.encode("utf-8"), hashlib.sha256).hexdigest()


def bits_estimados(valor: str) -> float:
    """Estimacion por clases de caracteres. No es un medidor de diccionario."""
    if not valor:
        return 0.0
    clases = 0
    if any(c.islower() for c in valor):
        clases += 26
    if any(c.isupper() for c in valor):
        clases += 26
    if any(c.isdigit() for c in valor):
        clases += 10
    if any(not c.isalnum() for c in valor):
        clases += 33
    return len(valor) * math.log2(max(2, clases))


def _rotacion_vencida(meta: dict, hoy: date) -> bool:
    cada = meta.get("rotate_every_days")
    base = _fecha(meta.get("last_rotated") or meta.get("created"))
    if not cada or base is None:
        return False
    return base + timedelta(days=int(cada)) <= hoy


def _motivos(meta: dict, hoy: date, duplicada: bool, verificada_ahora: bool,
             resultado_verify=None, error: str = "", valor: str = "",
             con_proveedor: bool = False) -> list[str]:
    motivos: list[str] = []
    if resultado_verify is not None and not resultado_verify.ok:
        motivos.append("invalida")
    elif error:
        motivos.append("sin_verificar")
    expira = _fecha(meta.get("expires_at"))
    if expira is not None:
        dias = (expira - hoy).days
        if 0 <= dias <= DIAS_CADUCA:
            motivos.append("caduca")
    if _rotacion_vencida(meta, hoy):
        motivos.append("rotación")
    if duplicada:
        motivos.append("duplicada")
    if str(meta.get("type") or "") == "password":
        if valor and bits_estimados(valor) < BITS_MINIMOS:
            motivos.append("debil")
    if con_proveedor and not verificada_ahora and not error:
        ultima = _fecha(meta.get("last_verified"))
        if ultima is None or (hoy - ultima).days > DIAS_SIN_VERIFICAR:
            motivos.append("sin_verificar")
    return [m for m in ESTADOS if m in motivos] or ["ok"]


def revisar(store, master: bytes, verificar: bool = True,
            hoy: date | None = None) -> list[Resultado]:
    """Leer, comparar y (si toca) preguntar a los proveedores. No escribe."""
    from cofre.providers import get as provider_get

    hoy = hoy or date.today()
    idx = store.index(store._data, master)
    entradas = idx.get("entries") or {}

    valores: dict[str, str] = {}
    huellas: dict[str, list[str]] = {}
    for nombre, meta in entradas.items():
        if str(meta.get("type") or "") in SIN_VALOR:
            continue
        try:
            valor = store._vault.get(store._data, master, nombre)
        except Exception:                          # noqa: BLE001
            continue
        valores[nombre] = valor
        if valor:
            huellas.setdefault(fingerprint(master, valor), []).append(nombre)
    duplicadas = {nombre for grupo in huellas.values() if len(grupo) > 1
                  for nombre in grupo}

    salida: list[Resultado] = []
    for nombre, meta in entradas.items():
        tipo = str(meta.get("type") or "")
        if tipo in SIN_VALOR:
            continue
        proveedor_nombre = str(meta.get("provider") or "")
        resultado = None
        error = ""
        if verificar and proveedor_nombre and tipo != "private_key":
            try:
                proveedor = provider_get(proveedor_nombre)
                resultado = proveedor.verify(valores.get(nombre, ""), meta)
            except Exception as exc:               # noqa: BLE001
                error = f"no se pudo comprobar: {exc}"

        valor = valores.get(nombre, "")
        motivos = _motivos(meta, hoy, nombre in duplicadas,
                           resultado is not None, resultado, error, valor,
                           bool(proveedor_nombre))
        estado = motivos[0]
        if estado == "invalida" and resultado is not None:
            detalle = resultado.detail or "el proveedor la rechaza"
        elif error:
            detalle = error
        elif estado == "ok":
            detalle = "correcta"
        else:
            detalle = ", ".join(motivos)
        salida.append(Resultado(
            nombre=nombre, estado=estado, detalle=detalle[:160],
            caduca=(resultado.expires_at if resultado is not None else "") or "",
            comprobado=_ahora() if resultado is not None else ""))
    return salida


def aplicar(store, master: bytes, resultados: list[Resultado]) -> int:
    """Guardar el resultado en el indice cifrado. Devuelve cuantas entradas."""
    idx = store.index(store._data, master)
    entradas = idx.get("entries") or {}
    cambios = 0
    for resultado in resultados:
        meta = entradas.get(resultado.nombre)
        if meta is None:
            continue
        meta["health"] = resultado.estado
        meta["health_detail"] = resultado.detalle
        if resultado.comprobado:
            meta["last_verified"] = resultado.comprobado
        if resultado.caduca:
            meta["expires_at"] = resultado.caduca
        cambios += 1
    if cambios:
        store._write_index(store._data, master, idx)
        store.save(store._data)
    return cambios


def resumen(resultados: list[Resultado]) -> dict[str, int]:
    cuenta = {estado: 0 for estado in ESTADOS}
    for resultado in resultados:
        cuenta[resultado.estado] = cuenta.get(resultado.estado, 0) + 1
    return {estado: n for estado, n in cuenta.items() if n}
