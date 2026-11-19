"""COFRE - candado para agentes (D20, 2026-11-19).

Contexto: la sesion del LLM que trabaja en este proyecto **no es local**, va a una
API en la nube. Todo lo que el agente lee o imprime sale del equipo: la salida de
los comandos, los ficheros que abre, los errores. Asi salio el codigo de
recuperacion del incidente del 19.

Esta regla tiene que ser un candado tecnico, no una promesa del prompt:

  COFRE_AGENT=1 en el entorno del agente

Con la variable puesta, COFRE **rechaza** lo que muestra valores:

  - `get` y `export`, con o sin `--allow-pipe`;
  - `--recovery` en cualquier comando (el codigo de papel no lo maneja el agente);
  - `describe` sin `--minimal` (la version completa lleva urls y referencias);
  - `add` con el valor como argumento (quedaria en el historial de la terminal);
  - `log --reanchor` (mover el punto de firma es cosa del usuario).

Sigue permitido: `exec` y `run` (el valor va al programa, no a la pantalla),
`check`, `health`, `describe --minimal`, `log verify`, `scan`, `list`, `version`,
`alerts`, `due`, `token-info`, `stick-*`, `host-list`, `meta` (sin valores).

Los simulacros con el codigo de recuperacion los hace el usuario en su terminal.
"""

from __future__ import annotations

import os

VERDADEROS = {"1", "si", "sí", "true", "yes", "on"}

# comandos que muestran el valor de un secreto (o lo dejan a mano)
PROHIBIDOS = {"get", "export",
              # A2 de la revision (2026-11-19): `shell` lleva get/export dentro;
              # `serve` es el puente por puerto (origen falsificable); `gui` no la
              # maneja un agente y su --selftest no pinta nada util.
              "shell", "serve", "gui"}

# comandos que existen pero cambian de comportamiento con el candado
CONDICIONADOS = {"describe": "describe --minimal"}

MENSAJE = ("COFRE_AGENT=1: '{comando}' muestra valores y un agente no debe usarlo. "
           "Ejecutalo tú en tu terminal{extra}.")


def activo() -> bool:
    """True si el entorno dice que quien llama es un agente."""
    return str(os.environ.get("COFRE_AGENT", "")).strip().lower() in VERDADEROS


CONFIRMACION = ("Con COFRE_AGENT=1, exec y run piden confirmación en la ventana de "
                "COFRE cada vez (sin permiso de 5 minutos). Sin la ventana abierta "
                "no se ejecuta.")


def confirmar_por_la_gui(comando, nombres: list[str], timeout_ms: int = 120_000) -> bool:
    """Preguntar a la ventana de COFRE por la tubería. Sin ventana, no.

    La ventana enseña el comando completo y qué secretos se inyectan. No se cachea
    nada: cada ejecución se confirma (lo pide D20 para los agentes).
    """
    from cofre import nmhost
    from cofre.redact import comando_visible
    mensaje = {"type": "exec-confirm", "command": comando_visible(comando),
               "secrets": list(nombres), "agent": True}
    try:
        respuesta = nmhost.forward(mensaje, reply_timeout_ms=timeout_ms)
    except Exception:                              # noqa: BLE001
        return False
    return bool(isinstance(respuesta, dict) and respuesta.get("ok")
                and respuesta.get("allowed"))


def motivo(args) -> str:
    """Devuelve el motivo del bloqueo, o "" si el comando puede pasar."""
    if not activo():
        return ""
    comando = str(getattr(args, "command", "") or "")

    if getattr(args, "recovery", False):
        return MENSAJE.format(comando=f"{comando} --recovery",
                              extra=" (el código de papel no lo maneja el agente)")
    if comando in PROHIBIDOS:
        return MENSAJE.format(comando=comando, extra="")
    if comando == "describe" and not getattr(args, "minimal", False):
        return MENSAJE.format(comando="describe",
                              extra="; usa `describe --minimal`, que no lleva urls")
    if comando == "add" and getattr(args, "value", None):
        # el valor en la linea de comandos queda en el historial y en el registro
        # del agente: se escribe a ciegas (sin argumento) o con --from-file
        return ("COFRE_AGENT=1: no pases el valor como argumento (queda en el "
                "historial). Escribe `add NOMBRE` y pégalo cuando lo pida, o usa "
                "--from-file.")
    if comando == "log" and getattr(args, "reanchor", False):
        return ("COFRE_AGENT=1: re-anclar el registro es cosa del usuario, a mano y "
                "con motivo.")
    return ""
