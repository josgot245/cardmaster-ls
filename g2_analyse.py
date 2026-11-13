# -*- coding: utf-8 -*-
"""Gen-2-Bloecke (Typ 2/3) der Firmendatei analysieren:
EF 0506 G2 (Places, 21-Byte-Records mit GNSS) und EF 0524 (GNSS_Places)."""
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

NAMES = {
    0x0501: "AppIdent", 0x0502: "Events", 0x0503: "Faults",
    0x0504: "DriverActivity", 0x0505: "VehiclesUsed", 0x0506: "Places",
    0x0507: "CurrentUsage", 0x0508: "Control", 0x050E: "CardDownload",
    0x0520: "Identification", 0x0521: "DrivingLicence",
    0x0522: "SpecificConditions",
    0x0523: "VehicleUnits?", 0x0524: "GNSS_Places?",
    0x0525: "?", 0x0526: "?", 0x0527: "?", 0x0528: "?",
    0x0529: "?", 0x0530: "?",
    0xC101: "?", 0xC108: "CA_Cert", 0xC109: "?",
}


def blocks(data):
    pos = 0
    while pos + 5 <= len(data):
        ef, typ, length = struct.unpack_from(">HBH", data, pos)
        yield ef, typ, data[pos + 5:pos + 5 + length]
        pos += 5 + length


def fmt_time(t):
    if t == 0 or t >= 0xF0000000:
        return "-"
    try:
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "?"


def koord(raw):
    """DDMM.M*10 -> Dezimalgrad (None bei unbekannt)."""
    if raw in (0, 0x7FFFFF, -0x7FFFFF):
        return None
    neg = raw < 0
    raw = abs(raw)
    wert = (raw // 1000) + ((raw % 1000) / 10.0) / 60.0
    return -wert if neg else wert


def dump_g2_places(chunk):
    print("\n=== EF 0506 G2 (Places, 21-Byte-Records) ===")
    ptr = chunk[0]
    n = chunk[1]
    print("Zeiger-Bytes: %02X %02X" % (ptr, n))
    recs = chunk[2:]
    print("Records: %d" % (len(recs) // 21))
    for i in range(len(recs) // 21):
        r = recs[i * 21:(i + 1) * 21]
        if r == b"\x00" * 21:
            continue
        t = int.from_bytes(r[0:4], "big")
        typ = r[4]
        land = r[5]
        region = r[6]
        odo = int.from_bytes(r[7:10], "big")
        # entryGNSSPlaceRecord (11): timeStamp 4 + accuracy 1 + geo 6
        gt = int.from_bytes(r[10:14], "big")
        acc = r[14]
        lat = koord(int.from_bytes(r[15:18], "big", signed=True))
        lon = koord(int.from_bytes(r[18:21], "big", signed=True))
        print("%3d  %s  typ=%02X land=%02X reg=%02X km=%6d | GNSS %s acc=%02X lat=%s lon=%s" % (
            i, fmt_time(t), typ, land, region, odo, fmt_time(gt), acc,
            "%.5f" % lat if lat is not None else "-",
            "%.5f" % lon if lon is not None else "-"))


def dump_gnss(chunk):
    print("\n=== EF 0524 (GNSS_Places, 18-Byte-Records?) ===")
    print("Zeiger-Bytes: %02X %02X" % (chunk[0], chunk[1]))
    recs = chunk[2:]
    print("Bytes: %d  -> /18 = %d  /9 = %d  /12 = %d" % (
        len(recs), len(recs) / 18, len(recs) / 9, len(recs) / 12))
    step = 18
    for i in range(len(recs) // step):
        r = recs[i * step:(i + 1) * step]
        if r == b"\x00" * step:
            continue
        print("%3d  %s" % (i, " ".join("%02X" % b for b in r)))


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).parent / "C_20261111_0853_DF00039608838.DDD"
    data = path.read_bytes()
    print("Datei:", path.name, len(data), "Bytes")

    g2 = {}
    ident = {}
    for ef, typ, chunk in blocks(data):
        if typ in (2, 3):
            g2.setdefault(ef, {})[typ] = chunk
        elif ef == 0x0520 and typ == 0:
            ident[1] = chunk
        elif ef == 0x0520 and typ == 2:
            ident[2] = chunk

    print("\nG2-Bloecke (Typ 2):")
    for ef in sorted(g2):
        c = g2[ef].get(2, b"")
        print("  EF %04X  %-18s Len %5d  (%d Records?" % (
            ef, NAMES.get(ef, "?"), len(c), 0))
        if ef in (0x0523, 0x0524, 0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x0530):
            ln = len(c)
            for n in (9, 10, 11, 12, 18, 20, 21, 24, 28, 40, 48, 56, 60):
                if (ln - 2) % n == 0:
                    print("        -> (Len-2) = %d = %d x %d" % (ln - 2, (ln - 2) // n, n))

    # Fahrer-Identifikation beider Ansichten vergleichen
    print("\n=== EF 0520 Identification (Gen-1-Ansicht) ===")
    if 1 in ident:
        c = ident[1]
        print("  Karten-Nr:", c[20:41].decode("latin-1", "replace").rstrip())
        print("  Name:", c[43:71].decode("latin-1", "replace").rstrip(),
              c[73:101].decode("latin-1", "replace").rstrip())
        print("  gueltig ab:", fmt_time(int.from_bytes(c[2:6], "big")),
              "bis:", fmt_time(int.from_bytes(c[6:10], "big")))
    print("=== EF 0520 Identification (Gen-2-Ansicht) ===")
    if 2 in ident:
        c = ident[2]
        print("  Karten-Nr:", c[20:41].decode("latin-1", "replace").rstrip())
        print("  Name:", c[43:71].decode("latin-1", "replace").rstrip(),
              c[73:101].decode("latin-1", "replace").rstrip())

    if 0x0506 in g2 and 2 in g2[0x0506]:
        dump_g2_places(g2[0x0506][2])
    if 0x0524 in g2 and 2 in g2[0x0524]:
        dump_gnss(g2[0x0524][2])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
