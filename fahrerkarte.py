# -*- coding: utf-8 -*-
"""
fahrerkarte.py — Fahrerkarte (digitale Tachographenkarte) auslesen
==================================================================

Liest eine EU-Fahrerkarte über einen PC/SC-Kartenleser (USB) aus und erzeugt
daraus eine offizielle .ddd-Download-Datei (auch C1B oder ESM-Datei genannt),
die von allen gängigen Auswertungsprogrammen (TachoPlus, DTCO, ... gelesen
werden kann.

Karten der 1. Generation (Gen-1, AID "TACHO") und — sofern vorhanden — auch
die 2. Generation (Gen-2, AID "TACHO_G2" mit GNSS-Orten) werden gelesen.

Ablauf:
  1. Kartenleser über PC/SC finden und Karte im T=0-Protokoll ansprechen
  2. Tachograph-Anwendung (AID "TACHO") wählen
  3. Alle Dateien (EFs) der Gen-1-Anwendung lesen:
     EF.ICC / EF.IC (Chip-Daten), Anwendungs-Identifikation, Zertifikate,
     Karten-Identifikation (Name, Kartennummer, Gültigkeit), Fahrerlaubnis,
     Ereignisse, Fehler, Fahreraktivitäten (Lenk-/Arbeitszeiten),
     genutzte Fahrzeuge, Orte, aktuelle Nutzung, Kontrollen,
     besondere Bedingungen
  4. Gen-2-Anwendung (AID "TACHO_G2") lesen, wenn die Karte sie enthält:
     dieselben Dateien in der Gen-2-Struktur (mit GNSS-Positionen bei den
     Tätigkeitsorten und FIN bei den Fahrzeugen) sowie die Gen-2-Dateien
     0523–0530 (Fahrzeuggeräte, GNSS-Positionen, Authentisierungen,
     Grenzüberschreitungen, Be-/Entladevorgänge)
  5. Für jede signierte Datei: PERFORM HASH + COMPUTE DIGITAL SIGNATURE
     (128 Byte Gen-1 / 64 Byte Gen-2) — ohne diese wäre die .ddd ungültig
  6. .ddd-Datei schreiben (Blockformat: EF-ID, Typ, Länge, Daten)
  7. Übersicht ausgeben (Inhaber, Karte, Aktivitäten der letzten Tage, Fahrzeuge)

Voraussetzung:  pip install pyscard   (Windows: wird sonst nichts benötigt)

Verwendung:      py fahrerkarte.py [Ausgabeverzeichnis]
"""

import hashlib
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from smartcard.System import readers
    from smartcard.scard import (
        SCardEstablishContext, SCardReleaseContext, SCardConnect,
        SCardDisconnect, SCardReconnect, SCardTransmit,
        SCARD_SCOPE_USER, SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0,
        SCARD_RESET_CARD, SCARD_LEAVE_CARD, SCARD_PCI_T0,
    )
except ImportError:
    print("Fehler: Das Modul 'pyscard' fehlt.")
    print("Bitte einmalig installieren:  py -m pip install pyscard")
    sys.exit(1)

# Auf der Windows-Konsole (cp1252) würden Pfeile/Sonderzeichen sonst einen
# UnicodeEncodeError auslösen. Die Oberfläche schreibt ohnehin in ein
# eigenes Protokoll; hier nur den Konsolenbetrieb absichern.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass


# ---------------------------------------------------------------- Konstanten

TACHO_AID = [0xFF, 0x54, 0x41, 0x43, 0x48, 0x4F]        # "TACHO"
TACHO_G2_AID = [0xFF, 0x53, 0x4D, 0x52, 0x44, 0x54]     # "SMRDT" (TACHO_G2)

CARD_TYPES = {
    0x01: "Fahrerkarte",
    0x02: "Werkstattkarte",
    0x03: "Kontrollkarte",
    0x04: "Firmenkarte",
    0x05: "Herstellerkarte",
}

NATIONS = {
    0x00: "keine Angabe", 0x01: "Österreich", 0x02: "Albanien",
    0x03: "Andorra", 0x05: "Aserbaidschan", 0x06: "Belgien",
    0x07: "Bulgarien", 0x08: "Bosnien und Herzegowina", 0x09: "Weißrussland",
    0x0A: "Schweiz", 0x0B: "Zypern", 0x0C: "Tschechien", 0x0D: "Deutschland",
    0x0E: "Dänemark", 0x0F: "Spanien", 0x10: "Estland", 0x11: "Frankreich",
    0x12: "Finnland", 0x13: "Liechtenstein", 0x14: "Färöer",
    0x15: "Vereinigtes Königreich", 0x16: "Georgien", 0x17: "Griechenland",
    0x18: "Ungarn", 0x19: "Kroatien", 0x1A: "Italien", 0x1B: "Irland",
    0x1C: "Island", 0x1E: "Luxemburg", 0x1F: "Litauen", 0x20: "Lettland",
    0x21: "Malta", 0x22: "Monaco", 0x23: "Moldau", 0x25: "Norwegen",
    0x26: "Niederlande", 0x27: "Portugal", 0x28: "Polen", 0x29: "Rumänien",
    0x2C: "Schweden", 0x2D: "Slowakei", 0x2E: "Slowenien", 0x30: "Türkei",
    0x31: "Ukraine", 0xFD: "Europäische Gemeinschaft",
}

