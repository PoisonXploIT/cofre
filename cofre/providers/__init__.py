"""Proveedores de rotación (fase 5)."""

from cofre.providers.base import REGISTRY, Provider, get, register  # noqa: F401
from cofre.providers.http import ProviderError  # noqa: F401
from cofre.providers.cloudflare import CLOUDFLARE  # noqa: F401
from cofre.providers.github import GITHUB  # noqa: F401,E402
from cofre.providers.generic import GENERICO, conocido  # noqa: F401,E402
