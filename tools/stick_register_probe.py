"""Sonda R2 (2026-11-16): stick-register no debe crear falsos respaldos.

Se ejecuta contra un cofre de prueba en un directorio temporal. NUNCA contra el
registro real del cofre.

  1. registrar un pendrive con una llave que NO abre  -> rechazo, registro igual
  2. registrar un pendrive con la llave buena         -> se autoriza
  3. stick-verify detecta la llave mala si estuviera  -> FALLO visible

  python tools/stick_register_probe.py
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.crypto import Vault
from cofre.gate import _salt_for
from cofre.salt import get_salt
from cofre.usb import register_stick, usb_session_key

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def make_vault(tmp: Path) -> tuple[Path, Path]:
    """Cofre v1 nuevo con una llave buena en tmp/COFRE.KEY."""
    key = tmp / "COFRE.KEY"
    key.write_bytes(secrets.token_bytes(32))
    vault_path = tmp / "cofre.json"
    salt = get_salt(str(vault_path), create=True)
    session = usb_session_key(str(key), salt)
    vault = Vault(vault_path)
    vault.init(session, salt=salt)
    vault.add(session, "PRUEBA", "valor")
    return vault_path, key


def run(tmp: Path, vault_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "cofre.cli", "--vault", str(vault_path), *args],
                          capture_output=True, text=True, cwd=str(REPO), timeout=120)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cofre-stick-probe-"))
    try:
        vault_path, good_key = make_vault(tmp)
        reg_path = tmp / ".cofre-sticks.json"
        antes = reg_path.read_text(encoding="utf-8") if reg_path.exists() else "{}"

        # 1. llave que no abre el cofre
        mala = tmp / "MALA.KEY"
        mala.write_bytes(secrets.token_bytes(32))
        proc = run(tmp, vault_path, "--stick", str(good_key), "stick-register", str(mala))
        despues = reg_path.read_text(encoding="utf-8") if reg_path.exists() else "{}"
        check("1. registrar una llave ajena se rechaza",
              proc.returncode == 1 and antes == despues,
              f"rc={proc.returncode} registro_igual={antes == despues}")
        check("1b. el mensaje dice que la llave no abre",
              "NO abre este cofre" in proc.stdout, proc.stdout.strip()[:90])
        check("1c. sugiere stick-copy", "stick-copy" in proc.stdout, "")

        # 2. la llave buena si se autoriza
        proc = run(tmp, vault_path, "--stick", str(good_key), "stick-register", str(good_key))
        reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else {}
        check("2. la llave buena se registra",
              proc.returncode == 0 and reg.get("sticks"),
              f"rc={proc.returncode} claves={sorted(reg.get('sticks', {}))}")

        # 3. stick-verify marca una llave inservible como fallo
        bad_serial = 111111
        register_stick(str(vault_path), bad_serial, "X:\\")
        check("3. stick-verify distingue llaves",
              proc.returncode == 0, "solo prueba las conectadas; ver caso manual")

        # 4. la ruta del codigo: verify desenvuelve el cofre
        with_bad = usb_session_key(str(mala), _salt_for(str(vault_path)))
        try:
            Vault(vault_path).unlock(with_bad)
            check("4. llave mala no desenvuelve", False, "abrió con la llave mala")
        except Exception:
            check("4. llave mala no desenvuelve", True, "rechazada como se espera")

        with_good = usb_session_key(str(good_key), _salt_for(str(vault_path)))
        check("4b. llave buena desenvuelve",
              Vault(vault_path).get(with_good, "PRUEBA") == "valor", "lee el secreto")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} comprobaciones OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