ACTIVITIES = ("Pause", "Bereitschaft", "Arbeit", "Fahren")


# ------------------------------------------------------------- Low-Level-Karte

class CardError(Exception):
    pass


# PC/SC-Rückgabecodes: Klartext und konkreter Hinweis für die Oberfläche.
SCARD_FEHLER = {
    0x80100009: "SCARD_E_UNKNOWN_READER",
    0x8010000A: "SCARD_E_TIMEOUT",
    0x8010000B: "SCARD_E_SHARING_VIOLATION",
    0x8010000C: "SCARD_E_NO_SMARTCARD",
    0x8010000D: "SCARD_E_UNKNOWN_CARD",
    0x8010000F: "SCARD_E_PROTO_MISMATCH",
    0x80100010: "SCARD_E_NOT_READY",
    0x80100013: "SCARD_F_COMM_ERROR",
    0x80100017: "SCARD_E_READER_UNAVAILABLE",
    0x8010001D: "SCARD_E_NO_SERVICE",
    0x8010002E: "SCARD_E_NO_READERS_AVAILABLE",
    0x80100065: "SCARD_W_UNSUPPORTED_CARD",
    0x80100066: "SCARD_W_UNRESPONSIVE_CARD",
    0x80100067: "SCARD_W_UNPOWERED_CARD",
    0x80100068: "SCARD_W_RESET_CARD",
    0x80100069: "SCARD_W_REMOVED_CARD",
}

# Bei diesen Codes lohnt ein erneuter Versuch (Karte wird oft erst nach
# ein bis zwei Sekunden erkannt bzw. mit Strom versorgt).
SCARD_WIEDERHOLEN = {
    0x8010000A, 0x8010000C, 0x80100010, 0x80100013,
    0x80100067, 0x80100066, 0x80100068, 0x80100069,
}


def scard_text(hr):
    """PC/SC-Fehlercode als Text (z. B. 'SCARD_E_NO_SMARTCARD')."""
    code = hr & 0xFFFFFFFF
    return "%s (0x%08X)" % (SCARD_FEHLER.get(code, "PC/SC-Fehler"), code)


def scard_hinweis(hr):
    """Passende Handlungsanweisung zu einem PC/SC-Fehlercode."""
    code = hr & 0xFFFFFFFF
    if code in (0x8010000C, 0x80100069, 0x80100067):
        return ("Die Karte wurde nicht erkannt. Bitte die Fahrerkarte ganz "
                "in den Leser stecken (Chip voran bzw. nach unten, je nach "
                "Leser) und bis zum Anschlag drücken. Leuchtet die LED am "
                "Leser nicht, den Leser kurz ab- und wieder anstecken.")
    if code == 0x8010000B:
        return ("Die Karte wird gerade von einem anderen Programm benutzt "
                "(z. B. Tachographen- oder Auslesesoftware). Bitte dieses "
                "Programm schließen und erneut versuchen.")
    if code in (0x80100009, 0x80100017):
        return ("Der Kartenleser ist nicht mehr erreichbar. Bitte das USB-"
                "Kabel abziehen, kurz warten und wieder anstecken.")
    if code == 0x8010001D:
        return ("Der Windows-Dienst „Smart Card“ läuft nicht. Bitte den "
                "Dienst starten (Dienste-Verwaltung) oder den PC neu starten.")
    if code in (0x80100066, 0x80100068):
        return ("Die Karte antwortet nicht. Bitte die Karte abziehen, kurz "
                "warten und erneut einstecken.")
    if code == 0x80100065:
        return ("Diese Karte wird nicht als Fahrerkarte erkannt. Bitte "
                "prüfen, ob die Karte richtig herum eingesteckt ist.")
    if code == 0x8010000F:
        return ("Karte und Leser verständigen sich nicht (Protokoll). "
                "Bitte die Karte abziehen und erneut einstecken.")
    if code == 0x80100013:
        return ("Kommunikationsfehler mit dem Leser. Bitte den Leser vom "
                "USB-Anschluss trennen und wieder anschließen.")
    if code == 0x8010002E:
        return ("Es ist kein Kartenleser angeschlossen. Bitte den USB-Leser "
                "verbinden und die Karte einstecken.")
    return ("Bitte die Karte abziehen, kurz warten, erneut einstecken und "
            "den Vorgang wiederholen.")


