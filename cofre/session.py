"""COFRE - sesion abierta y decisiones de bloqueo (paso 2.1).

Todo lo que decide "hay que cerrar" vive aqui, con el reloj inyectable para poder
probarlo sin esperar ocho horas.

Motivos posibles:
  - "inactividad"      no se toca el cofre en N minutos
  - "tiempo maximo"    la sesion lleva abierta M horas
  - "el equipo estuvo suspendido"  entre dos comprobaciones pasa demasiado tiempo
  - "pendrive retirado" lo detecta la GUI (hotplug) y llama a lock()
  - "windows bloqueado"    se bloqueo la sesion de Windows (Win+L)
"""

from __future__ import annotations

import time

DEFAULTS = {
    "idle_minutes": 10,        # inactividad
    "max_hours": 8,            # tope de la sesion
    "suspend_gap_seconds": 60,  # salto de reloj que delata una suspension
}


class Session:
    """Estado de una sesión abierta. No sabe descifrar: eso es del cofre."""

    def __init__(self, settings: dict | None = None, now=None, wall=None,
                 lock_state=None):
        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in (settings or {}).items() if k in DEFAULTS})
        self.settings = cfg
        self._now = now or time.monotonic
        self._wall = wall or time.time
        # 2.2: probado en esta maquina; si no se puede saber, devuelve None
        if lock_state is None:
            from cofre.winlock import is_locked as lock_state
        self._lock_state = lock_state
        self._bloqueada_antes: bool | None = None
        self.opened_at = self._now()
        self.opened_wall = self._wall()
        self.last_activity = self.opened_at
        self.last_wall = self.opened_wall
        self.locked_reason: str | None = None
        self.activity_count = 0

    # ---------------------------------------------------------------- estado

    def touch(self) -> None:
        """Marca actividad de la persona (no del sondeo automático)."""
        self.last_activity = self._now()
        self.last_wall = self._wall()
        self.activity_count += 1

    def idle_seconds(self) -> float:
        return max(0.0, self._now() - self.last_activity)

    def age_seconds(self) -> float:
        return max(0.0, self._now() - self.opened_at)

    # ---------------------------------------------------------------- decision

    def check(self) -> str | None:
        """Motivo para bloquear, o None si la sesión sigue valida."""
        if self.locked_reason:
            return self.locked_reason

        # suspension: si el reloj de pared ha saltado mucho mas que el monotono,
        # el equipo estuvo dormido y no nos enteramos
        wall_gap = self._wall() - self.last_wall
        mono_gap = self._now() - self.last_activity
        if wall_gap - mono_gap > self.settings["suspend_gap_seconds"] and wall_gap > 60:
            return "el equipo estuvo suspendido"

        # bloqueo de Windows: solo cuenta cuando pasa de desbloqueado a bloqueado,
        # para no bloquear el cofre al abrirlo desde una sesion ya bloqueada
        try:
            bloqueada = self._lock_state()
        except Exception:
            bloqueada = None
        if self._bloqueada_antes is None:
            # primera observacion: estado de partida, sin bloquear
            self._bloqueada_antes = bool(bloqueada)
        elif bloqueada is True and not self._bloqueada_antes:
            self._bloqueada_antes = True
            return "windows bloqueado"
        elif bloqueada is False:
            self._bloqueada_antes = False

        if self.idle_seconds() >= self.settings["idle_minutes"] * 60:
            return "inactividad"
        if self.age_seconds() >= self.settings["max_hours"] * 3600:
            return "tiempo maximo"
        return None

    def lock(self, reason: str) -> str:
        self.locked_reason = reason
        return reason

    # ---------------------------------------------------------------- ayudas

    def describe(self, reason: str) -> str:
        """Texto para el pie de la ventana."""
        if reason == "inactividad":
            return (f"cofre bloqueado por inactividad "
                    f"({self.settings['idle_minutes']} min sin usarlo)")
        if reason == "tiempo maximo":
            return (f"cofre bloqueado por tiempo maximo "
                    f"({self.settings['max_hours']} h de sesión)")
        if reason == "el equipo estuvo suspendido":
            return "cofre bloqueado: el equipo estuvo suspendido"
        if reason == "windows bloqueado":
            return "cofre bloqueado: se bloqueo Windows"
        return f"cofre bloqueado: {reason}"
