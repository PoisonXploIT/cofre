import json
import os
import struct
import sys

def main():
    raw = sys.stdin.buffer.read(4)
    if len(raw) != 4:
        return
    n = struct.unpack("<I", raw)[0]
    msg = sys.stdin.buffer.read(n)
    try:
        data = json.loads(msg.decode("utf-8"))
    except Exception:
        data = {}
    reply = {
        "pong": True,
        "recibido": data,
        "argv": sys.argv[1:],
        "exe": os.path.basename(sys.executable),
        "pid": os.getpid(),
    }
    out = json.dumps(reply).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(out)) + out)
    sys.stdout.buffer.flush()

if __name__ == "__main__":
    main()