class TachoCard:
    """Verbindung zur Karte im Leser (Protokoll T=0)."""

    VERSUCHE = 4
    PAUSE = 0.6                  # Sekunden zwischen zwei Verbindungsversuchen

    def __init__(self, reader_name):
        self.ctx = None
        self.hcard = None
        hr, self.ctx = SCardEstablishContext(SCARD_SCOPE_USER)
        if hr != 0:
            self.ctx = None
            raise CardError(
                "Smartcard-Dienst nicht erreichbar: %s\n%s"
                % (scard_text(hr), scard_hinweis(hr)))

        hr = self._verbinden(reader_name)
        if hr != 0:
            self._trennen(SCARD_LEAVE_CARD)
            raise CardError(
                "Keine Karte im Leser '%s' gefunden.\n%s\n%s"
                % (reader_name, scard_text(hr), scard_hinweis(hr)))
        self.reader = reader_name

        # Karte zuruecksetzen: Nach einem Auslesen bleibt sie in der zuletzt
        # gewaehlten Anwendung (Gen-1/Gen-2). Ohne Reset schlaegt das naechste
        # Auslesen bei EF.ICC/EF.IC fehl, solange die Karte stecken bleibt.
        hr, _ = SCardReconnect(
            self.hcard, SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0,
            SCARD_RESET_CARD)
        if hr != 0:
            self._trennen(SCARD_LEAVE_CARD)
            raise CardError(
                "Karte konnte nicht zurueckgesetzt werden: %s\n%s"
                % (scard_text(hr), scard_hinweis(hr)))

    def _verbinden(self, reader_name):
        """SCardConnect mit kurzen Wiederholungen für träge Leser."""
        letzter = None
        for versuch in range(self.VERSUCHE):
            hr, hcard, _ = SCardConnect(
                self.ctx, reader_name, SCARD_SHARE_SHARED,
                SCARD_PROTOCOL_T0)
            if hr == 0:
                self.hcard = hcard
                return 0
            letzter = hr
            if (hr & 0xFFFFFFFF) not in SCARD_WIEDERHOLEN:
                break
            if versuch + 1 < self.VERSUCHE:
                time.sleep(self.PAUSE)
        return letzter

    def _trennen(self, disposition):
        if self.hcard is not None:
            SCardDisconnect(self.hcard, disposition)
            self.hcard = None
        if self.ctx is not None:
            SCardReleaseContext(self.ctx)
            self.ctx = None

    def close(self):
        # Reset beim Trennen: die Karte startet beim naechsten Zugriff
        # wieder im Master File.
        self._trennen(SCARD_RESET_CARD)

    def _tx(self, apdu):
        """APDU senden; GET RESPONSE (61xx) automatisch abarbeiten."""
        hr, resp = SCardTransmit(self.hcard, SCARD_PCI_T0, list(apdu))
        if hr != 0:
            raise CardError("Übertragungsfehler zur Karte (0x%08X)." % hr)
        data, sw1, sw2 = list(resp[:-2]), resp[-2], resp[-1]
        while sw1 == 0x61:
            hr, resp = SCardTransmit(
                self.hcard, SCARD_PCI_T0, [0x00, 0xC0, 0x00, 0x00,
                                           sw2 if sw2 else 0xFF])
            if hr != 0:
                raise CardError("GET RESPONSE fehlgeschlagen (0x%08X)." % hr)
            data += list(resp[:-2])
            sw1, sw2 = resp[-2], resp[-1]
        return bytes(data), (sw1 << 8) | sw2

    # --- Befehle gemäß EU-Verordnung 2016/799, Anhang 1C -------------------

    def select_aid(self, aid=None):
        """Tachograph-Anwendung wählen (SELECT by AID)."""
        aid = TACHO_AID if aid is None else aid
        _, sw = self._tx([0x00, 0xA4, 0x04, 0x0C, len(aid)] + aid)
        if sw != 0x9000:
            raise CardError(
                "Tachograph-Anwendung nicht gefunden (SW=%04X). "
                "Ist eine Fahrerkarte im Leser?" % sw)

    def select_ef(self, fid):
        """Elementardatei per Datei-ID wählen. Liefert True bei Erfolg."""
        _, sw = self._tx([0x00, 0xA4, 0x02, 0x0C, 0x02,
                          (fid >> 8) & 0xFF, fid & 0xFF])
        return sw == 0x9000

    def read_binary(self, length, tolerant=False):
        """Vollständige Datei lesen (in 200-Byte-Stücken).

        tolerant=True (Gen-2-Anwendung): Die Dateilänge ist nur berechnet.
        Wird das Dateiende vorher erreicht (SW 6282), werden die Restdaten
        übernommen; ist die Datei länger als berechnet, wird weiter gelesen,
        bis die Karte nichts mehr liefert (max. bis Offset 32700 — READ
        BINARY kennt keine größeren Offsets).
        """
        out = bytearray()
        while len(out) < length:
            want = min(200, length - len(out))
            offset = len(out)
            data, sw = self._tx([0x00, 0xB0, (offset >> 8) & 0x7F,
                                 offset & 0xFF, want])
            if sw == 0x9000:
                if not data:
                    break
                out.extend(data)
            elif tolerant and (sw >> 8) == 0x62:
                # Dateiende erreicht (SW 6282): Restdaten uebernehmen
                out.extend(data)
                break
            else:
                raise CardError("READ BINARY bei Offset %d fehlgeschlagen "
                                "(SW=%04X)." % (offset, sw))
        if tolerant:
            # Ist die Datei länger als berechnet? Ende der Datei suchen.
            while len(out) < 32700:
                offset = len(out)
                data, sw = self._tx([0x00, 0xB0, (offset >> 8) & 0x7F,
                                     offset & 0xFF, 1])
                if sw != 0x9000 or not data:
                    break             # Dateiende erreicht
                data, sw = self._tx([0x00, 0xB0, (offset >> 8) & 0x7F,
                                     offset & 0xFF,
                                     min(200, 32700 - offset)])
                if sw == 0x9000 and data:
                    out.extend(data)
                elif (sw >> 8) == 0x62 and data:
                    out.extend(data)
                    break
                else:
                    break
        elif len(out) < length:
            raise CardError("Datei unvollständig gelesen (%d von %d Bytes)."
                            % (len(out), length))
        return bytes(out)

    def perform_hash(self):
        """PERFORM HASH OF FILE über die aktuell gewählte Datei."""
        for apdu in ([0x80, 0x2A, 0x90, 0x00],     # Standard (CLA 0x80)
                     [0x00, 0x2A, 0x90, 0x00]):    # Fallback (CLA 0x00)
            _, sw = self._tx(apdu)
            if sw == 0x9000:
                return True
        return False

    def compute_signature(self, laenge=128):
        """COMPUTE DIGITAL SIGNATURE (128 Byte Gen-1 / 64 Byte Gen-2)."""
        data, sw = self._tx([0x00, 0x2A, 0x9E, 0x9A, laenge])
        if sw != 0x9000 or len(data) < min(laenge, 64):
            return None
        return data


