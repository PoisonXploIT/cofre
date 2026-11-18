"""Servidor falso de GitHub para las pruebas de 5.4.

Imita:

  GET    /user
  DELETE /user/personal-access-tokens/{id}
  POST   /app/installations/{id}/access_tokens
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeGitHub:
    def __init__(self):
        self.pat = "ghp_bueno"
        self.login = "sammi"
        self.scopes = "repo, read:user"
        self.installation = "12345"
        self.installation_token = "ghs_instalacion"
        self.app_jwt_esperado = None       # si se define, se comprueba tal cual
        self.llamadas: list[tuple[str, str]] = []
        self.secretos: dict[str, str] = {}
        self.clave_publica = None      # (b64, key_id) si se configura
        self.server: ThreadingHTTPServer | None = None
        self.revocados: list[str] = []

    def start(self) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _json(self, code: int, body: dict, extra: dict | None = None) -> None:
                datos = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                for clave, valor in (extra or {}).items():
                    self.send_header(clave, valor)
                self.end_headers()
                self.wfile.write(datos)

            def _auth(self) -> str:
                return self.headers.get("Authorization", "").replace("Bearer ", "")

            def do_GET(self):
                fake.llamadas.append(("GET", self.path))
                if self.path.endswith("/secrets/public-key") and fake.clave_publica:
                    clave, key_id = fake.clave_publica
                    return self._json(200, {"key": clave, "key_id": key_id})
                if self.path == "/user":
                    if self._auth() != fake.pat:
                        return self._json(401, {"message": "Bad credentials"})
                    return self._json(200, {"login": fake.login},
                                      {"X-OAuth-Scopes": fake.scopes})
                return self._json(404, {"message": "Not Found"})

            def do_POST(self):
                fake.llamadas.append(("POST", self.path))
                if self.path == "/credentials/revoke":
                    # sin autenticar: si llega cabecera, GitHub devuelve 403
                    if self.headers.get("Authorization"):
                        return self._json(403, {"message": "Must not be authenticated"})
                    largo = int(self.headers.get("Content-Length", "0") or 0)
                    cuerpo = json.loads(self.rfile.read(largo) or b"{}")
                    credenciales = cuerpo.get("credentials") or []
                    if len(credenciales) > 1000:
                        return self._json(422, {"message": "Too many credentials"})
                    fake.revocados.extend(credenciales)
                    return self._json(202, {})
                if self.path.endswith(f"/app/installations/{fake.installation}/access_tokens"):
                    jwt = self._auth()
                    if fake.app_jwt_esperado and jwt != fake.app_jwt_esperado:
                        return self._json(401, {"message": "A JSON web token could not be decoded"})
                    return self._json(201, {"token": fake.installation_token,
                                            "expires_at": "2026-11-17T23:00:00Z"})
                return self._json(404, {"message": "Not Found"})

            def do_PUT(self):
                fake.llamadas.append(("PUT", self.path))
                largo = int(self.headers.get("Content-Length", "0") or 0)
                cuerpo = json.loads(self.rfile.read(largo) or b"{}")
                if "/actions/secrets/" in self.path:
                    nombre = self.path.rsplit("/", 1)[-1]
                    fake.secretos[nombre] = json.dumps(cuerpo)
                    return self._json(201, {})
                return self._json(404, {"message": "Not Found"})

            def do_DELETE(self):
                fake.llamadas.append(("DELETE", self.path))
                return self._json(404, {"message": "Not Found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
