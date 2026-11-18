#!/usr/bin/env python
"""COFRE - gancho de pre-commit del escaner de fugas (paso 3.4).

Lo instala `run.cmd scan --install-hook <repo>` y lo llama git en cada commit,
desde la raiz del repo.

Reglas:

  - si encuentra un secreto del cofre pegado en lo que se va a commitear, **para
    el commit** y dice nombre, fichero y linea (nunca el valor);
  - si no puede abrir el cofre (sin pendrive), **avisa y deja pasar**: es un
    aviso, no una cerradura. La alternativa seria no poder commitear sin el
    pendrive puesto;
  - con `--forzar` (o `--no-verify` de git) no se ejecuta.

  python tools/leak_hook.py [--repo RUTA]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_COFRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_COFRE))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = Path(argv[argv.index("--repo") + 1]) if "--repo" in argv else Path.cwd()

    from cofre import leak
    from cofre.cli import prepare_audit
    from cofre.crypto import Vault
    from cofre.paths import default_vault

    vault_path = Path(os.environ.get("COFRE_VAULT") or default_vault())
    vault = prepare_audit(vault_path, os.environ.get("COFRE_GATE", "usb"),
                          os.environ.get("COFRE_STICK") or None, False)
    if not isinstance(vault, Vault) or not vault.is_v2():
        print("COFRE: no se pudo abrir el cofre; el escaneo de fugas no se ha hecho.")
        return 0
    store = vault._v2store()
    if store.master is None:
        print("COFRE: sin el pendrive no se pueden calcular las huellas; "
              "el escaneo de fugas no se ha hecho (el commit sigue).")
        return 0

    clave = leak.clave_de_huellas(store.master)
    secretos = {}
    for nombre in vault.names():
        try:
            valor = vault.get(None, nombre)
        except Exception:                              # noqa: BLE001
            continue
        if valor:
            secretos[nombre] = valor
    tabla, cortos = leak.huellas_de(clave, secretos)
    hallazgos = leak.escanear_escenificados(repo, clave, tabla, cortos)

    if not hallazgos:
        return 0
    print("")
    print("COFRE: hay secretos del cofre en lo que vas a commitear.")
    print("No se muestra el valor; esto es nombre, fichero y línea:")
    vistos: set[tuple[str, str]] = set()
    for ruta, linea, nombre in hallazgos:
        try:
            relativa = ruta.relative_to(repo)
        except ValueError:
            relativa = ruta
        clave_vista = (str(relativa), nombre)
        if clave_vista in vistos:
            continue
        vistos.add(clave_vista)
        print(f"  {nombre}  {relativa}:{linea}")
    print("")
    print("Quita el valor del fichero y vuelve a commitear. Si es un falso "
          "positivo, revisa el secreto en el cofre.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