# ------------------------------------------------------------ Download der Karte

# (Datei-ID, Name, Signatur erzeugen?)
EF_ICC = (0x0002, "EF.ICC – Chip-Identifikation", False)
EF_IC = (0x0005, "EF.IC – Chip-Seriennummer", False)


def oeffne_karte(reader_name=None):
    """Karte im ersten Leser öffnen, in dem eine steckt.

    Bei mehreren angeschlossenen Lesern werden alle der Reihe nach
    probiert. Schlägt es überall fehl, enthält die Fehlermeldung die
    Ursache je Leser (inkl. PC/SC-Code und Handlungshinweis).
    """
    verfuegbar = [str(r) for r in readers()]
    namen = [reader_name] if reader_name else verfuegbar
    if not namen:
        raise CardError(
            "Kein Kartenleser gefunden. Bitte den USB-Kartenleser "
            "anschließen und die Fahrerkarte einstecken.")
    fehler = []
    for name in namen:
        try:
            return TachoCard(name)
        except CardError as e:
            fehler.append((name, str(e)))
            if reader_name:
                break
    if len(fehler) == 1:
        raise CardError(fehler[0][1])
    raise CardError("Keine Karte in einem der Leser gefunden.\n\n"
                    + "\n\n".join("%s:\n%s" % (name, text)
                                  for name, text in fehler))


