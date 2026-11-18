"""Sonda del escaner de fugas (paso 3.4, hecho el 2026-11-18).

  python tools/leak_probe.py

Con un cofre falso (tools/tmpvault.py) y carpetas de prueba:

  1. una carpeta con un secreto pegado devuelve codigo 1 y lo nombra;
  2. el valor no aparece en la salida;
  3. una carpeta limpia devuelve 0;
  4. el gancho de pre-commit se instala, **para** un commit con fuga y deja pasar
     uno limpio;
  5. el gancho se puede quitar.

No toca el cofre real ni el pendrive.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import tmpvault                                    # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    RESULTS.append((nombre, bool(ok), detalle))
    print(f"{'OK   ' if ok else 'FALLO'}  {nombre}  {detalle}")


def main() -> int:
    if shutil.which("git") is None:
        print("sin git: sonda omitida")
        return 0
    vault, llave, tmp = tmpvault.cofre_temporal()
    entorno = dict(os.environ, COFRE_VAULT=str(vault), COFRE_GATE="usb",
                   COFRE_STICK=str(llave), GIT_AUTHOR_NAME="sonda",
                   GIT_AUTHOR_EMAIL="sonda@local", GIT_COMMITTER_NAME="sonda",
                   GIT_COMMITTER_EMAIL="sonda@local")
    base = [sys.executable, "-m", "cofre.cli", "--vault", str(vault),
            "--stick", str(llave)]

    def correr(*args, cwd=None):
        return subprocess.run(base + list(args), capture_output=True, text=True,
                              env=entorno, cwd=cwd, timeout=180)

    # 1. carpeta con fuga
    sucia = tmp / "sucia"
    (sucia / "sub").mkdir(parents=True)
    (sucia / "sub" / "config.env").write_text("NORMAL=1\nCF=valor-de-prueba\n",
                                              encoding="utf-8")
    (sucia / "notas.txt").write_text("nada\nSIMULACRO=restauracion-ok-42\n",
                                     encoding="utf-8")
    proc = correr("scan", str(sucia))
    check("1. encuentra los secretos pegados", proc.returncode == 1
          and "CF_TEST_TOKEN" in proc.stdout and "SIMULACRO_RESTAURA" in proc.stdout,
          f"rc={proc.returncode}")
    check("1b. dice fichero y línea",
          "config.env:2" in proc.stdout and "notas.txt:2" in proc.stdout,
          proc.stdout.strip().splitlines()[1][:70] if proc.stdout else "")
    check("2. el valor no sale en la salida",
          "valor-de-prueba" not in proc.stdout
          and "restauracion-ok-42" not in proc.stdout, "")

    # 2. JSON para maquinas
    proc = correr("scan", str(sucia), "--json")
    check("2b. salida JSON sin valores",
          '"count": 2' in proc.stdout and "valor-de-prueba" not in proc.stdout,
          proc.stdout.strip().splitlines()[1][:60] if proc.stdout else "")

    # 3. carpeta limpia
    limpia = tmp / "limpia"
    limpia.mkdir()
    (limpia / "app.py").write_text("print('hola')\n", encoding="utf-8")
    proc = correr("scan", str(limpia))
    check("3. una carpeta limpia devuelve 0", proc.returncode == 0,
          proc.stdout.strip()[:70])

    # 4. gancho de pre-commit
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], capture_output=True, timeout=60)
    proc = correr("scan", "--install-hook", str(repo))
    gancho = repo / ".git" / "hooks" / "pre-commit"
    check("4. instala el gancho", proc.returncode == 0 and gancho.exists(),
          str(gancho) if gancho.exists() else proc.stderr[-80:])

    (repo / "fuga.env").write_text("CF=valor-de-prueba\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "fuga.env"], capture_output=True,
                   timeout=60)
    commit = subprocess.run(["git", "-C", str(repo), "commit", "-m", "fuga"],
                            capture_output=True, text=True, env=entorno, timeout=180)
    check("4b. el commit con fuga se para",
          commit.returncode != 0
          and "CF_TEST_TOKEN" in (commit.stdout + commit.stderr),
          f"rc={commit.returncode}")
    check("4c. el mensaje del gancho no lleva el valor",
          "valor-de-prueba" not in (commit.stdout + commit.stderr), "")

    (repo / "fuga.env").write_text("CF=nada\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "fuga.env"], capture_output=True,
                   timeout=60)
    commit = subprocess.run(["git", "-C", str(repo), "commit", "-m", "limpio"],
                            capture_output=True, text=True, env=entorno, timeout=180)
    check("4d. el commit limpio pasa", commit.returncode == 0,
          commit.stdout.strip().splitlines()[-1][:60] if commit.stdout else "")

    # 5. quitar el gancho
    proc = correr("scan", "--uninstall-hook", str(repo))
    check("5. se puede quitar el gancho", proc.returncode == 0 and not gancho.exists(),
          proc.stdout.strip()[:60])

    # 6. sin pendrive no inventa: codigo 2 y lo dice
    entorno_sin = dict(entorno)
    entorno_sin.pop("COFRE_STICK", None)
    proc = subprocess.run([sys.executable, "-m", "cofre.cli", "--vault", str(vault),
                           "--gate", "usb", "scan", str(limpia)],
                          capture_output=True, text=True, env=entorno_sin, timeout=180)
    check("6. sin la llave no escanea y avisa", proc.returncode == 2,
          proc.stderr.strip().splitlines()[-1][:80] if proc.stderr else "")

    shutil.rmtree(tmp, ignore_errors=True)
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
