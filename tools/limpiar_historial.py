"""COFRE - limpiar del historial los logs que se colaron (2026-11-19).

En el commit `4766a45` entraron `.cofre-audit.jsonl` y
`.cofre-access-v1-hasta-2026-11-16.log`; salieron en `04a0051`, pero siguen en el
historial. Llevan **nombres** de secretos y detalles de eventos (nunca valores),
así que antes de subir el repo a un remoto hay que quitarlos de todos los commits.

  python tools/limpiar_historial.py --ensayo    (por defecto: clona y prueba)
  python tools/limpiar_historial.py --aplicar   (reescribe el repo de verdad)

Reglas:

  - `--ensayo` trabaja sobre un clon en un directorio temporal y no toca el repo;
  - `--aplicar` exige que exista el bundle de seguridad y lo dice antes de empezar;
  - se comprueba antes y después: los blobs no están, el número de commits se
    mantiene (salvo los que se queden vacíos) y `git fsck` no se queja;
  - no se toca ningún fichero de trabajo: es solo historial.

Ojo: después de aplicarlo, **todos los hashes cambian**. Los que estén escritos en
las notas (plan, estado) pasan a ser históricos.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLE = REPO.parent / "cofre-antes-de-limpiar-2026-11-19.bundle"
RUTAS = [".cofre-audit.jsonl", ".cofre-access-v1-hasta-2026-11-16.log"]


def git(carpeta: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(carpeta), capture_output=True,
                          text=True, timeout=600)
    return (proc.stdout or "") + (proc.stderr or "")


def blobs(carpeta: Path) -> list[str]:
    salida = git(carpeta, "rev-list", "--objects", "--all")
    return [ln for ln in salida.splitlines()
            if any(ruta in ln for ruta in RUTAS)]


def commits(carpeta: Path) -> int:
    salida = git(carpeta, "rev-list", "--all", "--count").strip()
    return int(salida) if salida.isdigit() else 0


def reescribir(carpeta: Path) -> str:
    """Quita las dos rutas de todos los commits y tira las copias de seguridad."""
    filtro = ("git rm -r --cached --ignore-unmatch -- "
              + " ".join(f'"{r}"' for r in RUTAS))
    env = dict(os.environ, FILTER_BRANCH_SQUELCH_WARNING="1")
    proc = subprocess.run(
        ["git", "filter-branch", "--force", "--index-filter", filtro,
         "--prune-empty", "--tag-name-filter", "cat", "--", "--all"],
        cwd=str(carpeta), capture_output=True, text=True, timeout=1800, env=env)
    salida = (proc.stdout or "") + (proc.stderr or "")
    # filter-branch deja refs/original con el historial viejo: si no se borran,
    # los blobs siguen alcanzables y `rev-list --all` los encuentra.
    for linea in git(carpeta, "for-each-ref", "--format=%(refname)",
                     "refs/original").splitlines():
        linea = linea.strip()
        if linea:
            git(carpeta, "update-ref", "-d", linea)
    git(carpeta, "reflog", "expire", "--expire=now", "--all")
    git(carpeta, "gc", "--prune=now", "--quiet")
    return salida


def informe(carpeta: Path, etiqueta: str) -> bool:
    quedan = blobs(carpeta)
    total = commits(carpeta)
    fsck = git(carpeta, "fsck", "--no-progress")
    limpio = not quedan
    print(f"{etiqueta}: {total} commits, "
          f"{'historial limpio' if limpio else f'{len(quedan)} blob(s) con logs'}")
    if not limpio:
        for linea in quedan[:5]:
            print("   queda:", linea[:90])
    if fsck.strip() and ("error" in fsck.lower() or "corrupt" in fsck.lower()):
        print("   fsck:", fsck.strip().splitlines()[0][:90])
    return limpio


def ensayo() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cofre-historial-"))
    clon = tmp / "cofre"
    try:
        print(f"ensayo en {clon}")
        git(tmp, "clone", "--quiet", str(REPO), str(clon))
        antes = commits(clon)
        if informe(clon, "antes"):
            print("   (el repo ya estaba limpio)")
            return 0
        reescribir(clon)
        sano = informe(clon, "despues")
        if commits(clon) != antes:
            print(f"   aviso: commits {antes} -> {commits(clon)} "
                  "(los vacios se podan: es normal)")
        print("ENSAYO OK" if sano else "ENSAYO FALLO")
        return 0 if sano else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def aplicar() -> int:
    if not BUNDLE.exists():
        print(f"falta el bundle de seguridad: {BUNDLE}")
        print("crealo antes:  git bundle create ../<nombre>.bundle --all")
        return 2
    print(f"bundle de seguridad: {BUNDLE}")
    informe(REPO, "antes")
    reescribir(REPO)
    sano = informe(REPO, "despues")
    if sano:
        print("historial limpio. Todos los hashes anteriores han cambiado.")
        print("Revisa que las pruebas siguen en verde y sigue con el remoto.")
        return 0
    print("NO ha quedado limpio: restaura con el bundle y avisa.")
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--aplicar" in argv:
        return aplicar()
    return ensayo()


if __name__ == "__main__":
    raise SystemExit(main())