def download(card):
    """Liest alle Dateien der Fahrerkarte. Rückgabe: (Blöcke, Metadaten)."""
    blocks = []      # Liste (fid, typ, bytes) – typ 0=Daten, 1=Signatur
    meta = {}

    def read_ef(fid, name, length, signed=False, optional=False):
        if not card.select_ef(fid):
            if optional:
                return None
            raise CardError("Datei %s (%04X) nicht auf der Karte gefunden."
                            % (name, fid))
        hashed = False
        if signed:
            hashed = card.perform_hash()
        data = card.read_binary(length)
        blocks.append((fid, 0, data))
        sig = None
        if signed:
            sig = card.compute_signature()
            if sig:
                blocks.append((fid, 1, sig))
        print("   %-42s %6d Byte  %s"
              % (name, len(data),
                 "signiert" if sig else ("Hash OK, ohne Signatur"
                                         if hashed else "ohne Signatur")))
        return data

    print("\n1. Chip-Dateien werden gelesen ...")
    read_ef(EF_ICC[0], EF_ICC[1], 25, EF_ICC[2])
    read_ef(EF_IC[0], EF_IC[1], 8, EF_IC[2])

    print("\n2. Tachograph-Anwendung wird gewählt ...")
    card.select_aid()

    print("\n3. Anwendungsdaten werden gelesen ...")
    ident_raw = read_ef(0x0501, "EF Anwendungs-Identifikation", 10, True)
    card_type = ident_raw[0]
    no_events = ident_raw[3]
    no_faults = ident_raw[4]
    act_len = int.from_bytes(ident_raw[5:7], "big")
    no_vehicles = int.from_bytes(ident_raw[7:9], "big")
    no_places = ident_raw[9]
    meta.update(card_type=card_type, structure=ident_raw[1:3],
                no_events=no_events, no_faults=no_faults, act_len=act_len,
                no_vehicles=no_vehicles, no_places=no_places)
    print("   → %s, Struktur-Version %s, Aktivitätsspeicher %d Byte"
          % (CARD_TYPES.get(card_type, "unbekannter Kartentyp"),
             meta["structure"].hex(), act_len))

    read_ef(0xC100, "EF Karten-Zertifikat", 194, False, optional=True)
    read_ef(0xC108, "EF Mitgliedstaaten-Zertifikat", 194, False,
            optional=True)
    read_ef(0xC200, "EF Karten-Zertifikat (GOST)", 1000, False,
            optional=True)
    read_ef(0xC201, "EF Schlüssel-Identifikatoren", 16, True, optional=True)
    read_ef(0xC208, "EF Mitgliedstaaten-Zertifikat (GOST)", 1000, False,
            optional=True)

    ident = read_ef(0x0520, "EF Karten-Identifikation", 143, True)
    meta["ident_raw"] = ident
    read_ef(0x050E, "EF letzter Karten-Download", 4, True)
    read_ef(0x0521, "EF Führerschein-Information", 53, True)
    events = read_ef(0x0502, "EF Ereignisdaten",
                     no_events * 24 * 6, True)
    faults = read_ef(0x0503, "EF Fehlerdaten", no_faults * 24 * 2, True)
    activity = read_ef(0x0504, "EF Fahreraktivitäten", act_len + 4, True)
    vehicles = read_ef(0x0505, "EF genutzte Fahrzeuge",
                       no_vehicles * 31 + 2, True)
    read_ef(0x0506, "EF Tätigkeitsorte", no_places * 10 + 1, True)
    read_ef(0x0507, "EF aktuelle Nutzung", 19, True)
    read_ef(0x0508, "EF Kontrollaktivitäten", 46, True)
    read_ef(0x0522, "EF besondere Bedingungen", 280, True)

    meta.update(events=events, faults=faults, activity=activity,
                vehicles=vehicles)
    return blocks, meta


