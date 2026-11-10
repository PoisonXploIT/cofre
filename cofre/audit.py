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
