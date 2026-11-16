"""COFRE - host de mensajeria nativa (repetidor tonto).

Este proceso lo lanza el navegador, uno nuevo por cada mensaje de la extension.
NO abre el cofre, NO lee el pendrive, NO importa crypto ni gate: no tiene
secretos. Solo traduce stdio (lo que habla el navegador) a la tuberia con
nombre donde escucha la GUI, y devuelve la respuesta.

Protocolo (los dos lados):
    4 bytes  longitud del JSON en little-endian
    N bytes  JSON UTF-8

Lo que hace para no ser un tonto util:
  - tope de tamano (1 MiB) al leer, para que nadie pida 4 GB;
  - temporizador en todo: el navegador NO tiene timeout y dejaria la promesa
    colgada para siempre;
  - si no existe la tuberia: "cofre cerrado" (es la verdad, no un error);
  - comprueba que el servidor de la tuberia es el proceso que la GUI declaro
    en el fichero de la tuberia, y que su ejecutable es el esperado;
  - los errores van a nmhost.log, nunca a stdout (stdout es del protocolo).

Ver el plan, paso 4.0.b.
"""

from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes
from pathlib import Path

MAX_MESSAGE = 1 << 20          # 1 MiB
CONNECT_TIMEOUT_MS = 3000
REPLY_TIMEOUT_MS = 3000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
ERROR_PIPE_BUSY = 231
ERROR_FILE_NOT_FOUND = 2
ERROR_PIPE_NOT_CONNECTED = 233

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                   wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD]
kernel32.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               wintypes.LPDWORD, wintypes.LPVOID]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                              wintypes.LPDWORD, wintypes.LPVOID]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, wintypes.LPDWORD]


# ---------------------------------------------------------------- utilidades

def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "cofre"


def pipe_info_path() -> Path:
    return Path(os.environ.get("COFRE_PIPE_INFO") or data_dir() / "pipe-name")


def log(message: str) -> None:
    """Errores y diagnostico. Nunca el valor de un secreto."""
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} pid={os.getpid()} {message}\n"
    try:
        path = Path(os.environ.get("COFRE_NM_LOG") or data_dir() / "nmhost.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass          # un log que falla no puede romper el host


# ---------------------------------------------------------------- protocolo

def read_message(stream) -> dict | None:
    head = stream.read(4)
    if len(head) != 4:
        return None
    (length,) = struct.unpack("<I", head)
    if length > MAX_MESSAGE:
        log(f"mensaje demasiado grande: {length} bytes")
        return None
    body = stream.read(length)
    if len(body) != length:
        log(f"cuerpo incompleto: {len(body)}/{length}")
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        log(f"JSON invalido: {exc}")
        return None
    return data if isinstance(data, dict) else None


def write_message(stream, data: dict) -> None:
    body = json.dumps(data).encode("utf-8")
    stream.write(struct.pack("<I", len(body)) + body)
    stream.flush()


def error(text: str, **extra) -> dict:
    out = {"ok": False, "error": text}
    out.update(extra)
    return out


# ---------------------------------------------------------------- tuberia

def read_pipe_info() -> dict | None:
    """Lo escribe la GUI al abrir el puente. Solo el nombre y su PID."""
    path = pipe_info_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        log(f"pipe-name ilegible: {path}")
        return None
    if not isinstance(info, dict) or not info.get("pipe"):
        return None
    return info


def expected_server_image() -> str:
    """Ejecutable del servidor de la tuberia (la GUI). Configurable para pruebas."""
    return os.environ.get("COFRE_GUI_EXE", "").strip().lower()


def image_path_of(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def server_is_trusted(handle) -> tuple[bool, str]:
    pid = wintypes.DWORD(0)
    if not kernel32.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)):
        return False, "no se pudo identificar el servidor"
    info = read_pipe_info() or {}
    declared = info.get("pid")
    if declared and int(declared) != int(pid.value):
        return False, f"el servidor (pid {pid.value}) no es el que declaro la GUI ({declared})"
    image = image_path_of(pid.value)
    expected = expected_server_image()
    if expected and os.path.normcase(image) != os.path.normcase(expected):
        return False, f"ejecutable del servidor inesperado: {image or 'desconocido'}"
    return True, f"pid {pid.value}"


def wait_for_data(handle, timeout_ms: int) -> int:
    deadline = time.time() + timeout_ms / 1000.0
    available = wintypes.DWORD(0)
    while time.time() < deadline:
        if not kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            return -1
        if available.value:
            return int(available.value)
        time.sleep(0.02)
    return 0


def forward(message: dict) -> dict:
    info = read_pipe_info()
    if not info:
        return error("cofre cerrado")

    pipe = str(info["pipe"])
    name = pipe if pipe.startswith("\\\\") else f"\\\\.\\pipe\\{pipe}"

    handle = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None,
                                  OPEN_EXISTING, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        err = ctypes.get_last_error()
        if err == ERROR_PIPE_BUSY:
            kernel32.WaitNamedPipeW(name, CONNECT_TIMEOUT_MS)
            handle = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None,
                                          OPEN_EXISTING, 0, None)
        if handle in (None, wintypes.HANDLE(-1).value):
            log(f"no se pudo abrir la tuberia {name}: error {ctypes.get_last_error()}")
            return error("cofre cerrado")

    try:
        ok, detail = server_is_trusted(handle)
        if not ok:
            log(f"servidor no fiable ({detail})")
            return error("servidor de tuberia no fiable")
        log(f"conectado a {name} ({detail})")

        body = json.dumps(message).encode("utf-8")
        if len(body) > MAX_MESSAGE:
            return error("mensaje demasiado grande")
        payload = struct.pack("<I", len(body)) + body      # mismo formato que stdio
        written = wintypes.DWORD(0)
        if not kernel32.WriteFile(handle, payload, len(payload),
                                  ctypes.byref(written), None) \
                or written.value != len(payload):
            log(f"escritura incompleta: {written.value}/{len(payload)} "
                f"error {ctypes.get_last_error()}")
            return error("no se pudo enviar al cofre")

        if wait_for_data(handle, REPLY_TIMEOUT_MS) <= 0:
            log("el servidor no respondio a tiempo")
            return error("sin respuesta del cofre")

        head = ctypes.create_string_buffer(4)
        read = wintypes.DWORD(0)
        if not kernel32.ReadFile(handle, head, 4, ctypes.byref(read), None) or read.value != 4:
            return error("respuesta incompleta del cofre")
        (length,) = struct.unpack("<I", head.raw)
        if length > MAX_MESSAGE:
            log(f"respuesta demasiado grande: {length}")
            return error("respuesta demasiado grande")
        payload = ctypes.create_string_buffer(length)
        if not kernel32.ReadFile(handle, payload, length, ctypes.byref(read), None) \
                or read.value != length:
            return error("respuesta incompleta del cofre")
        try:
            return json.loads(payload.raw[:length].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log(f"respuesta invalida: {exc}")
            return error("respuesta invalida del cofre")
    finally:
        kernel32.CloseHandle(handle)


def main() -> int:
    stdin = getattr(sys.stdin, "buffer", None)
    stdout = getattr(sys.stdout, "buffer", None)
    if stdin is None or stdout is None:
        # Con pythonw y segun como se herede el handle, stdin llega None.
        # Mejor fallar de forma visible que colgarse sin decir nada.
        log("stdin/stdout no disponibles; usa python.exe -u, no pythonw")
        return 1

    message = read_message(stdin)
    if message is None:
        write_message(stdout, error("mensaje ilegible"))
        return 0

    reply = forward(message)
    write_message(stdout, reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