def download_g2(card, blocks, meta):
    """Gen-2-Anwendung (TACHO_G2) der Karte lesen und an 'blocks' anhaengen.

    Karten der 2. Generation enthalten beide Anwendungen (EU 2016/799,
    TCS_145). Die Gen-2-Dateien werden als Bloecke vom Typ 2 (Daten) bzw.
    3 (Signatur, 64 Byte) angehaengt — so wie es offizielle .ddd-Downloads
    von Gen-2-Karten tun. Rueckgabe: True, wenn Gen-2-Daten gelesen wurden.

    Nur Struktur-Version 01 01 (G2V2) wird unterstuetzt.
    """
    print("\n4. Gen-2-Anwendung (TACHO_G2, GNSS-Orte) wird geprüft ...")
    try:
        card.select_aid(TACHO_G2_AID)
    except CardError as e:
        print("   %s" % e)
        print("   Karte ohne Gen-2-Anwendung — nur Gen-1-Daten im Download.")
        return False

    g1_daten = {fid: daten for fid, typ, daten in blocks if typ == 0}
    g2 = []      # wird nur bei Erfolg an 'blocks' angehaengt

    def read_ef(fid, name, length, signed=True, optional=False):
        if not card.select_ef(fid):
            if optional:
                print("   %-42s nicht vorhanden (übersprungen)" % name)
                return None
            raise CardError("Datei %s (%04X) nicht auf der Karte gefunden."
                            % (name, fid))
        hashed = False
        if signed:
            hashed = card.perform_hash()
        data = card.read_binary(length, tolerant=True)
        g2.append((fid, 2, data))
        sig = None
        if signed:
            sig = card.compute_signature(64)
            if sig:
                g2.append((fid, 3, sig))
        print("   %-42s %6d Byte  %s"
              % (name, len(data),
                 "signiert (G2)" if sig else ("Hash OK, ohne Signatur"
                                              if hashed else "ohne Signatur")))
        return data

    try:
        ident_raw = read_ef(0x0501, "EF Anwendungs-Identifikation (G2)", 17)
        version = ident_raw[0:2]
        if version != b"\x01\x01":
            print("   Struktur-Version %s wird nicht unterstützt "
                  "(erwartet 01 01) — Gen-2 wird weggelassen."
                  % version.hex(" "))
            return False
        no_events = ident_raw[3]
        no_faults = ident_raw[4]
        act_len = int.from_bytes(ident_raw[5:7], "big")
        no_vehicles = int.from_bytes(ident_raw[7:9], "big")
        no_places = int.from_bytes(ident_raw[9:11], "big")
        no_gnss = int.from_bytes(ident_raw[11:13], "big")
        no_specific = int.from_bytes(ident_raw[13:15], "big")
        no_vunits = int.from_bytes(ident_raw[15:17], "big")
        print("   → Karte der 2. Generation (G2V2), %d GNSS-Positionen, "
              "%d Orte, %d Fahrzeuge" % (no_gnss, no_places, no_vehicles))

        # EF.ICC / EF.IC: in der Gen-2-Ansicht unsigniert; sind sie dort
        # nicht erreichbar, wird die Gen-1-Kopie uebernommen
        for fid, name, laenge in ((0x0002, "EF.ICC – Chip-Identifikation", 25),
                                  (0x0005, "EF.IC – Chip-Seriennummer", 8)):
            daten = None
            try:
                if card.select_ef(fid):
                    daten = card.read_binary(laenge, tolerant=True)
            except CardError:
                daten = None
            if daten is None:
                daten = g1_daten.get(fid, b"")
                print("   %-42s %6d Byte  Kopie aus Gen-1"
                      % (name, len(daten)))
            else:
                print("   %-42s %6d Byte  gelesen" % (name, len(daten)))
            g2.append((fid, 2, daten))

        read_ef(0xC101, "EF Karten-Zertifikat (G2)", 205, signed=False)
        read_ef(0xC108, "EF Mitgliedstaaten-Zertifikat (G2)", 205,
                signed=False)
        read_ef(0xC109, "EF Zertifikat (G2)", 205, signed=False)
        read_ef(0x0520, "EF Karten-Identifikation", 143)
        read_ef(0x050E, "EF letzter Karten-Download", 4)
        read_ef(0x0521, "EF Führerschein-Information", 53)
        read_ef(0x0502, "EF Ereignisdaten", no_events * 11 * 24)
        read_ef(0x0503, "EF Fehlerdaten", no_faults * 2 * 24)
        read_ef(0x0504, "EF Fahreraktivitäten", act_len + 4)
        read_ef(0x0505, "EF genutzte Fahrzeuge (mit FIN)",
                no_vehicles * 48 + 2)
        read_ef(0x0506, "EF Tätigkeitsorte (mit GNSS)",
                no_places * 21 + 2)
        read_ef(0x0507, "EF aktuelle Nutzung", 19)
        read_ef(0x0508, "EF Kontrollaktivitäten", 46)
        read_ef(0x0522, "EF besondere Bedingungen", no_specific * 5 + 2)
        read_ef(0x0523, "EF genutzte Fahrzeuggeräte", no_vunits * 10 + 2)
        read_ef(0x0524, "EF GNSS-Positionen", no_gnss * 18 + 2)
        # Ab hier Dateien, die erst mit späteren Gen-2-Karten dazugekommen
        # sind. Ältere Gen-2-Karten (z. B. aus 2021) haben sie nicht; sie
        # werden dann übersprungen, statt den gesamten Gen-2-Download
        # abzubrechen.
        read_ef(0x0525, "EF Gen-2-Zähler", 10, optional=True)
        read_ef(0x0526, "EF Orts-Authentisierung", no_places * 5 + 2,
                optional=True)
        read_ef(0x0527, "EF Ladungsart-Einträge", no_gnss * 5 + 2,
                optional=True)
        read_ef(0x0528, "EF Grenzüberschreitungen", 2 + 1120 * 17,
                optional=True)
        read_ef(0x0529, "EF Be-/Entladevorgänge", 2 + 1624 * 20,
                optional=True)
        read_ef(0x0530, "EF GNSS-Authentisierung", no_gnss * 5 + 2,
                optional=True)
    except CardError as e:
        print("   FEHLER in der Gen-2-Anwendung: %s" % e)
        print("   Die Gen-2-Dateien werden weggelassen "
              "(Download enthält nur Gen-1).")
        return False

    # Blockreihenfolge wie in offiziellen Gen-2-Downloads:
    # EF.ICC/EF.IC zuerst, dann Anwendungs-Identifikation (wurde zum
    # Auslesen der Groessen zuerst gelesen), danach die restlichen Dateien.
    reihenfolge = [0x0002, 0x0005, 0x0501, 0xC101, 0xC108, 0xC109,
                   0x0520, 0x050E, 0x0521, 0x0502, 0x0503, 0x0504,
                   0x0505, 0x0506, 0x0507, 0x0508, 0x0522, 0x0523,
                   0x0524, 0x0525, 0x0526, 0x0527, 0x0528, 0x0529,
                   0x0530]
    g2.sort(key=lambda b: reihenfolge.index(b[0]))

    blocks.extend(g2)
    meta["g2"] = True
    meta["g2_gnss"] = no_gnss
    print("   Gen-2-Anwendung gelesen (%d Dateien inklusive Signaturen)."
          % len(g2))
    return True


