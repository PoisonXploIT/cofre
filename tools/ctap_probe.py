"""Probe CTAP2/HID de la llave FIDO2: INIT + GET_INFO, y si se puede, hmac-secret.

Detalles que han costado (2026-11-08):
- El interface FIDO se enumera (usage page 0xF1D0) pero CreateFileW da err=5
  (ERROR_ACCESS_DENIED) la mayor parte del tiempo. En alguna ocasion si se abre:
  el acceso es intermitente, muy probablemente porque el driver FIDO de Windows
  (fidohid.inf) o el servicio WebAuthn del navegador tienen el dispositivo
  reservado.
- HidD_SetFeature da err=1 (ERROR_INVALID_FUNCTION): los dispositivos CTAP no
  tienen feature report. La escritura correcta es WriteFile con el reporte de
  salida, y el primer byte es el report ID (0x00) + 64 bytes de paquete CTAP.
  (Igual que hace fido2: out = b"\0" + data, y se leen report_size_in + 1 bytes.)

Uso:
  python tools/ctap_probe.py                 # busca la llave, INIT + GET_INFO
  python tools/ctap_probe.py --retries 20
"""
import argparse
import ctypes
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hid_enum import (GENERIC_READ, GENERIC_WRITE, FILE_SHARE_READ_WRITE, OPEN_EXISTING,
                      INVALID_HANDLE, list_hid_paths, usage_from_registry, kernel32, hid)

CTAPHID_INIT = 0x06
CTAPHID_MSG = 0x03
GET_INFO = 0x01
FIDO_PAGE, FIDO_USAGE = 0xF1D0, 0x0001


def product_string(handle):
    buf = ctypes.create_string_buffer(256)
    if hid.HidD_GetProductString(handle, buf, 256):
        return buf.value.decode("utf-16", "replace")
    return None


def find_fido_path():
    for path, inst in list_hid_paths():
        if usage_from_registry(inst) == (FIDO_PAGE, FIDO_USAGE):
            return path
    return None


def open_with_retry(path, retries=10, delay=0.5):
    last_err = 0
    for i in range(retries):
        h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                 FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
        if h not in (None, INVALID_HANDLE):
            return h, i
        last_err = kernel32.GetLastError()
        print("  intento %d: err=%d" % (i + 1, last_err))
        time.sleep(delay)
    return None, last_err


def caps(handle):
    pp = ctypes.c_void_p(0)
    if not hid.HidD_GetPreparsedData(handle, ctypes.byref(pp)):
        return None
    buf = (ctypes.c_ubyte * 128)()
    ret = hid.HidP_GetCaps(pp, buf)
    hid.HidD_FreePreparsedData(pp)
    if ret != 0x00110000:
        return None
    b = bytes(buf)
    return (int.from_bytes(b[0:2], "little"), int.from_bytes(b[2:4], "little"),
            int.from_bytes(b[4:6], "little"), int.from_bytes(b[6:8], "little"),
            int.from_bytes(b[8:10], "little"))


def packet(cmd, channel, seq, payload):
    out = bytearray(64)
    out[0] = 0x80 if seq == 0 else 0x00
    out[1:5] = channel.to_bytes(4, "big")
    out[5] = cmd if seq == 0 else 0x00
    out[6] = seq
    out[7:7 + len(payload)] = payload
    return out


def make_report(pkt, report_len, framing="id0"):
    """Ajusta el paquete CTAP de 64 bytes al tamano real del reporte HID.

    Esta llave reporta Input/OutputReportByteLength = 65: el reporte incluye el
    report ID (0x00) + 64 bytes de paquete CTAP. id0 es el framing correcto segun
    la spec; noprefix y raw64 son variantes para descartar que el problema sea la
    forma del paquete.
    """
    if framing == "noprefix":
        return bytes(pkt)[:report_len]
    if framing == "raw64":
        return (bytes(pkt) + b"\x00" * 64)[:report_len]
    if report_len == 64:
        return bytes(pkt)
    return b"\x00" + bytes(pkt)


def send(handle, cmd, channel, payload, out_len, framing="id0"):
    total = len(payload)
    seq = 0
    while True:
        chunk = payload[seq * 57:(seq + 1) * 57]
        data = make_report(packet(cmd, channel, seq, chunk), out_len, framing)
        buf = ctypes.create_string_buffer(len(data))
        buf[:] = data
        written = ctypes.c_ulong(0)
        if not kernel32.WriteFile(handle, buf, len(data), ctypes.byref(written), None):
            raise OSError("WriteFile fallo (err=%d)" % kernel32.GetLastError())
        if written.value != len(data):
            raise OSError("WriteFile corto: %d de %d" % (written.value, len(data)))
        if (seq + 1) * 57 >= total:
            return
        seq += 1


