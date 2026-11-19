"""COFRE - puente para el navegador (servidor local, solo loopback).

Por que un servidor y no un host de mensajeria nativa: Chrome lanza el host con
`CreateProcess` y sin argumentos, asi que el manifest tendria que apuntar a un
.exe. Sin PyInstaller no hay .exe, y un .cmd no lo ejecuta CreateProcess. Un
servidor en 127.0.0.1 evita ese problema y se puede probar con curl.

Modelo de seguridad, dicho sin adornos:

  - Solo escucha en 127.0.0.1 (no accesible desde la red).
  - Solo responde si la cabecera Origin es exactamente el de la extension
    autorizada. Una pagina web normal manda su propio Origin y se rechaza.
  - Solo existe mientras el cofre esta abierto: al bloquear, se cierra.
  - Cada peticion comprueba que el pendrive sigue puesto. Si se quita, deja de
    contestar aunque el proceso siga vivo.
  - Nunca devuelve el valor salvo en /get, y /get queda en el log de accesos.

Limite honesto: un programa local del mismo usuario puede falsificar Origin y
llamar al puerto. Eso no es una defensa contra malware en la sesion; es una
defensa contra paginas web y contra procesos de otros usuarios. El mismo limite
que ya tiene el resto del proyecto.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cofre.paths import default_vault
from cofre.audit import record
from cofre.crypto import Vault
from cofre.gate import GateUnavailable, resolve_session_key

DEFAULT_PORT = 47653


class _Handler(BaseHTTPRequestHandler):
    server: "SecretServer"

    def log_message(self, fmt: str, *args) -> None:  # silencio: no ensuciar stdout
        pass

    # ---------- utilidades ----------

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin", "")
        return origin in self.server.allowed_origins

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, code: int, error: str) -> None:
        self._send(code, {"ok": False, "error": error})

    def _session(self):
        """Clave de sesión valida ahora mismo. Lanza si el pendrive no esta."""
        session, serial = resolve_session_key(
            self.server.gate, self.server.vault_path, stick=self.server.stick)
        return session, serial

    def _vault(self, session) -> Vault:
        """Cofre ligado al material de la llave (necesario en v2)."""
        vault = Vault(Path(self.server.vault_path))
        if vault.is_v2():
            from cofre.gate import material_for
            vault.bind_material(material_for(self.server.gate, self.server.vault_path,
                                             self.server.stick))
        return vault

    # ---------- rutas ----------

    def do_OPTIONS(self) -> None:  # preflight
        if not self._origin_ok():
            self._reject(403, "origen no autorizado")
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", ""))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._origin_ok():
            record(self.server.vault_path, "bridge-reject", self.server.gate, None,
                   ok=False, detail="origen no autorizado")
            self._reject(403, "origen no autorizado")
            return
        if self.path.startswith("/status"):
            self._status()
        elif self.path.startswith("/list"):
            self._list()
        elif self.path.startswith("/match"):
            self._match()
        else:
            self._reject(404, "ruta desconocida")

    def do_POST(self) -> None:
        if not self._origin_ok():
            record(self.server.vault_path, "bridge-reject", self.server.gate, None,
                   ok=False, detail="origen no autorizado")
            self._reject(403, "origen no autorizado")
            return
        if not self.path.startswith("/get"):
            self._reject(404, "ruta desconocida")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._reject(400, "cuerpo inválido")
            return
        name = str(payload.get("name", "")).strip()
        domain = str(payload.get("domain", "")).strip().lower()
        if not name:
            self._reject(400, "falta el nombre")
            return
        try:
            session, serial = self._session()
        except GateUnavailable as exc:
            record(self.server.vault_path, "browser-get", self.server.gate, None,
                   name=name, ok=False, detail="gate")
            self._reject(409, f"pendrive no disponible: {exc}")
            return
        vault = self._vault(session)

        # R1 (2026-11-16): el dominio se comprueba AQUI, contra los dominios
        # asignados a ESE secreto. Sin asignacion no se rellena en ningun sitio,
        # y un dominio que no coincide se rechaza sin preguntar. La extension no
        # decide nada: solo informa del host de la pestana.
        from cofre.hosts import HostsError, allows, host_matches
        try:
            if vault.is_v2():
                patrones = vault.urls(name)
                if not patrones:
                    permitido, motivo = False, f"'{name}' no tiene ningún sitio asignado"
                elif not host_matches(domain, patrones):
                    permitido, motivo = False, f"'{domain}' no esta asignado a '{name}'"
                else:
                    permitido, motivo = True, ""
            else:
                permitido, motivo = allows(self.server.vault_path, name, domain)
        except HostsError as exc:
            record(self.server.vault_path, "browser-get", self.server.gate, serial,
                   name=name, ok=False, detail="hosts ilegible")
            self._reject(409, f"no se pueden leer los dominios asignados: {exc}")
            return
        if not permitido:
            record(self.server.vault_path, "browser-get", self.server.gate, serial,
                   name=name, ok=False,
                   detail=f"dominio rechazado: {domain or 'sin dominio'}")
            self._reject(403, motivo)
            return

        try:
            value = vault.get(session, name)
        except KeyError:
            record(self.server.vault_path, "browser-get", self.server.gate, serial,
                   name=name, ok=False, detail="no existe")
            self._reject(404, "no existe ese secreto")
            return
        except Exception as exc:
            # Un fallo de descifrado aqui casi siempre es el pendrive equivocado:
            # se responde 409 (autorizacion), no 500 (error del servidor).
            record(self.server.vault_path, "browser-get", self.server.gate, serial,
                   name=name, ok=False, detail=type(exc).__name__)
            self._reject(409, "el pendrive no corresponde a este cofre")
            return
        # H16/H17: queda constancia del dominio donde se relleno, no del valor.
        record(self.server.vault_path, "browser-get", self.server.gate, serial,
               name=name, ok=True, detail=f"dominio={domain or 'sin dominio'}")
        self._send(200, {"ok": True, "name": name, "value": value})

    # ---------- vistas ----------

    def _status(self) -> None:
        try:
            _session, serial = self._session()
        except GateUnavailable as exc:
            self._send(200, {"ok": True, "open": False, "error": str(exc)})
            return
        vault = self._vault(_session)
        self._send(200, {"ok": True, "open": True, "serial": serial,
                         "count": len(vault.names())})

    def _list(self) -> None:
        try:
            self._session()
        except GateUnavailable as exc:
            self._reject(409, f"pendrive no disponible: {exc}")
            return
        vault = self._vault(None)
        data = vault.load().get("entries", {})
        if vault.is_v2():
            nombres = vault.names()
            items = [{"name": n, "tags": vault.meta(n).get("tags", []),
                      "kind": vault.meta(n).get("type", "secret")} for n in nombres]
            record(self.server.vault_path, "browser-list", self.server.gate, None,
                   name=f"{len(items)} nombres", ok=True)
            self._send(200, {"ok": True, "items": items})
            return
        items = []
        for name in sorted(data):
            info = data[name]
            items.append({"name": name,
                          "tags": info.get("tags", []),
                          "kind": info.get("kind", "secret")})
        record(self.server.vault_path, "browser-list", self.server.gate, None,
               name=f"{len(items)} nombres", ok=True)
        self._send(200, {"ok": True, "items": items})


    def _match(self) -> None:
        """4.6: secretos que valen para este host, para el aviso del navegador."""
        from cofre.hosts import host_matches
        try:
            self._session()
        except GateUnavailable as exc:
            self._reject(409, f"pendrive no disponible: {exc}")
            return
        from urllib.parse import parse_qs, urlsplit
        consulta = parse_qs(urlsplit(self.path).query)
        domain = str((consulta.get("domain") or [""])[0]).strip().lower()
        if not domain:
            self._reject(400, "falta el dominio")
            return
        vault = self._vault(None)
        items = []
        for nombre in vault.names():
            try:
                patrones = list(vault.urls(nombre) or [])
            except Exception:                        # noqa: BLE001
                continue
            if patrones and host_matches(domain, patrones):
                meta = dict(vault.meta(nombre) or {})
                items.append({"name": nombre,
                              "kind": meta.get("type") or "secret",
                              "tags": list(meta.get("tags") or []),
                              "exact": domain in [str(p).lower() for p in patrones]})
        record(self.server.vault_path, "browser-list", self.server.gate, None,
               name=f"{len(items)} para {domain}", ok=True, detail="match")
        self._send(200, {"ok": True, "host": domain, "items": items})


class SecretServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, vault_path: str, allowed_origins: list[str],
                 gate: str = "usb", stick: str | None = None,
                 port: int = DEFAULT_PORT):
        super().__init__(("127.0.0.1", port), _Handler)
        self.vault_path = vault_path
        self.allowed_origins = set(allowed_origins)
        self.gate = gate
        self.stick = stick
        self._thread: threading.Thread | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> "SecretServer":
        self._thread = threading.Thread(target=self.serve_forever, daemon=True,
                                        name="cofre-browser-bridge")
        self._thread.start()
        return self

    def stop(self) -> None:
        try:
            self.shutdown()
            self.server_close()
        except Exception:
            pass


def extension_id_from_manifest(manifest_path: Path) -> str | None:
    """El id de una extension empaquetada con 'key' se deduce de su clave publica."""
    try:
        import base64
        import hashlib
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        key = data.get("key")
        if not key:
            return None
        der = base64.b64decode(key)
        digest = hashlib.sha256(der).hexdigest()[:32]
        alphabet = "abcdefghijklmnop"
        return "".join(alphabet[int(ch, 16)] for ch in digest)
    except Exception:
        return None


def allowed_origins_for(manifest_path: Path | None = None) -> list[str]:
    """Origenes permitidos: el de la extension si el manifest tiene 'key'."""
    env = os.environ.get("COFRE_EXTENSION_ID")
    if env:
        return [f"chrome-extension://{env}"]
    manifest = manifest_path or (Path(__file__).resolve().parent.parent
                                 / "extension" / "manifest.json")
    ext_id = extension_id_from_manifest(manifest)
    if ext_id:
        return [f"chrome-extension://{ext_id}"]
    return []


def main(argv: list[str] | None = None) -> int:
    """Arranca solo el puente, sin GUI. Util para depurar con curl.

    H6: antes se leian a mano solo --port y --vault; --gate y --stick se
    ignoraban y el puente sempre usaba 'usb' con el pendrive que encontrara.
    """
    import argparse
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    # A2 de la revision (2026-11-19): el agente no levanta el puente por puerto,
    # ni con COFRE_BRIDGE=tcp. Se comprueba aqui tambien porque `python -m
    # cofre.serve` no pasa por cli.main.
    from cofre import agent_guard
    if agent_guard.activo():
        print("COFRE_AGENT=1: un agente no debe abrir el puente por puerto. "
              "Usa la tuberia (la abre la ventana).", file=sys.stderr)
        return 3
    ap = argparse.ArgumentParser(description="puente loopback del cofre para el navegador")
    ap.add_argument("--vault", default=str(default_vault()))
    ap.add_argument("--gate", default="usb", choices=["pin", "hid", "usb", "usb-pin"])
    ap.add_argument("--stick", help="ruta explicita del COFRE.KEY del pendrive")
    ap.add_argument("--allow-new-stick", action="store_true")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)

    origins = allowed_origins_for()
    if not origins:
        print("sin origenes autorizados: falta 'key' en extension/manifest.json")
        print("ejecuta: python tools/install_extension.py")
        return 1
    server = SecretServer(args.vault, origins, gate=args.gate, stick=args.stick,
                          port=args.port)
    print(f"escuchando en {server.origin}")
    print(f"cofre: {args.vault}  gate: {args.gate}  stick: {args.stick or 'auto'}")
    print(f"origenes permitidos: {', '.join(origins)}")
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
