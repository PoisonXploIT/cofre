"""COFRE - GitHub App desde un manifest (paso M5, hecho el 2026-11-19).

Flujo contrastado con la documentación oficial (nota
`COFRE-GITHUB-APP-MANIFEST-2026-11-19.md` del vault):

  1. COFRE levanta un servidor de un solo uso en `127.0.0.1:<puerto libre>` con dos
     rutas: `/` (la página que envía el manifest) y `/callback` (a donde vuelve
     GitHub con el `code`);
  2. se abre el navegador en `http://127.0.0.1:<puerto>/`; el usuario pulsa
     **Create** en github.com;
  3. GitHub redirige a `/callback?code=...&state=...`: se valida `state` con
     `hmac.compare_digest` y se guarda el código;
  4. se canjea en `POST /app-manifests/{code}/conversions` (api.github.com) y la
     respuesta trae `id` y `pem`: la clave va directa al cofre, sin pasar por disco
     ni por la pantalla;
  5. se devuelve el id y el `slug` (para abrir la página de instalación).

Nada de esto imprime el `pem`. El agente no debe ejecutar este flujo con el cofre
cerrado: necesita la sesión para guardar la clave.
"""

from __future__ import annotations

import hmac
import html
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from cofre.providers.http import ProviderError, request

NUEVA_APP = "https://github.com/settings/apps/new"
API = "https://api.github.com"
MINUTOS = 10


def manifest(nombre: str, redirect_url: str, pagina: str,
             permisos: dict | None = None, descripcion: str = "") -> dict:
    """Manifest mínimo. `url` es obligatoria; sin webhook (no lo necesitamos)."""
    if not pagina.startswith("https://") and not pagina.startswith("http://"):
        raise ValueError("la página de inicio (url) tiene que ser una dirección")
    datos = {
        "name": nombre,
        "url": pagina,
        "redirect_url": redirect_url,
        "public": False,
        "default_permissions": dict(permisos or {"contents": "read",
                                                 "metadata": "read"}),
    }
    if descripcion:
        datos["description"] = descripcion
    return datos


PAGINA = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>COFRE - crear la GitHub App</title>
<style>body{{background:#080B0F;color:#E9EEF5;font:14px "Segoe UI",sans-serif;
padding:40px;max-width:620px;margin:auto}}code{{color:#3E9C7A}}
input{{display:none}}</style>
<h2>Crear la GitHub App</h2>
<p>Si el navegador no te lleva solo a GitHub, pulsa el botón.</p>
<form id="f" method="post" action="{accion}">
  <input type="hidden" name="manifest" value="{manifest}">
  <input type="hidden" name="state" value="{state}">
  <button style="padding:10px 16px;font-size:15px">Ir a GitHub</button>
</form>
<p>Cuando GitHub te devuelva aquí, la clave privada irá directa a COFRE.</p>
<script>document.getElementById("f").submit()</script>
</html>"""

HECHO = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>COFRE</title><style>body{{background:#080B0F;color:#E9EEF5;
font:14px "Segoe UI",sans-serif;padding:40px;max-width:620px;margin:auto}}</style>
<h2>{titulo}</h2><p>{texto}</p></html>"""


class Servidor:
    """Servidor de un solo uso: recibe el código y se para."""

    def __init__(self, manifiesto: dict, accion: str = NUEVA_APP):
        self.manifiesto = manifiesto
        self.accion = accion
        self.state = secrets.token_urlsafe(32)
        self.codigo: str | None = None
        self.error = ""
        self.listo = threading.Event()
        self._httpd: ThreadingHTTPServer | None = None
        self._hilo: threading.Thread | None = None

    @property
    def puerto(self) -> int:
        return int(self._httpd.server_address[1]) if self._httpd else 0

    def arrancar(self) -> str:
        yO = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _responder(self, codigo: int, cuerpo: str) -> None:
                datos = cuerpo.encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def do_GET(self):                       # noqa: N802
                partes = urlsplit(self.path)
                if partes.path == "/":
                    yO.state = secrets.token_urlsafe(32)
                    contenido = PAGINA.format(
                        accion=html.escape(yO.accion),
                        manifest=html.escape(json.dumps(yO.manifiesto)),
                        state=html.escape(yO.state))
                    self._responder(200, contenido)
                    return
                if partes.path == "/callback":
                    parametros = parse_qs(partes.query)
                    state = str((parametros.get("state") or [""])[0])
                    codigo = str((parametros.get("code") or [""])[0])
                    if not hmac.compare_digest(state, yO.state):
                        yO.error = "el parámetro state no coincide (posible CSRF)"
                        self._responder(400, HECHO.format(
                            titulo="No vale",
                            texto="El aviso no coincide con la petición. Vuelve a "
                                  "empezar desde COFRE."))
                        yO.listo.set()
                        return
                    if not codigo:
                        yO.error = "GitHub no devolvió código"
                        self._responder(400, HECHO.format(
                            titulo="No vale", texto="No llegó el código."))
                        yO.listo.set()
                        return
                    yO.codigo = codigo
                    self._responder(200, HECHO.format(
                        titulo="Hecho",
                        texto="Ya está: vuelve a la ventana de COFRE. Puedes cerrar "
                              "esta pestaña."))
                    yO.listo.set()
                    return
                self._responder(404, "no existe")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self._hilo = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._hilo.start()
        return f"http://127.0.0.1:{self.puerto}/"

    def esperar(self, minutos: int = MINUTOS) -> str | None:
        self.listo.wait(timeout=minutos * 60)
        return self.codigo

    def parar(self) -> None:
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:                      # noqa: BLE001
                pass
            self._httpd = None


def canjear(codigo: str) -> dict:
    """POST /app-manifests/{code}/conversions. Devuelve la respuesta tal cual."""
    base = os.environ.get("COFRE_GITHUB_API", API).rstrip("/")
    url = f"{base}/app-manifests/{codigo}/conversions"
    try:
        estado, _cabeceras, cuerpo = request("POST", url,
                                            headers={"Accept": "application/vnd.github+json"},
                                            timeout=30)
    except ProviderError as exc:
        raise ProviderError(str(exc)) from exc
    if estado != 201 and estado != 200:
        raise ProviderError(f"GitHub contesta HTTP {estado} al canjear el código")
    if not isinstance(cuerpo, dict) or not cuerpo.get("pem"):
        raise ProviderError("la respuesta de GitHub no trae la clave privada")
    return cuerpo


def crear(manifiesto: dict, abrir: bool = True, minutos: int = MINUTOS,
          accion: str = NUEVA_APP) -> dict:
    """Flujo completo hasta tener la respuesta de GitHub (sin guardar nada)."""
    servidor = Servidor(manifiesto, accion=accion)
    try:
        direccion = servidor.arrancar()
        if abrir:
            webbrowser.open(direccion)
        codigo = servidor.esperar(minutos)
        if not codigo:
            raise ProviderError(servidor.error or
                                "no llegó el código de GitHub a tiempo")
        return canjear(codigo)
    finally:
        servidor.parar()


def esperar_un_poco(segundos: float) -> None:
    """Solo para las pruebas: deja respirar al servidor."""
    time.sleep(segundos)
