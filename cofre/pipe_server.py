r"""COFRE - servidor de la tuberia con nombre (plan 4.0.b, lado GUI).

La GUI es la unica que tiene la sesion abierta. Este servidor:

  - crea `\\.\pipe\cofre-<16 hex>` con FILE_FLAG_FIRST_PIPE_INSTANCE **solo en la
    primera instancia**; las demas, para atender conexiones simultaneas, no;
  - protege la tuberia con un descriptor de seguridad que solo da acceso al SID
    del usuario actual, y con PIPE_REJECT_REMOTE_CLIENTS;
  - escribe `%LOCALAPPDATA%\\cofre\\pipe-name` con el nombre y su PID, y lo borra
    al parar;
  - comprueba al cliente: el proceso que se conecta tiene que ser el interprete
    configurado para el host y del mismo usuario (igual que hace el host con el
    servidor);
  - habla el mismo formato que el host: 4 bytes de longitud little-endian + JSON;
  - **nunca toca Tkinter**: el despacho se hace en un callback que se ejecuta en
    el hilo de la GUI a traves de una cola (ver BridgeController).

Desbloqueo: el hilo esta parado en ConnectNamedPipe. `stop()` abre una conexion
propia a la tuberia para soltarlo, cierra los handles y borra el fichero.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import secrets
import threading
import time
from ctypes import wintypes
from pathlib import Path

MAX_MESSAGE = 1 << 20
BUFFER = 64 * 1024
# M2: un cliente que se conecta y no envia nada no puede quedarse con un hilo.
LECTURA_MS = 5_000         # plazo para recibir la peticion completa
# 32: la sonda de estres abre 20 a la vez (12 de git y 8 del navegador) y hace
# falta sitio para `status` y para el ayudante. Sigue siendo un tope duro.
MAX_CONEXIONES = 32

PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000004
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
PIPE_UNLIMITED_INSTANCES = 255
INVALID_HANDLE = wintypes.HANDLE(-1).value
ERROR_PIPE_CONNECTED = 535
ERROR_PIPE_BUSY = 231
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SDDL_REVISION_1 = 1

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
kernel32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.LPVOID]
kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                              wintypes.LPDWORD, wintypes.LPVOID]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               wintypes.LPDWORD, wintypes.LPVOID]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.LPDWORD, wintypes.LPDWORD]
kernel32.GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, wintypes.LPDWORD]
kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID),
    ctypes.POINTER(wintypes.ULONG)]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.HANDLE)]
advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "cofre"


def pipe_info_path() -> Path:
    return Path(os.environ.get("COFRE_PIPE_INFO") or data_dir() / "pipe-name")


def _sid_string(sid_ptr) -> str:
    out = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(out)):
        return ""
    try:
        return out.value or ""
    finally:
        kernel32.LocalFree(out)


def process_sid(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
            return ""
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(token, 1, buf, size.value, ctypes.byref(size)):
                return ""
            sid_ptr = ctypes.cast(buf, ctypes.POINTER(wintypes.LPVOID)).contents
            return _sid_string(sid_ptr)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(handle)


def process_image(pid: int) -> str:
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


def rutas_del_programa(exe: str) -> set[str]:
    """Ver `cofre.paths.rutas_del_ejecutable`: venv y interprete base son el
    mismo programa. Vive alli porque el ayudante de la tuberia (`nmhost`)
    necesita exactamente la misma cuenta.
    """
    from cofre.paths import rutas_del_ejecutable

    return rutas_del_ejecutable(exe)


def security_descriptor(sid: str):
    """D:P(A;;GA;;;<sid>) — solo ese usuario, y sin acceso remoto.

    Se libera con LocalFree (lo hace el llamante).
    """
    sddl = f"D:P(A;;GA;;;{sid})"
    sd = wintypes.LPVOID()
    size = wintypes.ULONG(0)
    ok = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, SDDL_REVISION_1, ctypes.byref(sd), ctypes.byref(size))
    return sd if ok else None


def _esperar_datos(handle, plazo_ms: int | None = None) -> int:
    """Espera a que haya bytes en la tubería. Devuelve los disponibles o -1.

    M2 de la revision (2026-11-19): `ReadFile` bloqueante sin plazo dejaba un hilo
    colgado por cada cliente que abria y no enviaba nada. Ahora se mira con
    `PeekNamedPipe` (que no bloquea) y, si no llega nada en el plazo, se cierra.
    """
    import time
    plazo_ms = LECTURA_MS if plazo_ms is None else plazo_ms
    fin = time.monotonic() + plazo_ms / 1000
    while True:
        disponible = wintypes.DWORD(0)
        ok = kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(disponible),
                                    None)
        if not ok:
            return -1                      # tuberia rota o cerrada
        if disponible.value:
            return int(disponible.value)
        if time.monotonic() >= fin:
            return -1                      # plazo agotado
        time.sleep(0.02)


def read_frame(handle, plazo_ms: int | None = None) -> dict | None:
    if _esperar_datos(handle, plazo_ms) < 0:
        return None
    head = ctypes.create_string_buffer(4)
    read = wintypes.DWORD(0)
    if not kernel32.ReadFile(handle, head, 4, ctypes.byref(read), None) or read.value != 4:
        return None
    (length,) = __import__("struct").unpack("<I", head.raw)
    if length > MAX_MESSAGE:
        return None
    if _esperar_datos(handle, plazo_ms) < 0:
        return None
    body = ctypes.create_string_buffer(length)
    if not kernel32.ReadFile(handle, body, length, ctypes.byref(read), None) \
            or read.value != length:
        return None
    try:
        return json.loads(body.raw[:length].decode("utf-8"))
    except Exception:
        return None


def write_frame(handle, data: dict) -> bool:
    import struct
    body = json.dumps(data).encode("utf-8")
    if len(body) > MAX_MESSAGE:
        return False
    payload = struct.pack("<I", len(body)) + body
    written = wintypes.DWORD(0)
    return bool(kernel32.WriteFile(handle, payload, len(payload),
                                   ctypes.byref(written), None) and written.value == len(payload))


class PipeServer:
    """Servidor de la tuberia. `handler(message)` se ejecuta en el hilo llamante.

    El handler debe ser rapido o delegar: no puede tocar Tkinter. Para la GUI se
    usa BridgeController, que pasa la peticion al hilo de la ventana.
    """

    def __init__(self, handler, name: str | None = None,
                 expected_client_exe: str | None = None, log=None):
        self.handler = handler
        self.name = name or f"cofre-{secrets.token_hex(8)}"
        self.full_name = rf"\\.\pipe\{self.name}"
        self.expected_client_exe = expected_client_exe
        self.log = log or (lambda msg: None)
        self.ready = threading.Event()
        self.failed = ""
        self._stop = threading.Event()
        self._first_instance_used = False
        self._sid = ""
        self._last_client: dict = {}
        self._vivas = 0
        self._cuenta_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- ciclo

    def start(self) -> "PipeServer":
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="cofre-pipe-server")
        self._thread.start()
        self.ready.wait(timeout=5)
        if self.failed:
            raise RuntimeError(self.failed)
        return self

    def stop(self) -> None:
        self._stop.set()
        # soltar el ConnectNamedPipe con una conexion propia
        try:
            h = kernel32.CreateFileW(self.full_name, GENERIC_READ | GENERIC_WRITE, 0,
                                     None, OPEN_EXISTING, 0, None)
            if h and h != INVALID_HANDLE:
                kernel32.CloseHandle(h)
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=3)
        try:
            pipe_info_path().unlink(missing_ok=True)
        except OSError:
            pass

    # ---------------------------------------------------------------- interno

    def _create(self, first: bool):
        self._sid = self._sid or process_sid(os.getpid())
        sd = security_descriptor(self._sid) if self._sid else None
        flags = PIPE_ACCESS_DUPLEX
        if first:
            flags |= 0x00080000          # FILE_FLAG_FIRST_PIPE_INSTANCE
        handle = kernel32.CreateNamedPipeW(
            self.full_name, flags,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            PIPE_UNLIMITED_INSTANCES, BUFFER, BUFFER, 0, sd)
        if sd:
            kernel32.LocalFree(sd)
        if not handle or handle == INVALID_HANDLE:
            err = ctypes.get_last_error()
            if first and err == 5:
                self.failed = ("ya existe una tuberia con ese nombre: otro proceso se ha "
                               "adelantado. No se arranca el puente.")
            else:
                self.failed = f"CreateNamedPipeW fallo: error {err}"
            return None
        self._first_instance_used = True
        return handle

    def _client_ok(self, handle) -> tuple[bool, str]:
        pid = wintypes.DWORD(0)
        if not kernel32.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)):
            return False, "no se pudo identificar al cliente"
        image = process_image(int(pid.value))
        if self.expected_client_exe:
            if os.path.normcase(os.path.realpath(image)) not in rutas_del_programa(
                    self.expected_client_exe):
                return False, f"cliente inesperado: {image or 'desconocido'}"
        sid = process_sid(int(pid.value))
        if not sid or sid != (self._sid or process_sid(os.getpid())):
            return False, "el cliente es de otro usuario"
        self._last_client = {"pid": int(pid.value), "image": image}
        return True, f"pid {pid.value}"

    def _run(self) -> None:
        while not self._stop.is_set():
            handle = self._create(first=not self._first_instance_used)
            if handle is None:
                self.ready.set()
                return
            self.ready.set()
            try:
                if not kernel32.ConnectNamedPipe(handle, None):
                    err = ctypes.get_last_error()
                    if err not in (ERROR_PIPE_CONNECTED, 0):
                        kernel32.CloseHandle(handle)
                        if self._stop.is_set():
                            break
                        self.log(f"ConnectNamedPipe error {err}")
                        continue
                if self._stop.is_set():
                    kernel32.DisconnectNamedPipe(handle)
                    kernel32.CloseHandle(handle)
                    break
                ok, motivo = self._client_ok(handle)
                if not ok:
                    self.log(f"cliente rechazado: {motivo}")
                    kernel32.DisconnectNamedPipe(handle)
                    kernel32.CloseHandle(handle)
                    continue
                # Una conexion = un hilo. Si el despacho pide confirmacion y
                # espera 20 s, las demas peticiones no se quedan detras:
                # mientras el dialogo esta abierto, el cofre sigue contestando
                # a `status` y a las peticiones de un host ya permitido.
                cliente = dict(self._last_client)
                # M2: tope de conexiones vivas. Si se llega, se cierra sin
                # atender: mejor eso que un hilo por cada cliente curioso.
                with self._cuenta_lock:
                    vivas = self._vivas
                if vivas >= MAX_CONEXIONES:
                    self.log(f"demasiadas conexiones ({vivas}); se cierra esta")
                    # se contesta para que el cliente no se quede esperando
                    write_frame(handle, {"ok": False,
                                         "error": "demasiadas conexiones al cofre"})
                    kernel32.FlushFileBuffers(handle)
                    kernel32.DisconnectNamedPipe(handle)
                    kernel32.CloseHandle(handle)
                    continue
                with self._cuenta_lock:
                    self._vivas += 1
                obrero = threading.Thread(target=self._serve, args=(handle, cliente),
                                          daemon=True, name="cofre-pipe-conn")
                obrero.start()
            except Exception as exc:                         # noqa: BLE001
                self.log(f"fallo al aceptar la conexion: {type(exc).__name__}")
                try:
                    kernel32.DisconnectNamedPipe(handle)
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
        # limpieza final
        try:
            pipe_info_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _serve(self, handle, cliente: dict) -> None:
        """Atiende una conexion ya aceptada y validada (hilo propio)."""
        try:
            message = read_frame(handle)
            if message is None:
                self.log("mensaje ilegible del cliente")
                return
            if isinstance(message, dict):
                message["_client"] = dict(cliente)
            try:
                reply = self.handler(message)
            except Exception as exc:                         # noqa: BLE001
                self.log(f"el manejador fallo: {type(exc).__name__}")
                reply = {"ok": False, "error": "fallo interno del cofre"}
            if not write_frame(handle, reply or {"ok": False, "error": "sin respuesta"}):
                self.log("no se pudo escribir la respuesta")
            else:
                # Sin esto, DisconnectNamedPipe tira los datos antes de que
                # el cliente los lea (ERROR_PIPE_NOT_CONNECTED en el host).
                kernel32.FlushFileBuffers(handle)
        finally:
            kernel32.DisconnectNamedPipe(handle)
            kernel32.CloseHandle(handle)
            with self._cuenta_lock:
                self._vivas = max(0, self._vivas - 1)

    def write_pipe_info(self, extra: dict | None = None) -> Path:
        """Nombre y PID. Solo eso: nada que sirva para abrir el cofre."""
        info = {"pipe": self.name, "pid": os.getpid(),
                "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
        info.update(extra or {})
        path = pipe_info_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        from cofre.paths import atomic_write
        return atomic_write(path, json.dumps(info, indent=2))


class BridgeController:
    """Puente entre los hilos de la tuberia y la GUI (corregido 2026-11-18).

    El despacho corre en el hilo de la tuberia, **nunca en el de Tkinter**:
    aqui se lee el cofre y, cuando hace falta confirmar, se encola en la
    ConfirmQueue; el unico hilo que espera es este. Lo que haya que pintar va
    al hilo de la ventana con `ui_call`.

    Antes el despacho se hacia en el hilo de Tk: al pedir confirmacion se abria
    un `wait_window()` dentro del propio sondeo y Tk se quedaba sin vaciar la
    cola. Ahora el sondeo solo atiende `ui_call` y confirmaciones.
    """

    def __init__(self, root, dispatch, log=None):
        self.root = root
        self.dispatch = dispatch          # corre en el hilo de la tuberia
        self.log = log or (lambda msg: None)
        self.requests: queue.Queue = queue.Queue()
        self.server: PipeServer | None = None

    def _handler(self, message: dict) -> dict:
        try:
            respuesta = self.dispatch(message)
        except Exception as exc:                              # noqa: BLE001
            self.log(f"fallo al despachar: {type(exc).__name__}")
            return {"ok": False, "error": f"fallo: {type(exc).__name__}"}
        return respuesta or {"ok": False, "error": "sin respuesta"}

    def poll(self) -> bool:
        """Se mantiene por compatibilidad: el despacho ya no pasa por aquí."""
        return False


    def start(self, expected_client_exe: str | None = None) -> None:
        self.server = PipeServer(self._handler, expected_client_exe=expected_client_exe,
                                 log=self.log).start()
        self.server.write_pipe_info()

    def stop(self) -> None:
        if self.server:
            self.server.stop()
            self.server = None
