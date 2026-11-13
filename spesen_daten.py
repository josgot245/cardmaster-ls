# -*- coding: utf-8 -*-
"""Reisen (EF 0506) aus einem Fahrerkarten-Download lesen und
als Tabelle/CSV fuer die Reisekostenabrechnung aufbereiten.

Karten der 2. Generation (G2) speichern zu jedem Tätigkeitsort
zusaetzlich eine GNSS-Position (Breite/Laenge). Enthält der Download
Gen-2-Blöcke (Typ 2), werden diese automatisch bevorzugt.
"""
import csv
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

NAMES = {
    0x0002: "EF_ICC", 0x0005: "EF_IC", 0x0501: "EF_Application_Identification",
    0x0502: "EF_Events_Data", 0x0503: "EF_Faults_Data",
    0x0504: "EF_Driver_Activity_Data", 0x0505: "EF_Vehicles_Used",
    0x0506: "EF_Places", 0x0507: "EF_Current_Usage",
    0x0508: "EF_Control_Activity_Data", 0x050E: "EF_Card_Download",
    0x0520: "EF_Identification", 0x0521: "EF_Driving_Licence_info",
    0x0522: "EF_Specific_Conditions",
    0x0523: "EF_Vehicle_Units", 0x0524: "EF_GNSS_Places",
    0x0525: "EF_G2_Counters", 0x0526: "EF_Places_Authentication",
    0x0527: "EF_Load_Type_Entries", 0x0528: "EF_Border_Crossings",
    0x0529: "EF_Load_Unload_Operations",
    0x0530: "EF_GNSS_Places_Authentication",
    0xC101: "EF_Card_Certificate_G2", 0xC109: "EF_MS_Certificate_G2",
}


def blocks(data):
    pos = 0
    while pos + 5 <= len(data):
        ef, typ, length = struct.unpack_from(">HBH", data, pos)
        yield ef, typ, data[pos + 5:pos + 5 + length]
        pos += 5 + length


def as_text(b):
    return b[1:].decode("latin-1", "replace").rstrip() if b else ""


# Die Karte speichert Breite/Laenge als ganze Zahl in der Form DDMM.M
# (Breite) bzw. DDDMM.M (Laenge), also als Zehnfaches von "Grad + Minuten"
# (VO (EU) 2016/799, Anhang 1C). Beispiel: 53° 32,4' -> 53324.
# Ein unbekannter Wert ist 0x7FFFFF.
_KOORD_UNBEKANNT = 0x7FFFFF


def _koordinate(raw):
    """GNSS-Koordinate in Dezimalgrad aus der Ganzzahl-Kodierung.

    Rohwert = DDMM.M * 10 (Breite) bzw. DDDMM.M * 10 (Laenge).
    Rueckgabe: Dezimalgrad oder None (unbekannt/leer).
    """
    if raw in (0, _KOORD_UNBEKANNT, -_KOORD_UNBEKANNT):
        return None
    negativ = raw < 0
    raw = abs(raw)
    grad = raw // 1000
    minuten = (raw % 1000) / 10.0
    wert = grad + minuten / 60.0
    return -wert if negativ else wert


def _ring(chunk, ptr_len, rec_len, leer):
    """Ringpuffer chronologisch auslesen.

    Der Zeiger am Dateianfang zeigt auf den NEUESTEN Datensatz.
    Zurueckgegeben werden die belegten Datensaetze in chronologischer
    Reihenfolge (ältester zuerst). 'leer' entscheidet, ob ein
    Datensatz unbenutzt ist (Standard: Zeitstempel 0).
    """
    n = (len(chunk) - ptr_len) // rec_len
    if n <= 0:
        return []
    ptr = int.from_bytes(chunk[:ptr_len], "big")
    reihenfolge = ([(ptr + k) % n for k in range(1, n + 1)]
                   if ptr < n else list(range(n)))
    out = []
    for i in reihenfolge:
        r = chunk[ptr_len + i * rec_len:ptr_len + (i + 1) * rec_len]
        if len(r) < rec_len or leer(r):
            continue
        out.append(r)
    return out


