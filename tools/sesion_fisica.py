#!/usr/bin/env python
r"""COFRE - lanzador de la sesion fisica (la logica vive en cofre/sesion_fisica.py).

  python tools/sesion_fisica.py [--carpeta D:\Cofre] [--comprobar]
  run.cmd sesion
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cofre.sesion_fisica import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
