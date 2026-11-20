"""M2 de la revisión independiente (2026-11-19): clientes mudos no cuelgan hilos.

Fallo: `_serve` hacía `ReadFile` bloqueante sin plazo. Cada cliente que abría la
tubería y no enviaba nada dejaba un hilo colgado para siempre, y no había tope de
conexiones.

Ahora: espera con `PeekNamedPipe` y plazo de 5 s (`LECTURA_MS`), y como mucho 16
conexiones vivas (`MAX_CONEXIONES`). La prueba baja el plazo a 800 ms para no
tardar.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cofre import pipe_server                              # noqa: E402
from cofre.pipe_server import (GENERIC_READ, GENERIC_WRITE,  # noqa: E402
                               INVALID_HANDLE, OPEN_EXISTING, PipeServer,
                               kernel32)


def _abrir(nombre: str, plazo: float = 10.0):
    fin = time.time() + plazo
    while True:
        handle = kernel32.CreateFileW(nombre, GENERIC_READ | GENERIC_WRITE, 0, None,
                                      OPEN_EXISTING, 0, None)
        if handle and handle != INVALID_HANDLE:
            return handle
        if time.time() > fin:
            return None
        time.sleep(0.02)


class TestClientesMudos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cofre-m2-"))
        os.environ["COFRE_PIPE_INFO"] = str(self.tmp / "pipe-name")
        self.plazo_original = pipe_server.LECTURA_MS
        pipe_server.LECTURA_MS = 800          # rápido en la batería
        self.servidor = PipeServer(lambda _m: {"ok": True},
                                   expected_client_exe=sys.executable).start()

    def tearDown(self):
        pipe_server.LECTURA_MS = self.plazo_original
        self.servidor.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_muchos_clientes_mudos_no_dejan_hilos(self):
        manos = []
        for _ in range(20):
            mano = _abrir(self.servidor.full_name)
            if mano:
                manos.append(mano)
        self.assertGreaterEqual(len(manos), 1)
        # el tope: nunca más de MAX_CONEXIONES vivas
        self.assertLessEqual(self.servidor._vivas, pipe_server.MAX_CONEXIONES)
        # y con el plazo, todas se sueltan solas
        time.sleep(1.8)
        self.assertEqual(self.servidor._vivas, 0,
                         "quedan conexiones mudas ocupando hilos")
        for mano in manos:
            kernel32.CloseHandle(mano)

    def test_una_peticion_normal_sigue_funcionando(self):
        # el plazo no puede romper el caso bueno: el cliente de la sonda manda datos
        import json
        import struct
        handle = _abrir(self.servidor.full_name)
        self.assertTrue(handle)
        cuerpo = json.dumps({"type": "echo"}).encode()
        kernel32.WriteFile(handle, struct.pack("<I", len(cuerpo)) + cuerpo,
                           len(cuerpo) + 4, ctypes.byref(wintypes.DWORD(0)), None)
        cabecera = ctypes.create_string_buffer(4)
        leido = wintypes.DWORD(0)
        kernel32.ReadFile(handle, cabecera, 4, ctypes.byref(leido), None)
        (largo,) = struct.unpack("<I", cabecera.raw)
        cuerpo = ctypes.create_string_buffer(largo)
        kernel32.ReadFile(handle, cuerpo, largo, ctypes.byref(leido), None)
        self.assertEqual(json.loads(cuerpo.raw[:largo]), {"ok": True})
        kernel32.CloseHandle(handle)


class TestReconocerElPropioPython(unittest.TestCase):
    """2026-11-20: la tuberia rechazaba a su propio python.

    Con un venv de Windows el proceso informa de la ruta del interprete base, no
    la de `.venv\Scripts\python.exe`; comparar rutas a pelo hacia que el cliente
    legitimo se quedara sin respuesta (y la prueba de la peticion normal en
    rojo). Se acepta el propio python y se sigue rechazando lo ajeno.
    """

    def test_la_imagen_que_informa_windows_es_el_propio_python(self):
        from cofre.pipe_server import process_image, rutas_del_programa
        imagen = process_image(os.getpid())
        self.assertTrue(imagen)
        self.assertIn(os.path.normcase(os.path.realpath(imagen)),
                      rutas_del_programa(sys.executable))

    def test_un_programa_ajeno_no_cuela(self):
        from cofre.pipe_server import rutas_del_programa
        ajeno = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
        self.assertNotIn(os.path.normcase(os.path.realpath(str(ajeno))),
                         rutas_del_programa(sys.executable))


if __name__ == "__main__":
    unittest.main()