def ring_slice(buf, start, length):
    """Teil aus einem Ringpuffer (mit Umbruch am Ende)."""
    n = len(buf)
    if not n:
        return b""
    return bytes(buf[(start + i) % n] for i in range(length))


def _chunks(pfad, ef):
    """Blöcke eines EF nach Typ: {0: Gen-1-Daten, 2: Gen-2-Daten}."""
    out = {}
    for efid, typ, chunk in blocks(Path(pfad).read_bytes()):
        if efid == ef and typ in (0, 2) and typ not in out:
            out[typ] = chunk
    return out


def read_places(pfad):
    """Alle EF-0506-Records (Tätigkeitsorte) chronologisch.

    Gen-2 (bevorzugt): 21 Byte je Record mit GNSS-Position.
    Gen-1: 10 Byte je Record ohne Position (lat/lon = None).
    Rückgabe: Liste von dicts mit zeit, typ, land, region, km,
    fix (GNSS-Zeitpunkt), acc (Genauigkeit), lat, lon.
    """
    teile = _chunks(pfad, 0x0506)
    quelle = 2 if 2 in teile else 0
    chunk = teile.get(quelle)
    if chunk is None:
        return []
    if quelle == 2:
        recs = _ring(chunk, 2, 21,
                     lambda r: int.from_bytes(r[0:4], "big") == 0)
    else:
        recs = _ring(chunk, 1, 10,
                     lambda r: int.from_bytes(r[0:4], "big") == 0)
    out = []
    for r in recs:
        p = {
            "zeit": datetime.fromtimestamp(
                int.from_bytes(r[0:4], "big"), tz=timezone.utc),
            "typ": r[4],                      # 00 = Karte gesteckt, 01 = entnommen
            "land": r[5], "region": r[6],
            "km": int.from_bytes(r[7:10], "big"),
            "fix": None, "acc": None, "lat": None, "lon": None,
        }
        if quelle == 2:
            p["fix"] = datetime.fromtimestamp(
                int.from_bytes(r[10:14], "big"), tz=timezone.utc)
            p["acc"] = r[14]
            p["lat"] = _koordinate(int.from_bytes(r[15:18], "big", signed=True))
            p["lon"] = _koordinate(int.from_bytes(r[18:21], "big", signed=True))
        out.append(p)
    return out


def read_activity(pfad):
    """Tagesaktivitäten (EF 0504) chronologisch.

    Jeder Tag enthält die Tageskilometer und die Aktivitätswechsel als
    Liste (Minute 0..1439, Art):
        0 = Ruhe, 1 = Bereitschaft, 2 = Arbeit, 3 = Fahrt

    Der letzte Wechsel eines Tages gilt bis 24:00; das ist keine
    gemessene Endzeit, sondern die Fortschreibung des letzten Zustands.

    Rückgabe: Liste von dicts mit tag (date), km und wechsel.
    """
    teile = _chunks(pfad, 0x0504)
    chunk = teile.get(2) or teile.get(0)
    if not chunk or len(chunk) < 5:
        return []
    ring = chunk[4:]
    if not ring:
        return []
    oldest = int.from_bytes(chunk[0:2], "big")
    newest = int.from_bytes(chunk[2:4], "big")
    if oldest >= len(ring) or newest >= len(ring):
        return []

    pos, seen, tage = oldest, set(), []
    while pos not in seen:
        seen.add(pos)
        rec_len = int.from_bytes(ring_slice(ring, pos + 2, 2), "big")
        if rec_len < 12 or rec_len > len(ring):
            break
        ts = int.from_bytes(ring_slice(ring, pos + 4, 4), "big")
        km = int.from_bytes(ring_slice(ring, pos + 10, 2), "big")
        roh = ring_slice(ring, pos + 12, rec_len - 12)
        wechsel = []
        for i in range(0, len(roh) - 1, 2):
            b0 = roh[i]
            minute = ((b0 & 0x07) << 8) | roh[i + 1]
            wechsel.append((minute, (b0 >> 3) & 0x03))
        try:
            tag = datetime.fromtimestamp(ts, tz=BERLIN).date()
        except (ValueError, OSError, OverflowError):
            tag = None
        if tag is not None:
            tage.append({"tag": tag, "km": km, "wechsel": wechsel})
        if pos == newest:
            break
        pos = (pos + rec_len) % len(ring)
    tage.sort(key=lambda d: d["tag"])
    return tage


