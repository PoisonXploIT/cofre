"""Simular un click de raton real en una coordenada (SendInput).

Siraba para comprobar que el boton 'Ver' responde a un click genuino y no a
una llamada programatica.
"""
import ctypes
import sys

class PT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("extraInfo", ctypes.POINTER(ctypes.c_long))]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("pad", ctypes.c_ulong), ("mi", MOUSEINPUT)]

def click(x, y):
    inp = INPUT(type=0, pad=0, mi=MOUSEINPUT(x, y, 0, 0, 0, None))
    ctypes.windll.user32.SetCursorPos(x, y)
    for flag in (0x0001, 0x0002):  # LEFTDOWN, LEFTUP
        i = INPUT(type=0, pad=0, mi=MOUSEINPUT(0, 0, 0, flag, 0, None))
        ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))

if __name__ == "__main__":
    click(int(sys.argv[1]), int(sys.argv[2]))
