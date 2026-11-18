"""COFRE - ajustes no secretos en cofre-settings.json (paso 6.7).

El fichero vive junto al cofre y no lleva nada cifrado ni sensible: tiempos de
bloqueo, portapapeles, navegador, generador, carpeta de copias y umbrales de
alerta. La seccion `alerts` la escribe `cofre.alerts`; aqui se conserva.

La version de la aplicacion tambien vive aqui para que la pantalla Acerca de no
tenga que inventarla.
"""

from __future__ import annotations

import json
from pathlib import Path

from cofre import __version__
from cofre.paths import atomic_write

NAME = "cofre-settings.json"
# una sola fuente: cofre/__init__.py
VERSION = __version__

DEFAULTS = {
    "idle_minutes": 10,       # 1..240
    "max_hours": 8,           # 1..72
    "clipboard_seconds": 30,  # 0 = no borrar solo
    "reveal_seconds": 15,
    "bridge_on_start": False,
    "gen_profile": "machine",  # machine | human
    "gen_words": 6,
    "gen_lang": "es",          # es | en
    "backup_folder": "",
}


def path_for(vault_path: str | Path) -> Path:
    return Path(vault_path).parent / NAME


def _leer(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return datos if isinstance(datos, dict) else {}


def load(vault_path: str | Path) -> dict:
    cfg = dict(DEFAULTS)
    datos = _leer(path_for(vault_path))
    gui = datos.get("gui")
    if isinstance(gui, dict):
        for clave, valor in gui.items():
            if clave in DEFAULTS:
                cfg[clave] = valor
    elif any(clave in datos for clave in DEFAULTS):
        # compatibilidad: si alguien dejo los ajustes en la raiz
        for clave in DEFAULTS:
            if clave in datos:
                cfg[clave] = datos[clave]
    return cfg


def save(vault_path: str | Path, valores: dict) -> Path:
    p = path_for(vault_path)
    datos = _leer(p)
    gui = datos.get("gui") if isinstance(datos.get("gui"), dict) else {}
    gui.update({k: v for k, v in valores.items() if k in DEFAULTS})
    datos["gui"] = gui
    return atomic_write(p, json.dumps(datos, indent=2, sort_keys=True))


def clamp(cfg: dict) -> dict:
    """Valores dentro de limites razonables; la GUI no debe poder dejarse fuera."""
    salida = dict(cfg)
    salida["idle_minutes"] = max(1, min(240, int(cfg.get("idle_minutes", 10))))
    salida["max_hours"] = max(1, min(72, int(cfg.get("max_hours", 8))))
    salida["clipboard_seconds"] = max(0, min(600, int(cfg.get("clipboard_seconds", 30))))
    salida["reveal_seconds"] = max(3, min(120, int(cfg.get("reveal_seconds", 15))))
    salida["gen_words"] = max(4, min(8, int(cfg.get("gen_words", 6))))
    salida["gen_lang"] = "en" if str(cfg.get("gen_lang")) == "en" else "es"
    salida["gen_profile"] = ("human" if str(cfg.get("gen_profile")) == "human"
                             else "machine")
    salida["bridge_on_start"] = bool(cfg.get("bridge_on_start"))
    salida["backup_folder"] = str(cfg.get("backup_folder") or "")
    return salida
