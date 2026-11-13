# -*- coding: utf-8 -*-
"""Spesenzettel (Reisekostenabrechnung) aus einem Fahrerkarten-Download.

Verwendung:
    py spesenzettel.py [fahrerkarte.ddd] [--alle]

Ohne Datei-Argument wird die neueste .ddd im Ordner verwendet.
Es werden nur Fahrten ausgegeben, die noch auf keinem Spesenzettel standen
(Abrechnungsstand je Karte in spesen_state.json). Mit --alle werden alle
gespeicherten Fahrten neu erstellt.

Fuer die Fenster-Oberflaeche:  py spesenzettel_gui.py
"""
import sys
from datetime import date
from pathlib import Path

import spesen_lib


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--alle" in argv
    dateien = [a for a in argv if not a.startswith("-")]

    basis = spesen_lib.ddd_ordner()
    if dateien:
        pfad = Path(dateien[0])
        if not pfad.is_absolute():
            pfad = basis / pfad
    else:
        kandidaten = []
        for ordner in (basis, spesen_lib.DATA_DIR):
            kandidaten += sorted(ordner.glob("C_*.DDD"))
            kandidaten += sorted(ordner.glob("C_*.ddd"))
        if not kandidaten:
            print("Keine .ddd-Datei gefunden – bitte Datei angeben oder "
                  "Karte mit py fahrerkarte.py auslesen.")
            return 1
        pfad = kandidaten[-1]

    print("Datei:", pfad.name)
    try:
        info = spesen_lib.lade_ddd(pfad)
    except (ValueError, OSError) as e:
        print("FEHLER:", e)
        return 1

    print("Karte    : %s" % info["kartennummer"])
    print("Fahrer   : %s (gültig bis %s)"
          % (info["name"],
             spesen_lib._fmt(info["gueltig_bis"]) if info["gueltig_bis"] else "?"))
    print("Fahrten  : %d gespeichert, letzte: %s"
          % (len(info["touren"]),
             spesen_lib._fmt(info["touren"][-1]["tag"]) if info["touren"] else "-"))

    st = spesen_lib.load_state()
    ks = st["karten"].get(info["kartennummer"], {})
    if ks:
        letzte = ks.get("letzte_zeile")
        print("Abgerechnet bis: %s (%d Blatt bereits erstellt)"
              % (spesen_lib._fmt(date.fromisoformat(letzte)) if letzte else "-",
                 len(ks.get("blaetter", []))))
    else:
        print("Diese Karte wurde noch nicht abgerechnet.")

    name = ks.get("name") or info["name"]
    abteilung = ks.get("abteilung", "")
    personal_nr = ks.get("personal_nr", "")
    if not ks:
        print("Hinweis: Abteilung und Personal-Nr. sind unbekannt und "
              "bleiben leer (im Fenster spesenzettel_gui.py erfassen).")

    erstellt = spesen_lib.erstelle_spesenzettel(
        info, name, abteilung, personal_nr, force=force, log=print)

    if erstellt:
        print("\nFertig. %d PDF-Datei(en) erstellt." % len(erstellt))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
