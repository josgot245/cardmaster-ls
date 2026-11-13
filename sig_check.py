# -*- coding: utf-8 -*-
"""Sind alle 128-Byte-Signaturen in der .ddd verschieden?"""
import struct
import sys
from pathlib import Path


def main(path):
    data = Path(path).read_bytes()
    pos, sigs = 0, []
    while pos + 5 <= len(data):
        ef, typ, length = struct.unpack_from(">HBH", data, pos)
        if typ in (1, 3):
            sigs.append((ef, data[pos + 5:pos + 5 + length]))
        pos += 5 + length
    print("%d Signaturblöcke gefunden" % len(sigs))
    uniq = {bytes(s) for _, s in sigs}
    print("%d unterschiedliche Signaturen" % len(uniq))
    for ef, s in sigs:
        print("  EF %04X  %s...  SHA-256-Anfang: %s"
              % (ef, s[:8].hex(" "), 
                 __import__("hashlib").sha256(s).hexdigest()[:16]))
    if len(uniq) == len(sigs):
        print("OK — alle Signaturen sind eindeutig.")
    else:
        print("WARNUNG — doppelte Signaturen!")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1])
