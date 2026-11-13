# -*- coding: utf-8 -*-
"""Struktur-Analyse echter .ddd-Dateien (Fahrerkarten-Downloads)."""
import struct
import sys
from pathlib import Path

NAMES = {
    0x0002: "EF_ICC (CardIccIdentification)",
    0x0005: "EF_IC (CardChipIdentification)",
    0x0501: "EF_Application_Identification",
    0x0502: "EF_Events_Data",
    0x0503: "EF_Faults_Data",
    0x0504: "EF_Driver_Activity_Data",
    0x0505: "EF_Vehicles_Used",
    0x0506: "EF_Places",
    0x0507: "EF_Current_Usage",
    0x0508: "EF_Control_Activity_Data",
    0x050E: "EF_Card_Download",
    0x0520: "EF_Identification",
    0x0521: "EF_Driving_Licence_info",
    0x0522: "EF_Specific_Conditions",
    0xC100: "EF_Card_Certificate",
    0xC108: "EF_CA_Certificate",
    0xC200: "EF_Card_Certificate_GOST",
    0xC201: "EF_Key_Identificators",
    0xC208: "EF_CA_Certificate_GOST",
}


def parse(path):
    data = path.read_bytes()
    print("\n### %s (%d Bytes)" % (path.name, len(data)))
    pos = 0
    blocks = []
    while pos + 5 <= len(data):
        ef, typ, length = struct.unpack_from(">HBH", data, pos)
        if typ not in (0, 1, 2, 3):
            print("  ABBRUCH bei Offset %d: Typ %02X ist unbekannt" % (pos, typ))
            print("  Rest hex:", data[pos:pos + 16].hex(" "))
            break
        chunk = data[pos + 5:pos + 5 + length]
        blocks.append((ef, typ, length, pos))
        name = NAMES.get(ef, "?")
        print("  EF %04X  Typ %d  Len %5d  @%5d  %s%s"
              % (ef, typ, length, pos, name,
                 "   [SIGNATUR]" if typ in (1, 3) else ""))
        pos += 5 + length
    print("  verbleibend: %d Bytes" % (len(data) - pos))


def main():
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        base = Path(__file__).parent / "sampledata"
        paths = [f for f in sorted(base.glob("*.DDD"))
                 if f.name.startswith(("C_", "smith"))]
    for f in paths:
        parse(f)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
