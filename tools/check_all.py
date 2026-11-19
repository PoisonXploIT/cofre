"""COFRE - comprobacion completa antes de decir "hecho" (paso 8.1).

  python tools/check_all.py            # todo
  python tools/check_all.py --solo escaneo

Pasos, en orden:

  1. pruebas         unittest de tests/
  2. selftest        `gui --selftest` (la ventana se construye sin error)
  3. layout          tools/layout_check.py (nada fuera de su padre)
  4. tema            tools/theme_check.py (tokens de color y tamanos)
  5. log temporal    `log verify` sobre un cofre temporal, no el real
  6. escaneo         el repo (solo lo versionado) no lleva secretos con pinta real

El cofre real y el pendrive no se tocan: lo que necesita llave usa
tools/tmpvault.py. Sale 1 si algo falla.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

PY = sys.executable

# Lo que de verdad no puede estar en el repo. Nada generico: una cadena de 40
# caracteres puede ser un hash, y eso solo genera ruido.
PATRONES = [
    ("token de GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("clave privada", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("clave de AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token de Slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("token de Google", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")),
]

# Sitios donde un valor de prueba es esperado y no es un secreto real.
EXENTOS = {
    "tools/confirm_stress_probe.py": "valores de mentira del cofre falso",
    "tools/tmpvault.py": "cofre temporal de las sondas",
    "tests/test_git_helper.py": "credencial de mentira del ayudante",
}


def _decir(nombre: str, ok: bool, detalle: str = "", segundos: float = 0.0) -> bool:
    etiqueta = "OK   " if ok else "FALLO"
    print(f"{etiqueta}  {nombre:<12} {segundos:5.1f}s  {detalle}")
    return ok


def paso_proceso(nombre: str, cmd: list[str]) -> bool:
    inicio = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                              timeout=600)
        ok = proc.returncode == 0
        lineas = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
        detalle = lineas[-1] if lineas else (proc.stderr or "").strip()[-120:]
    except subprocess.TimeoutExpired:
        ok, detalle = False, "tiempo agotado"
    except FileNotFoundError as exc:
        ok, detalle = False, str(exc)
    return _decir(nombre, ok, " ".join(str(detalle).split())[:120],
                  time.time() - inicio)


def paso_log_temporal() -> bool:
    """`log verify` completo: escribir eventos y comprobar la cadena."""
    inicio = time.time()
    from cofre.audit import clear_key, record, set_key, verify
    import tmpvault

    try:
        vault, llave, tmp = tmpvault.cofre_temporal()
    except Exception as exc:                         # noqa: BLE001
        return _decir("log temporal", False, f"no se pudo crear: {exc}")
    try:
        master = b"k" * 32
        set_key(master)
        try:
            for i in range(3):
                record(vault, "get", "usb", 1, name=f"PRUEBA_{i}")
        finally:
            clear_key()
        ok, detalle = verify(str(vault))
        return _decir("log temporal", ok, str(detalle)[:110], time.time() - inicio)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _versionados() -> list[str]:
    proc = subprocess.run(["git", "ls-files"], cwd=str(REPO),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def paso_escaneo() -> bool:
    """Solo lo versionado: .venv y las copias locales no cuentan.

    Incluye la regla del 2026-11-19: 24 o más palabras seguidas de la lista del
    código de recuperación se tratan como fuga (un código pegado en el repo).
    """
    inicio = time.time()
    hallazgos: list[str] = []
    from cofre.leak import codigos_de_recuperacion
    ficheros = _versionados()
    for rel in ficheros:
        ruta = REPO / rel
        if not ruta.is_file():
            continue
        try:
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for linea, cuantas in codigos_de_recuperacion(texto):
            if rel not in EXENTOS:
                hallazgos.append(f"{rel}:{linea} código de recuperación "
                                 f"({cuantas} palabras de la lista)")
        for nombre, patron in PATRONES:
            for m in patron.finditer(texto):
                linea = texto[:m.start()].count("\n") + 1
                if rel in EXENTOS:
                    continue
                hallazgos.append(f"{rel}:{linea} {nombre}")
    ok = not hallazgos
    detalle = f"{len(ficheros)} ficheros versionados"
    if hallazgos:
        detalle = "; ".join(hallazgos[:3])
    return _decir("escaneo", ok, detalle[:120], time.time() - inicio)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    solo = ""
    if "--solo" in argv:
        i = argv.index("--solo")
        if i + 1 < len(argv):
            solo = argv[i + 1]

    pasos = {
        "pruebas": lambda: paso_proceso(
            "pruebas", [PY, "-m", "unittest", "discover", "-s", "tests"]),
        "selftest": lambda: paso_proceso(
            "selftest", [PY, "-m", "cofre.cli", "gui", "--selftest"]),
        "layout": lambda: paso_proceso(
            "layout", [PY, "tools/layout_check.py"]),
        "tema": lambda: paso_proceso(
            "tema", [PY, "tools/theme_check.py"]),
        "log temporal": paso_log_temporal,
        "escaneo": paso_escaneo,
    }
    if solo:
        elegidos = {solo: pasos[solo]} if solo in pasos else {}
        if not elegidos:
            print(f"no existe el paso '{solo}'. Hay: {', '.join(pasos)}")
            return 2
    else:
        elegidos = pasos

    print(f"COFRE - comprobacion completa  ({REPO})")
    print("")
    resultados = [fn() for fn in elegidos.values()]
    print("")
    fallos = len([r for r in resultados if not r])
    if fallos:
        print(f"{fallos} paso(s) en rojo. No se dice 'hecho' hasta que esten en verde.")
        return 1
    print(f"{len(resultados)}/{len(resultados)} pasos en verde.")
    print("Falta lo que necesita hardware: log verify sobre el cofre real (M1), "
          "recordatorio (M2) y copia en D: (M3).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