def read_gnss(pfad):
    """GNSS-Positionen (EF 0524) chronologisch.

    Die Karte speichert während der Fahrt etwa alle 3 Stunden eine
    Position. Layout je 18-Byte-Record (Ringpuffer ab Offset 2):
        [0:4] Zeit, [4:8] GNSS-Fix, [8] Typ/Genauigkeit,
        [9:12] Breite (DDMM.M*10, signed), [12:15] Länge (DDDMM.M*10, signed),
        [15:18] Odometer.

    Rückgabe: Liste von dicts mit zeit (Europe/Berlin), lat, lon, km.
    """
    teile = _chunks(pfad, 0x0524)
    chunk = teile.get(2) or teile.get(0)
    if not chunk or len(chunk) < 20:
        return []
    out = []
    for i in range(2, len(chunk) - 17, 18):
        r = chunk[i:i + 18]
        if r == b"\x00" * 18:
            continue
        ts = int.from_bytes(r[0:4], "big")
        if not ts:
            continue
        lat = _koordinate(int.from_bytes(r[9:12], "big", signed=True))
        lon = _koordinate(int.from_bytes(r[12:15], "big", signed=True))
        if lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        try:
            zeit = datetime.fromtimestamp(
                ts, tz=timezone.utc).astimezone(BERLIN)
        except (ValueError, OSError, OverflowError):
            continue
        out.append({"zeit": zeit, "lat": lat, "lon": lon,
                    "km": int.from_bytes(r[15:18], "big")})
    out.sort(key=lambda p: p["zeit"])
    return out


def read_border_crossings(pfad):
    """Grenzübertritte (EF 0528) chronologisch.

    Layout je 17-Byte-Record (Ringpuffer ab Offset 1 oder 2):
        [0] Land verlassen, [1] Land eingereist,
        [2:6] Zeitpunkt (UTC), [7:10] Breite (DDMM.M*10, signed),
        [10:13] Länge (DDDMM.M*10, signed), [14:17] Odometer.

    Rückgabe: Liste von dicts mit zeit (UTC), von, nach, lat, lon, km.
    """
    teile = _chunks(pfad, 0x0528)
    chunk = teile.get(2) or teile.get(0)
    if not chunk or len(chunk) < 19:
        return []
    rec_len = 17
    ptr_len = None
    for kandidat in (2, 1):
        if (len(chunk) - kandidat) % rec_len == 0:
            ptr_len = kandidat
            break
    if ptr_len is None:
        return []
    n = (len(chunk) - ptr_len) // rec_len
    ptr = int.from_bytes(chunk[:ptr_len], "big")
    if ptr >= n:
        return []
    # Der Zeiger zeigt auf den NEUESTEN Datensatz; chronologisch ab dem
    # naechsten (aeltesten) Record.
    reihenfolge = [(ptr + k) % n for k in range(1, n + 1)]
    out = []
    for i in reihenfolge:
        r = chunk[ptr_len + i * rec_len:ptr_len + (i + 1) * rec_len]
        if len(r) < rec_len:
            continue
        ts = int.from_bytes(r[2:6], "big")
        if not ts:
            continue
        try:
            zeit = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            continue
        out.append({
            "zeit": zeit,
            "von": r[0],
            "nach": r[1],
            "lat": _koordinate(int.from_bytes(r[7:10], "big", signed=True)),
            "lon": _koordinate(int.from_bytes(r[10:13], "big", signed=True)),
            "km": int.from_bytes(r[14:17], "big"),
        })
    out.sort(key=lambda p: p["zeit"])
    return out