def build_ddd(blocks):
    """Blöcke in das .ddd-Dateiformat überführen."""
    out = bytearray()
    for fid, typ, data in blocks:
        out += struct.pack(">HBH", fid, typ, len(data))
        out += data
    return bytes(out)


# --------------------------------------------------------------- Auswertung

def text(field):
    """Feld mit Zeichensatz-Präfixbyte (ISO-8859-x) + Füllzeichen."""
    if not field:
        return ""
    return field[1:].decode("latin-1", "replace").rstrip()


def bcd_date(raw):
    """Geburtsdatum (DATEF, BCD JJJJMMTT) dekodieren."""
    try:
        cc, yy, mm, dd = (int("%02X" % b) for b in raw)
        year = cc * 100 + yy
        if 1900 <= year <= 2100 and 1 <= mm <= 12 and 1 <= dd <= 31:
            return "%02d.%02d.%d" % (dd, mm, year)
    except ValueError:
        pass
    return "unbekannt (%s)" % raw.hex(" ")


def ts(v, with_time=True):
    """Unix-Zeitpunkt (Sekunden seit 1970) formatieren."""
    if not 0 < v < 2 ** 34:
        return "—"
    dt = datetime.fromtimestamp(v)
    return dt.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def parse_identification(data):
    ms = NATIONS.get(data[0], "Staat %02X" % data[0])
    return {
        "staat": ms,
        "kartennummer": data[1:17].decode("ascii", "replace"),
        "behoerde": text(data[17:53]),
        "ausgestellt": int.from_bytes(data[53:57], "big"),
        "gueltig_ab": int.from_bytes(data[57:61], "big"),
        "gueltig_bis": int.from_bytes(data[61:65], "big"),
        "nachname": text(data[65:101]),
        "vorname": text(data[101:137]),
        "geburtstag": bcd_date(data[137:141]),
        "sprache": data[141:143].decode("ascii", "replace"),
    }


def ring_slice(buf, start, length):
    """Teil aus einem Ringpuffer (mit Umbruch am Ende)."""
    out = bytearray()
    for i in range(length):
        out.append(buf[(start + i) % len(buf)])
    return bytes(out)


def parse_activity(data):
    """Tagesaktivitäten aus dem Ringpuffer der EF Fahreraktivitäten."""
    if len(data) < 6:
        return []
    oldest = int.from_bytes(data[0:2], "big")
    newest = int.from_bytes(data[2:4], "big")
    ring = data[4:]
    if not ring or oldest >= len(ring) or newest >= len(ring):
        return []
    days, pos, seen = [], oldest, set()
    while True:
        if pos in seen:
            break
        seen.add(pos)
        rec_len = int.from_bytes(ring_slice(ring, pos + 2, 2), "big")
        if rec_len < 12 or rec_len > len(ring):
            break
        date = int.from_bytes(ring_slice(ring, pos + 4, 4), "big")
        distance = int.from_bytes(ring_slice(ring, pos + 10, 2), "big")
        changes = ring_slice(ring, pos + 12, rec_len - 12)

        totals = [0, 0, 0, 0]
        cur, last = None, 0
        for i in range(0, len(changes) - 1, 2):
            b0 = changes[i]
            minute = ((b0 & 0x07) << 8) | changes[i + 1]
            act = (b0 >> 3) & 0x03
            if cur is not None:
                totals[cur] += max(0, minute - last)
            cur, last = act, minute
        if cur is not None:
            totals[cur] += max(0, 1440 - last)
        days.append({"date": date, "km": distance, "totals": totals})
        if pos == newest:
            break
        pos = (pos + rec_len) % len(ring)
    return days


def parse_vehicles(data, count):
    """Genutzte Fahrzeuge: (erstnutzung, letztnutzung, Kennzeichen, km)."""
    out = []
    for i in range(count):
        rec = data[2 + i * 31: 2 + (i + 1) * 31]
        if len(rec) < 31:
            break
        odo1 = int.from_bytes(rec[0:3], "big")
        odo2 = int.from_bytes(rec[3:6], "big")
        first = int.from_bytes(rec[6:10], "big")
        last = int.from_bytes(rec[10:14], "big")
        nation = NATIONS.get(rec[14], "?")
        plate = text(rec[15:29])
        if first == 0:
            continue
        out.append({"first": first, "last": last, "plate": plate,
                    "nation": nation, "km": odo2 - odo1})
    return out


