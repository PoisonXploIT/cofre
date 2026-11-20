r"""COFRE - sesion fisica: lo que el usuario hace en 10 minutos (D18).

  python tools/sesion_fisica.py            [--carpeta D:\\Cofre]
  python tools/sesion_fisica.py --comprobar    (sin copia)

Regla D18 (2026-11-19): todo lo que se pueda hacer desde la maquina, lo hace el
modelo. El usuario solo enchufa discos, teclea el codigo de recuperacion, pulsa
"Permitir" en el dialogo de git y, si quiere, Create/Install en GitHub.

Este guion hace la parte de la maquina de M1, M1b, M2, M3 y M9:

  1. ver que discos hay (E:, F:, D:) y que el registro los conoce;
  2. `log verify` sobre el cofre real;
  3. `stick-verify` (la reserva abre de verdad);
  4. recordatorio: lanzar la tarea programada y leer el calendario en JSON;
  5. `panic --dry-run` y resumen del plan (no ejecuta nada);
  6. copia a D:\\Cofre (.json + registro de pendrives + sal) y simulacro de
     restauracion con `backup_restore_probe`.

No muestra valores, no pide el codigo de recuperacion y no ejecuta el panico.
Sale 0 si lo obligatorio esta bien; 1 si algo que deberia funcionar no funciona.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.paths import default_vault          # noqa: E402
from cofre.usb import key_drives, volume_serial  # noqa: E402

PY = sys.executable
RESULTADOS: list[tuple[str, str, str]] = []      # (estado, nombre, detalle)


def apuntar(estado: str, nombre: str, detalle: str = "") -> None:
    RESULTADOS.append((estado, nombre, detalle))
    print(f"{estado:<6} {nombre:<28} {detalle}")


def cli(*args: str, timeout: int = 180,
        pin: str = "") -> tuple[int, str]:
    """Lanza un comando del cofre. La frase va SOLO en el entorno del hijo.

    Asi el hijo no se queda esperando en `getpass` (ya tiene COFRE_PIN) y la
    frase del usuario no acaba en `os.environ` del padre ni la hereda nada mas
    (2026-11-20, instruccion de cierre 1).
    """
    entorno = dict(os.environ)
    if pin:
        entorno["COFRE_PIN"] = pin
    proc = subprocess.run([PY, "-m", "cofre.cli", *args], cwd=str(REPO),
                          capture_output=True, text=True, timeout=timeout,
                          env=entorno)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def leer_frase(prompt: str = "Frase del cofre: ") -> str:
    """La frase se pide aqui, una sola vez, en el proceso padre.

    En una consola de verdad: `getpass`, no se ve al teclear. Si la entrada no
    es una consola (tuberia, prueba) se lee la primera linea de stdin, porque
    `getpass` en Windows se queda bloqueado esperando una consola real.
    """
    if sys.stdin.isatty():
        from getpass import getpass
        return getpass(prompt)
    sys.stderr.write(prompt + "(por stdin)\n")
    return sys.stdin.readline().rstrip("\n")


def _letra(drive: str) -> str:
    """'E:' con barra al final -> 'E:'. Nunca duplica los dos puntos."""
    texto = str(drive).strip().upper().rstrip("/" + chr(92))
    return texto if texto.endswith(":") else texto + ":"


def discos() -> dict[str, dict]:
    """Letra -> {key, mounted}. Con plazo: un USB muerto no cuelga (08-11 y 16-11)."""
    try:
        con_llave = {_letra(d) for d in key_drives()}
    except Exception:                                # noqa: BLE001
        con_llave = set()
    salida: dict[str, dict] = {}
    for letra in ("E:", "F:", "D:"):
        salida[letra] = {"key": letra in con_llave, "mounted": False}
        try:
            salida[letra]["mounted"] = Path(letra + chr(92)).exists()
        except OSError:
            salida[letra]["mounted"] = False
    return salida


def paso_discos(estado_discos: dict[str, dict]) -> bool:
    e = estado_discos["E:"]
    f = estado_discos["F:"]
    d = estado_discos["D:"]
    apuntar("OK" if e["key"] else "FALTA", "pendrive E: (principal)",
            "COFRE.KEY en su sitio" if e["key"] else "no esta conectado")
    apuntar("OK" if f["key"] else "FALTA", "pendrive F: (reserva)",
            "COFRE.KEY en su sitio" if f["key"] else "no esta conectado")
    apuntar("OK" if d["mounted"] else "FALTA", "disco D: (copias)",
            "montado" if d["mounted"] else "no esta conectado")
    return e["key"]


def paso_registro() -> bool:
    """El registro de pendrives conoce E: y F: por su serial."""
    vault = Path(default_vault())
    registro = vault.parent / ".cofre-sticks.json"
    if not registro.exists():
        apuntar("FALLO", "registro de pendrives", f"no existe {registro}")
        return False
    try:
        datos = json.loads(registro.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        apuntar("FALLO", "registro de pendrives", f"ilegible: {exc}")
        return False
    seriales = {str(s.get("serial")) for s in (datos.get("sticks") or {}).values()}
    try:
        llaves = [str(d) for d in key_drives()]
    except Exception:                                # noqa: BLE001
        llaves = []
    vistos = []
    for drive in llaves:
        serial = volume_serial(drive)
        vistos.append((_letra(drive), serial,
                       serial is not None and str(serial) in seriales))
    if not vistos:
        apuntar("FALTA", "registro de pendrives", "sin pendrives que comprobar")
        return False
    ok = all(v[2] for v in vistos)
    detalle = ", ".join(f"{l} {'registrado' if b else 'NO registrado'}"
                        for l, _s, b in vistos)
    apuntar("OK" if ok else "FALLO", "registro de pendrives", detalle)
    return ok


def paso_log_verify(gate: str = "usb", pin: str = "") -> bool:
    codigo, salida = cli("log", "verify", "--gate", gate, timeout=240, pin=pin)
    lineas = [ln for ln in salida.splitlines() if ln.strip()]
    fallos = [ln for ln in lineas if ln.strip().startswith("FALLO")]
    avisos = [ln for ln in lineas if "reancl" in ln.lower() or "aviso" in ln.lower()]
    detalle = "cadena y checkpoint OK" if codigo == 0 and not fallos else \
        (fallos[0][:90] if fallos else f"código {codigo}")
    apuntar("OK" if codigo == 0 and not fallos else "FALLO", "M1 log verify", detalle)
    if avisos:
        apuntar("AVISO", "M1 avisos del registro", avisos[0][:90])
    return codigo == 0 and not fallos


def paso_reserva(gate: str = "usb", pin: str = "") -> bool:
    codigo, salida = cli("stick-verify", "--gate", gate, timeout=180, pin=pin)
    ok = codigo == 0 and "NO abre" not in salida and "no abre" not in salida.lower()
    apuntar("OK" if ok else "FALLO", "M1b stick-verify",
            "cada pendrive conectado abre" if ok else salida.splitlines()[-1][:90])
    return ok


def paso_recordatorio() -> bool:
    """Lanza la tarea programada y comprueba con el calendario, no con la ventana."""
    try:
        proc = subprocess.run(["schtasks", "/run", "/tn", "COFRE recordatorio"],
                              capture_output=True, text=True, timeout=60)
        lanzada = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        lanzada = False
    apuntar("OK" if lanzada else "AVISO", "M2 tarea programada",
            "lanzada" if lanzada else "no se pudo lanzar (mira schtasks /query)")
    time.sleep(2)
    codigo, salida = cli("due", "--json", timeout=60)
    try:
        datos = json.loads(salida)
    except json.JSONDecodeError:
        apuntar("FALLO", "M2 calendario", "no se pudo leer due --json")
        return False
    if not datos.get("hay_calendario"):
        apuntar("AVISO", "M2 calendario",
                "sin calendario: hay que abrir la GUI una vez con el pendrive")
        return lanzada
    apuntar("OK", "M2 calendario", str(datos.get("describe", ""))[:90])
    if datos.get("toca"):
        apuntar("OK", "M2 aviso pendiente", str(datos.get("mensaje", ""))[:90])
    return lanzada


def paso_panico(gate: str = "usb", pin: str = "") -> bool:
    codigo, salida = cli("panic", "--dry-run", "--gate", gate, timeout=180,
                         pin=pin)
    acciones = [ln for ln in salida.splitlines()
                if ln.strip().startswith("-") or "revocar" in ln.lower()]
    if codigo == 0:
        apuntar("OK", "M9 panic --dry-run",
                f"plan leido, {len(acciones)} accion(es); no se ejecuto nada")
        return True
    # si no abrio, no hay plan leido: decir "0 acciones" era mentir
    motivo = (salida.splitlines() or ["sin salida"])[-1]
    apuntar("FALLO", "M9 panic --dry-run", motivo[:90])
    return False


def paso_copia(carpeta: str, gate: str = "usb", pin: str = "") -> bool:
    destino = Path(carpeta)
    if not destino.exists():
        apuntar("FALTA", "M3 copia", f"no existe {destino}")
        return False
    vault = Path(default_vault())
    piezas = ["cofre.json", ".cofre-sticks.json", ".cofre-salt"]
    copiadas = 0
    try:
        for pieza in piezas:
            origen = vault.parent / pieza
            if origen.exists():
                if pieza == "cofre.json" and (destino / pieza).exists():
                    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
                    shutil.copy2(destino / pieza,
                                 destino / f"cofre-{marca}.json")
                shutil.copy2(origen, destino / pieza)
                copiadas += 1
    except OSError as exc:
        apuntar("FALLO", "M3 copia", f"no se pudo copiar: {exc}")
        return False
    apuntar("OK" if copiadas else "FALLO", "M3 copia",
            f"{copiadas} fichero(s) a {destino}")
    entorno = dict(os.environ)
    if pin:
        entorno["COFRE_PIN"] = pin
    proc = subprocess.run(
        [PY, str(REPO / "tools" / "backup_restore_probe.py"),
         "--backup", str(destino), "--gate", gate],
        cwd=str(REPO), capture_output=True, text=True, timeout=300, env=entorno)
    if proc.returncode == 2:
        # el codigo 2 del simulacro es "no se puede comprobar sin la frase":
        # la copia no esta mal, falta la frase (D22)
        apuntar("FALTA", "M3 simulacro de copia",
                "la copia pide la frase del cofre y no se paso")
        return True
    apuntar("OK" if proc.returncode == 0 else "FALLO", "M3 simulacro de copia",
            "la copia abre con el pendrive" if proc.returncode == 0
            else "la copia NO abre: no la des por buena")
    return proc.returncode == 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    carpeta = "D:\\Cofre"
    if "--carpeta" in argv:
        carpeta = argv[argv.index("--carpeta") + 1]
    gate = "usb"
    if "--gate" in argv:
        gate = argv[argv.index("--gate") + 1]
    sin_copia = "--comprobar" in argv

    print(f"COFRE - sesión fisica  ({datetime.now():%Y-%m-%d %H:%M})")
    print(f"cofre: {default_vault()}")
    print("")

    # La frase se pide UNA vez, aqui, en el proceso padre. Cada paso hijo la
    # recibe solo en su propio entorno (ver `cli`). Ni se toca `os.environ` del
    # usuario ni la hereda nada mas. Con COFRE_AGENT=1 no se pide: un agente no
    # puede teclearla, y un `getpass` a ciegas seria un cuelgue (2026-11-20).
    pin = ""
    if gate == "usb-pin":
        from cofre.agent_guard import activo as es_agente
        if es_agente():
            print("COFRE_AGENT=1: la sesión con PIN la lanza el usuario en su "
                  "consola; yo no puedo teclear la frase.", file=sys.stderr)
            return 3
        pin = leer_frase()
        if not pin.strip():
            print("falta la frase del cofre: sin ella no se pueden comprobar las "
                  "firmas ni el simulacro.", file=sys.stderr)
            return 3

    estado_discos = discos()
    obligatorio = paso_discos(estado_discos)
    if not obligatorio:
        print("")
        print("Falta E: (o su COFRE.KEY): sin el pendrive no se puede seguir.")
        return 1
    ok = paso_registro()
    ok = paso_log_verify(gate, pin) and ok
    if estado_discos["F:"]["key"]:
        ok = paso_reserva(gate, pin) and ok
    else:
        apuntar("FALTA", "M1b stick-verify", "conecta F: para comprobarlo")
    paso_recordatorio()
    paso_panico(gate, pin)
    if sin_copia:
        apuntar("SALTA", "M3 copia", "--comprobar: no se copia nada")
    else:
        ok = paso_copia(carpeta, gate, pin) and ok

    print("")
    fallos = [r for r in RESULTADOS if r[0] == "FALLO"]
    faltan = [r for r in RESULTADOS if r[0] == "FALTA"]
    print("--- lo que queda para ti (una vez, unos 10 minutos) ---")
    print("1. Enchufa E:, F: y D: a la vez (si algo sale FALTA arriba).")
    print("2. COFRE > Llaves > Probar código: teclea tus 25 palabras de papel.")
    print("   Ese código no lo ve el modelo: solo lo tecleas tu, en la ventana.")
    print("3. Si git pide acceso: pulsa Permitir en el dialogo de COFRE.")
    print("4. Si quieres la GitHub App: en la pagina que se abra, Create e Install.")
    print("")
    if fallos:
        print(f"{len(fallos)} paso(s) en rojo. No des el cierre por bueno.")
        return 1
    if faltan:
        print(f"{len(faltan)} cosa(s) pendiente(s) de hardware (arriba). El resto, OK.")
    else:
        print("Todo lo que se puede comprobar desde aquí esta OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
