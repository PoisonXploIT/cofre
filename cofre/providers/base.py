"""COFRE - interfaz de proveedores (paso 5.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VerifyResult:
    ok: bool
    expires_at: str = ""
    detail: str = ""


class Provider:
    name = "base"
    can_auto_rotate = False

    def verify(self, value: str, meta: dict) -> VerifyResult:
        raise NotImplementedError

    def roll_value(self, token_id: str, admin_value: str, meta: dict) -> str:
        """Variante A: mismo token, valor nuevo."""
        raise NotImplementedError

    def create_replacement(self, meta: dict, admin_value: str) -> tuple[str, dict]:
        """Variante B: token nuevo equivalente. Devuelve (valor, provider_ref)."""
        raise NotImplementedError

    def revoke(self, token_id: str, admin_value: str, meta: dict) -> None:
        raise NotImplementedError

    def manual_url(self, meta: dict) -> str:
        return ""


REGISTRY: dict[str, Provider] = {}


def register(provider: Provider) -> Provider:
    REGISTRY[provider.name] = provider
    return provider


def get(name: str) -> Provider:
    if name not in REGISTRY:
        raise KeyError(f"proveedor desconocido: {name}")
    return REGISTRY[name]
