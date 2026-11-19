"""COFRE - fachada de almacenamiento (plan 1.9).

Detecta el formato del cofre y devuelve un objeto con la misma API que la clase
Vault de v1, para que CLI, GUI y puente no tengan que saber en que formato esta:

    data = open_any(path).load()      # dict en crudo
    store = open_any(path, session=session, material=material)
    store.get(name)  store.add(name, value)  store.names()  store.meta(name)

El adaptador de v2 ignora `session`: trabaja con la clave maestra ya abierta.
Los dominios asignados, en v2, viven dentro del indice cifrado (D10).
"""

from __future__ import annotations

from pathlib import Path

from cofre.crypto import Vault
from cofre.v2.slots import SlotError, open_with_recovery, open_with_stick
from cofre.v2.vault import VaultV2


class StoreError(RuntimeError):
    pass


class V1Store:
    """Formato v1 (wrapper unico + entradas sueltas)."""

    format = 1

    def __init__(self, path: str | Path, session: bytes | None = None):
        self.path = Path(path)
        self._vault = Vault(self.path)
        self._session = session
        self._data = self._vault.load()
        self.master = None

    def load(self) -> dict:
        return self._vault.load()

    def save(self, data: dict) -> None:
        self._vault.save(data)

    def init(self, salt: bytes | None = None) -> None:
        self._vault.init(self._session, salt=salt)

    def unlock(self) -> bytes:
        self.master = self._vault.unlock(self._session)
        return self.master

    def get(self, name: str) -> str:
        return self._vault.get(self._session, name)

    def add(self, name: str, value: str, tags: list[str] | None = None,
            urls: list[str] | None = None) -> None:
        self._vault.add(self._session, name, value, tags)
        if urls:
            self.set_urls(name, urls)

    def delete(self, name: str) -> bool:
        return self._vault.delete(self._session, name)

    def rename(self, old: str, new: str) -> bool:
        return self._vault.rename(self._session, old, new)

    def names(self) -> list[str]:
        return self._vault.names()

    def meta(self, name: str) -> dict:
        return self._vault.meta(name)

    def urls(self, name: str) -> list[str]:
        # v1 no tiene indice cifrado: los dominios estaban en .cofre-hosts.json
        from cofre import hosts
        try:
            return hosts.hosts_for(self.path, name)
        except hosts.HostsError:
            return []

    def set_urls(self, name: str, urls: list[str]) -> None:
        from cofre import hosts
        hosts.assign(self.path, name, urls)


class V2Store:
    """Formato v2: indice cifrado, slots por pendrive, dominios dentro."""

    format = 2

    def __init__(self, path: str | Path, material: dict | None = None,
                 recovery_code: str | None = None):
        self.path = Path(path)
        self._vault = VaultV2(self.path)
        self._data = self._vault.load()
        self.master: bytes | None = None
        self.slot: dict | None = None
        if material and material.get("stick_key"):
            self.master, self.slot = open_with_stick(
                self._data, material["stick_key"], int(material["serial"]),
                material.get("pin", ""))
        elif recovery_code:
            self.master, self.slot = open_with_recovery(self._data, recovery_code)

    def load(self) -> dict:
        return self._data

    def index(self, data: dict, master: bytes) -> dict:
        return self._vault.index(data, master)

    def _write_index(self, data: dict, master: bytes, idx: dict) -> None:
        self._vault._write_index(data, master, idx)

    def refresh(self) -> None:
        """Releer el fichero. La GUI mantiene el cofre en memoria y un cambio
        hecho desde la CLI (asignar dominios, anadir un secreto) no se veria."""
        self._data = self._vault.load()

    def save(self, data: dict | None = None) -> None:
        self._data = data or self._data
        self._vault.save(self._data)

    def init(self, salt: bytes | None = None) -> None:
        raise StoreError("v2 se crea con migrate, no con init")

    def unlock(self) -> bytes:
        if self.master is None:
            raise StoreError("el cofre v2 necesita la llave del pendrive o el código")
        return self.master

    def _need(self) -> bytes:
        if self.master is None:
            raise StoreError("cofre v2 abierto sin sesión")
        return self.master

    def get(self, name: str) -> str:
        return self._vault.get(self._data, self._need(), name)

    def add(self, name: str, value: str, tags: list[str] | None = None,
            urls: list[str] | None = None, kind: str | None = None) -> None:
        self._vault.put(self._data, self._need(), name, value, tags=tags, urls=urls, kind=kind)
        self._vault.save(self._data)

    def delete(self, name: str) -> bool:
        ok = self._vault.delete(self._data, self._need(), name)
        if ok:
            self._vault.save(self._data)
        return ok

    def rename(self, old: str, new: str) -> bool:
        ok = self._vault.rename(self._data, self._need(), old, new)
        if ok:
            self._vault.save(self._data)
        return ok

    def names(self) -> list[str]:
        if self.master is None:
            return []
        return self._vault.names(self._data, self.master)

    def meta(self, name: str) -> dict:
        if self.master is None:
            return {}
        return self._vault.meta(self._data, self.master, name)

    def urls(self, name: str) -> list[str]:
        if self.master is None:
            return []
        return self._vault.urls(self._data, self.master, name)

    def set_urls(self, name: str, urls: list[str]) -> None:
        self._vault.set_urls(self._data, self._need(), name, urls)
        self._vault.save(self._data)


def detect_format(data: dict) -> int:
    if isinstance(data, dict) and data.get("format") == 2:
        return 2
    return 1


def open_any(path: str | Path, session: bytes | None = None,
             material: dict | None = None, recovery_code: str | None = None):
    p = Path(path)
    try:
        import json
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    if detect_format(data) == 2:
        return V2Store(p, material=material, recovery_code=recovery_code)
    return V1Store(p, session=session)
