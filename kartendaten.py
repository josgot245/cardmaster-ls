# -*- coding: utf-8 -*-
"""Tagesauswertung der Fahrerkarte für die Kartenansicht.

Die Karte speichert je Kalendertag (EF 0504) die Tageskilometer und die
Aktivitätswechsel (Ruhe, Bereitschaft, Arbeit, Fahrt). Daraus entsteht
ein Minutenprofil 0..1440, das die Tagesgrafik und das Kreisdiagramm
speist. Zusätzlich werden die wichtigsten Lenk- und Ruhezeitregeln
geprüft und die aufgezeichneten Ereignisse/Störungen des Tages
(EF 0502/0503) aufgelistet.
"""
from datetime import date, timedelta

import spesen_daten

ARTEN = ("Ruhe", "Bereitschaft", "Arbeit", "Fahrt")
KURZ = ("Ruhe", "Bereit.", "Arbeit", "Fahrt")

# Farben der Tagesanteile – gedeckt und zu den Firmen-Assets (Rot/Grau)
# passend. Das frühere Navyblau der Fahrt entfällt. „Unbekannt“ wird im
# Programm hell mit roten Schrägstrichen gezeichnet.
FARBEN = ("#C8CDD5", "#E3A94E", "#5C6672", "#B91D21")

WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

# Grenzwerte in Minuten (EU-Lenk- und Ruhezeiten)
MAX_LENK_TAG = 9 * 60          # tägliche Lenkzeit, 10 h zweimal pro Woche
MAX_LENK_WOCHE = 56 * 60       # Wochenlenkzeit
MAX_LENK_2WOCHE = 90 * 60      # zwei aufeinanderfolgende Wochen
MAX_LENK_BLOCK = 4 * 60 + 30   # Lenkzeitblock ohne 45 min Pause
MIN_RUHE = 9 * 60              # verkürzte Tagesruhe, Ausgleich nötig
REGEL_RUHE = 11 * 60           # reguläre Tagesruhe
MAX_ARBEIT = 10 * 60           # Arbeitszeit (Arbeit + Fahrt) pro Tag
MAX_ARBEIT_WOCHE = 60 * 60     # § 21a Abs. 4 ArbZG
SCHNITT_ARBEIT_WOCHE = 48 * 60  # Ø über 4 Monate/16 Wochen, § 21a Abs. 4
MIN_WOCHENRUHE = 24 * 60       # reduzierte Wochenruhe
REGEL_WOCHENRUHE = 45 * 60     # regelmäßige Wochenruhe
MAX_ABSTAND_WOCHENRUHE = 6 * 24 * 60   # Art. 8 Abs. 6 VO (EG) 561/2006
MAX_TAGESARBEIT_NACHT = 8 * 60  # § 6 Abs. 2 ArbZG (Nachtarbeit)

# Rechtsgrundlagen je Prüfung (für die Anzeige)
R_LENK_TAG = "Art. 6 Abs. 1 VO (EG) 561/2006"
R_LENK_WOCHE = "Art. 6 Abs. 2 VO (EG) 561/2006"
R_LENK_2WOCHE = "Art. 6 Abs. 3 VO (EG) 561/2006"
R_PAUSE = "Art. 7 VO (EG) 561/2006"
R_TAGRUHE = "Art. 8 Abs. 2 VO (EG) 561/2006"
R_TAGRUHE_ANZ = "Art. 8 Abs. 4 VO (EG) 561/2006"
R_WOCHENRUHE = "Art. 8 Abs. 6 VO (EG) 561/2006"
R_WOCHENRUHE_AUSGLEICH = "Art. 8 Abs. 6b VO (EG) 561/2006"
R_ARBEIT_TAG = "§ 3 ArbZG i. V. m. § 21a Abs. 1 ArbZG"
R_ARBEIT_WOCHE = "§ 21a Abs. 4 ArbZG"
R_ARBEIT_SCHNITT = "§ 3 Abs. 1 ArbZG"
R_PAUSE_ARBZG = "§ 4 ArbZG i. V. m. § 21a Abs. 1 ArbZG"
R_NACHT = "§ 6 Abs. 2 ArbZG"
R_RUHEZEIT_ARBZG = "§ 21a Abs. 5 ArbZG"
R_FPERSV = "§ 1 FPersV"
R_EREIGNIS = "Art. 27/32–34 VO (EU) 165/2014"
R_STOERUNG = "Art. 37 VO (EU) 165/2014"
R_GESCHWINDIGKEIT = "§ 3 StVO"

# Vorschriften für die Registerkarte „Rechtsgrundlagen“
RECHTSGRUNDLAGEN = (
    ("VO (EG) 561/2006",
     "Art. 6 – Lenkzeiten: 9:00 h täglich, zweimal pro Woche 10:00 h; "
     "56:00 h wöchentlich; 90:00 h in zwei aufeinanderfolgenden Wochen.\n"
     "Art. 7 – Pausen: 45 min nach 4:30 h Lenkzeit, teilbar in 15 + 30 min.\n"
     "Art. 8 – Ruhezeiten: 11:00 h täglich (dreimal 9:00 h zwischen "
     "Wochenruhen); Wochenruhe 45:00 h, auf 24:00 h verkürzbar; Beginn "
     "spätestens nach 6 × 24 h; Ausgleich verkürzter Wochenruhen bis zum "
     "Ende der dritten Folgewoche."),
    ("Fahrpersonalverordnung (FPersV)",
     "§ 1 Abs. 1 – verweist für Fahrzeuge über 2,8 t bis 3,5 t auf Art. 4, "
     "6–9 und 12 VO (EG) 561/2006.\n"
     "§ 1 Abs. 5/6 – Pflichten des Unternehmers, Aufzeichnung und "
     "Mitführung.\n"
     "§ 20 – Nachweis berücksichtigungsfreier Tage.\n"
     "§ 21 – Bußgeldvorschriften."),
    ("Arbeitszeitgesetz (ArbZG)",
     "§ 3 – werktäglich 8:00 h, höchstens 10:00 h; Ausgleich innerhalb "
     "von 6 Monaten bzw. 24 Wochen.\n"
     "§ 4 – Ruhepausen: 30 min bei mehr als 6:00 h, 45 min bei mehr als "
     "9:00 h; mindestens 15 min je Pause.\n"
     "§ 6 – Nachtarbeit (23–6 Uhr): 8:00 h täglich; Verlängerung nur bei "
     "einem Durchschnitt von höchstens 8:00 h in vier Wochen.\n"
     "§ 21a Abs. 1 – Anwendung des ArbZG auf das Fahrpersonal.\n"
     "§ 21a Abs. 4 – Wochenarbeitszeit höchstens 60:00 h; Durchschnitt "
     "48:00 h über vier Monate bzw. 16 Wochen.\n"
     "§ 21a Abs. 5 – Ruhezeiten nach VO (EG) 561/2006 gehen vor."),
    ("VO (EU) 165/2014",
     "Art. 27/32–34 – Aufzeichnungspflichten und Ereignisse.\n"
     "Art. 37 – Störungen des Fahrzeuggeräts."),
    ("Straßenverkehrs-Ordnung (StVO)",
     "§ 3 – Geschwindigkeitsüberschreitung (Ereignis 0x07)."),
)

