"""Cofre - log de accesos.

Se anota CUANDO, QUE gate, QUE pendrive (por serial) y QUE secreto, nunca el
valor del secreto. El fichero vive junto al cofre y esta en .gitignore.

Rotacion: el log se recorta a MAX_LINES entradas (por defecto 500). Las entradas
que salen se escriben en .cofre-access.log.old, que se borra al alcanzar
OLD_MAX. No es un log antimaniipulacion: quien tenga la maquina puede borrarlo.
Su utilidad es de deteccion y depuracion.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

LOG_NAME = ".cofre-access.log"
OLD_NAME = ".cofre-access.log.old"
MAX_LINES = 500
OLD_MAX_LINES = 2000


def log_path(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / LOG_NAME


def _prune(path: Path, max_lines: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_lines:
        return
    overflow = lines[:-max_lines]
    old = path.with_suffix(".log.old") if path.name.endswith(".log") else Path(str(path) + ".old")
    prev = old.read_text(encoding="utf-8").splitlines() if old.exists() else []
    merged = (prev + overflow)[-OLD_MAX_LINES:]
    old.write_text("\n".join(merged) + "\n", encoding="utf-8")
    path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def record(vault_path: str | Path, command: str, gate: str,
           serial: int | None = None, name: str | None = None,
           ok: bool = True, detail: str = "") -> Path:
    line = (
        f"{datetime.now().isoformat(timespec='seconds')} "
        f"cmd={command} gate={gate} stick={serial if serial is not None else '-'} "
        f"name={name or '-'} ok={1 if ok else 0}"
    )
    if detail:
        line += f" detail={detail}"
    p = log_path(vault_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    _prune(p, MAX_LINES)
    return p


def tail(vault_path: str | Path, lines: int = 20) -> list[str]:
    p = log_path(vault_path)
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8").splitlines()[-lines:]


VERBS = {
    "add": "guardado",
    "get": "leido",
    "reveal": "mostrado en pantalla",
    "clipboard": "copiado al portapapeles",
    "del": "borrado",
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
    "stick-role": "rol de pendrive cambiado",
}


def tail_human(vault_path: str | Path, lines: int = 6) -> list[str]:
    """Las mismas entradas del log, pero legibles para una persona."""
    out = []
    for line in tail(vault_path, lines):
        parts = line.split()
        if not parts:
            continue
        stamp = parts[0][11:16] if len(parts[0]) > 11 else parts[0]
        fields = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in parts[1:] if "=" in p}
        cmd = fields.get("cmd", "?")
        name = fields.get("name", "-")
        stick = fields.get("stick", "-")
        ok = "ok" if fields.get("ok") == "1" else "FALLO"
        verb = VERBS.get(cmd, cmd)
        extra = name if name not in ("-",) else ""
        out.append(f"{stamp}  {verb} {extra}  [{ok}]  llave {stick}")
    return out


def stats(vault_path: str | Path) -> dict:
    p = log_path(vault_path)
    if not p.exists():
        return {"entradas": 0, "archivo": str(p)}
    lines = p.read_text(encoding="utf-8").splitlines()
    fails = sum(1 for l in lines if " ok=0" in l)
    sticks = {l.split(" stick=")[1].split(" ")[0] for l in lines if " stick=" in l}
    return {"entradas": len(lines), "fallos": fails, "pendrives_usados": sorted(sticks),
            "archivo": str(p), "max": MAX_LINES}


def vault_from_env() -> Path:
    return Path(os.environ.get("COFRE_VAULT", Path.home() / "AI" / "cofre" / "cofre.json"))
