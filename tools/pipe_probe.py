"""Sonda del puente por tuberia con nombre (paso 4.0.e, sin navegador).

Lanza `python -m cofre.nmhost` como lo haria el navegador y comprueba, con un
servidor de tuberia de prueba, que el repetidor hace lo que debe:

  1. sin fichero de tuberia        -> {"ok": false, "error": "cofre cerrado"}
  2. fichero que apunta a la nada  -> "cofre cerrado"
  3. servidor que no es la GUI     -> "servidor de tuberia no fiable"
  4. servidor de confianza         -> reenvia el mensaje y devuelve la respuesta
  5. respuesta gigante del servidor-> "respuesta demasiado grande"
  6. peticion gigante del navegador-> "mensaje ilegible" (no reserva 4 GB)

No toca el cofre real ni el pendrive: el servidor de prueba contesta lo que se
le diga. La sonda de verdad (cofre abierto / bloqueado) necesita la GUI.

  python tools/pipe_probe.py
"""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import struct
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
INVALID_HANDLE = wintypes.HANDLE(-1).value
BUFFER_SIZE = 64 * 1024

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
kernel32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.LPVOID]
kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                              wintypes.LPDWORD, wintypes.LPVOID]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               wintypes.LPDWORD, wintypes.LPVOID]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


def frame(data: dict) -> bytes:
    body = json.dumps(data).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def read_frame(handle) -> dict | None:
    head = ctypes.create_string_buffer(4)
    read = wintypes.DWORD(0)
    if not kernel32.ReadFile(handle, head, 4, ctypes.byref(read), None)             or read.value != 4:
        return None
    (length,) = struct.unpack("<I", head.raw)
    if length > 8 << 20:
        return None
    body = ctypes.create_string_buffer(length)
    if not kernel32.ReadFile(handle, body, length, ctypes.byref(read), None) \
            or read.value != length:
        return None
    return json.loads(body.raw[:length].decode("utf-8"))


def write_raw(handle, payload: bytes) -> None:
    kernel32.WriteFile(handle, payload, len(payload), ctypes.byref(wintypes.DWORD(0)), None)


class FakeServer(threading.Thread):
    """Servidor de tuberia de prueba. Responde lo que se le diga."""

    def __init__(self, name: str, reply: dict | bytes, raw_reply: bool = False):
        super().__init__(daemon=True)
        self.name = name
        self.reply = reply
        self.raw_reply = raw_reply
        self.received: dict | None = None
        self.error = ""

    def run(self) -> None:
        handle = kernel32.CreateNamedPipeW(
            self.name, PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            1, BUFFER_SIZE, BUFFER_SIZE, 0, None)
        if handle == INVALID_HANDLE or not handle:
            self.error = f"CreateNamedPipe fallo: {ctypes.get_last_error()}"
            return
        try:
            if not kernel32.ConnectNamedPipe(handle, None):
                err = ctypes.get_last_error()
                if err not in (535,):        # ERROR_PIPE_CONNECTED
                    self.error = f"ConnectNamedPipe fallo: {err}"
                    return
            got = read_frame(handle)
            self.received = got
            if self.raw_reply:
                write_raw(handle, self.reply)     # bytes tal cual
            else:
                write_raw(handle, frame(self.reply))
            time.sleep(0.1)
        except Exception as exc:                  # noqa: BLE001
            self.error = str(exc)
        finally:
            kernel32.DisconnectNamedPipe(handle)
            kernel32.CloseHandle(handle)