# Kennzeichnet Zeiten nach dem letzten Auslesen der Karte.
UNBEKANNT = -1

# Ereignis-/Störungstypen der Fahrerkarte (EF 0502/0503)
EREIGNIS_NAMEN = {
    0x00: "Keine weiteren Angaben",
    0x01: "Unzulässige Karte gesteckt",
    0x02: "Kartenkonflikt",
    0x03: "Zeitüberschneidung",
    0x04: "Fahren ohne passende Karte",
    0x05: "Karte während der Fahrt gesteckt",
    0x06: "Letzte Kartensitzung nicht korrekt beendet",
    0x07: "Geschwindigkeitsüberschreitung",
    0x08: "Stromversorgung unterbrochen",
    0x09: "Bewegungsdatenfehler",
    0x0A: "Fahrzeugbewegungskonflikt",
    0x0B: "Zeitkonflikt GNSS/Fahrzeuggerät",
    0x0C: "Kommunikationsfehler Fernabfrage",
    0x0D: "Keine GNSS-Position",
    0x0E: "Kommunikationsfehler externes GNSS",
    0x0F: "GNSS-Anomalie",
    0x10: "Sicherheitsverletzung Fahrzeuggerät",
    0x11: "Bewegungssensor nicht authentifiziert",
    0x12: "Karte nicht authentifiziert",
    0x13: "Bewegungssensor unzulässig getauscht",
    0x14: "Datenintegrität der Karte fehlerhaft",
    0x15: "Gespeicherte Nutzerdaten fehlerhaft",
    0x16: "Interner Datenübertragungsfehler",
    0x17: "Gehäuse unzulässig geöffnet",
    0x18: "Hardware-Sabotage",
    0x19: "Manipulation am GNSS erkannt",
    0x1A: "Externes GNSS nicht authentifiziert",
    0x1B: "Zertifikat externes GNSS abgelaufen",
    0x1C: "Bewegung und Aktivität widersprüchlich",
    0x20: "Sicherheitsverletzung Sensor",
    0x21: "Sensor nicht authentifiziert",
    0x22: "Sensordaten fehlerhaft",
    0x23: "Interner Sensor-Datenfehler",
    0x24: "Sensor-Gehäuse geöffnet",
    0x25: "Sensor-Hardware-Sabotage",
    0x30: "Störung Fahrzeuggerät",
    0x31: "Interner Gerätefehler",
    0x32: "Druckerfehler",
    0x33: "Displayfehler",
    0x34: "Download-Fehler",
    0x35: "Sensorfehler",
    0x36: "GNSS-Empfänger gestört",
    0x37: "Externes GNSS gestört",
    0x38: "Fernabfrage gestört",
    0x39: "ITS-Schnittstelle gestört",
    0x3A: "Interner Sensor gestört",
    0x40: "Störung Fahrerkarte",
}

# Ereignisse, die als Verstoß des Fahrers gewertet werden.
VERSTOSS_TYPEN = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07}

# Rechtsbezug der aufgezeichneten Ereignisse/Störungen
EREIGNIS_RECHT = {
    0x01: R_EREIGNIS,
    0x02: R_EREIGNIS,
    0x03: R_EREIGNIS,
    0x04: R_EREIGNIS,
    0x05: R_EREIGNIS,
    0x06: R_EREIGNIS,
    0x07: R_GESCHWINDIGKEIT,
}


