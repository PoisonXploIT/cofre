"""Enumerador HID propio (WinAPI) para localizar la llave FIDO2.

Corregido el 2026-11-08. Los dos errores que daban err=6 en
SetupDiEnumDeviceInterfaces eran:
  1. setupapi no tenia argtypes: ctypes pasaba el HDEVINFO (puntero de 64 bits)
     como c_int -> handle truncado -> ERROR_INVALID_HANDLE (6).
  2. SP_DEVICE_INTERFACE_DETAIL_DATA: cbSize debe ser 8 en x64, no sizeof(struct).
     La ruta se lee desde el offset 4 del buffer.

La deteccion de FIDO (usage page 0xF1D0, usage 0x0001) se hace por dos vias:
  - HidP_GetCaps si el dispositivo se puede abrir.
  - HardwareID del registro (contiene "UP:F1D0_U:0001") si CreateFileW falla,
    que es el caso de las llaves FIDO en Windows 11 (driver fidohid.inf).

Uso: python tools/hid_enum.py
"""
import ctypes
import re
import winreg
from ctypes import wintypes

GUID = type("GUID", (ctypes.Structure,), {
    "_fields_": [("Data1", wintypes.DWORD),
                 ("Data2", wintypes.WORD),
                 ("Data3", wintypes.WORD),
                 ("Data4", ctypes.c_ubyte * 8)]})

hid = ctypes.WinDLL("hid")
setupapi = ctypes.WinDLL("setupapi")
kernel32 = ctypes.WinDLL("kernel32")

SP_DEVICE_INTERFACE_DATA = type("SP_DEVICE_INTERFACE_DATA", (ctypes.Structure,), {
    "_fields_": [("cbSize", wintypes.DWORD),
                 ("DeviceInstance", GUID),
                 ("Reserved", ctypes.c_void_p)]})

FIDO_PAGE, FIDO_USAGE = 0xF1D0, 0x0001
DETAIL_CBSIZE = 8  # x64, version A
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ_WRITE = 0x03
OPEN_EXISTING = 0x03
INVALID_HANDLE = (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1

kernel32.GetLastError.restype = wintypes.DWORD
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

setupapi.SetupDiGetClassDevsA.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsA.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
                                          ctypes.c_void_p, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOLEAN
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.POINTER(GUID), wintypes.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailA.restype = wintypes.BOOLEAN
setupapi.SetupDiGetDeviceInterfaceDetailA.argtypes = [ctypes.c_void_p,
                                                      ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wintypes.DWORD,
                                                      ctypes.POINTER(wintypes.DWORD),
                                                      ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOLEAN
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

hid.HidD_GetHidGuid.restype = None
hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
hid.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.restype = ctypes.c_long
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


def hid_guid():
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    return g


def list_hid_paths():
    """Todas las interfaces HID presentes, como (path, instance_id)."""
    g = hid_guid()
    hdev = setupapi.SetupDiGetClassDevsA(ctypes.byref(g), None, None,
                                        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev is None or hdev == INVALID_HANDLE:
        raise OSError("SetupDiGetClassDevsA fallo (err=%d)" % kernel32.GetLastError())
    out = []
    i = 0
    while True:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
        if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(g), i,
                                                   ctypes.byref(did)):
            err = kernel32.GetLastError()
            if err != 251:  # ERROR_NO_MORE_ITEMS
                print("  [!] enumeracion i=%d err=%d" % (i, err))
            break
        req = wintypes.DWORD(0)
        setupapi.SetupDiGetDeviceInterfaceDetailA(hdev, ctypes.byref(did), None, 0,
                                                  ctypes.byref(req), None)
        size = req.value or 1024
        buf = (ctypes.c_ubyte * size)()
        buf[0:4] = DETAIL_CBSIZE.to_bytes(4, "little")
        if setupapi.SetupDiGetDeviceInterfaceDetailA(hdev, ctypes.byref(did), buf, size,
                                                    None, None):
            path = bytes(buf[4:size]).split(b"\x00")[0].decode("ascii", "replace")
            # \\?\hid#<class>_<id>#<instance>#{guid}  -> las dos piezas entre '#' 1 y 3
            parts = path.split("#")
            inst = "#".join(parts[1:3]) if len(parts) > 2 else ""
            out.append((path, inst))
        i += 1
    setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


def usage_from_registry(instance_id):
    """Lee HardwareID del registro; devuelve (usage_page, usage) o None."""
    # El path de la interfaz usa '#' como separador de la instancia:
    # vid_096e&pid_0854&mi_01 + a&2eb92e31&0&0000
    parts = instance_id.split("#")
    if len(parts) < 2:
        return None
    key = r"SYSTEM\CurrentControlSet\Enum\HID\%s\%s" % (parts[0].upper(), parts[1].lower())
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as h:
            hw, _ = winreg.QueryValueEx(h, "HardwareID")
        if isinstance(hw, (list, tuple)):
            hw = " ".join(hw)
        for tok in re.findall(r"UP:([0-9A-Fa-f]+)_U:([0-9A-Fa-f]+)", hw):
            return int(tok[0], 16), int(tok[1], 16)
    except OSError:
        return None
    return None


def caps_for(handle):
    pp = ctypes.c_void_p(0)
    if not hid.HidD_GetPreparsedData(handle, ctypes.byref(pp)):
        return None
    buf = (ctypes.c_ubyte * 128)()
    ret = hid.HidP_GetCaps(pp, buf)
    hid.HidD_FreePreparsedData(pp)
    if ret != 0x00110000:  # HIDP_STATUS_SUCCESS
        return None
    b = bytes(buf)
    a, c = int.from_bytes(b[0:2], "little"), int.from_bytes(b[2:4], "little")
    return a, c, int.from_bytes(b[4:6], "little"), int.from_bytes(b[6:8], "little")


def main():
    paths = list_hid_paths()
    print("interfaces HID presentes: %d" % len(paths))
    fido = []
    for path, inst in paths:
        h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                 FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
        if h is None or h == INVALID_HANDLE:
            err = kernel32.GetLastError()
            reg = usage_from_registry(inst)
            is_fido = reg == (FIDO_PAGE, FIDO_USAGE)
            print("  %-14s %s" % ("FIDO" if is_fido else "cerrado(err=%d)" % err, path))
            if reg:
                print("     usage registry: %04x/%04x" % reg)
            if is_fido:
                fido.append((path, None, err))
            continue
        caps = caps_for(h)
        kernel32.CloseHandle(h)
        if caps:
            a, c, in_len, out_len = caps
            is_fido = (a == FIDO_PAGE and c == FIDO_USAGE) or (a == FIDO_USAGE and c == FIDO_PAGE)
            print("  %-10s %s | a=%04x b=%04x in=%d out=%d"
                  % ("FIDO" if is_fido else "hid", path, a, c, in_len, out_len))
            if is_fido:
                fido.append((path, caps, 0))
        else:
            print("  %-10s %s" % ("hid", path))
    if not fido:
        print("Ninguna interfaz FIDO (usage page 0xF1D0) en la enumeracion.")
        return 1
    print("\nLLAVE FIDO LOCALIZADA (%d interfaz/ces):" % len(fido))
    for path, caps, err in fido:
        print("  %s" % path)
        print("  caps=%s CreateFileW err=%d" % (caps, err))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