def read_packet(handle, in_len, timeout=5.0, framing="id0"):
    """ReadFile de un reporte HID, con watchdog: si la llave no responde,
    cerrar el handle desde otro hilo desbloquea la lectura y devolvemos None.
    Sin esto el probe se queda colgado y parece que 'no hace nada'.
    """
    data = make_report(bytearray(64), in_len, framing)
    buf = ctypes.create_string_buffer(len(data))
    read = ctypes.c_ulong(0)
    outcome = {}

    def worker():
        ok = kernel32.ReadFile(handle, buf, len(data), ctypes.byref(read), None)
        outcome["ok"] = ok
        outcome["err"] = kernel32.GetLastError()
        outcome["n"] = read.value
        outcome["raw"] = buf.raw[:read.value]

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, "timeout"
    if not outcome.get("ok"):
        return None, "err %d" % outcome.get("err", 0)
    raw = outcome["raw"]
    if in_len == 65 and len(raw) >= 1:
        raw = raw[1:]  # quitar el report ID
    return raw, None


def recv(handle, expected_cmd, in_len, max_packets=30, timeout=5.0, framing="id0"):
    payload = bytearray()
    channel = None
    for _ in range(max_packets):
        raw, problem = read_packet(handle, in_len, timeout, framing)
        if problem:
            raise OSError("sin respuesta de la llave (%s)" % problem)
        b = raw
        ch = int.from_bytes(b[1:5], "big")
        cmd = b[5]
        seq = b[6]
        if ch == 0xFFFFFFFF:
            continue
        if channel is None:
            channel = ch
        if cmd not in (0x00, expected_cmd):
            raise OSError("comando CTAP inesperado 0x%02x" % cmd)
        payload.extend(b[7:])
        if (seq + 1) * 57 > len(payload):
            break
    return channel, bytes(payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path")
    ap.add_argument("--retries", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--framing", choices=["id0", "noprefix", "raw64"], default="id0",
                    help="id0: report ID 0x00 + 64 bytes (estandar CTAP2 en Windows). "
                         "noprefix: el paquete tal cual. raw64: paquete 64 sin ID, "
                         "relleno a tamano de reporte.")
    ap.add_argument("--listen", action="store_true",
                    help="solo leer, sin escribir: comprueba si la llave emite algo")
    args = ap.parse_args()

    path = args.path or find_fido_path()
    if not path:
        print("No se encontró ninguna interfaz con usage page 0xF1D0.")
        return 1
    print("interfaz FIDO:", path)

    handle, info = open_with_retry(path, args.retries)
    if handle is None:
        print("CreateFileW no pudo abrir la llave en %d intentos (último err=%d)."
              % (args.retries, info))
        print("El interface esta enumerado pero el driver FIDO (fidohid.inf) no")
        print("permite abrirlo desde este proceso. Pruebas a hacer:")
        print("  - cerrar Chrome/Edge y repetir (el servicio WebAuthn puede tener")
        print("    el dispositivo reservado);")
        print("  - repetir desde una consola elevada;")
        print("  - comparar con otra llave FIDO en el mismo puerto.")
        return 2

    print("handle abierto tras %d intento(s)" % info)
    c = caps(handle)
    print("caps (usage, page, in, out, feature): %s" % (c,))
    print("producto: %s" % product_string(handle))
    in_len = c[2] if c else 64
    out_len = c[3] if c else 64

    try:
        if args.listen:
            print("escuchando el interface sin escribir nada (%s s)..." % args.timeout)
            raw, problem = read_packet(handle, in_len, args.timeout, args.framing)
            if problem:
                print("la llave no emite nada por si misma:", problem)
                return 3
            print("emitido: %s" % raw.hex())
            return 0
        print("escribiendo INIT (nonce de 8 bytes, framing %s)..." % args.framing)
        send(handle, CTAPHID_INIT, 0, os.urandom(8), out_len, args.framing)
        print("leyendo respuesta INIT (%s s). Toque el boton de la llave." % args.timeout)
        _, resp = recv(handle, CTAPHID_INIT, in_len, timeout=args.timeout, framing=args.framing)
        channel = int.from_bytes(resp[:4], "big")
        print("INIT OK, canal=%08x, capabilities=0x%02x" % (channel, resp[8] if len(resp) > 8 else 0))
        print("escribiendo GET_INFO...")
        send(handle, CTAPHID_MSG, channel, b"\x81\x01", out_len, args.framing)
        _, data = recv(handle, CTAPHID_MSG, in_len, timeout=args.timeout, framing=args.framing)
        print("GET_INFO (%d bytes): %s" % (len(data), data.hex()))
        try:
            import cbor2
            gi = cbor2.loads(data)
            print("versión:", gi.get("versión"))
            print("extensions:", gi.get("extensions"))
            print("algorithms:", gi.get("algorithms"))
            print("options:", gi.get("options"))
        except ImportError:
            print("pip install cbor2 para decodificar GET_INFO.")
    except OSError as exc:
        print("CTAP2 fallo:", exc)
        print("La llave se abre pero no responde: hay que tocar su boton para que")
        print("CTAP2 conteste, o el interface esta medio bloqueado por el driver")
        print("FIDO de Windows.")
        return 3
    finally:
        kernel32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
