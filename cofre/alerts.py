"""COFRE - reglas de alerta (paso 3.2).

Cinco decisiones que estan en el codigo, no en la cabeza de quien lo lea:

  1. Se evalua SOLO lo nuevo: el estado guarda el ultimo `seq` visto y no se
     vuelve a mirar el log entero.
  2. Cada alerta se registra como evento del log (`ev="alert"`), asi que queda
     firmada si el cofre esta abierto.
  3. Pausa por regla: 10 minutos por defecto antes de repetir la misma alerta.
  4. Umbrales configurables en `cofre-settings.json`, junto al cofre.
  5. `MessageBoxW` se lanza en su propio hilo: bloquea a quien lo llama, y nunca
     debe ser el hilo de Tkinter ni el de la tuberia.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cofre.paths import atomic_write

SETTINGS_NAME = "cofre-settings.json"

DEFAULTS = {
    "burst_count": 10,        # lecturas
    "burst_minutes": 5,
    "odd_from": 1,            # hora local
    "odd_to": 6,
    "cooldown_minutes": 10,
    "open_failures": 3,
    "rotation_hours": 24,      # diario de rotacion abierto demasiado tiempo
}

READ_EVENTS = {"get", "browser-get", "clipboard", "reveal"}
SEVERITY_ORDER = {"baja": 0, "media": 1, "alta": 2, "critica": 3}


@dataclass
class Alert:
    rule: str
    severity: str
    text: str
    seq: int = 0

    @property
    def critical(self) -> bool:
        return self.severity in ("alta", "critica")


@dataclass
class AlertState:
    last_seq: int = 0
    cooldowns: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"last_seq": self.last_seq, "cooldowns": dict(self.cooldowns)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "AlertState":
        data = data or {}
        return cls(last_seq=int(data.get("last_seq", 0)),
                   cooldowns={str(k): float(v) for k, v in (data.get("cooldowns") or {}).items()})


# ---------------------------------------------------------------- ajustes

def settings_path(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / SETTINGS_NAME


def load_settings(vault_path: str | Path) -> dict:
    cfg = dict(DEFAULTS)
    p = settings_path(vault_path)
    if p.exists():
        try:
            datos = json.loads(p.read_text(encoding="utf-8"))
            alertas = datos.get("alerts", datos)
            if isinstance(alertas, dict):
                for k, v in alertas.items():
                    if k in DEFAULTS:
                        cfg[k] = v
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def write_settings(vault_path: str | Path, values: dict) -> Path:
    p = settings_path(vault_path)
    actual = {}
    if p.exists():
        try:
            actual = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            actual = {}
    alertas = actual.get("alerts") if isinstance(actual.get("alerts"), dict) else {}
    alertas.update({k: v for k, v in values.items() if k in DEFAULTS})
    actual["alerts"] = alertas
    return atomic_write(p, json.dumps(actual, indent=2, sort_keys=True))


def events_of(vault_path: str | Path) -> list[dict]:
    """Eventos del log, en orden. Lo usa la GUI y la CLI."""
    from cofre.audit import _events          # mismo parser, una sola verdad
    return _events(vault_path)


# ---------------------------------------------------------------- reglas

def _hora(ts: str) -> int:
    try:
        return datetime.fromisoformat(str(ts)).hour
    except Exception:
        return -1


def evaluate(events: list[dict], settings: dict, state: AlertState,
             now: float | None = None) -> list[Alert]:
    """Alertas nuevas a partir de los eventos posteriores a state.last_seq."""
    now = time.time() if now is None else now
    cfg = dict(DEFAULTS)
    cfg.update(settings or {})
    nuevos = [e for e in events if int(e.get("seq", 0)) > state.last_seq]
    if not nuevos:
        return []
    state.last_seq = max(int(e.get("seq", 0)) for e in nuevos)

    encontradas: list[Alert] = []

    # senuelo: cualquier acceso es critico
    for ev in nuevos:
        if ev.get("ev") == "canary-access":
            encontradas.append(Alert("senuelo", "critica",
                                     f"alguien pidio el senuelo '{ev.get('name')}' "
                                     f"({ev.get('detail','')})", int(ev.get("seq", 0))))

    # rafaga de lecturas
    ventana = float(cfg["burst_minutes"]) * 60
    lecturas = []
    for ev in events:
        if ev.get("ev") not in READ_EVENTS or not ev.get("ok"):
            continue
        try:
            ts = datetime.fromisoformat(str(ev.get("ts"))).timestamp()
        except Exception:
            continue
        if now - ts <= ventana:
            lecturas.append(ev)
    if len(lecturas) > int(cfg["burst_count"]):
        encontradas.append(Alert("rafaga", "alta",
                                 f"{len(lecturas)} lecturas en {cfg['burst_minutes']} min",
                                 int(lecturas[-1].get("seq", 0))))

    # fallos de apertura seguidos
    fallos = 0
    for ev in reversed(events):
        if ev.get("ev") in ("gui-gate", "get", "check") and ev.get("ok") is False:
            fallos += 1
            if fallos >= int(cfg["open_failures"]):
                break
        elif ev.get("ev") in ("gui-gate", "get", "check"):
            break
    if fallos >= int(cfg["open_failures"]):
        encontradas.append(Alert("fallos-apertura", "media",
                                 f"{fallos} fallos de apertura seguidos",
                                 int(events[-1].get("seq", 0))))

    # hora rara
    for ev in nuevos:
        if ev.get("ev") in READ_EVENTS and ev.get("ok"):
            h = _hora(ev.get("ts"))
            if int(cfg["odd_from"]) <= h < int(cfg["odd_to"]):
                encontradas.append(Alert("hora-rara", "baja",
                                         f"lectura a las {h:02d}:00", int(ev.get("seq", 0))))
                break

    # puente: origen rechazado
    for ev in nuevos:
        if ev.get("ev") in ("bridge-reject", "browser-get") and not ev.get("ok") \
                and "origen" in str(ev.get("detail", "")):
            encontradas.append(Alert("puente", "media",
                                     "peticion del puente con origen no autorizado",
                                     int(ev.get("seq", 0))))
            break

    # re-anclaje: solo el ultimo, no todos los historicos
    anclas = [e for e in nuevos if e.get("ev") in ("reanchor", "fin-de-pruebas")]
    if anclas:
        ultimo = max(anclas, key=lambda e: int(e.get("seq", 0)))
        encontradas.append(Alert("reanclaje", "media",
                                 f"log re-anclado en la línea {ultimo.get('seq')} "
                                 f"({ultimo.get('detail') or 'sin motivo escrito'})",
                                 int(ultimo.get("seq", 0))))

    # rotacion estancada: se evalua fuera de los eventos (lo mira la GUI)
    # log manipulado: cuenta el ULTIMO veredicto, no los historicos que ya se
    # resolvieron con un re-anclaje
    veredictos = [e for e in events if e.get("ev") == "audit-verify"]
    notas = [e for e in events if e.get("ev") == "audit-note" and e.get("mac")]
    if veredictos:
        ultimo = veredictos[-1]
        ultima_nota = max((int(n.get("seq", 0)) for n in notas), default=0)
        explicado = bool(notas) and all(
            ultima_nota > int(ev.get("seq", 0))
            for ev in veredictos if not ev.get("ok"))
        if not ultimo.get("ok") and not explicado:
            encontradas.append(Alert("log-manipulado", "critica",
                                     str(ultimo.get("detail", "el log no cuadra"))[:160],
                                     int(ultimo.get("seq", 0))))

    return encontradas


def apply_cooldown(alerts: list[Alert], state: AlertState, settings: dict,
                   now: float | None = None) -> list[Alert]:
    """Quitar las que estan en pausa y anotar las que salen."""
    now = time.time() if now is None else now
    pausa = float(settings.get("cooldown_minutes", DEFAULTS["cooldown_minutes"])) * 60
    salida = []
    for a in alerts:
        hasta = state.cooldowns.get(a.rule, 0.0)
        if now < hasta:
            continue
        state.cooldowns[a.rule] = now + pausa
        salida.append(a)
    return salida


def evaluate_unrevoked(store, events: list[dict],
                       days: int | None = None) -> list[Alert]:
    """Credenciales viejas que siguen vivas demasiado tiempo.

    No sale de un evento sino del indice cifrado (la entrada recuerda la
    credencial que no se revoco al cerrar la rotacion). Para no repetir el
    aviso en cada pasada se mira si ya hay un evento con ese nombre y fecha.
    """
    from cofre.rotation import DIAS_SIN_REVOCAR, dias_desde, pendientes_de_revocar

    if store is None or getattr(store, "master", None) is None:
        return []
    limite = DIAS_SIN_REVOCAR if days is None else int(days)
    salida: list[Alert] = []
    for pendiente in pendientes_de_revocar(store, store.master):
        dias = dias_desde(pendiente.get("desde"))
        if dias < limite:
            continue
        nombre = str(pendiente.get("nombre") or "")
        desde = str(pendiente.get("desde") or "")[:10]
        if _aviso_ya_escrito(events, nombre, desde):
            continue
        texto = (f"'{nombre}': credencial antigua sin revocar desde "
                 f"{desde} ({dias} días)")
        salida.append(Alert("credencial-sin-revocar", "baja", texto))
    return salida


def _aviso_ya_escrito(events: list[dict], nombre: str, desde: str) -> bool:
    for event in events:
        if event.get("ev") != "alert" or event.get("name") != "credencial-sin-revocar":
            continue
        detalle = str(event.get("detail") or "")
        if nombre and nombre in detalle and desde and desde in detalle:
            return True
    return False



# ---------------------------------------------------------------- avisos

MessageBoxW = None


def _messagebox(titulo: str, texto: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, titulo,
                                         0x00040000 | 0x00000030)
    except Exception:
        pass


def notify(alerts: list[Alert]) -> None:
    """Aviso bloqueante para alertas altas o criticas, SIEMPRE en su hilo."""
    graves = [a for a in alerts if a.critical]
    if not graves:
        return
    texto = "\n".join(f"- {a.text}" for a in graves)
    hilo = threading.Thread(target=_messagebox,
                            args=("COFRE - alerta", texto), daemon=True)
    hilo.start()


def show_message(titulo: str, texto: str) -> None:
    """MessageBoxW en su propio hilo, esperando a que se cierre.

    `due --notify` termina en cuanto se cierra el aviso; si el hilo fuera daemon
    el proceso moriria antes de mostrarlo. Para la GUI existe `notify`, que no
    espera para no bloquear a Tkinter.
    """
    hilo = threading.Thread(target=_messagebox, args=(titulo, texto),
                            daemon=False)
    hilo.start()
    hilo.join()


def describe(alerts: list[Alert]) -> str:
    if not alerts:
        return ""
    peor = max(alerts, key=lambda a: SEVERITY_ORDER.get(a.severity, 0))
    return f"{peor.severity.upper()}: {peor.text}"
