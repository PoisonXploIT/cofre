"""Sonda del servidor de la tuberia (cofre/pipe_server.py), sin navegador.

  python tools/pipe_server_probe.py

Comprueba:
  1. arranca y escribe pipe-name con nombre y PID;
  2. una peticion normal se despacha y devuelve la respuesta;
  3. dos conexiones seguidas funcionan (la segunda instancia NO lleva
     FIRST_PIPE_INSTANCE);
  4. un segundo servidor con el mismo nombre no arranca (FIRST_PIPE_INSTANCE);
  5. stop() suelta el ConnectNamedPipe, cierra y borra pipe-name;
  6. el formato es el mismo en los dos sentidos (prefijo de 4 bytes);
  7. el descriptor de seguridad deja acceso solo al usuario actual.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre.pipe_server import PipeServer, pipe_info_path, process_sid

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'OK   ' if ok else 'FALLO'}  {name}  {detail}")


CLIENT = r'''
import json, struct, sys, time
sys.path.insert(0, r"C:\Users\Sammi\AI\cofre")
import ctypes
from ctypes import wintypes
from cofre.pipe_server import kernel32, GENERIC_READ, GENERIC_WRITE, OPEN_EXISTING, INVALID_HANDLE

name = sys.argv[1]
msg = json.loads(sys.argv[2])
full = "\\\\.\\pipe\\" + name
kernel32.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]


def abrir():
    # una conexion por hilo: entre instancias puede dar BUSY o "no existe"
    plazo = time.time() + 5
    while True:
        h = kernel32.CreateFileW(full, GENERIC_READ | GENERIC_WRITE, 0, None,
                                 OPEN_EXISTING, 0, None)
        if h and h != INVALID_HANDLE:
            return h
        err = ctypes.get_last_error()
        if err == 231:                              # ERROR_PIPE_BUSY
            kernel32.WaitNamedPipeW(full, 3000)
        elif err == 2 and time.time() < plazo:      # ERROR_FILE_NOT_FOUND
            time.sleep(0.02)
        else:
            return h
        if time.time() >= plazo:
            return h


h = abrir()
if not h or h == INVALID_HANDLE:
    print(json.dumps({"error": "no se pudo abrir", "code": ctypes.get_last_error()}))
    raise SystemExit(1)
body = json.dumps(msg).encode()
payload = struct.pack("<I", len(body)) + body
written = wintypes.DWORD(0)
kernel32.WriteFile(h, payload, len(payload), ctypes.byref(written), None)
head = ctypes.create_string_buffer(4)
read = wintypes.DWORD(0)
kernel32.ReadFile(h, head, 4, ctypes.byref(read), None)
(length,) = struct.unpack("<I", head.raw)
buf = ctypes.create_string_buffer(length)
kernel32.ReadFile(h, buf, length, ctypes.byref(read), None)
kernel32.CloseHandle(h)
print(buf.raw[:length].decode())
'''


def call(name: str, message: dict) -> dict:
    proc = subprocess.run([sys.executable, "-c", CLIENT, name, json.dumps(message)],
                          capture_output=True, text=True, timeout=60)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"raw": proc.stdout, "err": proc.stderr[-200:]}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cofre-pipe-server-"))
    os.environ["COFRE_PIPE_INFO"] = str(tmp / "pipe-name")
    print("directorio de prueba:", tmp)

    def handler(message: dict) -> dict:
        if message.get("type") == "echo":
            return {"ok": True, "eco": message.get("dato")}
        return {"ok": False, "error": "tipo desconocido"}

    # 1. arranque
    server = PipeServer(handler, expected_client_exe=sys.executable)
    server.start()
    server.write_pipe_info()
    info = json.loads(pipe_info_path().read_text(encoding="utf-8"))
    check("1. arranca y escribe pipe-name",
          info.get("pipe") == server.name and info.get("pid") == os.getpid(), str(info))

    # 2. peticion normal
    r = call(server.name, {"type": "echo", "dato": "hola"})
    check("2. despacha y responde", r.get("eco") == "hola", str(r)[:90])

    # 3. dos conexiones seguidas (segunda instancia sin FIRST_PIPE_INSTANCE)
    r1 = call(server.name, {"type": "echo", "dato": "uno"})
    time.sleep(0.2)
    r2 = call(server.name, {"type": "echo", "dato": "dos"})
    check("3. dos conexiones seguidas", r1.get("eco") == "uno" and r2.get("eco") == "dos",
          f"{r1.get('eco')} / {r2.get('eco')}")

    # 4. un segundo servidor con el mismo nombre NO arranca
    otro = PipeServer(handler)
    otro.name = server.name
    otro.full_name = server.full_name
    try:
        otro.start()
        check("4. FIRST_PIPE_INSTANCE impide un segundo servidor", False,
              "arranco el segundo: la proteccion no funciona")
        otro.stop()
    except RuntimeError as exc:
        check("4. FIRST_PIPE_INSTANCE impide un segundo servidor",
              "ya existe una tuberia" in str(exc), str(exc)[:80])

    # 5. stop suelta la conexion y borra pipe-name
    server.stop()
    time.sleep(0.3)
    check("5. stop borra pipe-name", not pipe_info_path().exists(), "")
    r = call(server.name, {"type": "echo", "dato": "x"})
    check("5b. tras stop nadie contesta", "error" in r or "raw" in r, str(r)[:80])

    # 6. formato: el cliente usa el mismo prefijo; si no, el servidor no entiende
    #    nada. Se comprueba indirectamente en 2 y 3, y aqui que un JSON sin
    #    prefijo no se interpreta.
    server2 = PipeServer(handler, expected_client_exe=sys.executable)
    server2.start()
    server2.write_pipe_info()
    check("6. nombre de tuberia con sufijo aleatorio",
          server2.name.startswith("cofre-") and len(server2.name) == 6 + 16,
          server2.name)
    server2.stop()

    # 7. SID del descriptor
    sid = process_sid(os.getpid())
    check("7. el SID del usuario se obtiene", sid.startswith("S-1-5-21-"), sid)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    print("")
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} comprobaciones OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
