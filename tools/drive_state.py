"""Comprueba el estado del volumen E: sin colgarse (topes de tiempo)."""
import ctypes
import string
import sys
import threading
import time

k32 = ctypes.windll.kernel32
KEY = "COFRE.KEY"


def kind(letter: str) -> int:
    return int(k32.GetDriveTypeW(ctypes.c_wchar_p(letter + ":\\")))


def volume_info(letter: str, timeout: float = 5.0) -> dict:
    out: dict = {}

    def probe() -> None:
        buf = ctypes.create_string_buffer(64)
        serial = ctypes.c_ulong(0)
        ok = k32.GetVolumeInformationW(
            ctypes.c_wchar_p(letter + ":\\"), buf, 64, ctypes.byref(serial),
            None, None, None, 0)
        out["ok"] = bool(ok)
        out["serial"] = int(serial.value)
        out["label"] = buf.value.decode("utf-8", "replace")
        out["err"] = ctypes.get_last_error()

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return {"estado": f"BLOQUEA (>{timeout} s)"}
    return out


def open_test(letter: str, timeout: float = 5.0) -> str:
    import pathlib
    res: dict = {}

    def probe() -> None:
        start = time.time()
        try:
            res["existe"] = (pathlib.Path(letter + ":\\") / KEY).is_file()
        except OSError as exc:
            res["error"] = str(exc)
        res["segundos"] = round(time.time() - start, 2)

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return f"abrir {letter}:\\{KEY} -> BLOQUEA (>{timeout} s)"
    return f"abrir {letter}:\\{KEY} -> {res}"


def main() -> int:
    mask = k32.GetLogicalDrives()
    letters = [c for c in string.ascii_uppercase if mask & (1 << (ord(c) - 65))]
    print("letras:", letters)
    for letter in letters:
        print(f"\n{letter}: tipo={kind(letter)}")
        print("  info:", volume_info(letter))
        print(" ", open_test(letter))
    return 0


if __name__ == "__main__":
    sys.exit(main())