def _read_ereignis_records(pfad, ef):
    """Gemeinsamer Leser fuer EF 0502 (Ereignisse) und EF 0503 (Stoerungen).

    Je Datensatz 24 Byte:
        [0] Typ, [1:5] Beginn (UTC), [5:9] Ende (UTC),
        [9] Land, [10] Laengenbyte, [11:24] Kennzeichen (13 Zeichen).
    """
    teile = _chunks(pfad, ef)
    chunk = teile.get(2) or teile.get(0)
    if not chunk:
        return []
    out = []
    for i in range(0, len(chunk) - 23, 24):
        r = chunk[i:i + 24]
        ts = int.from_bytes(r[1:5], "big")
        if not ts:
            continue
        try:
            beginn = datetime.fromtimestamp(ts, tz=timezone.utc)
            ende = datetime.fromtimestamp(
                int.from_bytes(r[5:9], "big"), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            continue
        out.append({
            "typ": r[0],
            "beginn": beginn,
            "ende": ende,
            "land": r[9],
            "kennzeichen": as_text(r[10:24]),
        })
    out.sort(key=lambda e: e["beginn"])
    return out


def read_events(pfad):
    """Ereignisse (EF 0502) chronologisch.

    Rückgabe: Liste von dicts mit typ, beginn/ende (UTC), land und
    kennzeichen. Die Bedeutung der Typen steht in spesen_lib.EREIGNIS_NAMEN.
    """
    return _read_ereignis_records(pfad, 0x0502)


def read_faults(pfad):
    """Störungen (EF 0503) chronologisch – gleiches Format wie Ereignisse."""
    return _read_ereignis_records(pfad, 0x0503)


def read_vehicles(pfad):
    """EF 0505 (genutzte Fahrzeuge) chronologisch.

    Gen-2 (bevorzugt): 48 Byte je Record inkl. FIN (Fahrgestellnummer).
    Rückgabe: Liste von (kennzeichen, nation, odo_anfang, odo_ende,
    erste_nutzung, letzte_nutzung, fin).
    """
    teile = _chunks(pfad, 0x0505)
    quelle = 2 if 2 in teile else 0
    chunk = teile.get(quelle)
    if chunk is None:
        return []
    if quelle == 2:
        recs = _ring(chunk, 2, 48,
                     lambda r: int.from_bytes(r[6:10], "big") == 0)
    else:
        recs = _ring(chunk, 1, 31,
                     lambda r: int.from_bytes(r[6:10], "big") == 0)
    out = []
    for r in recs:
        odo_a = int.from_bytes(r[0:3], "big")
        odo_e = int.from_bytes(r[3:6], "big")
        first = datetime.fromtimestamp(
            int.from_bytes(r[6:10], "big"), tz=timezone.utc)
        last = datetime.fromtimestamp(
            int.from_bytes(r[10:14], "big"), tz=timezone.utc)
        # Kennzeichen: Laengenbyte + 13 Zeichen (r[15:29]); danach folgen
        # 2 Byte Verwendungs-Zahler, bei Gen-2 dahinter die FIN (r[31:48])
        reg = as_text(r[15:29])
        fin = (r[31:48].decode("ascii", "replace").rstrip("\x00 ")
               if len(r) >= 48 else "")
        out.append((reg, r[14], odo_a, odo_e, first, last, fin))
    return out


def build_tours(places):
    """Reisen = Folgen Typ00(Karte gesteckt) -> Typ01(Karte entnommen).

    Kurze Luecken (< 60 min) am selben Tag werden zu einer Tour
    verschmolzen. Jede Tour trägt Start- und Ziel-Position (GNSS,
    wenn vorhanden) sowie die Odometer-Stände.
    """
    pairs = []
    open_start = None
    for p in places:
        if p["typ"] == 0x00:
            open_start = p
        elif p["typ"] == 0x01 and open_start is not None:
            pairs.append({
                "start": open_start["zeit"], "end": p["zeit"],
                "km0": open_start["km"], "km1": p["km"],
                "start_lat": open_start["lat"], "start_lon": open_start["lon"],
                "end_lat": p["lat"], "end_lon": p["lon"],
                "segments": 1,
            })
            open_start = None

    tours = []
    for p in pairs:
        if tours:
            prev = tours[-1]
            gap = (p["start"] - prev["end"]).total_seconds()
            same_day = p["start"].astimezone(BERLIN).date() == \
                prev["end"].astimezone(BERLIN).date()
            if same_day and gap < 3600:
                prev["end"] = p["end"]
                prev["km1"] = p["km1"]
                prev["end_lat"] = p["end_lat"]
                prev["end_lon"] = p["end_lon"]
                prev["segments"] += 1
                continue
        tours.append(dict(p))
    return tours


def verpflegung(span_hours):
    """Eintägige Reise (Inland): >8 h = 14 EUR, sonst 0 EUR."""
    if span_hours > 8:
        return 14.0
    return 0.0


def _pos_text(lat, lon):
    return "%.3f, %.3f" % (lat, lon) if lat is not None else ""


def main():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        cands = sorted(Path(__file__).parent.glob("C_*.DDD")) + \
                sorted(Path(__file__).parent.glob("C_*.ddd"))
        if not cands:
            print("Keine .ddd-Datei gefunden.")
            return
        path = cands[-1]

    places = read_places(path)
    vehicles = read_vehicles(path)
    tours = build_tours(places)
    gnss = any(p["lat"] is not None for p in places)

    print("Datei:", path.name)
    print("Tätigkeitsorte: %d Records (%s)"
          % (len(places), "Gen 2 mit GNSS" if gnss else "Gen 1"))
    regs = sorted({v[0] for v in vehicles if v[0]})
    fins = sorted({v[6] for v in vehicles if v[6]})
    print("Fahrzeuge (EF 0505): %s" % (", ".join(regs) if regs else "-"))
    if fins:
        print("FINs: %s" % ", ".join(fins))
    print()

    hdr = ("Nr", "Datum", "Beginn", "Ende", "Dauer", "Std", "km",
           "Verpfleg.", "Start", "Ziel")
    print("%-3s %-10s %-5s %-5s %-7s %5s %6s %7s  %-16s %-16s" % hdr)
    print("-" * 96)

    rows = []
    total_km = 0
    total_vpf = 0.0
    total_min = 0.0
    for i, t in enumerate(tours, 1):
        s = t["start"].astimezone(BERLIN)
        e = t["end"].astimezone(BERLIN)
        dur = e - s
        hours = dur.total_seconds() / 3600.0
        km = t["km1"] - t["km0"]
        vpf = verpflegung(hours)
        total_km += km
        total_vpf += vpf
        total_min += dur.total_seconds()
        start = _pos_text(t["start_lat"], t["start_lon"])
        ziel = _pos_text(t["end_lat"], t["end_lon"])
        print("%-3d %-10s %-5s %-5s %-7s %5.2f %6d %7.2f  %-16s %-16s" % (
            i, s.strftime("%d.%m.%Y"), s.strftime("%H:%M"), e.strftime("%H:%M"),
            "%dh%02d" % (dur.seconds // 3600, (dur.seconds % 3600) // 60),
            hours, km, vpf, start, ziel))
        rows.append({
            "Nr": i,
            "Datum": s.strftime("%d.%m.%Y"),
            "Beginn": s.strftime("%H:%M"),
            "Ende": e.strftime("%H:%M"),
            "Dauer": "%dh%02d" % (dur.seconds // 3600, (dur.seconds % 3600) // 60),
            "Std": round(hours, 2),
            "km": km,
            "Verpflegung": vpf,
            "Segmente": t["segments"],
            "km0": t["km0"],
            "km1": t["km1"],
            "Start": start,
            "Ziel": ziel,
            "Start_UTC": t["start"].isoformat(),
            "Ende_UTC": t["end"].isoformat(),
        })

    print("-" * 96)
    print("%-3s %-10s %-5s %-5s %-7s %5.2f %6d %7.2f" % (
        "", "Summe", "", "", "", total_min / 3600.0, total_km, total_vpf))

    csv_path = path.with_suffix(".spesen.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)
    print("\nCSV geschrieben:", csv_path.name)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
