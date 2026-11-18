"""COFRE - a que dominio pertenece cada secreto (R1, 2026-11-16).

Antes la extension llevaba una lista plana de dominios y, si el sitio no estaba,
pedia un segundo clic. Eso es exactamente lo que hace la victima de un phishing:
la proteccion se quedaba en un aviso. Ademas la lista era global, asi que el
token de GitHub se podia rellenar en Cloudflare.

Ahora:
  - la lista es POR SECRETO y vive junto al cofre (`.cofre-hosts.json`);
  - si un secreto no tiene dominio asignado, no se rellena en ningun sitio;
  - si el dominio no coincide, se rechaza sin preguntar;
  - solo se asigna desde la GUI o desde la CLI con el cofre abierto
    (paso 4.6: "Asignar este sitio a X").

Formato del fichero (nombre de host, sin esquema, sin rutas):

    {"GITHUB_TOKEN": ["github.com"],
     "TAVILY_API_KEY": ["tavily.com", "*.tavily.com"]}
"""

from __future__ import annotations

import json
from pathlib import Path

from cofre.paths import atomic_write, hosts_path


class HostsError(ValueError):
    pass


def load(vault_path: str | Path) -> dict[str, list[str]]:
    p = hosts_path(vault_path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HostsError(f"no se puede leer {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise HostsError(f"{p} no tiene la forma esperada")
    out: dict[str, list[str]] = {}
    for name, hosts in data.items():
        if isinstance(hosts, list):
            out[str(name)] = [str(h) for h in hosts]
    return out


def save(vault_path: str | Path, mapping: dict[str, list[str]]) -> Path:
    return atomic_write(hosts_path(vault_path), json.dumps(mapping, indent=2, sort_keys=True))


def clean_host(value: str) -> str:
    """Validar lo que se asigna: nombre de host, sin esquema, sin barra, minusculas."""
    host = str(value).strip().lower().rstrip(".")
    if not host:
        raise HostsError("host vacio")
    if "://" in host or "/" in host or " " in host:
        raise HostsError(f"'{value}' no es un nombre de host: sin http://, sin barras")
    if host != "*" and not all(c.isalnum() or c in ".-*" for c in host):
        raise HostsError(f"'{value}' tiene caracteres que no van en un host")
    return host


def assign(vault_path: str | Path, name: str, hosts: list[str]) -> dict[str, list[str]]:
    """Asignar la lista completa de dominios de un secreto (reemplaza)."""
    mapping = load(vault_path)
    limpios = [clean_host(h) for h in hosts]
    if limpios:
        mapping[name] = limpios
    else:
        mapping.pop(name, None)
    save(vault_path, mapping)
    return mapping


def hosts_for(vault_path: str | Path, name: str) -> list[str]:
    return load(vault_path).get(name, [])


def host_matches(page_host: str, patterns: list[str]) -> bool:
    """Coincidencia estricta: el host de la pagina debe ser igual a un patron,
    o subdominio suyo. `github.com.evil.co` NO coincide con `github.com`."""
    host = str(page_host or "").strip().lower().rstrip(".")
    if not host:
        return False
    for pattern in patterns:
        pat = str(pattern).strip().lower().rstrip(".")
        if not pat:
            continue
        if pat.startswith("*."):
            base = pat[2:]
            if host == base or host.endswith("." + base):
                return True
            continue
        if host == pat or host.endswith("." + pat):
            return True
    return False


def allows(vault_path: str | Path, name: str, page_host: str) -> tuple[bool, str]:
    """(permitido, motivo). Sin asignacion no se permite nada."""
    patterns = hosts_for(vault_path, name)
    if not patterns:
        return False, f"'{name}' no tiene ningún sitio asignado"
    if not host_matches(page_host, patterns):
        return False, f"'{page_host}' no está asignado a '{name}'"
    return True, ""
