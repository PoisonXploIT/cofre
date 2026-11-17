"""Un solo comando para pasar todas las sondas (paso 8.1 del plan).

  python tools/run_all_probes.py

Cada sonda se ejecuta aislada, con tope de tiempo, y se resume el resultado.
Las sondas que necesitan hardware (pendrive) o navegador se marcan como
opcionales y su fallo no tumba el conjunto: se avisa y se sigue.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PROBES = [
    ("backup_restore", [sys.executable, "tools/backup_restore_probe.py"], True),
    ("unittest", [sys.executable, "-m", "unittest", "discover", "-s", "tests"], False),
    ("hardening", [sys.executable, "tools/hardening_probe.py"], False),
    ("gui_shortcut", [sys.executable, "tools/gui_shortcut_probe.py"], False),
    ("gui_audit", [sys.executable, "tools/gui_audit_probe.py"], False),
    ("dark_bar", [sys.executable, "tools/dark_bar_probe.py"], False),
    ("stick_register", [sys.executable, "tools/stick_register_probe.py"], False),
    ("pipe", [sys.executable, "tools/pipe_probe.py"], False),
    ("pipe_server", [sys.executable, "tools/pipe_server_probe.py"], False),
    ("confirm", [sys.executable, "tools/confirm_probe.py"], False),
    ("serve", [sys.executable, "tools/serve_probe.py"], False),
    ("extension", ["node", "tools/extension_fill_test.mjs"], True),
]


def main() -> int:
    fallos: list[str] = []
    for nombre, cmd, opcional in PROBES:
        inicio = time.time()
        try:
            proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True,
                                  text=True, timeout=300)
            ok = proc.returncode == 0
            salida = (proc.stdout or "").strip().splitlines()
        except FileNotFoundError:
            ok, salida = False, ["no se encontro el ejecutable"]
        except subprocess.TimeoutExpired:
            ok, salida = False, ["tiempo agotado"]
        segundos = time.time() - inicio
        etiqueta = "OK   " if ok else ("AVISO" if opcional else "FALLO")
        print(f"{etiqueta} {nombre:16} {segundos:5.1f}s  {salida[-1] if salida else ''}")
        if not ok and not opcional:
            fallos.append(nombre)
    print("")
    if fallos:
        print("sondas obligatorias fallidas: " + ", ".join(fallos))
        return 1
    print("todas las sondas obligatorias OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
