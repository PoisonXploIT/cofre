"""COFRE - log de auditoria encadenado (paso 3.1).

Cada linea es un JSON con:

    seq     numero de evento (empieza en 1)
    ts      fecha y hora
    ev      que paso (get, exec, lock, ...)
    entry   id de la entrada (o "-")
    name    nombre del secreto (nunca el valor)
    actor   quien lo pidio: gui, cli, exec:<prog>, browser:<host>
    ok      true/false
    detail  texto libre, sin valores
    prev    sha256 de la linea anterior completa; la primera, "0"*64
    mac     HMAC-SHA256 del JSON sin "mac", con una subclave derivada de K

Si el cofre esta cerrado no hay K y `mac` queda en null: la linea sigue
encadenada por `prev`, pero no se puede firmar. Por eso la verificacion distingue
"cadena rota" de "linea sin firma".

Ademas hay un checkpoint cifrado dentro del cofre (ultimo seq y hash de la ultima
linea). Si alguien borra las ultimas lineas del fichero, el checkpoint lo delata.

Uso:
    audit.set_key(master)      al abrir el cofre (K en memoria)
    audit.record(...)          en cada accion
    audit.verify(vault)        al abrir y desde `log verify`
    audit.clear_key()          al bloquear
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from pathlib import Path

from cofre.paths import atomic_write, audit_path

MAX_LINES = 5000

# Eventos que SOLO pueden ocurrir con el cofre abierto. Si aparecen sin firma no
# es que se escribieran con el cofre cerrado: alguien los anadio a mano.
PRIVILEGED = {
    "get", "reveal", "clipboard", "browser-get", "browser-list", "add", "del",
    "rename", "rotate", "lock", "exec", "export", "host-assign", "migrate",
    "stick-add-v2", "audit-verify", "fin-de-pruebas", "reanchor", "restore",
    "meta", "host-assign",
}
GENESIS = "0" * 64
_KEY: bytes | None = None
_STORE = None      # V2Store abierto: permite sellar el checkpoint al escribir


# ---------------------------------------------------------------- clave

def _subkey(master: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"cofre/v2/audit").derive(master)


def set_key(master: bytes | None) -> None:
    global _KEY
    _KEY = _subkey(master) if master else None


def bind_store(store) -> None:
    """El cofre abierto. Con esto, cada linea queda sellada en el checkpoint."""
    global _STORE
    _STORE = store


def clear_key() -> None:
    global _KEY, _STORE
    _KEY = None
    _STORE = None


def has_key() -> bool:
    return _KEY is not None


# ---------------------------------------------------------------- formato

def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _line_hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _last_line(path: Path) -> tuple[int, str, str]:
    """(seq, hash, texto) de la ultima linea, o (0, GENESIS, '') si no hay."""
    if not path.exists():
        return 0, GENESIS, ""
    try:
        lineas = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, GENESIS, ""
    if not lineas:
        return 0, GENESIS, ""
    ultima = lineas[-1]
    try:
        seq = int(json.loads(ultima).get("seq", 0))
    except Exception:
        seq = 0
    return seq, _line_hash(ultima), ultima


# ---------------------------------------------------------------- historico v1

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for bloque in iter(lambda: fh.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def legacy_files(vault_path: str | Path) -> list[Path]:
    """Los .cofre-access*.log antiguos, ya archivados o no."""
    base = Path(vault_path).parent
    return sorted([p for p in base.glob(".cofre-access*.log*") if p.is_file()])


def archive_legacy(vault_path: str | Path) -> tuple[Path, str] | None:
    """Renombrar el log v1 a .cofre-access-v1-hasta-AAAA-MM-DD.log y dejarlo de
    solo lectura. Devuelve (ruta, sha256) o None si no habia nada.

    No se migra: meter esos eventos en la cadena obligaria a firmarlos ahora, y
    eso seria dar por integros unos datos que pudieron editarse antes.
    """
    import stat
    pendientes = []
    for p in legacy_files(vault_path):
        if p.name.startswith(".cofre-access-v1-"):
            continue
        pendientes.append(p)
    if not pendientes:
        return None
    marca = datetime.now().strftime("%Y-%m-%d")
    destino = Path(vault_path).parent / f".cofre-access-v1-hasta-{marca}.log"
    # el archivo del dia puede existir ya (y estar en solo lectura): se busca
    # un nombre libre en vez de fallar
    n = 2
    while destino.exists():
        destino = Path(vault_path).parent / f".cofre-access-v1-hasta-{marca}-{n}.log"
        n += 1
    # si hay varios (log y .old) se concatenan en el mismo archivo
    with destino.open("ab") as salida:
        for p in pendientes:
            cabecera = "\n# --- " + p.name + " ---\n"
            salida.write(cabecera.encode("utf-8"))
            salida.write(p.read_bytes())
    for p in pendientes:
        try:
            os.chmod(p, stat.S_IWRITE)
            p.unlink()
        except OSError:
            pass
    os.chmod(destino, stat.S_IREAD)
    return destino, _sha256_file(destino)


def ensure_anchor(vault_path: str | Path, gate: str = "-",
                  serial: int | None = None) -> None:
    """Si hay historico v1 sin anclar, escribir el evento audit-start.

    El ancla es el SHA-256 del fichero archivado: si alguien lo edita despues,
    `log verify` lo detecta aunque no pueda decir que cambio.
    """
    archivados = [p for p in legacy_files(vault_path)
                  if p.name.startswith(".cofre-access-v1-")]
    if not archivados:
        return
    for ev in _events(vault_path):
        if ev.get("ev") == "audit-start":
            return
    destino = archivados[0]
    huella = _sha256_file(destino)
    p = audit_path(vault_path)
    seq_prev, hash_prev, _ = _last_line(p)
    payload = {
        "seq": seq_prev + 1,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ev": "audit-start",
        "entry": "-",
        "name": destino.name,
        "actor": "cli",
        "ok": True,
        "stick": str(serial) if serial is not None else "-",
        "gate": gate,
        "detail": f"historico v1 archivado sha256={huella} sin cadena",
        "prev": hash_prev,
    }
    mac = None
    if _KEY is not None:
        mac = hmac.new(_KEY, _canonical(payload), hashlib.sha256).hexdigest()
    payload["mac"] = mac
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def legacy_report(vault_path: str | Path) -> tuple[bool, str]:
    """Compara el historico con el hash anclado en la primera linea del v2."""
    archivados = [p for p in legacy_files(vault_path)
                  if p.name.startswith(".cofre-access-v1-")]
    if not archivados:
        return True, "sin historico v1"
    ancla = None
    for ev in _events(vault_path):
        if ev.get("ev") == "audit-start":
            ancla = (ev.get("detail") or "").split()
            break
    for p in archivados:
        actual = _sha256_file(p)
        coincide = bool(ancla) and any(tok == actual or tok == "sha256=" + actual
                                       for tok in ancla)
        if not coincide:
            return False, (f"{p.name}: el hash no coincide con el ancla "
                           "del registro nuevo (el historico se ha editado)")
        return True, f"{p.name}: anclado por hash, sin cadena (no verificable)"
    return True, "sin historico v1"


# ---------------------------------------------------------------- escritura

ACTORS = {"gui", "cli"}


def record(vault_path: str | Path, command: str, gate: str,
           serial: int | None = None, name: str | None = None,
           ok: bool = True, detail: str = "", actor: str | None = None,
           entry: str | None = None) -> Path:
    """Anotar un evento. Nunca se pasa el valor de un secreto."""
    p = audit_path(vault_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # el ancla va antes de calcular seq/prev, o la cadena se rompe
    archive_legacy(vault_path)
    ensure_anchor(vault_path, gate, serial)
    seq_prev, hash_prev, _texto = _last_line(p)
    if p.exists() and p.stat().st_size == 0:
        seq_prev, hash_prev = 0, GENESIS
    if not p.exists():
        archive_legacy(vault_path)
    ensure_anchor(vault_path, gate, serial)
    payload = {
        "seq": seq_prev + 1,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ev": command,
        "entry": entry or "-",
        "name": name or "-",
        "actor": actor or ("cli" if os.environ.get("COFRE_ACTOR") == "cli" else "gui"),
        "ok": bool(ok),
        "stick": str(serial) if serial is not None else "-",
        "gate": gate,
        "detail": detail or "",
        "prev": hash_prev,
    }
    mac = None
    if _KEY is not None:
        mac = hmac.new(_KEY, _canonical(payload), hashlib.sha256).hexdigest()
    payload["mac"] = mac
    texto = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with p.open("a", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    _rotate(p)
    # el checkpoint se sella SIEMPRE que haya cofre abierto: asi una linea
    # borrada al final no puede pasar por buena
    if _STORE is not None and getattr(_STORE, "master", None) is not None:
        stamp(_STORE, _STORE.master)
    return p


def _rotate(p: Path) -> None:
    try:
        lineas = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lineas) <= MAX_LINES:
        return
    marca = datetime.now().strftime("%Y%m%d")
    viejo = p.with_name(f"{p.stem}-{marca}{p.suffix}")
    atomic_write(viejo, "\n".join(lineas) + "\n")
    quedan = lineas[-1]
    atomic_write(p, quedan + "\n")


# ---------------------------------------------------------------- lectura

def _events(vault_path: str | Path) -> list[dict]:
    p = audit_path(vault_path)
    if not p.exists():
        return []
    salida = []
    for linea in p.read_text(encoding="utf-8").splitlines():
        try:
            salida.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return salida


def tail(vault_path: str | Path, lines: int = 20) -> list[str]:
    """Compatibilidad: las ultimas entradas en una linea de texto."""
    out = []
    for ev in _events(vault_path)[-lines:]:
        out.append(f"{ev.get('ts','')} cmd={ev.get('ev','-')} gate={ev.get('gate','-')} "
                   f"stick={ev.get('stick','-')} name={ev.get('name','-')} "
                   f"ok={1 if ev.get('ok') else 0}"
                   + (f" detail={ev['detail']}" if ev.get("detail") else ""))
    return out


VERBS = {
    "add": "guardado",
    "get": "leido",
    "reveal": "mostrado en pantalla",
    "clipboard": "copiado al portapapeles",
    "del": "borrado",
    "rename": "renombrado",
    "gen": "contrasena generada",
    "list": "listado de secretos",
    "exec": "comando ejecutado con",
    "export": "volcado a pantalla",
    "lock": "cofre bloqueado",
    "gui-gate": "intento de apertura rechazado",
    "stick-init": "llave creada en el pendrive",
    "stick-copy": "llave copiada a otro pendrive",
    "stick-register": "pendrive autorizado",
    "stick-revoke": "pendrive dado de baja",
    "stick-verify": "llaves comprobadas",
    "stick-role": "rol de pendrive cambiado",
    "host-assign": "dominios asignados",
    "bridge-start": "puente del navegador abierto",
    "browser-get": "pedido desde el navegador",
    "browser-list": "listado pedido desde el navegador",
    "migrate": "migrado a v2",
    "audit-verify": "log verificado",
}


def tail_human(vault_path: str | Path, lines: int = 6) -> list[str]:
    out = []
    for ev in _events(vault_path)[-lines:]:
        hora = str(ev.get("ts", ""))[11:16]
        verbo = VERBS.get(str(ev.get("ev", "?")), str(ev.get("ev", "?")))
        nombre = ev.get("name", "-")
        extra = "" if nombre in ("-", None) else f" {nombre}"
        estado = "ok" if ev.get("ok") else "FALLO"
        out.append(f"{hora}  {verbo}{extra}  [{estado}]  llave {ev.get('stick','-')}")
    return out


def stats(vault_path: str | Path) -> dict:
    eventos = _events(vault_path)
    sticks = {str(ev.get("stick")) for ev in eventos if ev.get("stick") not in (None, "-")}
    return {"entradas": len(eventos),
            "fallos": sum(1 for ev in eventos if not ev.get("ok")),
            "pendrives_usados": sorted(sticks),
            "archivo": str(audit_path(vault_path)),
            "max": MAX_LINES}


# ---------------------------------------------------------------- verificacion

def verify(vault_path: str | Path) -> tuple[bool, str]:
    """Comprueba la cadena, las firmas y (si hay) el checkpoint."""
    p = audit_path(vault_path)
    if not p.exists():
        return True, "no hay log todavia"
    lineas = p.read_text(encoding="utf-8").splitlines()
    prev = GENESIS
    seq_esperado = 1
    sin_firma = 0
    culpables: list[str] = []
    antes_de_uso: int | None = None
    # Desde la ULTIMA marca firmada ("fin-de-pruebas" o "reanchor") se exige
    # firma; lo anterior es historico y no se le pide. Re-anclar es decision del
    # usuario, queda firmado, se avisa en esta misma salida y dispara alerta.
    for texto in lineas:
        try:
            ev = json.loads(texto)
        except json.JSONDecodeError:
            continue
        if ev.get("ev") in ("fin-de-pruebas", "reanchor") and ev.get("mac"):
            antes_de_uso = int(ev.get("seq", 0))    # el ULTIMO, si hay varios
    for numero, texto in enumerate(lineas, start=1):
        try:
            ev = json.loads(texto)
        except json.JSONDecodeError:
            return False, f"linea {numero}: no es JSON"
        if ev.get("prev") != prev:
            return False, f"linea {numero}: la cadena no cuadra (prev distinto)"
        if int(ev.get("seq", 0)) != seq_esperado:
            return False, f"linea {numero}: seq {ev.get('seq')} cuando tocaba {seq_esperado}"
        mac = ev.pop("mac", None)
        if mac is None:
            sin_firma += 1
            privilegiado = str(ev.get("ev")) in PRIVILEGED
            en_uso_real = antes_de_uso is None or int(ev.get("seq", 0)) >= antes_de_uso
            if _KEY is not None and privilegiado and en_uso_real:
                culpables.append(f"{numero}:{ev.get('ev')}")
        elif _KEY is not None:
            esperado = hmac.new(_KEY, _canonical(ev), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, esperado):
                return False, f"linea {numero}: firma incorrecta (manipulada)"
        prev = _line_hash(texto)
        seq_esperado += 1
    if culpables:
        muestra = ", ".join(culpables[:6])
        extra = "" if len(culpables) <= 6 else f" y {len(culpables) - 6} mas"
        return False, (f"eventos que exigen cofre abierto y van sin firma: "
                       f"{muestra}{extra}. Se anadieron a mano")
    detalle = f"{len(lineas)} lineas, cadena intacta"
    anclas = []
    for texto in lineas:
        try:
            ev = json.loads(texto)
        except json.JSONDecodeError:
            continue
        if ev.get("ev") in ("fin-de-pruebas", "reanchor") and ev.get("mac"):
            anclas.append(int(ev.get("seq", 0)))
    if anclas:
        ultima_ancla = max(anclas)
        detalle += f", re-anclado en la linea {ultima_ancla}"
        if ultima_ancla > 1:
            detalle += f" (lineas 1-{ultima_ancla - 1} exentas de firma)"
    if sin_firma:
        detalle += f", {sin_firma} sin firma (escritas con el cofre cerrado)"
    return True, detalle


# ---------------------------------------------------------------- checkpoint

def checkpoint(store, master: bytes) -> dict:
    """Ultimo seq y hash de la linea, guardados dentro del indice cifrado."""
    p = audit_path(store.path)
    if not p.exists():
        return {}
    seq, hash_ultima, _ = _last_line(p)
    return {"seq": seq, "hash": hash_ultima}


def stamp(store, master: bytes) -> None:
    """Guardar el checkpoint en el cofre (solo funciona con el cofre abierto)."""
    try:
        # el store puede tener el indice cargado de antes de la ultima escritura
        if hasattr(store, "refresh"):
            store.refresh()
        datos = checkpoint(store, master)
        if not datos:
            return
        idx = store.index(store._data, master)
        idx.setdefault("settings", {})["audit"] = datos
        store._write_index(store._data, master, idx)
        store.save(store._data)
    except Exception:
        pass


def stamp_vault(vault) -> None:
    """Guardar el checkpoint usando el objeto Vault de la aplicacion."""
    try:
        if not vault.is_v2():
            return
        store = vault._v2store()
        if store.master is None:
            return
        stamp(store, store.master)
    except Exception:
        pass


def reseal_if_needed(store, master: bytes) -> bool:
    """Si el log va por delante del checkpoint (copia restaurada), resellarlo con
    un evento firmado 'restore'. Devuelve True si hizo algo."""
    try:
        idx = store.index(store._data, master)
        guardado = (idx.get("settings") or {}).get("audit") or {}
        if not guardado:
            return False
        seq, _hash, _ = _last_line(audit_path(store.path))
        if seq <= int(guardado.get("seq", 0)):
            return False
        record(store.path, "restore", "-", None, ok=True, actor="gui",
               detail=("checkpoint resellado: el log iba por delante "
                       f"({seq} > {guardado.get('seq')}), tipico tras restaurar una copia"))
        return True
    except Exception:
        return False


def verify_vault(vault) -> tuple[bool, str]:
    """verify + checkpoint. Acepta tanto el objeto Vault de la aplicacion como
    un V2Store (que es lo que sabe leer el checkpoint)."""
    path = getattr(vault, "path", None)
    ok, detalle = verify(path)
    store = None
    try:
        if hasattr(vault, "_v2store") and getattr(vault, "is_v2", lambda: False)():
            store = vault._v2store()
        elif hasattr(vault, "master"):
            store = vault
    except Exception:
        store = None
    if store is not None and getattr(store, "master", None) is not None:
        ok2, detalle2 = check_checkpoint(store, store.master)
        if not ok2:
            return ok2, detalle2
        detalle += "; " + detalle2
    return ok, detalle


def check_checkpoint(store, master: bytes) -> tuple[bool, str]:
    try:
        idx = store.index(store._data, master)
    except Exception as exc:                     # noqa: BLE001
        return False, f"no se puede leer el checkpoint: {type(exc).__name__}"
    guardado = (idx.get("settings") or {}).get("audit") or {}
    if not guardado:
        return True, "sin checkpoint todavia"
    p = audit_path(store.path)
    seq, hash_ultima, _ = _last_line(p)
    if not p.exists() or seq == 0:
        return False, "el log no existe pero el checkpoint dice que habia eventos"
    guardado_seq = int(guardado.get("seq", -1))
    if seq < guardado_seq:
        return False, (f"el log tiene {seq} eventos y el checkpoint {guardado_seq}: "
                       "faltan lineas al final")
    if seq > guardado_seq:
        # tipico tras restaurar una copia antigua del cofre: el log va por delante.
        # No es manipulacion; se avisa y se puede resellar con un evento firmado.
        return True, (f"aviso: el log va por delante del checkpoint ({seq} > {guardado_seq}); "
                      "normal si se ha restaurado una copia. Usa 'log reseal' para sellarlo")
    if guardado.get("hash") != hash_ultima:
        return False, "la ultima linea no coincide con el checkpoint"
    return True, f"{seq} eventos, checkpoint OK"