def hmm(minuten):
    """Minuten als 'H:MM' (z. B. 510 -> '8:30')."""
    minuten = int(round(minuten))
    return "%d:%02d" % (minuten // 60, minuten % 60)


def uhr(minuten):
    """Minuten seit Mitternacht als Uhrzeit 'H:MM' (Umlauf 24 h)."""
    m = int(minuten) % 1440
    return "%d:%02d" % (m // 60, m % 60)


def _profil(wechsel):
    """Aktivitätswechsel in ein Minutenprofil 0..1439 umrechnen."""
    profil = [0] * 1440
    wechsel = sorted((minute, art) for minute, art in (wechsel or [])
                     if 0 <= minute <= 1440)
    if not wechsel:
        return profil
    for i, (minute, art) in enumerate(wechsel):
        ende = wechsel[i + 1][0] if i + 1 < len(wechsel) else 1440
        minute = max(0, min(1440, minute))
        ende = max(minute, min(1440, ende))
        art = art if 0 <= art <= 3 else 0
        if ende > minute:
            profil[minute:ende] = [art] * (ende - minute)
    return profil


def _bloecke(profil, art, versatz=0):
    """Zusammenhängende Abschnitte einer Art als (von, bis) in Minuten."""
    out = []
    start = None
    for i, a in enumerate(profil):
        if a == art and start is None:
            start = i
        elif a != art and start is not None:
            out.append((start + versatz, i + versatz))
            start = None
    if start is not None:
        out.append((start + versatz, len(profil) + versatz))
    return out


def _pause_genuegt(pausen):
    """Reicht die Pausenverteilung fuer eine Unterbrechung der Lenkzeit?

    45 Minuten am Stueck oder 15 + 30 Minuten (auch in anderer Reihenfolge).
    """
    if any(p >= 45 for p in pausen):
        return True
    lang = [p for p in pausen if p >= 30]
    kurz = [p for p in pausen if p >= 15]
    return bool(lang) and len(kurz) >= 2


def _lenkbloecke_regel(profil):
    """Lenkzeit ohne ausreichende Pause (4:30-Grenze) ermitteln.

    Kurze Unterbrechungen zaehlen als Lenkzeit weiter; erst eine Pause
    von 45 min bzw. 15 + 30 min setzt die Lenkzeit zurueck.

    Rueckgabe: Liste von dicts mit von, bis und dauer (reine Lenkminuten).
    """
    out = []
    start = None
    lenk = 0
    pausen = []
    i = 0
    while i < len(profil):
        if profil[i] == 3:
            if start is None:
                start = i
            lenk += 1
            i += 1
            continue
        j = i
        while j < len(profil) and profil[j] != 3:
            j += 1
        if start is not None:
            pausen.append(j - i)
            if _pause_genuegt(pausen):
                if lenk > MAX_LENK_BLOCK:
                    out.append({"von": start, "bis": i, "dauer": lenk})
                start, lenk, pausen = None, 0, []
        i = j
    if start is not None and lenk > MAX_LENK_BLOCK:
        out.append({"von": start, "bis": len(profil), "dauer": lenk})
    return out


def _kalendertage(tage):
    """Alle Kalendertage der Karte (auch Tage ohne aufgezeichnete Aktivität)."""
    erster, letzter = tage[0]["tag"], tage[-1]["tag"]
    return [erster + timedelta(days=i)
            for i in range((letzter - erster).days + 1)]


def _gesamtprofil(tage):
    """Minutenprofil über alle Kalendertage.

    Tage ohne aufgezeichnete Aktivität gelten als Ruhe: Ohne Fahrerkarte
    im Gerät wurde nicht gefahren. So werden Ruhezeiten über Kartenlücken
    hinweg nicht künstlich zerschnitten.
    """
    profile = {t["tag"]: t["profil"] for t in tage}
    alle = _kalendertage(tage)
    gesamt = []
    for tag in alle:
        gesamt.extend(profile.get(tag) or [0] * 1440)
    return alle, gesamt


def wochenruhen(tage):
    """Ruheblöcke ab 9 h mit Datum und Uhrzeit.

    Rückgabe: (bloecke, alle_tage, gesamtprofil). Jeder Block ist ein
    dict mit start/ende (Minutenindex), tag_von/tag_bis, von/bis
    (Minuten des Tages), dauer und regelmaessig (ab 45 h).
    """
    alle, gesamt = _gesamtprofil(tage)
    bloecke = []
    start = None
    for i, art in enumerate(gesamt):
        if art == 0 and start is None:
            start = i
        elif art != 0 and start is not None:
            if i - start >= 9 * 60:
                bloecke.append((start, i))
            start = None
    if start is not None and len(gesamt) - start >= 9 * 60:
        bloecke.append((start, len(gesamt)))

    out = []
    for a, b in bloecke:
        out.append({
            "start": a,
            "ende": b,
            "tag_von": alle[a // 1440],
            "tag_bis": alle[(b - 1) // 1440],
            "von": a % 1440,
            "bis": ((b - 1) % 1440) + 1,
            "dauer": b - a,
            "regelmaessig": b - a >= REGEL_WOCHENRUHE,
            "wochenruhe": b - a >= MIN_WOCHENRUHE,
        })
    return out, alle, gesamt


def _meldung(tag, schwere, art, text, zeit, recht=None):
    """Meldung an einen Tagesdatensatz anhängen."""
    tag["meldungen"].append({
        "schwere": schwere, "art": art, "text": text,
        "zeit": zeit, "recht": recht,
    })


def _wochen(tage):
    """Tage nach Kalenderwoche (Montag bis Sonntag) gruppieren."""
    wochen = {}
    for t in tage:
        jahr, kw, _ = t["tag"].isocalendar()
        wochen.setdefault((jahr, kw), []).append(t)
    return wochen


def _woche_vollstaendig(tage, jahr, kw):
    """Liegt die Kalenderwoche komplett und vollständig in den Kartendaten?"""
    montag = date.fromisocalendar(jahr, kw, 1)
    sonntag = date.fromisocalendar(jahr, kw, 7)
    if not (tage[0]["tag"] <= montag and tage[-1]["tag"] >= sonntag):
        return False
    return not (tage[-1]["tag"] == sonntag and tage[-1]["unvollstaendig"])


def reduziert_tagesruhen(tage):
    """Höchste Anzahl verkürzter Tagesruhen zwischen zwei Wochenruhen.

    Rückgabe: (anzahl, tag) mit dem Tag des letzten gezählten Verstoßes.
    """
    zaehler = 0
    hoechste = 0
    tag_hoechste = None
    for t in tage:
        r = t["ruhe_vor"]
        if r is None or not r["sicher"]:
            continue
        if r["dauer"] >= MIN_WOCHENRUHE:
            zaehler = 0
            continue
        if not (MIN_RUHE <= r["dauer"] < REGEL_RUHE):
            continue
        zaehler += 1
        if zaehler > hoechste:
            hoechste, tag_hoechste = zaehler, t["tag"]
    return hoechste, tag_hoechste


def _pausen_statistik(tage):
    """Aufgezeichnete Pausen je Arbeitstag auswerten (§ 4 ArbZG).

    Rückgabe: dict mit unter30, unter45, ueber6h und tage.
    """
    unter30 = unter45 = ueber6h = 0
    for t in tage:
        p = t["profil"]
        arbeit = t["summen"]["arbeitszeit"]
        if arbeit <= 0:
            continue
        idx = [k for k in range(1440) if p[k] in (2, 3)]
        if not idx:
            continue
        a, b = idx[0], idx[-1] + 1
        pausen = 0
        for von, bis in _bloecke(p[a:b], 0, versatz=a):
            if bis - von >= 15:
                pausen += bis - von
        if arbeit > 9 * 60 and pausen < 45:
            unter45 += 1
        elif arbeit > 6 * 60 and pausen < 30:
            unter30 += 1
        # länger als 6 h am Stück ohne Pause (mindestens 15 min)
        block = 0
        ruhe = 0
        for minute in p:
            if minute in (2, 3):
                block += 1
                ruhe = 0
                if block > 6 * 60:
                    ueber6h += 1
                    break
            else:
                ruhe += 1
                if ruhe >= 15:
                    block = 0
    return {"unter30": unter30, "unter45": unter45,
            "ueber6h": ueber6h, "tage": len(tage)}


def _nachtarbeit(tage):
    """Nachtarbeit nach § 6 ArbZG (Nachtzeit 23–6 Uhr).

    Rückgabe: dict mit tage (Anzahl der Nachtschichten), max_schnitt
    (Ø Tagesarbeitszeit je Arbeitstag im schlechtesten 4-Wochen-Block)
    und block ((Jahr, erste KW des Blocks)).
    """
    nacht = 0
    bloecke = {}
    for t in tage:
        p = t["profil"]
        minuten = p[0:360].count(2) + p[0:360].count(3) \
            + p[1380:1440].count(2) + p[1380:1440].count(3)
        arbeit = t["summen"]["arbeitszeit"]
        if arbeit <= 0:
            continue
        jahr, kw, _ = t["tag"].isocalendar()
        schluessel = (jahr, kw - (kw - 1) % 4)
        eintrag = bloecke.setdefault(schluessel, {"werte": [], "nacht": 0})
        eintrag["werte"].append(arbeit)
        if minuten >= 2 * 60:
            nacht += 1
            eintrag["nacht"] += 1
    bester = (0, None)
    for schluessel, eintrag in bloecke.items():
        if not eintrag["nacht"] or not eintrag["werte"]:
            continue
        schnitt = sum(eintrag["werte"]) / len(eintrag["werte"])
        if schnitt > bester[0]:
            bester = (schnitt, schluessel)
    return {"tage": nacht, "max_schnitt": bester[0], "block": bester[1]}


def kennzahlen(tage):
    """Kennzahlen und Grenzwerte für die Registerkarte „Rechtsgrundlagen“."""
    if not tage:
        return []

    out = []

    def zeile(name, wert, grenze, status, recht, zusatz=""):
        out.append({"name": name, "wert": wert, "grenze": grenze,
                    "status": status, "recht": recht, "zusatz": zusatz})

    # --- Lenkzeiten ---------------------------------------------------
    max_tag = max(tage, key=lambda t: t["summen"]["lenk"])
    ueber9 = sum(1 for t in tage if t["summen"]["lenk"] > MAX_LENK_TAG)
    ueber10 = sum(1 for t in tage if t["summen"]["lenk"] > 10 * 60)
    if ueber10 or any(m["art"] == "Verstoß" and m.get("recht") == R_LENK_TAG
                      for t in tage for m in t["meldungen"]):
        status = "rot"
    elif ueber9:
        status = "warn"
    else:
        status = "ok"
    zeile("Tägliche Lenkzeit",
          "max. %s am %s · %d Tage über 9 h"
          % (hmm(max_tag["summen"]["lenk"]),
             max_tag["tag"].strftime("%d.%m.%Y"), ueber9),
          "9:00 h, zweimal pro Woche 10:00 h", status, R_LENK_TAG)

    wochen = _wochen(tage)
    max_woche = max(wochen.items(),
                    key=lambda kv: sum(t["summen"]["lenk"] for t in kv[1]))
    summe_woche = sum(t["summen"]["lenk"] for t in max_woche[1])
    zeile("Wochenlenkzeit",
          "max. %s (KW %02d/%d)" % (hmm(summe_woche), max_woche[0][1],
                                    max_woche[0][0]),
          "56:00 h", "rot" if summe_woche > MAX_LENK_WOCHE else "ok",
          R_LENK_WOCHE)

    paare = []
    for (jahr, kw), liste in wochen.items():
        naechste = wochen.get((jahr, kw + 1)) if kw < 52 else wochen.get((jahr + 1, 1))
        if naechste:
            paare.append(((jahr, kw), sum(t["summen"]["lenk"] for t in liste)
                          + sum(t["summen"]["lenk"] for t in naechste)))
    if paare:
        max_paar = max(paare, key=lambda p: p[1])
        zeile("Zwei aufeinanderfolgende Wochen",
              "max. %s (KW %02d/%d)" % (hmm(max_paar[1]),
                                         max_paar[0][1], max_paar[0][0]),
              "90:00 h", "rot" if max_paar[1] > MAX_LENK_2WOCHE else "ok",
              R_LENK_2WOCHE)
    else:
        zeile("Zwei aufeinanderfolgende Wochen", "zu wenig Daten",
              "90:00 h", "info", R_LENK_2WOCHE)

    # --- Ruhezeiten ---------------------------------------------------
    sicher = [t for t in tage
              if t["ruhe_vor"] and t["ruhe_vor"]["sicher"]]
    if sicher:
        min_ruhe = min(sicher, key=lambda t: t["ruhe_vor"]["dauer"])
        dauer = min_ruhe["ruhe_vor"]["dauer"]
        reduziert = sum(1 for t in sicher
                        if MIN_RUHE <= t["ruhe_vor"]["dauer"] < REGEL_RUHE)
        zeile("Tägliche Ruhezeit",
              "min. %s am %s · %d Tage verkürzt"
              % (hmm(dauer), min_ruhe["tag"].strftime("%d.%m.%Y"), reduziert),
              "11:00 h, auf 9:00 h verkürzbar", 
              "rot" if dauer < MIN_RUHE else "ok", R_TAGRUHE)

    anzahl, tag = reduziert_tagesruhen(tage)
    zeile("Verkürzte Tagesruhen zwischen Wochenruhen",
          "%d in Folge%s" % (anzahl,
                             " (bis %s)" % tag.strftime("%d.%m.%Y")
                             if tag else ""),
          "höchstens drei", "rot" if anzahl > 3 else "ok", R_TAGRUHE_ANZ)

    bloecke, alle, _gesamt = wochenruhen(tage)
    wochen_bloecke = [b for b in bloecke if b["wochenruhe"]]
    if wochen_bloecke:
        min_wr = min(wochen_bloecke, key=lambda b: b["dauer"])
        reduziert = sum(1 for b in wochen_bloecke if not b["regelmaessig"])
        groesster = 0
        for vor, nach in zip(wochen_bloecke, wochen_bloecke[1:]):
            groesster = max(groesster, nach["start"] - vor["ende"])
        zeile("Wochenruhezeit",
              "min. %s · %d verkürzt · größter Abstand %s"
              % (hmm(min_wr["dauer"]), reduziert, hmm(groesster)),
              "45:00 h (24:00 h verkürzt), Abstand max. 6 × 24 h",
              "rot" if groesster > MAX_ABSTAND_WOCHENRUHE else
              ("warn" if reduziert else "ok"), R_WOCHENRUHE)
    else:
        zeile("Wochenruhezeit", "keine erkannt", "45:00 h (24:00 h verkürzt)",
              "rot", R_WOCHENRUHE)

    # --- Arbeitszeit (ArbZG) -----------------------------------------
    max_arbeit = max(tage, key=lambda t: t["summen"]["arbeitszeit"])
    ueber10 = sum(1 for t in tage
                  if t["summen"]["arbeitszeit"] > MAX_ARBEIT)
    auffaellig = sum(1 for t in tage
                     if t["summen"]["arbeitszeit"] > 16 * 60)
    text = ("max. %s am %s · %d Tage über 10 h"
            % (hmm(max_arbeit["summen"]["arbeitszeit"]),
               max_arbeit["tag"].strftime("%d.%m.%Y"), ueber10))
    if auffaellig:
        text += " (davon %d über 16 h: Aufzeichnung prüfen)" % auffaellig
    zeile("Tägliche Arbeitszeit", text,
          "8:00 h, höchstens 10:00 h", "rot" if ueber10 else "ok",
          R_ARBEIT_TAG)

    max_aw = max(wochen.items(),
                 key=lambda kv: sum(t["summen"]["arbeitszeit"] for t in kv[1]))
    summe_aw = sum(t["summen"]["arbeitszeit"] for t in max_aw[1])
    zeile("Wochenarbeitszeit",
          "max. %s (KW %02d/%d)"
          % (hmm(summe_aw), max_aw[0][1], max_aw[0][0]),
          "höchstens 60:00 h; Ø 48:00 h über 16 Wochen",
          "rot" if summe_aw > MAX_ARBEIT_WOCHE else "ok", R_ARBEIT_WOCHE)

    volle = sorted(wochen)
    letzte = volle[-16:]
    letzte = [k for k in letzte if _woche_vollstaendig(tage, *k)]
    if len(letzte) >= 8:
        schnitt = sum(t["summen"]["arbeitszeit"]
                      for k in letzte for t in wochen[k]) / len(letzte)
        zeile("Ø Wochenarbeitszeit",
              "%s über %d Wochen" % (hmm(schnitt), len(letzte)),
              "48:00 h", "rot" if schnitt > SCHNITT_ARBEIT_WOCHE else "ok",
              R_ARBEIT_SCHNITT,
              "" if len(letzte) >= 16 else "noch keine 16 vollen Wochen")
    else:
        zeile("Ø Wochenarbeitszeit", "zu wenig Daten", "48:00 h", "info",
              R_ARBEIT_SCHNITT)

    # --- Pausen und Nachtarbeit --------------------------------------
    pausen = _pausen_statistik(tage)
    zeile("Aufgezeichnete Pausen",
          "%d Tage unter 30 min · %d unter 45 min · %d× über 6 h am Stück"
          % (pausen["unter30"], pausen["unter45"], pausen["ueber6h"]),
          "30 min ab 6 h, 45 min ab 9 h, max. 6 h am Stück",
          "warn" if (pausen["unter30"] or pausen["unter45"]
                     or pausen["ueber6h"]) else "ok", R_PAUSE_ARBZG,
          "Nicht im Fahrzeug verbrachte Pausen erscheinen nicht auf der Karte.")

    nacht = _nachtarbeit(tage)
    if nacht["tage"]:
        block = nacht["block"]
        zeile("Nachtarbeit (23–6 Uhr)",
              "%d Tage · Ø %s im 4-Wochen-Block%s"
              % (nacht["tage"], hmm(nacht["max_schnitt"]),
                 " (ab KW %02d)" % block[1] if block else ""),
              "8:00 h je Tag, Verlängerung nur bei Ø ≤ 8:00 h",
              "warn" if nacht["max_schnitt"] > MAX_TAGESARBEIT_NACHT else "ok",
              R_NACHT)
    else:
        zeile("Nachtarbeit (23–6 Uhr)", "keine Nachtschicht erkannt",
              "8:00 h je Tag", "ok", R_NACHT)

    unvoll = sum(1 for t in tage if t["unvollstaendig"])
    zeile("Datenlage",
          "%d Tage ausgewertet · %d unvollständig" % (len(tage), unvoll),
          "letzter Tag endet mit dem Auslesen", "info", None)

    return out


def tage_auswerten(aktivitaet, ereignisse=(), stoerungen=(), ende_am=None):
    """Alle Tage mit Profil, Summen, Lenkzeitblöcken und Meldungen.

    ende_am: Zeitpunkt des letzten Auslesens (z. B. Download der Karte).
    Der Tag, an dem die Karte zuletzt gelesen wurde, ist danach
    unbekannt; dieser Rest wird als „Unbekannt“ geführt und nicht als
    Arbeit oder Ruhe gewertet.

    Rückgabe: chronologische Liste von dicts:
        tag, km, profil (1440 Werte), summen (ruhe/bereit/arbeit/lenk/
        unbekannt/arbeitszeit), lenkbloecke, ruhe_vor, meldungen,
        verstoesse
    """
    profile, km = {}, {}
    for d in aktivitaet:
        tag = d["tag"]
        wechsel = sorted((minute, art)
                         for minute, art in (d.get("wechsel") or [])
                         if 0 <= minute <= 1440)
        profil = _profil(wechsel)
        # Der letzte Zustand eines Tages ist keine gemessene Endzeit, sondern
        # die Fortschreibung des letzten Wechsels. Bleibt die Mode nach
        # Schichtende auf "Arbeit" stehen (typisch beim Kartenziehen), wuerde
        # die Fortschreibung bis 24:00 viele Stunden Freizeit als Arbeitszeit
        # zaehlen. Deshalb gilt der letzte Abschnitt in diesem Fall als
        # unbekannt. Fahrt/Ruhe werden weiter fortgeschrieben: eine Fahrt
        # endet mit einem Wechsel, und Ruhe ist fuer die Tagesruhezeit
        # wichtig.
        if wechsel and wechsel[-1][1] == 2:
            profil[wechsel[-1][0]:] = [UNBEKANNT] * (1440 - wechsel[-1][0])
        profile[tag] = profil
        km[tag] = int(d.get("km") or 0)

    # Der neueste Tag ist nach dem letzten aufgezeichneten Wechsel nicht
    # mehr bekannt. Liegt der Zeitpunkt des Auslesens (ende_am) auf diesem
    # Tag, gilt er als Ende; sonst endet die Aufzeichnung mit dem letzten
    # Wechsel. Steht die Mode am Ende auf "Arbeit", wird sie nicht
    # fortgeschrieben (siehe oben) – dann endet die Messung mit dem
    # letzten Wechsel.
    unvollstaendig = {}
    if profile:
        letzter_tag = max(profile)
        letzte = sorted(
            (minute, art)
            for d in aktivitaet if d["tag"] == letzter_tag
            for minute, art in (d.get("wechsel") or []))
        letzter_wechsel = letzte[-1][0] if letzte else 0
        minute = letzter_wechsel
        if not (letzte and letzte[-1][1] == 2) and ende_am is not None:
            lokal = (ende_am.astimezone(spesen_daten.BERLIN)
                     if ende_am.tzinfo is not None else ende_am)
            if lokal.date() == letzter_tag:
                minute = max(minute, lokal.hour * 60 + lokal.minute)
        if 0 <= minute < 1440:
            profile[letzter_tag][minute:] = \
                [UNBEKANNT] * (1440 - minute)
            unvollstaendig[letzter_tag] = minute

    ereignisse = sorted(ereignisse, key=lambda e: e["beginn"])
    stoerungen = sorted(stoerungen, key=lambda e: e["beginn"])

    tage = []
    erster_tag, letzter_tag = min(profile), max(profile)
    for tag in sorted(profile):
        profil = profile[tag]
        # Fehlende Kalendertage gelten als Ruhe (Karte nicht im Gerät).
        vortag = (profile.get(tag - timedelta(days=1)) or [0] * 1440) \
            if tag > erster_tag else None

        summen = {
            "ruhe": profil.count(0),
            "bereit": profil.count(1),
            "arbeit": profil.count(2),
            "lenk": profil.count(3),
            "unbekannt": profil.count(UNBEKANNT),
        }
        summen["arbeitszeit"] = summen["arbeit"] + summen["lenk"]

        # Lenkzeitblöcke – mit dem Vortag verbunden, damit ein Block über
        # Mitternacht nicht künstlich zerteilt wird.
        if vortag is not None:
            gemeinsam, versatz = vortag + profil, 1440
        else:
            gemeinsam, versatz = profil, 0

        lenkbloecke = []
        for von, bis in _bloecke(gemeinsam, 3):
            if bis <= versatz or von >= versatz + 1440:
                continue
            lenkbloecke.append({
                "dauer": bis - von,
                "von": max(von, versatz) - versatz,
                "bis": min(bis, versatz + 1440) - versatz,
            })

        # Lenkzeit ohne ausreichende Pause (4:30-Grenze)
        regelbloecke = [b for b in _lenkbloecke_regel(gemeinsam)
                        if b["bis"] > versatz and b["von"] < versatz + 1440]

        # Längste zusammenhängende Ruhezeit, die den Tag berührt
        # (Vortag + Tag + Folgetag). Sie steht für die Tagesruhe; über
        # Mitternacht laufende Ruhezeiten werden nicht künstlich zerteilt.
        teile, basis = [], 0
        if vortag is not None:
            teile.append(vortag)
            basis = 1440
        teile.append(profil)
        folgetag = (profile.get(tag + timedelta(days=1)) or [0] * 1440) \
            if tag < letzter_tag else None
        if folgetag is not None:
            teile.append(folgetag)
        ruheprofil = [a for teil in teile for a in teil]
        tag_start, tag_ende = basis, basis + 1440
        ruhe_vor = None
        if summen["arbeitszeit"] or summen["bereit"]:
            for von, bis in _bloecke(ruheprofil, 0):
                if bis <= tag_start or von >= tag_ende:
                    continue
                dauer = bis - von
                if ruhe_vor is None or dauer > ruhe_vor["dauer"]:
                    ruhe_vor = {
                        "dauer": dauer,
                        "von": (max(von, tag_start) - basis) % 1440,
                        "bis": (min(bis, tag_ende) - basis) % 1440,
                        "sicher": not (tag in unvollstaendig),
                    }

        meldungen = []

        def verweiss(schwere, art, text, zeit, recht=None):
            meldungen.append({"schwere": schwere, "art": art,
                              "text": text, "zeit": zeit, "recht": recht})

        if tag in unvollstaendig:
            verweiss("info", "Hinweis",
                     "Tag unvollständig: aufgezeichnet bis %s, "
                     "danach unbekannt" % uhr(unvollstaendig[tag]),
                     uhr(unvollstaendig[tag]))

        # --- berechnete Lenk- und Ruhezeitprüfung -----------------------
        for b in regelbloecke:
            von = max(b["von"], versatz) - versatz
            bis = min(b["bis"], versatz + 1440) - versatz
            verweiss("rot", "Verstoß",
                     "Lenkzeit %s ohne ausreichende Pause (max. 4:30 h), "
                     "%s–%s" % (hmm(b["dauer"]), uhr(von), uhr(bis)),
                     uhr(von), R_PAUSE)
        arbeit = summen["arbeitszeit"]
        if arbeit > 16 * 60:
            verweiss("gelb", "Hinweis",
                     "Arbeitszeit %s – Aufzeichnung prüfen (mehr als 16:00 h)"
                     % hmm(arbeit), None, R_ARBEIT_TAG)
        elif arbeit > MAX_ARBEIT:
            verweiss("rot", "Verstoß",
                     "Tägliche Arbeitszeit %s (mehr als 10:00 h)"
                     % hmm(arbeit), None, R_ARBEIT_TAG)
        if ruhe_vor is not None and ruhe_vor["sicher"] \
                and ruhe_vor["dauer"] < MIN_RUHE:
            verweiss("rot", "Verstoß",
                     "Tagesruhezeit nur %s (mindestens 9:00 h), %s–%s"
                     % (hmm(ruhe_vor["dauer"]), uhr(ruhe_vor["von"]),
                        uhr(ruhe_vor["bis"])),
                     uhr(ruhe_vor["bis"]), R_TAGRUHE)
        elif ruhe_vor is not None and ruhe_vor["sicher"] \
                and ruhe_vor["dauer"] < REGEL_RUHE:
            verweiss("gelb", "Hinweis",
                     "Verkürzte Tagesruhe %s (Ausgleich nötig), %s–%s"
                     % (hmm(ruhe_vor["dauer"]), uhr(ruhe_vor["von"]),
                        uhr(ruhe_vor["bis"])),
                     uhr(ruhe_vor["bis"]), R_TAGRUHE)

        # --- aufgezeichnete Ereignisse und Störungen --------------------
        for quelle, standard_art in ((ereignisse, "Ereignis"),
                                     (stoerungen, "Störung")):
            for e in quelle:
                beginn = e["beginn"].astimezone(spesen_daten.BERLIN)
                ende = e["ende"].astimezone(spesen_daten.BERLIN)
                if ende < beginn:
                    beginn, ende = ende, beginn
                if not (beginn.date() <= tag <= ende.date()):
                    continue
                text = EREIGNIS_NAMEN.get(
                    e["typ"], "Ereignis/Störung 0x%02X" % e["typ"])
                if e.get("kennzeichen"):
                    text += " · %s" % e["kennzeichen"]
                text += " (%s–%s)" % (beginn.strftime("%H:%M"),
                                      ende.strftime("%H:%M"))
                if beginn.date() < tag:
                    text += ", seit Vortag"
                if ende.date() > tag:
                    text += ", bis Folgetag"
                if standard_art == "Ereignis" and e["typ"] in VERSTOSS_TYPEN:
                    art, schwere = "Verstoß", "rot"
                    recht = EREIGNIS_RECHT.get(e["typ"], R_EREIGNIS)
                elif standard_art == "Störung":
                    art, schwere = "Störung", "gelb"
                    recht = R_STOERUNG
                else:
                    art, schwere = "Ereignis", "info"
                    recht = EREIGNIS_RECHT.get(e["typ"])
                verweiss(schwere, art, text, beginn.strftime("%H:%M"), recht)

        rang = {"Verstoß": 0, "Hinweis": 1, "Störung": 2, "Ereignis": 3}
        meldungen.sort(key=lambda m: (rang.get(m["art"], 9),
                                      m["zeit"] or "99:99"))

        tage.append({
            "tag": tag,
            "km": km[tag],
            "profil": profil,
            "summen": summen,
            "lenkbloecke": lenkbloecke,
            "ruhe_vor": ruhe_vor,
            "meldungen": meldungen,
            "unvollstaendig": tag in unvollstaendig,
        })

    # --- Wochenprüfung: Art. 6 und Art. 8 VO (EG) 561/2006 -------------
    # Die tägliche Lenkzeit darf zweimal pro Woche auf 10 Stunden
    # verlängert werden (Montag bis Sonntag).
    if not tage:
        return tage
    wochen = _wochen(tage)
    schluessel = sorted(wochen)

    for (jahr, woche), liste in wochen.items():
        zehn = [t for t in liste if t["summen"]["lenk"] > MAX_LENK_TAG]
        erlaubt = 0
        for t in zehn:
            lenk = t["summen"]["lenk"]
            if lenk > 10 * 60:
                _meldung(t, "rot", "Verstoß",
                         "Tageslenkzeit %s (mehr als 10:00 h)" % hmm(lenk),
                         None, R_LENK_TAG)
            elif erlaubt < 2:
                erlaubt += 1
                _meldung(t, "info", "Hinweis",
                         "Tageslenkzeit %s – 10-Stunden-Ausnahme "
                         "(%d von 2 in dieser Woche)" % (hmm(lenk), erlaubt),
                         None, R_LENK_TAG)
            else:
                _meldung(t, "rot", "Verstoß",
                         "Tageslenkzeit %s – dritte Verlängerung in dieser "
                         "Woche (nur zweimal erlaubt)" % hmm(lenk),
                         None, R_LENK_TAG)

        # Wochenlenkzeit: 56 Stunden; Verstoß an dem Tag, an dem die
        # Grenze überschritten wird.
        summe = 0
        gemeldet = False
        for t in liste:
            summe += t["summen"]["lenk"]
            if summe > MAX_LENK_WOCHE and not gemeldet:
                _meldung(t, "rot", "Verstoß",
                         "Wochenlenkzeit %s (mehr als 56:00 h)" % hmm(summe),
                         None, R_LENK_WOCHE)
                gemeldet = True

    # Zwei aufeinanderfolgende Wochen: 90 Stunden.
    def folgewoche(jahr, kw):
        montag = date.fromisocalendar(jahr, kw, 1) + timedelta(weeks=1)
        j, k, _ = montag.isocalendar()
        return (j, k)

    for (jahr, kw) in schluessel:
        naechste = folgewoche(jahr, kw)
        if naechste not in wochen:
            continue
        summe = sum(t["summen"]["lenk"] for t in wochen[(jahr, kw)])
        gemeldet = False
        for t in wochen[naechste]:
            summe += t["summen"]["lenk"]
            if summe > MAX_LENK_2WOCHE and not gemeldet:
                _meldung(t, "rot", "Verstoß",
                         "Lenkzeit %s in zwei aufeinanderfolgenden Wochen "
                         "(mehr als 90:00 h)" % hmm(summe),
                         None, R_LENK_2WOCHE)
                gemeldet = True

    # Art. 8 Abs. 4: höchstens drei verkürzte Tagesruhen zwischen zwei
    # Wochenruhen.
    reduziert = 0
    for t in tage:
        r = t["ruhe_vor"]
        if r is None or not r["sicher"]:
            continue
        if r["dauer"] >= MIN_WOCHENRUHE:
            reduziert = 0
            continue
        if not (MIN_RUHE <= r["dauer"] < REGEL_RUHE):
            continue
        reduziert += 1
        if reduziert > 3:
            _meldung(t, "rot", "Verstoß",
                     "%d. verkürzte Tagesruhe (%s) zwischen zwei "
                     "Wochenruhen – nur drei erlaubt"
                     % (reduziert, hmm(r["dauer"])),
                     None, R_TAGRUHE_ANZ)

    # Wochenruhe: spätestens nach 6 × 24 h beginnen (Art. 8 Abs. 6).
    bloecke, alle, _gesamt = wochenruhen(tage)
    je_tag = {t["tag"]: t for t in tage}
    wochen_bloecke = [b for b in bloecke if b["wochenruhe"]]
    for vor, nach in zip(wochen_bloecke, wochen_bloecke[1:]):
        abstand = nach["start"] - vor["ende"]
        if abstand <= MAX_ABSTAND_WOCHENRUHE:
            continue
        grenze = vor["ende"] + MAX_ABSTAND_WOCHENRUHE
        if grenze >= len(_gesamt):
            continue
        tag = alle[grenze // 1440]
        eintrag = je_tag.get(tag)
        if eintrag is None:
            continue
        _meldung(eintrag, "rot", "Verstoß",
                 "Wochenruhe nicht rechtzeitig begonnen (Abstand %s seit "
                 "dem %s, höchstens 6 × 24 h)"
                 % (hmm(abstand), vor["tag_bis"].strftime("%d.%m.%Y")),
                 uhr(grenze % 1440), R_WOCHENRUHE)

    # Art. 8 Abs. 6b: verkürzte Wochenruhen sind bis zum Ende der dritten
    # Folgewoche durch eine angeschlossene Ruhezeit auszugleichen.
    for b in wochen_bloecke:
        if b["regelmaessig"]:
            continue
        fehlt = REGEL_WOCHENRUHE - b["dauer"]
        jahr, kw, _ = b["tag_von"].isocalendar()
        frist = date.fromisocalendar(jahr, kw, 1) + timedelta(weeks=4)
        ausgleich = None
        for kandidat in bloecke:
            if kandidat["start"] < b["ende"]:
                continue
            if kandidat["tag_von"] >= frist:
                continue
            if kandidat["dauer"] >= MIN_RUHE + fehlt:
                ausgleich = kandidat
                break
        if ausgleich is not None:
            continue
        if frist <= alle[-1] + timedelta(days=1):
            tag = frist - timedelta(days=1)
            eintrag = je_tag.get(tag)
            if eintrag is None:
                eintrag = je_tag.get(b["tag_bis"])
            if eintrag is not None:
                _meldung(eintrag, "rot", "Verstoß",
                         "Ausgleich für verkürzte Wochenruhe (%s am %s) "
                         "nicht nachgewiesen – %s bis zum %s nötig"
                         % (hmm(b["dauer"]),
                            b["tag_von"].strftime("%d.%m.%Y"),
                            hmm(fehlt), frist.strftime("%d.%m.%Y")),
                         None, R_WOCHENRUHE_AUSGLEICH)
        else:
            eintrag = je_tag.get(b["tag_bis"])
            if eintrag is not None:
                _meldung(eintrag, "info", "Hinweis",
                         "Verkürzte Wochenruhe %s – Ausgleich %s bis zum "
                         "%s nötig"
                         % (hmm(b["dauer"]), hmm(fehlt),
                            frist.strftime("%d.%m.%Y")),
                         None, R_WOCHENRUHE_AUSGLEICH)

    rang = {"Verstoß": 0, "Hinweis": 1, "Störung": 2, "Ereignis": 3}
    for t in tage:
        t["meldungen"].sort(key=lambda m: (rang.get(m["art"], 9),
                                           m["zeit"] or "99:99",
                                           m.get("recht") or ""))
        t["verstoesse"] = [m for m in t["meldungen"]
                           if m["schwere"] == "rot"]
    return tage
