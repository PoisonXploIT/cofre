"""Regresion del generador y del fallback sin wordlist.

Comprueba lo que fallo el 2026-11-13: con la lista de palabras ausente,
`entropy()` devolvia un dict sin 'bits_por_palabra' y la GUI petaba con
KeyError al pulsar los botones de idioma.

Uso: python tools/gen_probe.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import cofre.gen as gen

CLAVES = {"palabras", "lista", "bits", "bits_por_palabra", "aviso"}


def main() -> int:
    failures = 0

    def check(label, cond, extra=""):
        nonlocal failures
        print(f"{'OK   ' if cond else 'FALLO'} {label} {extra}")
        if not cond:
            failures += 1

    # 1. con lista
    info = gen.entropy(words=6, lang="es")
    check("con lista: mismas claves", CLAVES <= set(info), sorted(info))
    check("con lista: 2000 palabras", info["lista"] == 2000, info["lista"])
    check("con lista: 6 palabras = 66.8 bits", abs(info["bits"] - 66.8) < 0.2, info["bits"])

    # 2. sin lista (se aparta la carpeta data durante la prueba)
    data = REPO / "cofre" / "data"
    backup = REPO / "cofre" / "data__probe_off"
    moved = False
    try:
        if data.exists():
            data.rename(backup)
            moved = True
        info2 = gen.entropy(words=6, lang="es")
        check("sin lista: mismas claves", CLAVES <= set(info2), sorted(info2))
        check("sin lista: lista == 0", info2["lista"] == 0)
        check("sin lista: bits_por_palabra presente", info2["bits_por_palabra"] == 0.0)
        check("sin lista: aviso no vacio", bool(info2["aviso"]))
        words = gen.human_password(words=5)
        check("sin lista: genera igual", bool(words) and len(words) >= 6, words)
    finally:
        if moved:
            backup.rename(data)

    # 3. con lista restaurada
    info3 = gen.entropy(words=4, lang="en")
    check("restaurada: 2000 palabras", info3["lista"] == 2000, info3["lista"])
    pw = gen.human_password(words=4, lang="en")
    check("genera passphrase", len(pw) > 8 and pw[-1].isdigit(), pw)
    check("maquina: 64 caracteres", len(gen.machine_password()) >= 60)

    print()
    print("TODO OK" if not failures else f"{failures} fallo(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
