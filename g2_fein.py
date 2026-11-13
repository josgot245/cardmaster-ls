# -*- coding: utf-8 -*-
"""Gen-2-Feinanalyse: GNSS-Records (EF 0524), Fahrer, Fahrzeuge, AppIdent, EF 0525."""
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

def blocks(data):
    pos = 0
    while pos + 5 <= len(data):
        ef, typ, length = struct.unpack_from(">HBH", data, pos)
        yield ef, typ, data[pos + 5:pos + 5 + length]
        pos += 5 + length

def ts(b):
    if b >= 0xF0000000:
        return None
    try:
        return datetime.fromtimestamp(b, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None

def koord(raw):
    """DDMM.M*10 -> Dezimalgrad (None bei unbekannt)."""
    if raw in (0, 0x7FFFFF, -0x7FFFFF):
        return None
    neg = raw < 0
    raw = abs(raw)
    wert = (raw // 1000) + ((raw % 1000) / 10.0) / 60.0
    return -wert if neg else wert

def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).parent / "C_20261111_0853_DF00039608838.DDD"
    g1, g2 = {}, {}
    for ef, typ, chunk in blocks(path.read_bytes()):
        if typ == 0:
            g1[ef] = chunk
        elif typ == 2:
            g2[ef] = chunk

    # --- 1) GNSS-Records sortieren und Zeiger klaeren ---
    c = g2[0x0524]
    print("EF 0524: Zeigerbytes %02X %02X" % (c[0], c[1]))
    recs = [c[2 + i * 18:2 + (i + 1) * 18] for i in range(336)]
    parsed = []
    for i, r in enumerate(recs):
        if r == b"\x00" * 18:
            continue
        t1 = int.from_bytes(r[0:4], "big")
        t2 = int.from_bytes(r[4:8], "big")
        acc = r[8]
        lat = koord(int.from_bytes(r[9:12], "big", signed=True)) or 0.0
        lon = koord(int.from_bytes(r[12:15], "big", signed=True)) or 0.0
        x = int.from_bytes(r[15:18], "big")
        parsed.append((i, t1, t2, acc, lat, lon, x))
    print("gueltige GNSS-Records: %d" % len(parsed))
    print("\nchronologisch sortiert (nach t1) - erste 5 und letzte 8:")
    for i, t1, t2, acc, lat, lon, x in sorted(parsed, key=lambda p: p[1])[:5]:
        print("  idx=%3d  %s  t2-t1=%3ds acc=%02X lat=%.3f lon=%.3f x=%d"
              % (i, ts(t1).strftime("%d.%m.%y %H:%M:%S"), t2 - t1, acc, lat, lon, x))
    for i, t1, t2, acc, lat, lon, x in sorted(parsed, key=lambda p: p[1])[-8:]:
        print("  idx=%3d  %s  t2-t1=%3ds acc=%02X lat=%.3f lon=%.3f x=%d"
              % (i, ts(t1).strftime("%d.%m.%y %H:%M:%S"), t2 - t1, acc, lat, lon, x))
    # Zeiger-Theorie: ist idx 0x46=70 der neueste?
    newest = max(parsed, key=lambda p: p[1])
    print("\nneuester Record: idx=%d (Zeiger sagt 0x46=%d)" % (newest[0], c[1]))
    # Verteilung der Indizes ueber Zeit: wo liegt der Umbruch?
    by_idx = [p for p in parsed]
    print("Index-Struktur: erste 3 (idx, t1):",
          [(p[0], hex(p[1])) for p in by_idx[:3]])
    print("letzte 3 (idx, t1):", [(p[0], hex(p[1])) for p in by_idx[-3:]])
    print("idx 69-72:", [(p[0], hex(p[1])) for p in by_idx[69:73]])
    print("idx 334-335:", [(p[0], hex(p[1])) for p in by_idx[334:336]])
    # x-Werte in chronologischer Reihenfolge
    print("\nx-Werte chronologisch (letzte 30):")
    for i, t1, t2, acc, lat, lon, x in sorted(parsed, key=lambda p: p[1])[-30:]:
        print("  %s x=%6d (%04X) lat=%.3f lon=%.3f"
              % (ts(t1).strftime("%d.%m.%y %H:%M"), x, x, lat, lon))

    # --- 2) Fahrer-Identifikation beider Ansichten ---
    for label, d in (("G1", g1), ("G2", g2)):
        c = d[0x0520]
        print("\nEF 0520 %s (%d Bytes):" % (label, len(c)))
        print("  hex:", c.hex(" "))
        # Struktur: 2 Version + 5 Aussteller + 35 Autoritaet + 16 Kartennummer
        # + 3 Land + 4 Ablaufdatum + 35 Nachname + 35 Vorname + 4 Geburt + 2 Sprache
        off = 0
        ver = c[0:2]
        aut = c[7:42].decode("latin-1", "replace").rstrip()
        nr = c[42:58].decode("latin-1", "replace").rstrip()
        exp = ts(int.from_bytes(c[61:65], "big"))
        nach = c[65:100].decode("latin-1", "replace").rstrip()
        vor = c[100:135].decode("latin-1", "replace").rstrip()
        geb = ts(int.from_bytes(c[135:139], "big"))
        print("  Autoritaet=%r KartenNr=%r" % (aut, nr))
        print("  Nachname=%r Vorname=%r" % (nach, vor))
        print("  Ablauf=%s Geburt=%s" % (exp, geb))

    # --- 3) Fahrzeuge (G1 und G2) ---
    for label, d, rec_len in (("G1", g1, 31), ("G2", g2, 48)):
        c = d[0x0505]
        print("\nEF 0505 %s (%d Bytes):" % (label, len(c)))
        seen = set()
        for i in range((len(c) - 2) // rec_len):
            r = c[2 + i * rec_len:2 + (i + 1) * rec_len]
            if r == b"\x00" * rec_len:
                continue
            if label == "G1":
                odo0 = int.from_bytes(r[0:3], "big")
                odo1 = int.from_bytes(r[3:6], "big")
                f = ts(int.from_bytes(r[6:10], "big"))
                l = ts(int.from_bytes(r[10:14], "big"))
                reg = r[16:29].decode("latin-1", "replace").rstrip("\x00 ")
                key = reg
                info = "km %d-%d  %s .. %s" % (odo0, odo1, f, l)
            else:
                odo0 = int.from_bytes(r[0:3], "big")
                odo1 = int.from_bytes(r[3:6], "big")
                f = ts(int.from_bytes(r[6:10], "big"))
                l = ts(int.from_bytes(r[10:14], "big"))
                reg = r[16:29].decode("latin-1", "replace").rstrip("\x00 ")
                key = reg
                info = "km %d-%d  %s .. %s" % (odo0, odo1, f, l)
            if key not in seen:
                seen.add(key)
                print("  Kennzeichen %r  %s" % (reg, info))
        print("  Rohdaten erstes/letztes Record hex:")
        first = c[2:2 + rec_len]
        print("   ", first.hex(" "))

    # --- 4) AppIdent (Strukturversion) + EF 0525 + Certs ---
    for label, d in (("G1", g1), ("G2", g2)):
        c = d.get(0x0501, b"")
        print("\nEF 0501 %s (%d Bytes): %s" % (label, len(c), c.hex(" ")))
    c = g2.get(0x0525, b"")
    print("\nEF 0525 (10 Bytes): %s" % c.hex(" "))
    for fid in (0xC101, 0xC108, 0xC109):
        c = g2.get(fid, b"")
        if c:
            print("\nEF %04X G2 (%d Bytes), erste 40: %s" % (fid, len(c), c[:40].hex(" ")))

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
