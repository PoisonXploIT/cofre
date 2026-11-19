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
import threading
import time
from datetime import datetime
from pathlib import Path

from cofre.paths import atomic_write, audit_path

MAX_LINES = 5000

# Eventos que SOLO pueden ocurrir con el cofre abierto. Si aparecen sin firma no
# es que se escribieran con el cofre cerrado: alguien los anadio a mano.
# Eventos que pueden ocurrir con el cofre CERRADO: un intento de apertura
# fallido, una alerta de fallos, un rechazo del puente. Van sin firma y es
# normal; no se confunden con manipulacion.
# 'check' NO esta aqui: abre el cofre con la llave y por tanto puede y debe
# firmar. Si aparece sin firma es un fallo de orden, como el del lock.
EXPECTED_UNSIGNED = {"gui-gate", "alert", "bridge-reject", "audit-verify"}
# `audit-verify` puede escribirse con el cofre cerrado (log verify no necesita
# pendrive), asi que no puede exigir firma. `lock`, `meta` y `rotate` si: solo
# ocurren con el cofre abierto. (Corregido el 2026-11-19: antes estaba al reves y
# siete verificaciones echas sin llave se marcaban como manipulacion.)

PRIVILEGED = {
    "get", "reveal", "clipboard", "browser-get", "browser-list", "add", "del",
    "rename", "rotate", "lock", "exec", "export", "host-assign", "migrate",
    "stick-add-v2", "fin-de-pruebas", "reanchor", "restore",
    "meta", "seal", "check", "stick-register", "stick-verify", "stick-copy",
    "stick-revoke", "stick-role", "gate-explicit", "edit", "copy-name",
    "copy-exec", "edit-load", "bridge-start", "canary-access", "revoke",
    "discard", "health", "panic", "rekey", "recovery", "backup",
    "run", "describe", "git-get", "grant-revoke", "scan",
    "browser-save",
}
GENESIS = "0" * 64
_KEY: bytes | None = None
_STORE = None      # V2Store abierto: permite sellar el checkpoint al escribir
# El registro lo escriben el hilo de la GUI, el de la tuberia y el del TCP. Si
# dos anotan a la vez, el seq y el prev se pisan y la cadena se rompe sola.
_WRITE = threading.Lock()


# ---------------------------------------------------------------- clave

def _subkey(master: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"cofre/v2/audit").derive(master)


def set_key(master: bytes | None) -> None:
    global _KEY
    _KEY = _subkey(master) if master else None


def clave_ligada() -> bool:
    """True si hay clave de auditoria: sin ella, un evento no se puede firmar."""
    return _KEY is not None


def bind_store(store) -> None:
    """El cofre abierto. Con esto, cada línea queda sellada en el checkpoint."""
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
    """(seq, hash, texto) de la última línea, o (0, GENESIS, '') si no hay."""
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
    """Compara el historico con el hash anclado en la primera línea del v2."""
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
    with _WRITE:
        return _record(vault_path, command, gate, serial=serial, name=name, ok=ok,
                       detail=detail, actor=actor, entry=entry)


def _record(vault_path: str | Path, command: str, gate: str,
            serial: int | None = None, name: str | None = None,
            ok: bool = True, detail: str = "", actor: str | None = None,
            entry: str | None = None) -> Path:
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
    """Compatibilidad: las ultimas entradas en una línea de texto."""
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
    "gen": "contraseña generada",
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
    "revoke": "credencial antigua revocada",
    "discard": "aviso de credencial antigua descartado",
    "health": "salud de credenciales comprobada",
    "panic": "boton de panico",
    "rekey": "clave maestra cambiada",
    "recovery": "código de recuperación renovado",
    "backup": "copia del cofre",
    "run": "comando con variables del proyecto",
    "describe": "descripcion para agentes (sin valores)",
    "git-get": "credencial entregada a git",
    "grant-revoke": "permiso temporal retirado",
    "scan": "escaneo de fugas",
    "browser-save": "alta pedida desde el navegador",
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
        return True, "no hay log todavía"
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
            return False, f"línea {numero}: no es JSON"
        if ev.get("prev") != prev:
            return False, f"línea {numero}: la cadena no cuadra (prev distinto)"
        if int(ev.get("seq", 0)) != seq_esperado:
            return False, f"línea {numero}: seq {ev.get('seq')} cuando tocaba {seq_esperado}"
        mac = ev.pop("mac", None)
        if mac is None:
            sin_firma += 1
            privilegiado = str(ev.get("ev")) in PRIVILEGED
            en_uso_real = antes_de_uso is None or int(ev.get("seq", 0)) >= antes_de_uso
            if _KEY is not None and privilegiado and en_uso_real                     and str(ev.get("ev")) not in EXPECTED_UNSIGNED:
                culpables.append(f"{numero}:{ev.get('ev')}")
        elif _KEY is not None:
            esperado = hmac.new(_KEY, _canonical(ev), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, esperado):
                return False, f"línea {numero}: firma incorrecta (manipulada)"
        prev = _line_hash(texto)
        seq_esperado += 1
    if culpables:
        # si hay una nota firmada posterior que las explica, se dan por
        # explicadas: siguen en el log, pero no gritan para siempre
        nota = None
        for texto in lineas:
            try:
                ev = json.loads(texto)
            except json.JSONDecodeError:
                continue
            if ev.get("ev") == "audit-note" and ev.get("mac"):
                nota = int(ev.get("seq", 0))
        if nota and all(int(c.split(":")[0]) < nota for c in culpables):
            detalle = (f"{len(lineas)} líneas, cadena intacta; {len(culpables)} "
                       f"sin firma explicadas por la nota firmada de la línea {nota}")
            return True, detalle
        muestra = ", ".join(culpables[:6])
        extra = "" if len(culpables) <= 6 else f" y {len(culpables) - 6} mas"
        return False, (f"eventos que exigen cofre abierto y van sin firma: "
                       f"{muestra}{extra}. Se anadieron a mano")
    detalle = f"{len(lineas)} líneas, cadena intacta"
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
        detalle += f", re-anclado en la línea {ultima_ancla}"
        if ultima_ancla > 1:
            detalle += f" (líneas 1-{ultima_ancla - 1} exentas de firma)"
    if sin_firma:
        detalle += f", {sin_firma} sin firma (escritas con el cofre cerrado)"
    ok_tramos, detalle_tramos = retired_report(vault_path)
    if not ok_tramos:
        return False, detalle_tramos
    if detalle_tramos:
        detalle += "; " + detalle_tramos
    return True, detalle


