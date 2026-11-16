"""Pagina de prueba para el relleno (no forma parte de COFRE).

Sirve un formulario con campo de contrasena en http://localhost:8901/ para
probar el puente sin tocar ninguna web real. Se para con Ctrl+C.

  python tools/test_page.py
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Prueba COFRE</title>
<style>body{font:14px sans-serif;margin:40px}input{display:block;margin:8px 0;padding:6px;width:280px}</style>
</head><body>
<h1>Prueba de relleno de COFRE</h1>
<p>Esta pagina solo existe en tu equipo. El campo de contrasena debe quedar vacio.</p>
<form onsubmit="return false">
  <input type="text" name="usuario" placeholder="usuario">
  <input type="password" name="password" placeholder="contrasena" id="password">
  <input type="text" name="api_key" placeholder="api key" id="api_key">
</form>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    import sys

    # 8901 puede estar reservado por otro programa o por una politica local;
    # se prueban varios puertos hasta que uno escuche.
    server = None
    for puerto in (8901, 8902, 8903, 8904, 8905):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
            break
        except OSError as exc:
            print(f"puerto {puerto} no disponible: {exc}", file=sys.stderr)
    if server is None:
        print("no se pudo abrir ningun puerto de prueba", file=sys.stderr)
        return 1
    print(f"pagina de prueba en http://localhost:{server.server_address[1]}/")
    print("Ctrl+C para parar")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
