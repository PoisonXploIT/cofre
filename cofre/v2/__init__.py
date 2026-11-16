"""COFRE v2: formato con slots por pendrive e indice cifrado (fase 1 del plan).

Diferencias con v1:
  - el indice (nombres, etiquetas, dominios asignados) va CIFRADO dentro del
    cofre, no en un fichero aparte en claro (D10);
  - cada pendrive tiene su PROPIA llave de 32 bytes y su slot en cofre.json;
    revocar un pendrive es borrar su slot, sin tocarlo (D11);
  - hay un slot de recuperacion con un codigo de 24 palabras + palabra de control.
"""

from cofre.v2.slots import (  # noqa: F401
    SlotError, new_recovery_slot, new_usb_slot, open_with_recovery,
    open_with_stick, try_open_slot,
)
from cofre.v2.vault import VaultV2  # noqa: F401