SEGMENT_PREFIX = ".cofre-audit-retirado-"


def _segmentos_retirados(vault_path: str | Path) -> list[Path]:
    base = Path(vault_path).parent
    return sorted(base.glob(SEGMENT_PREFIX + "*.jsonl"))


def close_segment(vault_path: str | Path, new_master: bytes, motivo: str = "",
                  gate: str = "-", serial: int | None = None,
                  actor: str = "cli") -> dict | None:
    """Cerrar el tramo actual, archivarlo en solo lectura y anclar el nuevo.

    El tramo viejo NO se re-firma: se guarda tal cual, con las firmas de la clave
    que se retira. El tramo nuevo empieza con un `audit-start` firmado con la
    clave NUEVA que ancla por SHA-256 el archivo retirado. Quien llama debe
    haber escrito antes el evento de cierre con la clave vieja.
    """
    import stat

    p = audit_path(vault_path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    texto = p.read_text(encoding="utf-8")
    lineas = texto.splitlines()
    ok_viejo, detalle_viejo = verify(vault_path)
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path(vault_path).parent
    destino = base / f"{SEGMENT_PREFIX}{marca}.jsonl"
    n = 2
    while destino.exists():
        destino = base / f"{SEGMENT_PREFIX}{marca}-{n}.jsonl"
        n += 1
    atomic_write(destino, texto)
    try:
        os.chmod(destino, stat.S_IREAD)
    except OSError:
        pass
    huella = _sha256_file(destino)
    aviso = "" if ok_viejo else f" (el tramo viejo no verificaba: {detalle_viejo[:80]})"
    # un rekey puede ocurrir varias veces: los anclas anteriores se heredan en
    # el ancla nueva, firmada con la clave nueva
    heredados: list[str] = []
    for ev in _events(vault_path):
        if ev.get("ev") != "audit-start":
            continue
        detalle_prev = str(ev.get("detail") or "")
        nombre_prev = str(ev.get("name") or "")
        sha_prev = ""
        for trozo in detalle_prev.split():
            if trozo.startswith("sha256="):
                sha_prev = trozo.split("=", 1)[1]
                break
        if nombre_prev and sha_prev:
            heredados.append(f"{nombre_prev}={sha_prev}")
        if "anteriores=" in detalle_prev:
            lista = detalle_prev.split("anteriores=", 1)[1].split()[0]
            heredados.extend(t for t in lista.split(",") if "=" in t)
    heredados = sorted(set(heredados))
    cola = (" anteriores=" + ",".join(heredados)) if heredados else ""
    payload = {
        "seq": 1,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ev": "audit-start",
        "entry": "-",
        "name": destino.name,
        "actor": actor,
        "ok": True,
        "stick": str(serial) if serial is not None else "-",
        "gate": gate,
        "detail": (f"tramo retirado sha256={huella} motivo={motivo or 'rekey'}"
                   f"{aviso}{cola}"),
        "prev": GENESIS,
    }
    mac = hmac.new(_subkey(new_master), _canonical(payload),
                   hashlib.sha256).hexdigest()
    payload["mac"] = mac
    linea = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    atomic_write(p, linea + "\n")
    return {"archivo": str(destino), "nombre": destino.name, "sha256": huella,
            "líneas": len(lineas), "verificaba": ok_viejo,
            "detalle": detalle_viejo, "seq": 1, "hash": _line_hash(linea)}


def retired_report(vault_path: str | Path) -> tuple[bool, str]:
    """Comprobar los tramos retirados contra su ancla (hash, no firma)."""
    archivos = _segmentos_retirados(vault_path)
    anclas: dict[str, tuple[str, str, str]] = {}
    for ev in _events(vault_path):
        if ev.get("ev") != "audit-start":
            continue
        nombre = str(ev.get("name") or "")
        if not nombre.startswith(SEGMENT_PREFIX):
            continue
        detalle = str(ev.get("detail") or "")
        sha = ""
        for trozo in detalle.split():
            if trozo.startswith("sha256="):
                sha = trozo.split("=", 1)[1]
                break
        motivo = ""
        if "motivo=" in detalle:
            motivo = detalle.split("motivo=", 1)[1].split()[0]
        anclas[nombre] = (sha, str(ev.get("ts") or "")[:10], motivo)
        if "anteriores=" in detalle:
            lista = detalle.split("anteriores=", 1)[1].split()[0]
            for trozo in lista.split(","):
                if "=" in trozo:
                    otro, sha_otro = trozo.split("=", 1)
                    anclas.setdefault(otro, (sha_otro, str(ev.get("ts") or "")[:10],
                                             motivo))
    for nombre in anclas:
        if not nombre.startswith(SEGMENT_PREFIX):
            continue
        if not (Path(vault_path).parent / nombre).exists():
            return False, f"{nombre}: falta el tramo retirado anclado"
    partes = []
    for archivo in archivos:
        ancla = anclas.get(archivo.name)
        if not ancla:
            return False, (f"{archivo.name}: tramo retirado sin ancla en el "
                           "registro actual")
        sha, fecha, motivo = ancla
        actual = _sha256_file(archivo)
        if not sha or not hmac.compare_digest(actual, sha):
            return False, (f"{archivo.name}: el tramo retirado se ha editado "
                           "(el hash no coincide con el ancla)")
        partes.append(f"{archivo.name}: firmado con la clave retirada en el "
                      f"{motivo or 'cambio'} del {fecha}, anclado por hash")
    return True, "; ".join(partes)


def pending_unsigned(vault_path: str | Path) -> int:
    """Eventos esperados sin firma posteriores al último sello o nota firmada."""
    eventos = _events(vault_path)
    corte = 0
    for ev in eventos:
        if ev.get("ev") in ("seal", "audit-note") and ev.get("mac"):
            corte = max(corte, int(ev.get("seq", 0)))
    return sum(1 for ev in eventos
               if ev.get("mac") is None and str(ev.get("ev")) in EXPECTED_UNSIGNED
               and int(ev.get("seq", 0)) > corte)


def auto_seal(store, master: bytes, forzar: bool = False) -> bool:
    """Sellar el registro cuando lo pendiente es solo lo esperado.

    Escribe un evento 'seal' FIRMADO que deja constancia de cuantos eventos
    esperados habia, y actualiza el checkpoint. Si hay algo que no es esperado,
    no sella (salvo forzar, que solo usa el boton Sellar).
    """
    try:
        ok, _detalle = verify(store.path)
        esperados = pending_unsigned(store.path)
        if not esperados:
            return False
        if not ok and not forzar:
            return False
        record(store.path, "seal", "-", None, ok=True, actor="gui",
               detail=f"{esperados} eventos con el cofre cerrado, sellados")
        stamp(store, master)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- checkpoint

def checkpoint(store, master: bytes) -> dict:
    """Ultimo seq y hash de la línea, guardados dentro del indice cifrado."""
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
        return True, "sin checkpoint todavía"
    p = audit_path(store.path)
    seq, hash_ultima, _ = _last_line(p)
    if not p.exists() or seq == 0:
        return False, "el log no existe pero el checkpoint dice que habia eventos"
    guardado_seq = int(guardado.get("seq", -1))
    if seq < guardado_seq:
        return False, (f"el log tiene {seq} eventos y el checkpoint {guardado_seq}: "
                       "faltan líneas al final")
    if seq > guardado_seq:
        # tipico tras restaurar una copia antigua del cofre: el log va por delante.
        # No es manipulacion; se avisa y se puede resellar con un evento firmado.
        return True, (f"aviso: el log va por delante del checkpoint ({seq} > {guardado_seq}); "
                      "normal si se ha restaurado una copia. Usa 'log reseal' para sellarlo")
    if guardado.get("hash") != hash_ultima:
        return False, "la última línea no coincide con el checkpoint"
    return True, f"{seq} eventos, checkpoint OK"
