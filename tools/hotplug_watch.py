"""Vigilar la aparicion/desaparicion de pendrives COFRE.KEY (prueba del polling 1.3).

Uso:
  python tools/hotplug_watch.py [segundos]
Imprime cada 2 s el conjunto de volumenes con COFRE.KEY. Siraba para comprobar
que la GUI reacciona cuando se enchufa o se desenchufa un USB sin tocar
Reconectar.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.usb import KEY_FILENAME, drive_letters, volume_serial


def snapshot() -> list[tuple[str, int | None]]:
    out = []
    for drive in drive_letters():
        if (Path(drive) / KEY_FILENAME).is_file():
            out.append((drive, volume_serial(drive)))
    return sorted(out)


def main() -> int:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    prev = snapshot()
    print(f"{time.strftime('%H:%M:%S')} inicial: {prev}")
    for _ in range(seconds // 2):
        time.sleep(2)
        now = snapshot()
        if now != prev:
            added = [d for d, _ in now if d not in [p[0] for p in prev]]
            removed = [d for d, _ in prev if d not in [p[0] for p in now]]
            print(f"{time.strftime('%H:%M:%S')} CAMBIO  +{added} -{removed}  ahora: {now}")
            prev = now
        else:
            print(f"{time.strftime('%H:%M:%S')} sin cambio: {prev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