def run_host(message: dict | bytes, pipe_info: dict | None,
             gui_exe: str = "", raw_message: bool = False) -> dict:
    """Ejecuta nmhost como lo haria el navegador y devuelve su respuesta."""
    env = dict(os.environ)
    env["COFRE_PIPE_INFO"] = str(PIPE_INFO)
    env["COFRE_NM_LOG"] = str(LOG_PATH)
    if gui_exe:
        env["COFRE_GUI_EXE"] = gui_exe
    else:
        env.pop("COFRE_GUI_EXE", None)

    if pipe_info is None:
        PIPE_INFO.unlink(missing_ok=True)
    else:
        PIPE_INFO.write_text(json.dumps(pipe_info), encoding="utf-8")

    payload = message if raw_message else frame(message)
    proc = subprocess.run([sys.executable, "-u", "-m", "cofre.nmhost"],
                          input=payload, capture_output=True, cwd=str(REPO), env=env,
                          timeout=60)
    if len(proc.stdout) < 4:
        return {"ok": False, "error": f"sin respuesta (rc={proc.returncode}) "
                                      f"stderr={proc.stderr.decode('utf-8', 'replace')[:120]}"}
    (length,) = struct.unpack("<I", proc.stdout[:4])
    return json.loads(proc.stdout[4:4 + length].decode("utf-8"))


def main() -> int:
    global PIPE_INFO, LOG_PATH
    tmp = Path(tempfile.mkdtemp(prefix="cofre-pipe-probe-"))
    PIPE_INFO = tmp / "pipe-name"
    LOG_PATH = tmp / "nmhost.log"
    print(f"directorio de prueba: {tmp}")

    # 1. sin fichero de tuberia
    r = run_host({"type": "status"}, None)
    check("1. cofre cerrado (sin tuberia)", r.get("error") == "cofre cerrado", str(r))

    # 2. fichero que apunta a una tuberia que no existe
    r = run_host({"type": "status"}, {"pipe": f"cofre-{secrets.token_hex(8)}", "pid": 999999})
    check("2. cofre cerrado (tuberia inexistente)", r.get("error") == "cofre cerrado", str(r))

    # 3. servidor que no es la GUI: la GUI declara un pid distinto
    name = f"cofre-{secrets.token_hex(8)}"
    fake = FakeServer(rf"\\.\pipe\{name}", {"ok": True, "count": 3})
    fake.start()
    r = run_host({"type": "status"}, {"pipe": name, "pid": 424242}, gui_exe=sys.executable)
    check("3. servidor no fiable rechazado",
          r.get("error") == "servidor de tuberia no fiable", str(r))

    # 4. servidor de confianza (el propio proceso de prueba se declara como GUI)
    name = f"cofre-{secrets.token_hex(8)}"
    trusted = FakeServer(rf"\\.\pipe\{name}", {"ok": True, "open": True, "count": 3})
    trusted.start()
    r = run_host({"type": "status"}, {"pipe": name, "pid": os.getpid()},
                 gui_exe=sys.executable)
    trusted.join(timeout=5)
    check("4. reenvia y devuelve la respuesta",
          r.get("ok") is True and r.get("count") == 3
          and trusted.received == {"type": "status"},
          f"respuesta={r} recibido={trusted.received} error_srv={trusted.error}")

    # 5. respuesta gigante del servidor: no debe reservar memoria
    name = f"cofre-{secrets.token_hex(8)}"
    fake = FakeServer(rf"\\.\pipe\{name}", struct.pack("<I", 0xFFFFFF00), raw_reply=True)
    fake.start()
    r = run_host({"type": "status"}, {"pipe": name, "pid": os.getpid()},
                 gui_exe=sys.executable)
    check("5. respuesta gigante rechazada",
          r.get("error") == "respuesta demasiado grande", str(r))

    # 6. peticion gigante del navegador
    oversized = struct.pack("<I", 0xFFFFFF00) + b"{}"
    r = run_host(oversized, None, raw_message=True)
    check("6. peticion gigante rechazada",
          r.get("error") == "mensaje ilegible", str(r))

    logtxt = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    check("7. el log no contiene valores", "secreto" not in logtxt.lower(),
          f"{len(logtxt.splitlines())} lineas en nmhost.log")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} comprobaciones OK")
    if failed:
        print("pendientes: " + ", ".join(r[0] for r in failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
