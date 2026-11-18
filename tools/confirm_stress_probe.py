"""COFRE - sonda de hilos del puente y del dialogo de confirmacion (2026-11-18).

  python tools/confirm_stress_probe.py

Comprueba lo que no se ve a simple vista:

  1. el sondeo de Tk **no se queda esperando** dentro del dialogo: `pump()`
     vuelve enseguida y la respuesta la deja el dialogo al cerrarse;
  2. mientras hay un dialogo abierto, el cofre sigue contestando (una peticion
     `status` no se queda detras);
  3. 20 peticiones simultaneas (12 de git y 8 del navegador) por la tuberia
     real: 20 respuestas correctas, sin cuelgues;
  4. ninguna llamada a Tk ocurre fuera del hilo principal (los asserts estan
     dentro; aqui se comprueba que no saltan);
  5. al retirar el permiso, la siguiente peticion del mismo host vuelve a
     preguntar.

Usa cofres falsos: no toca el cofre real ni el pendrive.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cofre import bridge_ops                      # noqa: E402
from cofre.gui_confirm import ConfirmQueue        # noqa: E402
from cofre.pipe_server import BridgeController, PipeServer   # noqa: E402
from cofre.threads import WrongThread, assert_main  # noqa: E402
from pipe_server_probe import CLIENT, call        # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


# ------------------------------------------------------------ cofre falso

class FakeStore:
    master = None


class FakeVault:
    """Lo justo para el despacho: nombres, meta, sitios y valor."""

    def __init__(self) -> None:
        self.datos = {
            "GITHUB_TOKEN": {"type": "api_token", "tags": [],
                             "urls": ["github.com"]},
            "BANCO_PASS": {"type": "password", "tags": [],
                           "urls": ["*.banco.example"],
                           "policy": {"confirm": True, "browser": True}},
        }

    def refresh(self) -> None:
        return None

    def names(self) -> list[str]:
        return list(self.datos)

    def meta(self, nombre: str) -> dict:
        return dict(self.datos.get(nombre) or {})

    def is_v2(self) -> bool:
        return True

    def urls(self, nombre: str) -> list[str]:
        return list((self.datos.get(nombre) or {}).get("urls") or [])

    def get(self, session, nombre: str) -> str:
        return f"valor-de-{nombre}"

    def _v2store(self) -> FakeStore:
        return FakeStore()


class FakeApp:
    """Misma regla que CofreGUI.request_confirm, sin ventana de verdad."""

    def __init__(self, vault, vault_path: Path, cola: ConfirmQueue):
        self.vault = vault
        self.vault_path = vault_path
        self.gate = "usb"
        self.serial = 1
        self.session = b"x"
        self.cola = cola
        self.permisos: dict = {}
        self.pedidas = 0

    def request_confirm(self, who: str, what: str, contexto: str | None = None) -> str:
        assert not (threading.current_thread() is threading.main_thread()), \
            "la peticion de confirmación llego al hilo de Tk"
        clave = (contexto or what, who.split(" - ")[0])
        hasta = self.permisos.get(clave)
        if hasta and hasta > time.time():
            return "grant"
        self.pedidas += 1
        respuesta = self.cola.ask(who, what, timeout=30)
        if respuesta == "grant":
            self.permisos[clave] = time.time() + 300
        return respuesta


# ------------------------------------------------------------ utilidades

def esperar(root, cola: ConfirmQueue, listo, limite: float,
            respuesta: str = "grant") -> list[str]:
    """Bucle de Tk: atiende y cierra los dialogos solo, como una persona."""
    cerrados: list[str] = []
    abierto_desde = 0.0
    fin = time.time() + limite
    while not listo() and time.time() < fin:
        try:
            root.update()
        except tk.TclError:
            break
        cola.pump()
        ahora = time.time()
        if cola.ocupada:
            if not abierto_desde:
                abierto_desde = ahora
            elif ahora - abierto_desde > 0.8:      # ya armado: se puede permitir
                dialogo = cola._pendiente["dialogo"]  # noqa: SLF001
                cerrados.append("permitido")
                dialogo._close(respuesta)               # noqa: SLF001
                abierto_desde = 0.0
        else:
            abierto_desde = 0.0
        time.sleep(0.02)
    return cerrados


def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError:
        print("sin pantalla para Tk: sonda omitida")
        return 0
    root.withdraw()

    tmp = Path(tempfile.mkdtemp(prefix="cofre-stress-"))
    os.environ["COFRE_PIPE_INFO"] = str(tmp / "pipe-name")
    print("directorio de prueba:", tmp)

    # 4. el assert de hilo funciona (y es lo que protege a Tk)
    def otro_hilo() -> str:
        try:
            assert_main("prueba")
            return "no salto"
        except WrongThread:
            return "salto"

    malo = {}
    hilo = threading.Thread(target=lambda: malo.setdefault("r", otro_hilo()))
    hilo.start()
    hilo.join()
    check("1. assert_main detecta el hilo equivocado", malo.get("r") == "salto",
          str(malo.get("r")))
    check("1b. assert_main acepta el hilo principal",
          (assert_main("principal") or True) is True, "sin excepcion")

    cola = ConfirmQueue(root)
    app = FakeApp(FakeVault(), tmp / "cofre.json", cola)
    ctl = BridgeController(root, lambda msg: bridge_ops.dispatch(app, msg),
                           log=lambda m: None)
    ctl.start()
    cola_dentro = 0

    # 2. el sondeo no se queda esperando dentro del dialogo
    respuesta_pedir: dict = {}

    def pedir_git() -> None:
        respuesta_pedir["r"] = app.request_confirm("git - github.com", "GITHUB_TOKEN",
                                                   contexto="git:github.com")

    hilo = threading.Thread(target=pedir_git, daemon=True)
    hilo.start()
    time.sleep(0.2)
    inicio = time.time()
    cola.pump()
    tardanza = time.time() - inicio
    check("2. el sondeo abre el dialogo y vuelve", tardanza < 0.5 and cola.ocupada,
          f"{tardanza:.2f}s")
    check("2b. el que pide sigue esperando", hilo.is_alive(), "")
    cola._pendiente["dialogo"]._close("grant")          # noqa: SLF001
    hilo.join(timeout=3)
    check("2c. la respuesta llega al hilo que pidio",
          respuesta_pedir.get("r") == "grant", str(respuesta_pedir.get("r")))
    check("2d. el permiso queda anotado por host",
          bool(app.permisos), str(list(app.permisos)))
    app.permisos.clear()

    # 3. 20 peticiones simultaneas por la tuberia real
    nombre_host = {"git": 12, "browser": 8}
    lanzadas: list[dict] = []
    for i in range(nombre_host["git"]):
        lanzadas.append({"type": "git", "host": "github.com"})
    for i in range(nombre_host["browser"]):
        lanzadas.append({"type": "get", "name": "BANCO_PASS",
                         "domain": f"www{i}.banco.example"})

    salidas: list[dict] = [{} for _ in lanzadas]
    hilos = []

    def lanzar(indice: int) -> None:
        salidas[indice] = call(ctl.server.name, lanzadas[indice])

    for indice in range(len(lanzadas)):
        hilo = threading.Thread(target=lanzar, args=(indice,), daemon=True)
        hilo.start()
        hilos.append(hilo)

    # 2b bis: con una peticion de fondo en marcha, `status` contesta ya
    time.sleep(0.3)
    pronto = call(ctl.server.name, {"type": "status"})
    check("3. con el dialogo abierto, status contesta",
          pronto.get("ok") is True and pronto.get("open") is True, str(pronto)[:70])

    cerrados = esperar(root, cola, lambda: not any(h.is_alive() for h in hilos), 90)
    for hilo in hilos:
        hilo.join(timeout=10)
    ok_git = [r for r in salidas[:nombre_host["git"]]
              if r.get("ok") and r.get("password") == "valor-de-GITHUB_TOKEN"]
    ok_nav = [r for r in salidas[nombre_host["git"]:]
              if r.get("ok") and r.get("value") == "valor-de-BANCO_PASS"]
    check("4. 20 de 20 respuestas correctas",
          len(ok_git) == 12 and len(ok_nav) == 8,
          f"git {len(ok_git)}/12, navegador {len(ok_nav)}/8, "
          f"errores {[r.get('error') for r in salidas if not r.get('ok')][:3]}")
    check("4b. sin cuelgues: todos los hilos terminaron",
          all(not h.is_alive() for h in hilos), f"{len(cerrados)} dialogos")

    # 5. retirar el permiso hace que se vuelva a preguntar
    app.permisos.clear()
    preguntas_antes = app.pedidas
    otra: dict = {}
    hilo = threading.Thread(target=lambda: otra.setdefault(
        "r", app.request_confirm("git - github.com", "GITHUB_TOKEN",
                                 contexto="git:github.com")), daemon=True)
    hilo.start()
    esperar(root, cola, lambda: not hilo.is_alive(), 30)
    hilo.join(timeout=5)
    check("5. tras retirar el permiso se vuelve a preguntar",
          app.pedidas == preguntas_antes + 1, f"{otra.get('r')}")

    # 5b. el registro no guarda valores
    registro = tmp / ".cofre-audit.jsonl"
    texto = registro.read_text(encoding="utf-8") if registro.exists() else ""
    check("5b. el registro no guarda valores",
          "valor-de-" not in texto, f"{len(texto.splitlines())} eventos")

    ctl.stop()
    try:
        root.destroy()
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)

    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
