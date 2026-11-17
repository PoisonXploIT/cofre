"""Servidor falso de Cloudflare para las pruebas de rotacion (paso 5.3).

Imita solo lo que usa COFRE:

  GET    /client/v4/user/tokens/verify
  PUT    /client/v4/user/tokens/{id}/value
  GET    /client/v4/user/tokens/{id}
  POST   /client/v4/user/tokens
  DELETE /client/v4/user/tokens/{id}

Nunca se llama a Cloudflare real desde las pruebas.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeCloudflare:
    def __init__(self, admin_token: str = "admin-falso"):
        self.admin_token = admin_token
        self.tokens: dict[str, dict] = {}
        self.llamadas: list[tuple[str, str]] = []
        self.fallar_verify = False
        self.fallar_roll = False
        self.contador = 0
        self.server: ThreadingHTTPServer | None = None
        self.hilo: threading.Thread | None = None

    # -------------------------------------------------------------- datos

    def add_token(self, valor: str, token_id: str, nombre: str = "prueba",
                  status: str = "active", expires_on: str = "",
                  policies=None, condition=None) -> None:
        self.tokens[valor] = {"id": token_id, "name": nombre, "status": status,
                              "expires_on": expires_on,
                              "policies": policies or [],
                              "condition": condition or {}}

    def by_id(self, token_id: str) -> dict | None:
        for valor, datos in self.tokens.items():
            if datos["id"] == token_id:
                return {"value": valor, **datos}
        return None

    # -------------------------------------------------------------- servidor

    def start(self) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _auth(self) -> bool:
                cabecera = self.headers.get("Authorization", "")
                return cabecera == f"Bearer {fake.admin_token}"

            def _json(self, code: int, body: dict) -> None:
                datos = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def _body(self) -> dict:
                largo = int(self.headers.get("Content-Length", "0") or 0)
                if not largo:
                    return {}
                try:
                    return json.loads(self.rfile.read(largo).decode("utf-8"))
                except Exception:
                    return {}

            def do_GET(self):
                fake.llamadas.append(("GET", self.path))
                if self.path.endswith("/user/tokens/verify"):
                    if fake.fallar_verify:
                        return self._json(403, {"success": False,
                                                "errors": [{"message": "token invalido"}]})
                    cabecera = self.headers.get("Authorization", "").replace("Bearer ", "")
                    datos = fake.tokens.get(cabecera)
                    if not datos:
                        return self._json(403, {"success": False,
                                                "errors": [{"message": "token desconocido"}]})
                    return self._json(200, {"success": True,
                                            "result": {"id": datos["id"],
                                                       "status": datos["status"],
                                                       "expires_on": datos["expires_on"]}})
                if "/user/tokens/" in self.path:
                    if not self._auth():
                        return self._json(403, {"success": False,
                                                "errors": [{"message": "sin permiso"}]})
                    token_id = self.path.rsplit("/", 1)[-1]
                    datos = fake.by_id(token_id)
                    if not datos:
                        return self._json(404, {"success": False,
                                                "errors": [{"message": "no existe"}]})
                    return self._json(200, {"success": True, "result": {
                        "id": datos["id"], "name": datos["name"],
                        "policies": datos["policies"], "condition": datos["condition"],
                        "expires_on": datos["expires_on"]}})
                return self._json(404, {"success": False})

            def do_PUT(self):
                fake.llamadas.append(("PUT", self.path))
                if not self._auth():
                    return self._json(403, {"success": False,
                                            "errors": [{"message": "sin permiso"}]})
                if fake.fallar_roll:
                    return self._json(400, {"success": False,
                                            "errors": [{"message": "roll rechazado"}]})
                token_id = self.path.split("/")[-2]
                datos = fake.by_id(token_id)
                if not datos:
                    return self._json(404, {"success": False,
                                            "errors": [{"message": "no existe"}]})
                fake.contador += 1
                nuevo = f"valor-rotado-{fake.contador}"
                registro = fake.tokens.pop(datos["value"])
                fake.tokens[nuevo] = registro
                return self._json(200, {"success": True, "result": {"value": nuevo}})

            def do_POST(self):
                fake.llamadas.append(("POST", self.path))
                if not self._auth():
                    return self._json(403, {"success": False,
                                            "errors": [{"message": "sin permiso"}]})
                cuerpo = self._body()
                fake.contador += 1
                nuevo_id = f"id-nuevo-{fake.contador}"
                valor = f"valor-creado-{fake.contador}"
                fake.tokens[valor] = {"id": nuevo_id,
                                      "name": cuerpo.get("name", "nuevo"),
                                      "status": "active",
                                      "expires_on": cuerpo.get("expires_on", ""),
                                      "policies": cuerpo.get("policies", []),
                                      "condition": cuerpo.get("condition", {})}
                return self._json(200, {"success": True,
                                        "result": {"id": nuevo_id, "value": valor}})

            def do_DELETE(self):
                fake.llamadas.append(("DELETE", self.path))
                if not self._auth():
                    return self._json(403, {"success": False,
                                            "errors": [{"message": "sin permiso"}]})
                token_id = self.path.rsplit("/", 1)[-1]
                datos = fake.by_id(token_id)
                if datos:
                    fake.tokens.pop(datos["value"], None)
                return self._json(200, {"success": True, "result": {"id": token_id}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.hilo = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.hilo.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/client/v4"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
