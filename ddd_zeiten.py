# -*- coding: utf-8 -*-
"""Datums-Dekodierung an echten .ddd-Beispieldaten pruefen."""
import struct
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


def blocks(data):
    pos = 0
    while pos + 5 <= len(data):
        ef, typ, length = struct.unpack_from(">HBH", data, pos)
        yield ef, typ, data[pos + 5:pos + 5 + length]
        pos += 5 + length


def as_text(b):
    """Feld mit Charset-Präfixbyte (8859-Nummer) + fixed-string."""
    if not b:
        return ""
    return b[1:].decode("latin-1", "replace").rstrip()


def show(path):
    print("\n###", path.name)
    for ef, typ, chunk in blocks(path.read_bytes()):
        if ef == 0x0520 and typ == 0:
            ms = chunk[0]
            number = chunk[1:17].decode("ascii", "replace")
            authority = as_text(chunk[17:53])
            issue, valid, expiry = (
                int.from_bytes(chunk[53:57], "big"),
                int.from_bytes(chunk[57:61], "big"),
                int.from_bytes(chunk[61:65], "big"))
            surname = as_text(chunk[65:101])
            firstname = as_text(chunk[101:137])
            birth = chunk[137:141]
            lang = chunk[141:143]
            print("  Staat=%02X  Nr=%s" % (ms, number))
            print("  Behörde=%r" % authority)
            print("  Name=%r %r  Sprache=%r" % (firstname, surname, lang))
            print("  Geburtsdatum roh: %s" % birth.hex(" "))
            for label, v in (("Ausgestellt", issue),
                             ("Gültig ab", valid),
                             ("Gültig bis", expiry)):
                print("  %s: roh=0x%08X  sek=%s  min=%s" % (
                    label, v,
                    datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
                    if v < 2 ** 34 else "-",
                    datetime.fromtimestamp(v * 60, tz=timezone.utc).isoformat()
                    if v * 60 < 2 ** 34 else "-"))
        if ef == 0x050E and typ == 0:
            v = int.from_bytes(chunk, "big")
            print("  letzter Download: roh=0x%08X sek=%s" % (
                v, datetime.fromtimestamp(v, tz=timezone.utc).isoformat()))


def main():
    for arg in sys.argv[1:] or [
            "smith_emily_2022-07-13.DDD",
            "C_20190701_1042_K_Musterfrau 10_11000000071640.DDD",
            "C_20210222_0439_M_Sommer_00000200005313.DDD"]:
        p = Path(arg)
        show(p if p.exists() else Path(__file__).parent / "sampledata" / arg)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
