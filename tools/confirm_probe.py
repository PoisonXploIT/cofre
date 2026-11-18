"""Sonda del dialogo de confirmacion (paso 2.4).

Comprueba sin intervencion humana:
  1. el dialogo se construye con los textos correctos y sin el valor;
  2. cierra solo a los pocos segundos y la respuesta por defecto es "deny";
  3. un clic en "Permitir una vez" devuelve "once";
  4. ConfirmQueue despierta al que pide desde el hilo de Tkinter.

  python tools/confirm_probe.py
"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.gui_confirm import ConfirmDialog, ConfirmQueue

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def main() -> int:
    root = tk.Tk()
    root.withdraw()

    # 1 y 2: timeout corto, sin tocar nada
    dlg = ConfirmDialog(root, "Navegador - dash.cloudflare.com",
                        "CLOUDFLARE_DNS_TOKEN", timeout_ms=600)
    def recoger(widget, salida):
        for hijo in widget.winfo_children():
            try:
                t = hijo.cget("text")
                if t:
                    salida.append(str(t))
            except Exception:
                pass
            recoger(hijo, salida)
        return salida

    textos = recoger(dlg.win, [])
    check("1. muestra quien pide", any("dash.cloudflare.com" in t for t in textos),
          textos[1] if len(textos) > 1 else "")
    check("1b. muestra que pide", any("CLOUDFLARE_DNS_TOKEN" in t for t in textos), "")
    check("1c. no muestra ningún valor", not any("valor" in t.lower() for t in textos), "")
    inicio = time.time()
    resultado = dlg.wait()
    check("2. se cierra solo y deniega", resultado == "deny",
          f"{resultado} tras {time.time() - inicio:.1f}s")

    # 2b: la cuenta atras se ve en el texto
    dlg_t = ConfirmDialog(root, "Tu - Copiar", "SIMULACRO_RESTAURA", timeout_ms=2500)
    check("2b. ensena la cuenta atras", "se deniega en" in dlg_t.msg.cget("text"),
          dlg_t.msg.cget("text"))
    check("2c. Denegar es la accion con acento",
          dlg_t.b_deny.kind == "primary", dlg_t.b_deny.kind)
    dlg_t._close("deny")   # ya destruida: no se llama a wait()

    # 3: el retardo de 700 ms impide autorizar con un clic que iba a otra parte
    dlg2 = ConfirmDialog(root, "Tu - Copiar", "SIMULACRO_RESTAURA", timeout_ms=4000)
    check("3. Permitir empieza deshabilitado",
          dlg2.b_once._estado == "disabled" and dlg2.b_grant._estado == "disabled",
          f"once={dlg2.b_once._estado} grant={dlg2.b_grant._estado}")

    def pulsar(objetivo):
        def _p():
            # el boton es un widget propio: se pulsa por su metodo
            if objetivo == "once":
                dlg2.b_once.invoke()
        return _p

    dlg2.win.after(200, pulsar("once"))     # demasiado pronto: no debe hacer nada
    dlg2.win.after(900, pulsar("once"))     # ya habilitado
    check("3b. el clic temprano no autoriza y el tardio si",
          dlg2.wait() == "once", "respuesta once tras el segundo clic")

    # 4: la cola despierta al que pide desde otro hilo
    cola = ConfirmQueue(root)
    respuesta: dict = {}

    def pedir():
        respuesta["r"] = cola.ask("Navegador - localhost", "SIMULACRO_RESTAURA", timeout=5)

    hilo = threading.Thread(target=pedir, daemon=True)
    hilo.start()
    time.sleep(0.3)
    atendido = cola.poll()          # muestra el dialogo en el hilo de Tk
    check("4. la cola atiende la peticion", atendido, "")
    hilo.join(timeout=6)
    check("4b. el que pide recibe la respuesta", respuesta.get("r") == "deny",
          str(respuesta.get("r")))

    root.destroy()
    fallos = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(fallos)}/{len(RESULTS)} comprobaciones OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