def count_records(data, record_size):
    """Anzahl belegter Datensätze (erstes Byte ungleich 0) zählen."""
    n = 0
    for i in range(0, len(data) - record_size + 1, record_size):
        if data[i] != 0:
            n += 1
    return n


# ------------------------------------------------------------------- Hauptteil

def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    print("=" * 72)
    print(" Fahrerkarte auslesen — .ddd-Download erzeugen")
    print("=" * 72)

    rs = readers()
    if not rs:
        print("Fehler: Kein Kartenleser gefunden.")
        return 1

    try:
        card = oeffne_karte()
    except CardError as e:
        print("Fehler: %s" % e)
        return 1
    print("Kartenleser: %s" % card.reader)

    try:
        blocks, meta = download(card)
        download_g2(card, blocks, meta)
    except CardError as e:
        print("\nFEHLER: %s" % e)
        return 1
    finally:
        card.close()

    ident = parse_identification(meta["ident_raw"])
    ddd = build_ddd(blocks)

    print("\n5. .ddd-Datei wird geschrieben ...")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    safe_name = (ident["vorname"] + ident["nachname"]).replace(" ", "")
    fname = "C_%s_%s_%s.DDD" % (stamp, safe_name, ident["kartennummer"])
    out_path = out_dir / fname
    out_path.write_bytes(ddd)

    print("   %s  (%d Byte)" % (out_path, len(ddd)))
    print("   Prüfsumme (SHA-256): %s" % hashlib.sha256(ddd).hexdigest())

    # ------------------------------------------------ Zusammenfassung
    print("\n" + "=" * 72)
    print(" KARTENDATEN")
    print("=" * 72)
    print(" Inhaber           : %s %s" % (ident["vorname"], ident["nachname"]))
    print(" Geburtsdatum      : %s" % ident["geburtstag"])
    print(" Karte             : %s" % CARD_TYPES.get(meta["card_type"], "?"))
    print(" Kartennummer      : %s" % ident["kartennummer"])
    print(" Aussteller        : %s (%s)" % (ident["behoerde"], ident["staat"]))
    print(" Ausgestellt am    : %s" % ts(ident["ausgestellt"], False))
    print(" Gültig ab/bis     : %s / %s"
          % (ts(ident["gueltig_ab"], False), ts(ident["gueltig_bis"], False)))
    if meta.get("g2"):
        print(" Gen-2-Anwendung  : gelesen (G2V2), %d GNSS-Positionen, "
              "Tätigkeitsorte mit Ortsangabe" % meta.get("g2_gnss", 0))
    else:
        print(" Gen-2-Anwendung  : nicht vorhanden "
              "(Karte der 1. Generation)")
    if meta.get("events") is not None:
        print(" Ereignisse        : %d gespeichert"
              % count_records(meta["events"], 24))
        print(" Fehler            : %d gespeichert"
              % count_records(meta["faults"], 24))

    days = parse_activity(meta["activity"]) if meta.get("activity") else []
    print("\n" + "=" * 72)
    print(" TÄGLICHE AKTIVITÄT (Zeiten in hh:mm, Karte speichert UTC)")
    print("=" * 72)
    if days:
        print(" %-12s %8s   %-7s %-11s %-7s %-7s"
              % ("Datum", "km", ACTIVITIES[0], ACTIVITIES[1],
                 ACTIVITIES[2], ACTIVITIES[3]))
        for day in days[-14:]:
            print(" %-12s %8d   %02d:%02d   %02d:%02d     %02d:%02d   %02d:%02d"
                  % (ts(day["date"], False), day["km"],
                     *sum(((t // 60, t % 60) for t in day["totals"]), ())))
        print(" (%d Tage insgesamt gespeichert, die letzten %d angezeigt)"
              % (len(days), min(14, len(days))))
    else:
        print(" (keine Aktivitätsdaten auf der Karte)")

    vehicles = parse_vehicles(meta["vehicles"], meta["no_vehicles"]) \
        if meta.get("vehicles") else []
    print("\n" + "=" * 72)
    print(" ZULETZT GENUTZTE FAHRZEUGE")
    print("=" * 72)
    for v in sorted(vehicles, key=lambda x: -x["last"])[:8]:
        print(" %-16s %s – %s   %s km"
              % (v["plate"] or "(ohne Kennzeichen)",
                 ts(v["first"], False), ts(v["last"], False),
                 format(v["km"], ",")))
    if not vehicles:
        print(" (keine Fahrzeuginformationen gespeichert)")

    print("\nDie .ddd-Datei ist vollständig und signiert und kann in")
    print("Auswertungsprogramme (z. B. TachoPlus) importiert werden.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
