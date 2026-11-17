# -*- coding: utf-8 -*-
"""Gemeinsame Logik fuer den Spesenzettel-Generator (CardMaster LS).

Aufgaben:
  * .ddd-Datei auswerten (Fahrer, Karte, Reisen aus EF 0506 / Fahrzeuge 0505;
    bei Karten der 2. Generation mit GNSS-Orten)
  * GNSS-Koordinaten in Ortsnamen uebersetzen (OpenStreetMap/Nominatim,
    Ergebnisse dauerhaft im Datenordner gespeichert)
  * Abrechnungszeitraeume bilden: jeweils 16. eines Monats bis 15. des
    Folgemonats (so wie der Arbeitgeber die Spesenzettel fuehrt)
  * je Fahrerkarte merken, bis zu welchem Tag bereits abgerechnet wurde
    (spesen_state.json) und nur die noch offenen Fahrten ausgeben.
    Jede Karte (jeder Fahrer) hat ihren eigenen Stand.
  * Spesenzettel-PDF erzeugen: Text-Overlay auf dem gescannten
    Originalformular (Spesen.pdf). Nur Datum, Uhrzeiten, Reiseweg
    (Ort -> Ort, Fahrzeug, km) und die exakte Dauer werden eingetragen,
    keine Kostenspalten.
"""
import io
import json
import math
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import spesen_daten

# Laendercodes der Fahrerkarte (NationNumeric, 1 Byte) -> Kfz-Kuerzel.
# Quelle: Tachographen-Spezifikation (Annex 1C, DD 2.101).
NATIONEN = {
    1: "A", 2: "AL", 3: "AND", 4: "ARM", 5: "AZ", 6: "B", 7: "BG",
    8: "BIH", 9: "BY", 10: "CH", 11: "CY", 12: "CZ", 13: "D",
    14: "DK", 15: "E", 16: "EST", 17: "F", 18: "FIN", 19: "FL",
    20: "FO", 21: "UK", 22: "GE", 23: "GR", 24: "H", 25: "HR",
    26: "I", 27: "IRL", 28: "IS", 29: "KZ", 30: "L", 31: "LT",
    32: "LV", 33: "M", 34: "MC", 35: "MD", 36: "MK", 37: "N",
    38: "NL", 39: "P", 40: "PL", 41: "RO", 42: "RSM", 43: "RUS",
    44: "S", 45: "SK", 46: "SLO", 47: "TM", 48: "TR", 49: "UA",
    50: "V", 53: "SRB", 54: "MNE", 56: "KG", 253: "EC", 254: "WLD",
}


def _land_kuerzel(code):
    """NationNumeric (1 Byte) -> 'D', 'NL', ... oder None."""
    return NATIONEN.get(code)


def _lokal_naiv(zeit):
    if zeit.tzinfo is not None:
        return zeit.astimezone(spesen_daten.BERLIN).replace(tzinfo=None)
    return zeit


def laender_fuer_zeitraum(von, bis, grenzen=(), plaetze=()):
    """Laender, die in einem Zeitraum (Zeile) vorkommen – in Reihenfolge.

    Grenzübertritte liefern verlassenes und betretenes Land, die
    Tätigkeitsorte (EF 0506) ihr Land. Doppelte Laender werden entfernt.
    """
    von = _lokal_naiv(von)
    bis = _lokal_naiv(bis)
    if bis < von:
        von, bis = bis, von
    ereignisse = []
    for g in grenzen:
        t = _lokal_naiv(g["zeit"])
        for code in (g.get("von"), g.get("nach")):
            land = _land_kuerzel(code)
            if land:
                ereignisse.append((t, land))
    for p in plaetze:
        land = _land_kuerzel(p.get("land"))
        if land:
            ereignisse.append((_lokal_naiv(p["zeit"]), land))
    if not ereignisse:
        return []
    ereignisse.sort(key=lambda e: e[0])

    # Land zu Beginn der Zeile: letztes bekanntes Ereignis davor.
    davor = [e for e in ereignisse
             if von - timedelta(hours=24) <= e[0] <= von]
    auswahl = [davor[-1][1]] if davor else []
    auswahl.extend(land for t, land in ereignisse if von <= t <= bis)

    laender = []
    for land in auswahl:
        if land not in laender:
            laender.append(land)
    return laender


def dienstfahrt_text(zeile):
    """"Dienstfahrt (D)" bzw. "Dienstfahrt (D,NL)" fuer eine Zeile."""
    laender = zeile.get("laender") or ["D"]
    return "Dienstfahrt (%s)" % ",".join(laender)


# ------------------------------------------------------------------ Ordner
# BASE     : Quellordner der Skripte (nur bei Ausfuehrung ueber Python)
# APP_DIR  : Ordner der Anwendung; bei eingefrorener .exe (PyInstaller) liegt
#            dort das mitgelieferte Blanko-Formular Spesen.pdf
# DATA_DIR : Ordner fuer Ausgabedateien. Als .exe installiert:
#            Dokumente\CardMaster LS  (bleibt bei Deinstallation erhalten)


def _app_dir():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        return Path(base) if base else Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _migriere(quelle, ziel):
    """Dateien aus dem Datenordner der Version 1.0 (Dokumente\\Spesenzettel)
    einmalig in den neuen Ordner uebernehmen. Bestehende Dateien im Ziel
    werden nicht ueberschrieben."""
    try:
        eintraege = list(quelle.iterdir())
    except OSError:
        return
    for p in eintraege:
        if p.is_dir():
            continue
        z = ziel / p.name
        if z.exists():
            continue
        try:
            shutil.copy2(p, z)
        except OSError:
            pass


def _daten_ordner():
    if getattr(sys, "frozen", False):
        docs = Path.home() / "Documents"
        alt = docs / "Spesenzettel"
        ordner = docs / "CardMaster LS"
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            if alt.is_dir():
                _migriere(alt, ordner)
            probe = ordner / ".schreibtest"
            probe.touch()
            probe.unlink()
            return ordner
        except OSError:
            return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE = Path(__file__).resolve().parent
APP_DIR = _app_dir()
DATA_DIR = _daten_ordner()

FORMULAR = APP_DIR / "Spesen.pdf"           # gescanntes Blanko-Formular
STATE_DATEI = DATA_DIR / "spesen_state.json"  # Abrechnungsstand je Karte
ORTSCACHE_DATEI = DATA_DIR / "ortscache.json"  # Ortsnamen je Koordinate
EINSTELLUNGEN_DATEI = DATA_DIR / "einstellungen.json"  # Speicherorte

# ------------------------------------------------------------------ Version
# Programmversion (bei jedem Release anheben) und das öffentliche
# GitHub-Repository, in dem die Releases samt Setup liegen. Die Startseite
# vergleicht diese Version mit dem neuesten Release und weist auf eine
# neuere Fassung hin.
VERSION = "1.4.8"
GITHUB_REPO = "josgot245/cardmaster-ls"
RELEASES_SEITE = "https://github.com/%s/releases" % GITHUB_REPO


# --------------------------------------------------------- Speicherorte
# Standard ist der Datenordner (Dokumente\CardMaster LS). Abweichende
# Ordner fuer .ddd-Downloads und Spesenzettel-PDFs werden in
# einstellungen.json gemerkt. Abrechnungsstand, Ortscache und
# Einstellungen selbst bleiben immer im Datenordner.

def lade_einstellungen():
    """Gespeicherte Einstellungen als dict (leer, wenn keine Datei)."""
    try:
        daten = json.loads(EINSTELLUNGEN_DATEI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


def speichere_einstellungen(werte):
    """Einstellungen in den Datenordner schreiben."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        EINSTELLUNGEN_DATEI.write_text(
            json.dumps(werte, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except OSError as e:
        raise OSError("Einstellungen konnten nicht gespeichert werden: %s" % e)


def _ordner(schluessel, standard):
    """Ordner aus den Einstellungen; bei Fehlern der Standardordner."""
    wert = str(lade_einstellungen().get(schluessel) or "").strip()
    if not wert:
        return standard
    pfad = Path(wert).expanduser()
    try:
        pfad.mkdir(parents=True, exist_ok=True)
        probe = pfad / ".schreibtest"
        probe.touch()
        probe.unlink()
        return pfad
    except OSError:
        return standard


def ddd_ordner():
    """Ordner fuer die .ddd-Downloads der Fahrerkarte."""
    return _ordner("ddd_ordner", DATA_DIR)


def pdf_ordner():
    """Ordner fuer die erzeugten Spesenzettel-PDFs."""
    return _ordner("pdf_ordner", DATA_DIR)


def setze_ordner(schluessel, pfad):
    """Speicherort dauerhaft aendern; leerer Pfad = Standardordner."""
    if schluessel not in ("ddd_ordner", "pdf_ordner"):
        raise ValueError("Unbekannter Speicherort: %s" % schluessel)
    werte = lade_einstellungen()
    if pfad:
        ziel = Path(pfad).expanduser()
        try:
            ziel.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError("Ordner kann nicht angelegt werden: %s" % e)
        werte[schluessel] = str(ziel.resolve())
    else:
        werte.pop(schluessel, None)
    speichere_einstellungen(werte)
    return ddd_ordner() if schluessel == "ddd_ordner" else pdf_ordner()


# --------------------------------------------------------- Update-Prüfung

def _versions_teile(text):
    """Versionsnummer in Zahlen umwandeln: 'v1.4.5' -> (1, 4, 5)."""
    zahlen = re.findall(r"\d+", text or "")
    return tuple(int(z) for z in zahlen[:4]) or (0,)


def update_verfuegbar(neu, alt=VERSION):
    """True, wenn 'neu' eine höhere Version als 'alt' ist."""
    return _versions_teile(neu) > _versions_teile(alt)


def _datum_anzeigen(iso):
    """ISO-Zeitstempel ('2026-11-16T20:51:47Z') als '16.11.2026'."""
    if not iso:
        return ""
    try:
        text = str(iso).replace("Z", "+00:00")
        return datetime.fromisoformat(text).astimezone().strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return ""


def _groesse_anzeigen(bytes_):
    """Byte-Groesse als lesbaren Text: 27914289 -> '26,6 MB'."""
    try:
        wert = float(bytes_)
    except (TypeError, ValueError):
        return ""
    if wert <= 0:
        return ""
    if wert >= 1024 * 1024:
        return ("%.1f MB" % (wert / (1024 * 1024))).replace(".", ",")
    return ("%.0f KB" % (wert / 1024)).replace(".", ",")


def hole_neueste_version(timeout=6.0):
    """Neueste Veröffentlichung des GitHub-Repositories abfragen.

    Rückgabe: dict mit 'version' (z. B. 'v1.4.6'), 'seite' (Webadresse der
    Veröffentlichung), 'datum' (Veröffentlichungsdatum, ISO) und 'dateien'
    (Namen der Anhänge). Zusätzlich 'setup' mit Name, Groesse (Byte) und
    'groesse_text' des Setup-Anhangs, sofern vorhanden. Wirft bei
    Verbindungsfehlern eine Ausnahme.
    """
    url = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO
    anfrage = urllib.request.Request(
        url, headers={"User-Agent": "CardMaster LS %s" % VERSION,
                      "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
        daten = json.loads(antwort.read().decode("utf-8"))
    version = str(daten.get("tag_name") or daten.get("name") or "").strip()
    anhaenge = daten.get("assets") or []
    setup = None
    for a in anhaenge:
        name = a.get("name") or ""
        if name.lower().endswith(".exe"):
            setup = {
                "name": name,
                "groesse": a.get("size") or 0,
                "groesse_text": _groesse_anzeigen(a.get("size")),
            }
            break
    if setup is None and anhaenge:
        a = anhaenge[0]
        setup = {
            "name": a.get("name") or "",
            "groesse": a.get("size") or 0,
            "groesse_text": _groesse_anzeigen(a.get("size")),
        }
    return {
        "version": version,
        "seite": daten.get("html_url") or RELEASES_SEITE,
        "datum": daten.get("published_at") or daten.get("created_at") or "",
        "dateien": [a.get("name", "") for a in anhaenge],
        "setup": setup,
    }


def pruefe_update(timeout=6.0):
    """Update prüfen.

    Rückgabe: (info, fehler). Ist eine neuere Version vorhanden, steht in
    info ein dict (siehe hole_neueste_version); sonst ist info None.
    Schlägt die Abfrage fehl (z. B. keine Internetverbindung), steht in
    fehler ein Text.
    """
    try:
        info = hole_neueste_version(timeout=timeout)
    except Exception as e:
        return None, str(e)
    if info and update_verfuegbar(info["version"]):
        return info, None
    return None, None


def update_pruefen_aktiv():
    """Einstellung: beim Start nach Updates suchen (Standard: ja)."""
    return bool(lade_einstellungen().get("update_pruefen", True))


def setze_update_pruefen(aktiv):
    """Automatische Update-Prüfung ein- oder ausschalten."""
    werte = lade_einstellungen()
    werte["update_pruefen"] = bool(aktiv)
    speichere_einstellungen(werte)


# ----------------------------------------------------------- Formulargeometrie
# Der Scan wurde mit scale=3 analysiert: 3 Pixel = 1 Punkt (PDF 595 x 842).
PX = 3.0
PAGE_W, PAGE_H = 595.0, 842.0

# y-Positionen der 27 Tabellenlinien -> 26 Zeilen pro Blatt
LINES = [251, 317, 383, 449, 514, 581, 647, 713, 779, 845, 911, 978,
         1043, 1110, 1176, 1242, 1308, 1374, 1440, 1506, 1573, 1638,
         1704, 1772, 1836, 1903, 1970]
ZEILEN_PRO_BLATT = len(LINES) - 1

X_DATUM_C = 150.0    # Mitte der Datumsspalte
X_UHR_C = 224.5       # Mitte der Uhrspalte
X_ANLASS = 275.0      # linker Rand "Reiseanlass und Reiseweg"
X_STD_R = 832.0       # rechter Rand der Spalte "Std."
# "Reiseanlass und Reiseweg" reicht bis ca. Pixel 748 (Spaltenlinie im Scan);
# laengere Texte werden automatisch verkleinert statt ueber die Linie zu laufen
MAX_ANLASS_BREITE = 465.0

FONT = "Helvetica"
FONT_GROSS = 8.0
FONT_KLEIN = 7.0


# ------------------------------------------------------------------ Hilfsfunktionen

def _fmt(d):
    return d.strftime("%d.%m.%Y")


def dauer_exakt(start, end):
    """Exakte Dauer 'h:mm' (Sekunden bleiben unberuecksichtigt)."""
    minuten = int((end - start).total_seconds() // 60)
    return "%d:%02d" % (minuten // 60, minuten % 60)


def abrechnungsperiode(tag):
    """Abrechnungszeitraum (16. des Vormonats - 15. des Monats) zu einem Tag."""
    if tag.day >= 16:
        start = date(tag.year, tag.month, 16)
        jahr, monat = (tag.year + 1, 1) if tag.month == 12 else (tag.year, tag.month + 1)
        ende = date(jahr, monat, 15)
    else:
        ende = date(tag.year, tag.month, 15)
        jahr, monat = (tag.year - 1, 12) if tag.month == 1 else (tag.year, tag.month - 1)
        start = date(jahr, monat, 16)
    return start, ende


# ------------------------------------------------------------------ Ortsnamen
# GNSS-Koordinaten der Karte werden ueber OpenStreetMap (Nominatim) in
# Ortsnamen uebersetzt. Jede Koordinate wird nur einmal erfragt und das
# Ergebnis dauerhaft in ortscache.json gespeichert (leere Ergebnisse werden
# ebenfalls gespeichert, Netzwerkfehler nicht). Ohne Internet werden
# ersatzweise die Koordinaten angezeigt.

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"

_ORT_LOCK = threading.Lock()      # schuetzt Cache-Datei vor Parallelzugriff


def _lade_ortscache():
    try:
        daten = json.loads(ORTSCACHE_DATEI.read_text(encoding="utf-8"))
        if isinstance(daten, dict):
            return daten
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _speichere_ortscache(cache):
    try:
        ORTSCACHE_DATEI.write_text(
            json.dumps(cache, indent=1, sort_keys=True, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def _nominatim(lat, lon, timeout=8):
    """Eine Anfrage an Nominatim. Rueckgabe: Ortsname oder None (nicht
    gefunden). Erhaelt Netzwerkfehler als Ausnahme."""
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({
        "format": "jsonv2", "lat": "%.5f" % lat, "lon": "%.5f" % lon,
        "zoom": 10, "accept-language": "de"})
    anfrage = urllib.request.Request(url, headers={
        "User-Agent": "CardMasterLS/1.1 (Spesenzettel aus der Fahrerkarte)"})
    with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
        ergebnis = json.loads(antwort.read().decode("utf-8"))
    if not isinstance(ergebnis, dict):
        return None
    adresse = ergebnis.get("address")
    if not isinstance(adresse, dict):
        adresse = {}
    name = None
    for feld in ("city", "town", "village", "municipality", "county",
                 "state", "name"):
        wert = adresse.get(feld) or ergebnis.get(feld)
        if isinstance(wert, str) and wert.strip():
            name = wert.strip()
            break
    cc = adresse.get("country_code") or ergebnis.get("country_code") or ""
    if name and cc and cc.upper() != "DE":
        name = "%s (%s)" % (name, cc.upper())
    return name


def _nominatim_suche(text, timeout=12):
    """Ort/PLZ über die Nominatim-Suche in Koordinaten übersetzen."""
    url = NOMINATIM_SEARCH + "?" + urllib.parse.urlencode({
        "q": text, "format": "jsonv2", "limit": 1,
        "addressdetails": 1, "zoom": 10, "accept-language": "de"})
    anfrage = urllib.request.Request(url, headers={
        "User-Agent": "CardMasterLS/1.1 (Spesenzettel aus der Fahrerkarte)"})
    with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
        ergebnis = json.loads(antwort.read().decode("utf-8"))
    if not isinstance(ergebnis, list) or not ergebnis:
        return None
    treffer = ergebnis[0]
    if not isinstance(treffer, dict):
        return None
    try:
        return float(treffer["lat"]), float(treffer["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def heimatort_aufloesen(text, log=None):
    """Heimatort/Wohnort (Text oder 'lat, lon') -> (lat, lon).

    Typische Eingaben sind ein Ortsname („Bexhövede“), eine PLZ mit Ort
    („27612 Bexhövede“) oder direkt Koordinaten. Das Ergebnis wird
    dauerhaft in ortscache.json gespeichert (Schlüssel „heim:…“), damit
    die Suche nur einmal nötig ist. Ohne Treffer/ohne Netz: None.
    """
    text = (text or "").strip()
    if not text:
        return None

    m = re.fullmatch(
        r"(-?\d{1,2}[.,]\d+)\s*[,;]\s*(-?\d{1,3}[.,]\d+)", text)
    if m:
        try:
            return (float(m.group(1).replace(",", ".")),
                    float(m.group(2).replace(",", ".")))
        except ValueError:
            pass

    key = "heim:" + text.lower()
    with _ORT_LOCK:
        cache = _lade_ortscache()
        if key in cache:
            wert = cache[key]
            if not wert:
                return None
            try:
                lat, lon = wert.split(",")
                return float(lat), float(lon)
            except (ValueError, TypeError):
                return None
        try:
            treffer = _nominatim_suche(text)
        except Exception as e:
            if log:
                log("Heimatort „%s“ nicht ermittelbar (%s)" % (text, e))
            return None
        if treffer is None:
            cache[key] = ""
            _speichere_ortscache(cache)
            if log:
                log("Heimatort „%s“ wurde nicht gefunden." % text)
            return None
        cache[key] = "%.6f,%.6f" % treffer
        _speichere_ortscache(cache)
    if log:
        log("Heimatort: %s -> %.4f, %.4f" % (text, treffer[0], treffer[1]))
    return treffer


def heimat_anzeigename(text, heim=None, log=None):
    """Kurzen Ortsnamen für das Formular aus der Heimatort-Eingabe.

    „Dorfstraße-Ost 6, 27624 Geestland“ -> „Geestland“.
    „27624 Geestland“ -> „Geestland“. „Bexhövede“ bleibt „Bexhövede“.
    Bei reinen Koordinaten wird der Ort rückwärts gesucht.
    """
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"\b\d{5}\s+([^,;]+)", text)
    if m:
        return m.group(1).strip()
    if re.fullmatch(
            r"-?\d{1,2}[.,]\d+\s*[,;]\s*-?\d{1,3}[.,]\d+", text):
        if heim is not None:
            try:
                name = _nominatim(heim[0], heim[1])
            except Exception as e:
                if log:
                    log("Ortsname für den Heimatort nicht ermittelbar (%s)" % e)
                name = None
            if name:
                return name
        return "%.2f, %.2f" % (heim if heim else (0.0, 0.0))
    if "," in text:
        teile = [t.strip() for t in text.split(",") if t.strip()]
        for teil in reversed(teile):
            if not re.search(r"\d", teil):
                return teil
        return teile[-1]
    return text


def orte_aufloesen(touren, log=None, nur_cache=False):
    """Ortsnamen fuer alle Start-/Ziel-Orte der Fahrten ermitteln.

    Traegt 'start_ort' und 'end_ort' in jede Fahrt ein (Name oder None).
    Bereits bekannte Koordinaten kommen aus dem Cache; fuer fehlende wird
    hoechstens eine Anfrage pro 1,1 s gestellt (Nutzungsbedingungen von
    Nominatim). Netzwerkfehler werden still ignoriert.

    nur_cache=True fuellt nur die bereits bekannten Namen ein und stellt
    keine Netzwerkanfragen (fuer die schnelle Tabellenanzeige).

    Die Funktion ist gegen gleichzeitige Aufrufe (Hintergrundsuche der
    Fenster-Oberflaeche + PDF-Erstellung) gesperrt.
    """
    with _ORT_LOCK:
        cache = _lade_ortscache()
        anfragen = {}      # Koordinate -> (lat, lon), in Reihenfolge
        for t in touren:
            for seite in ("start", "end"):
                lat = t.get(seite + "_lat")
                lon = t.get(seite + "_lon")
                if lat is None:
                    t[seite + "_ort"] = None
                    continue
                key = "%.3f,%.3f" % (lat, lon)
                if key in cache:
                    t[seite + "_ort"] = cache[key] or None
                else:
                    t[seite + "_ort"] = None
                    anfragen.setdefault(key, (lat, lon))
        if not anfragen or nur_cache:
            return
        for nr, (key, (lat, lon)) in enumerate(anfragen.items()):
            if nr:
                time.sleep(1.1)
            name = None
            try:
                name = _nominatim(lat, lon)
            except Exception as e:
                if log:
                    log("Ortsname für %s nicht ermittelbar (%s)" % (key, e))
                continue      # Netzwerkfehler: nicht cachen, spaeter erneut
            if log and name:
                log("Ort ermittelt: %s (%s)" % (name, key))
            cache[key] = name or ""
            for t in touren:
                for seite in ("start", "end"):
                    if t.get(seite + "_lat") is None:
                        continue
                    if "%.3f,%.3f" % (t[seite + "_lat"],
                                      t[seite + "_lon"]) == key:
                        t[seite + "_ort"] = name
        _speichere_ortscache(cache)


def ortstext(tour, seite):
    """Anzeigetext fuer 'start' oder 'end' einer Fahrt: Ortsname,
    sonst die Koordinaten, sonst leer."""
    name = tour.get(seite + "_ort")
    if name:
        return name
    lat = tour.get(seite + "_lat")
    if lat is None:
        return ""
    return "%.2f, %.2f" % (lat, tour.get(seite + "_lon", 0.0))


def _fahrzeug_fuer_tour(tour, fahrzeuge):
    """Kennzeichen ueber die Nutzungszeitraeume der EF 0505 ermitteln.

    Eine Fahrt beginnt mit dem Einstecken der Karte — dieser Zeitpunkt
    liegt im Nutzungszeitraum genau des damals genutzten Fahrzeugs.
    Ergibt das keinen Treffer, werden ersatzweise die Odometer-Bereiche
    verglichen.
    """
    treffer = set()
    for reg, _nation, _odo_a, _odo_e, first, last, _fin in fahrzeuge:
        if reg and (first <= tour["start"] <= last
                    or first <= tour["end"] <= last):
            treffer.add(reg)
    if len(treffer) == 1:
        return treffer.pop()
    if treffer:
        return "/".join(sorted(treffer))

    treffer = set()
    for reg, _nation, odo_a, odo_e, _first, _last, _fin in fahrzeuge:
        if reg and odo_a <= tour["km1"] and odo_e >= tour["km0"]:
            treffer.add(reg)
    if len(treffer) == 1:
        return treffer.pop()
    if not treffer:
        return ""
    return "/".join(sorted(treffer))


def lade_ddd(pfad):
    """.ddd-Download auswerten. Rueckgabe: dict mit Karten- und Fahrtdaten."""
    pfad = Path(pfad)
    daten = pfad.read_bytes()
    kartennummer = vorname = nachname = None
    gueltig_bis = letzter_download = None
    hat_g2 = False

    for ef, typ, chunk in spesen_daten.blocks(daten):
        if ef == 0x0520 and kartennummer is None:
            if typ not in (0, 2):
                continue
            kartennummer = chunk[1:17].decode("ascii", "replace").strip()
            vorname = spesen_daten.as_text(chunk[101:137])
            nachname = spesen_daten.as_text(chunk[65:101])
            try:
                gueltig_bis = datetime.fromtimestamp(
                    int.from_bytes(chunk[61:65], "big"), tz=timezone.utc).date()
            except (ValueError, OSError, OverflowError):
                gueltig_bis = None
        elif ef == 0x050E and letzter_download is None:
            if typ not in (0, 2):
                continue
            try:
                letzter_download = datetime.fromtimestamp(
                    int.from_bytes(chunk, "big"), tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                pass
        if typ == 2:
            hat_g2 = True

    if not kartennummer:
        raise ValueError(
            "In %s wurde keine Fahrerkarten-Identifikation (EF 0520) "
            "gefunden. Ist das ein Fahrerkarten-Download (.ddd)?" % pfad.name)

    fahrzeuge = spesen_daten.read_vehicles(pfad)
    places = spesen_daten.read_places(pfad)
    grenzen = spesen_daten.read_border_crossings(pfad)
    touren = spesen_daten.build_tours(places)
    for t in touren:
        s = t["start"].astimezone(spesen_daten.BERLIN)
        e = t["end"].astimezone(spesen_daten.BERLIN)
        t["tag"] = s.date()
        t["beginn"] = s.strftime("%H:%M")
        t["ende"] = e.strftime("%H:%M")
        t["km"] = t["km1"] - t["km0"]
        t["dauer"] = dauer_exakt(t["start"], t["end"])
        t["fahrzeug"] = _fahrzeug_fuer_tour(t, fahrzeuge)
        t["start_ort"] = t["end_ort"] = None
        t["laender"] = laender_fuer_zeitraum(
            t["start"], t["end"], grenzen, places)

    name = ("%s %s" % (vorname, nachname)).strip()
    return {
        "pfad": pfad,
        "kartennummer": kartennummer,
        "vorname": vorname or "",
        "nachname": nachname or "",
        "name": name,
        "gueltig_bis": gueltig_bis,
        "letzter_download": letzter_download,
        "gen2": hat_g2,
        "touren": touren,
        "grenzen": grenzen,
        "aktivitaet": spesen_daten.read_activity(pfad),
        "ereignisse": spesen_daten.read_events(pfad),
        "stoerungen": spesen_daten.read_faults(pfad),
        "fahrzeuge": sorted({f[0] for f in fahrzeuge if f[0]}),
    }


def neue_fahrten(touren, letzte_zeile_iso):
    """Fahrten nach dem bereits abgerechneten Tag."""
    if not letzte_zeile_iso:
        return list(touren)
    grenze = date.fromisoformat(letzte_zeile_iso)
    return [t for t in touren if t["tag"] > grenze]


def gruppiere_nach_periode(touren):
    """Fahrten chronologisch nach Abrechnungsperiode gruppieren."""
    gruppen = {}
    for t in touren:
        von, bis = abrechnungsperiode(t["tag"])
        gruppen.setdefault((von, bis), []).append(t)
    return sorted(gruppen.items())


# ------------------------------------------------------------------ Fernverkehr

ART_FAHRT = 3          # EF 0504: 0=Ruhe, 1=Bereitschaft, 2=Arbeit, 3=Fahrt


def _km_abstand(lat1, lon1, lat2, lon2):
    """Entfernung zweier Koordinaten in km (Haversine)."""
    p = math.pi / 180.0
    a = (math.sin((lat2 - lat1) * p / 2.0) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p)
         * math.sin((lon2 - lon1) * p / 2.0) ** 2)
    return 2.0 * 6371.0 * math.asin(math.sqrt(a))


def _arbeitsfenster(wechsel, ende_max=None):
    """Anwesenheitsfenster eines Tages aus den EF-0504-Wechseln.

    Rückgabe (beginn, ende) in Minuten (0..1440) oder None.
      beginn = erste Phase, die nicht Ruhe ist
      ende   = Beginn der abschließenden Ruhephase; läuft die Tätigkeit
               über Mitternacht, ist ende = 1440.
    Ein Tag mit nur einem Eintrag ist ein Fortschreibungs-/Füllwert ohne
    echte Aktivität und liefert None.

    ende_max begrenzt das Ende, wenn der letzte Zustand keine
    abschließende Ruhephase hat (typisch: Karte wird während der Arbeit
    gezogen). Dann ist der letzte Wechsel keine gemessene Endzeit; die
    Karte wurde aber zu diesem Zeitpunkt entnommen.
    """
    if not wechsel or len(wechsel) == 1:
        return None

    beginn = None
    for minute, art in wechsel:
        if art != 0:
            beginn = minute
            break
    if beginn is None:
        return None

    j = len(wechsel) - 1
    while j >= 0 and wechsel[j][1] == 0:
        j -= 1
    if j < 0:
        return None
    if j == len(wechsel) - 1:
        ende = 1440
    else:
        ende = wechsel[j + 1][0]
    if ende_max is not None and ende_max > beginn:
        ende = min(ende, ende_max)
    if ende <= beginn:
        return None
    return beginn, ende


def _entnahme_zeiten(plaetze):
    """Zeitpunkt der letzten Kartenentnahme je Kalendertag (Minute).

    Die EF-0506-Records (Typ 1 = entnommen) belegen, wann die Karte aus
    dem Tachographen kam. Der letzte Aktivitätswechsel eines Tages ist
    dagegen nur der letzte Zustandswechsel, keine Endzeit.
    """
    zeiten = {}
    for p in plaetze:
        if p.get("typ") != 1:
            continue
        lokal = p["zeit"].astimezone(spesen_daten.BERLIN)
        minute = lokal.hour * 60 + lokal.minute
        tag = lokal.date()
        zeiten[tag] = max(zeiten.get(tag, 0), minute)
    return zeiten


def _position_nahe(positionen, zeit, max_stunden=8.0):
    """Position, deren Zeitpunkt 'zeit' am nächsten liegt (oder None)."""
    if not positionen:
        return None
    p = min(positionen, key=lambda x: abs((x["zeit"] - zeit).total_seconds()))
    if abs((p["zeit"] - zeit).total_seconds()) > max_stunden * 3600:
        return None
    return p


def _position_standort(positionen, zeit, max_stunden=24.0):
    """Standort zu einem Zeitpunkt: letzte bekannte Position davor.

    Die Positionen werden nur bei Ereignissen (0506) und alle paar
    Stunden (0524) gespeichert. Der zuletzt gemeldete Punkt ist der
    Standort, an dem der Lkw zu 'zeit' steht. Ist er älter als
    max_stunden (z. B. nach einem Wochenende), wird ersatzweise die
    nächstgelegene Position verwendet.
    """
    if not positionen:
        return None
    davor = [p for p in positionen if p["zeit"] <= zeit]
    if davor:
        p = max(davor, key=lambda x: x["zeit"])
        if (zeit - p["zeit"]).total_seconds() <= max_stunden * 3600:
            return p
    return _position_nahe(positionen, zeit)


def _nacht_zuhause(von, bis, positionen, heim, radius_km, basis=None):
    """Stand der Lkw in der Nacht am Heimatort?

    von/bis begrenzen die Nacht (Ende des Vortags, Beginn des Folgetags).
    Bevorzugt werden Steck-/Ziehpositionen (0506), sonst 3h-Positionen
    (0524). Rückgabe: True (zuhause), False (nicht zuhause), None
    (keine Position bekannt).

    basis ist die häufigste Steck-/Ziehposition (Betriebshof). Liegt der
    Lkw dort, gilt die Nacht ebenfalls als zuhause: Der Fahrer steht auf
    seinem Hof, auch wenn die Adresse des Hofs von der geokodierten
    Wohnadresse abweicht.
    """
    if heim is None:
        return None
    if bis < von:
        von, bis = bis, von
    mitte = von + (bis - von) / 2
    nah = [p for p in positionen
           if von - timedelta(hours=3) <= p["zeit"] <= bis + timedelta(hours=3)]
    if nah:
        steck = [p for p in nah if p.get("quelle") == "0506"]
        auswahl = steck or nah
        p = min(auswahl,
                key=lambda x: abs((x["zeit"] - mitte).total_seconds()))
    else:
        p = _position_nahe(positionen, mitte, max_stunden=36.0)
        if p is None:
            return None
    if _km_abstand(heim[0], heim[1], p["lat"], p["lon"]) <= radius_km:
        return True
    if basis is not None:
        return _km_abstand(basis[0], basis[1], p["lat"], p["lon"]) <= radius_km
    return False


def _basis_position(plaetze):
    """Häufigste Steck-/Ziehposition (Betriebshof/Abstellplatz)."""
    zaehler = {}
    for p in plaetze:
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        key = (round(lat, 2), round(lon, 2))
        zaehler[key] = zaehler.get(key, 0) + 1
    if not zaehler:
        return None
    return max(zaehler, key=zaehler.get)


def _wochenend_luecken(zeilen):
    """Bewegungsfreie Samstage/Sonntage als leere Zeilen einfügen.

    So sind die Arbeitswochen im Formular optisch getrennt. Nur Wochenenden
    zwischen zwei Arbeitstagen werden eingefügt (nicht am Rand).
    """
    echt = {z["tag"]: z for z in zeilen if not z.get("leer")}
    if len(echt) < 2:
        return zeilen
    erster, letzter = min(echt), max(echt)
    neu, tag = [], erster
    while tag <= letzter:
        if tag in echt:
            neu.append(echt[tag])
        elif tag.weekday() >= 5 and erster < tag < letzter:
            neu.append({
                "tag": tag, "leer": True, "beginn": "", "ende": "",
                "dauer": "", "km": 0, "fahrzeug": "",
                "start_lat": None, "start_lon": None,
                "end_lat": None, "end_lon": None,
                "start_ort": None, "end_ort": None,
                "heimat_ort": None, "nur_weg": True,
            })
        tag += timedelta(days=1)
    return neu


def leere_raender_entfernen(zeilen):
    """Führende/abschließende Leerzeilen entfernen (z. B. bei Ergänzungen)."""
    start, ende = 0, len(zeilen)
    while start < ende and zeilen[start].get("leer"):
        start += 1
    while ende > start and zeilen[ende - 1].get("leer"):
        ende -= 1
    return zeilen[start:ende]


def _fahrzeug_fuer_tag(tag, touren):
    """Kennzeichen des Fahrzeugs, das an diesem Kalendertag genutzt wurde."""
    treffer = []
    for t in touren:
        s = t["start"].astimezone(spesen_daten.BERLIN).date()
        e = t["end"].astimezone(spesen_daten.BERLIN).date()
        if s <= tag <= e and t.get("fahrzeug"):
            treffer.append(t["fahrzeug"])
    if treffer:
        return max(sorted(set(treffer)), key=treffer.count)
    if not touren:
        return ""
    t = min(touren, key=lambda x: min(
        abs((x["start"].astimezone(spesen_daten.BERLIN).date() - tag).days),
        abs((x["end"].astimezone(spesen_daten.BERLIN).date() - tag).days)))
    return t.get("fahrzeug", "")


def fernverkehr_zeilen(info, heim, radius_km=8.0, log=None,
                       heimat_text=None, nacht_im_lkw=None,
                       nacht_sammeln=None):
    """Tageszeilen für den Fernverkehr erzeugen.

    Eine Zeile je Kalendertag mit Anwesenheit (EF 0504). Folge von
    Anwesenheitstagen = ein Lauf, solange die Lücke kleiner als 24 h ist;
    größere Lücken (Wochenende, freier Tag) beenden den Lauf.

    Übernachtet der Fahrer nicht am Heimatort (Lkw-Nachtposition weiter
    als radius_km vom Wohnort entfernt), wird der Tag um 00:00 geteilt:
    Ende 00:00, Folgetag Beginn 00:00. Übernachtet er zuhause, bleiben die
    echten Zeiten stehen. Beide Fälle können gemischt auftreten.

    radius_km=8 km: Steht der Lkw über Nacht im Umkreis des Wohnorts bzw.
    auf dem Betriebshof (häufigste Steck-/Ziehposition), gilt das als
    „zuhause“. Der genaue Abstellplatz des Lkw wird nicht benötigt.

    heimat_text ist der Anzeigename im Formular (z. B. „Geestland“).
    Die Reiseweg-Zeile lautet damit „Geestland – Oelsnitz – Geestland“.
    Bewegungsfreie Wochenendtage zwischen zwei Arbeitswochen bleiben als
    leere Zeilen stehen.

    nacht_im_lkw: None bedeutet Fernverkehr — steht der Lkw nachts nicht
    am Heimatort, wird der Tag automatisch um 00:00 geteilt. Ist ein dict
    {(vortag, folgetag): True/False} übergeben (Nahverkehr), wird je Nacht
    nach dieser Angabe geteilt oder nicht; fehlt ein Schlüssel, wird die
    Nacht in nacht_sammeln gemeldet (für die Rückfrage) und vorläufig
    geteilt.
    nacht_sammeln: optionale Liste, die offene Nächte aufnimmt.

    Rückgabe: Liste von Tageszeilen wie bei den Fahrten (tag, beginn,
    ende, dauer, km, start_ort/end_ort, start_lat/…, fahrzeug).
    """
    log = log or (lambda text: None)
    tag_daten = spesen_daten.read_activity(info["pfad"])
    if not tag_daten:
        raise ValueError(
            "Diese Karte enthält keine Tagesaktivitäten (EF 0504). "
            "Der Fernverkehr-Modus ist damit nicht möglich.")

    positionen = []
    plaetze = spesen_daten.read_places(info["pfad"])
    basis_pos = _basis_position(plaetze)
    entnahme = _entnahme_zeiten(plaetze)
    for p in plaetze:
        if p.get("lat") is not None:
            positionen.append({
                "zeit": p["zeit"].astimezone(spesen_daten.BERLIN)
                              .replace(tzinfo=None),
                "lat": p["lat"], "lon": p["lon"], "quelle": "0506"})
    for p in spesen_daten.read_gnss(info["pfad"]):
        positionen.append({
            "zeit": p["zeit"].replace(tzinfo=None),
            "lat": p["lat"], "lon": p["lon"], "quelle": "0524"})
    positionen.sort(key=lambda p: p["zeit"])
    grenzen = info.get("grenzen")
    if grenzen is None:
        grenzen = spesen_daten.read_border_crossings(info["pfad"])

    tage = []
    for d in tag_daten:
        fenster = _arbeitsfenster(d["wechsel"], entnahme.get(d["tag"]))
        if not fenster:
            continue
        hat_fahrt = any(art == ART_FAHRT for _minute, art in d["wechsel"])
        if not (hat_fahrt or d["km"] > 0 or len(d["wechsel"]) >= 3):
            continue          # reiner Fülltag ohne echte Anwesenheit
        beginn, ende = fenster
        basis = datetime.combine(d["tag"], dtime(0, 0))
        tage.append({
            "tag": d["tag"],
            "km": d["km"],
            "real_start": basis + timedelta(minutes=beginn),
            "real_ende": basis + timedelta(minutes=ende),
            "start": basis + timedelta(minutes=beginn),
            "ende": basis + timedelta(minutes=ende),
        })

    # Nachtschichten: 00:00-Schnitt, wenn die Nacht nicht zuhause war.
    # Fernverkehr (nacht_im_lkw ist None): automatisch teilen.
    # Nahverkehr (dict): je Nacht nach Rückfrage teilen; offene Nächte
    # werden gesammelt und vorläufig geteilt.
    for i in range(1, len(tage)):
        vor, akt = tage[i - 1], tage[i]
        luecke = (akt["real_start"] - vor["real_ende"]).total_seconds()
        if luecke >= 24 * 3600:
            continue          # Wochenende/freier Tag beendet den Lauf
        zuhause = _nacht_zuhause(vor["real_ende"], akt["real_start"],
                                 positionen, heim, radius_km, basis_pos)
        if zuhause is None:
            log("Nacht %s -> %s: keine Position gefunden, echte Zeiten "
                "werden verwendet." % (_fmt(vor["tag"]), _fmt(akt["tag"])))
            continue
        if zuhause is True:
            continue          # Lkw stand am Heimatort — nichts zu teilen
        # Lkw stand nicht am Heimatort: im Nahverkehr nachfragen.
        teilen = True
        if nacht_im_lkw is not None:
            schluessel = (vor["tag"].isoformat(), akt["tag"].isoformat())
            if schluessel in nacht_im_lkw:
                teilen = bool(nacht_im_lkw[schluessel])
            elif nacht_sammeln is not None:
                nacht_sammeln.append({
                    "vor": vor["tag"], "nach": akt["tag"],
                    "von": vor["real_ende"], "bis": akt["real_start"]})
        if teilen:
            vor["ende"] = datetime.combine(
                vor["tag"] + timedelta(days=1), dtime(0, 0))
            akt["start"] = datetime.combine(akt["tag"], dtime(0, 0))

    touren = info.get("touren", [])
    heim_name = (heimat_text or "").strip()
    zeilen = []
    for d in tage:
        # Reiseweg: ein Ort aus der Schicht (am weitesten vom Standort zu
        # Beginn entfernt) — nicht der Abstellplatz. So steht bei
        # Wochenanfängen nicht immer der Hof/Heimatort im Formular.
        p_start = _position_standort(positionen, d["start"])
        p_weg = _ort_aus_schicht(positionen, d, p_start)
        if p_weg is not None and p_start is not None \
                and _km_abstand(p_start["lat"], p_start["lon"],
                                p_weg["lat"], p_weg["lon"]) < radius_km:
            p_weg = None          # kein echter Zwischenort (nur Hof)
        zeilen.append({
            "tag": d["tag"],
            "beginn": d["start"].strftime("%H:%M"),
            "ende": d["ende"].strftime("%H:%M"),
            "dauer": dauer_exakt(d["start"], d["ende"]),
            "km": d["km"],
            "fahrzeug": _fahrzeug_fuer_tag(d["tag"], touren),
            "laender": laender_fuer_zeitraum(
                d["start"], d["ende"], grenzen, plaetze),
            "start_lat": p_weg["lat"] if p_weg else None,
            "start_lon": p_weg["lon"] if p_weg else None,
            "end_lat": None,
            "end_lon": None,
            "nur_weg": True,
            "heimat_ort": heim_name or None,
            "start_ort": None,
            "end_ort": None,
        })
    return _wochenend_luecken(zeilen)


def naechte_ausser_heimat(info, heim, radius_km=8.0, log=None):
    """Nächte, in denen der Lkw nicht am Heimatort stand.

    Für die Rückfrage im Nahverkehr: Rückgabe ist eine Liste von dicts mit
    'vor'/'nach' (Datum) und 'von'/'bis' (echte Zeiten) je Nacht.
    """
    sammeln = []
    fernverkehr_zeilen(info, heim, radius_km=radius_km, log=log,
                       nacht_im_lkw={}, nacht_sammeln=sammeln)
    return sammeln


def _ort_aus_schicht(positionen, tag, p_start):
    """Einen Ort aus der Schicht wählen (für die Reiseweg-Spalte).

    Genommen wird der Punkt innerhalb der Arbeitszeit, der am weitesten
    vom Standort zu Beginn entfernt liegt. Das ist in der Regel das
    eigentliche Tagesziel und nicht der Abstellplatz. Tage ohne Fahrten
    (km = 0) liefern None, damit kein Hof/keine Wohnadresse erscheint.
    """
    if not positionen or tag["km"] <= 0:
        return None
    im_fenster = [p for p in positionen
                  if tag["real_start"] <= p["zeit"] <= tag["real_ende"]]
    if not im_fenster:
        return None
    basis = p_start or im_fenster[0]

    def abstand(p):
        return _km_abstand(basis["lat"], basis["lon"], p["lat"], p["lon"])

    # Ein einzelner fehlerhafter GNSS-Punkt kann nicht weiter entfernt
    # sein als die an diesem Tag gefahrene Strecke.
    grenze = tag["km"] + 20.0
    kandidaten = [p for p in im_fenster if abstand(p) <= grenze]
    if not kandidaten:
        return None
    return max(kandidaten, key=abstand)


# ------------------------------------------------------------------ Abrechnungsstand

def load_state():
    if STATE_DATEI.exists():
        try:
            st = json.loads(STATE_DATEI.read_text(encoding="utf-8"))
            if isinstance(st, dict) and isinstance(st.get("karten"), dict):
                return st
        except (json.JSONDecodeError, OSError):
            pass
    return {"karten": {}}


def save_state(st):
    STATE_DATEI.write_text(
        json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")


def kartenstand(st, kartennummer):
    return st.setdefault("karten", {}).setdefault(kartennummer, {})


def speichere_heimat(kartennummer, text, heim):
    """Heimatort (Wohnort) je Karte merken (oder entfernen)."""
    st = load_state()
    ks = kartenstand(st, kartennummer)
    if heim is None:
        ks.pop("heimat", None)
    else:
        ks["heimat"] = {"text": (text or "").strip(),
                        "lat": heim[0], "lon": heim[1]}
    save_state(st)


def speichere_kartenwert(kartennummer, schluessel, wert):
    """Beliebigen Wert je Karte merken (None entfernt ihn)."""
    st = load_state()
    ks = kartenstand(st, kartennummer)
    if wert is None:
        ks.pop(schluessel, None)
    else:
        ks[schluessel] = wert
    save_state(st)


# ------------------------------------------------------------------ PDF-Erzeugung

def _text(c, x_px, baseline_px, text, size=FONT_KLEIN, align="left",
          max_px=None):
    """Text zeichnen. Bei max_px wird die Schriftgroesse soweit verkleinert,
    dass der Text in die angegebene Breite (Pixel) passt; reicht das nicht,
    wird der Text gekuerzt."""
    if max_px and text:
        while size > 4.5 and stringWidth(text, FONT, size) * PX > max_px:
            size -= 0.25
        if stringWidth(text, FONT, size) * PX > max_px:
            while text and stringWidth(text + "…", FONT, size) * PX > max_px:
                text = text[:-1]
            text += "…"
    c.setFont(FONT, size)
    x = x_px / PX
    y = PAGE_H - baseline_px / PX
    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def _reise_weg(t, kompakt=False):
    """Zweite Zeile der Tabelle: 'Ort – Ort – Ort, Fzg. X, N km'.

    Bei Tageszeilen (nur_weg) stehen Heimatort, Zwischenort und
    Heimatort; ohne Heimatort bleibt der eine Ort aus der Schicht.
    Der Pfeil wird bewusst nicht verwendet.
    kompakt=True schreibt das Kennzeichen ohne das Wort 'Fzg. ' davor
    (fuer sehr lange Zeilen).
    """
    teile = []
    if t.get("nur_weg"):
        heim = (t.get("heimat_ort") or "").strip()
        zwischen = ortstext(t, "start")
        if heim:
            if zwischen and zwischen != heim:
                teile.append("%s – %s – %s" % (heim, zwischen, heim))
            else:
                teile.append(heim)
        elif zwischen:
            teile.append(zwischen)
    else:
        start = ortstext(t, "start")
        ziel = ortstext(t, "end")
        if start and ziel:
            teile.append("%s – %s" % (start, ziel))
        elif start:
            teile.append("%s – ?" % start)
        elif ziel:
            teile.append("? – %s" % ziel)
    if t.get("fahrzeug"):
        teile.append((t["fahrzeug"] if kompakt
                      else "Fzg. %s" % t["fahrzeug"]))
    teile.append("%d km" % t["km"])
    return ", ".join(teile)


def _weg_zeile(t):
    """Reiseweg-Zeile; sehr lange Zeilen werden kompakter geschrieben,
    damit sie ohne extreme Verkleinerung in die Spalte passen."""
    weg = _reise_weg(t)
    if (t.get("fahrzeug")
            and stringWidth(weg, FONT, 6.0) * PX > MAX_ANLASS_BREITE):
        weg = _reise_weg(t, kompakt=True)
    return weg


def _overlay_seite(c, zeilen, von_s, bis_s, name, abteilung, personal_nr):
    """Eine Formularseite (Kopf + bis zu 26 Tabellenzeilen) befuellen."""
    if personal_nr:
        _text(c, 795, 95, personal_nr, FONT_GROSS)     # Nr.
    _text(c, 995, 96, von_s, FONT_GROSS)               # vom
    _text(c, 1230, 97, bis_s, FONT_GROSS)               # bis
    if name:
        _text(c, 188, 156, name, FONT_GROSS)           # Name
    if abteilung:
        _text(c, 1052, 159, abteilung, FONT_GROSS)     # Abteilung

    for i, t in enumerate(zeilen):
        if t.get("leer"):
            continue              # Wochenendtrennung: Zeile bleibt frei
        top = LINES[i]
        bottom = LINES[i + 1]
        mid = (top + bottom) / 2.0
        hoehe = 1.05 * FONT_KLEIN

        _text(c, X_DATUM_C, mid + hoehe, t["tag"].strftime("%d.%m."),
              align="center")
        _text(c, X_UHR_C, (top + mid) / 2 + hoehe, t["beginn"], align="center")
        _text(c, X_UHR_C, (mid + bottom) / 2 + hoehe, t["ende"], align="center")
        _text(c, X_ANLASS, (top + mid) / 2 + hoehe, dienstfahrt_text(t))
        _text(c, X_ANLASS, (mid + bottom) / 2 + hoehe, _weg_zeile(t),
              max_px=MAX_ANLASS_BREITE)
        _text(c, X_STD_R, mid + hoehe, t["dauer"], align="right")


def _overlay_puffer(zeilen, von, bis, name, abteilung, personal_nr):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    von_s, bis_s = _fmt(von), _fmt(bis)
    for i in range(0, len(zeilen), ZEILEN_PRO_BLATT):
        teil = zeilen[i:i + ZEILEN_PRO_BLATT]
        _overlay_seite(c, teil, von_s, bis_s, name, abteilung, personal_nr)
        c.showPage()
    c.save()
    buf.seek(0)
    return buf


def _schreibe_blatt(pfad, zeilen, von, bis, name, abteilung, personal_nr):
    if not FORMULAR.is_file():
        raise FileNotFoundError(
            "Das Blanko-Formular Spesen.pdf wurde nicht gefunden "
            "(erwartet unter %s). Die Installation ist unvollständig."
            % FORMULAR)
    overlay = PdfReader(_overlay_puffer(zeilen, von, bis, name,
                                        abteilung, personal_nr))
    writer = PdfWriter()
    for i in range(len(overlay.pages)):
        writer.append(str(FORMULAR), pages=(0, 1))
        writer.pages[-1].merge_page(overlay.pages[i])
    with open(pfad, "wb") as f:
        writer.write(f)


def _neuer_pfad(nachname, von, bis):
    sicher = re.sub(r"[^A-Za-z0-9_-]+", "_", (nachname or "Fahrer").strip())
    sicher = sicher.strip("_") or "Fahrer"
    basis = "Reisekostenabrechnung_%s_%s_bis_%s" % (
        sicher, von.isoformat(), bis.isoformat())
    ordner = pdf_ordner()
    pfad = ordner / (basis + ".pdf")
    n = 2
    while pfad.exists():
        pfad = ordner / ("%s_%d.pdf" % (basis, n))
        n += 1
    return pfad


def erstelle_spesenzettel(info, name, abteilung, personal_nr,
                          force=False, log=print, heimat=None, zeitraum=None,
                          nacht_im_lkw=None):
    """Spesenzettel fuer alle noch offenen Einträge dieser Karte erstellen.

    Ist ein Heimatort (Wohnort des Fahrers, z. B. Bexhövede) angegeben,
    werden Tageszeilen erzeugt und Nächte außerhalb des Heimatorts
    automatisch um 00:00 geteilt (Fernverkehr). Ohne Heimatort bleiben die
    Touren unverändert (Nahverkehr).

    zeitraum=(von, bis) beschränkt die Erstellung auf genau diesen
    Abrechnungszeitraum (16. bis 15. des Folgemonats). Dann wird der
    Abrechnungsstand für die Auswahl nicht berücksichtigt — bereits
    abgerechnete Zeiträume entstehen als Ergänzungsblatt (…_2.pdf).

    nacht_im_lkw: Nur im Nahverkehr gesetzt. dict
    {(vortag, folgetag): True/False} — welche Nächte im Lkw verbracht
    wurden. None bedeutet Fernverkehr (automatischer 00:00-Schnitt).

    Rueckgabe: Liste der erzeugten PDF-Dateien (Path).
    Der Abrechnungsstand wird in spesen_state.json aktualisiert.
    """
    st = load_state()
    ks = kartenstand(st, info["kartennummer"])
    letzte = ks.get("letzte_zeile")

    heimat = (heimat or "").strip()
    heim = None
    heim_name = ""
    if heimat:
        heim = heimatort_aufloesen(heimat, log=log)
        if heim is None:
            raise ValueError(
                "Der Heimatort „%s“ wurde nicht gefunden. Bitte den Ort "
                "oder die PLZ genauer angeben." % heimat)
        heim_name = heimat_anzeigename(heimat, heim, log=log)
        ks["heimat"] = {"text": heimat, "name": heim_name,
                        "lat": heim[0], "lon": heim[1]}

    if heim is not None:
        zeilen = fernverkehr_zeilen(info, heim, log=log,
                                    heimat_text=heim_name,
                                    nacht_im_lkw=nacht_im_lkw)
        log("Abrechnungsart: Tageszeilen mit Heimatort %s (%d Tage)"
            % (heim_name or heimat, len(zeilen)))
    else:
        zeilen = list(info["touren"])

    if zeitraum is not None:
        von_z, bis_z = zeitraum
        zeilen = [z for z in zeilen
                  if abrechnungsperiode(z["tag"]) == (von_z, bis_z)]
        zeilen = leere_raender_entfernen(zeilen)
        log("Gewählter Zeitraum: %s – %s (%d Einträge)"
            % (_fmt(von_z), _fmt(bis_z), len(zeilen)))
    elif not force and letzte:
        zeilen = neue_fahrten(zeilen, letzte)
        zeilen = leere_raender_entfernen(zeilen)

    if not zeilen:
        if zeitraum is not None:
            log("Im Zeitraum %s – %s sind keine Einträge vorhanden."
                % (_fmt(zeitraum[0]), _fmt(zeitraum[1])))
        elif letzte:
            log("Keine neuen Einträge seit dem %s – kein Spesenzettel nötig."
                % _fmt(date.fromisoformat(letzte)))
        else:
            log("Auf der Karte sind keine Fahrten gespeichert.")
        return []

    # Ortsnamen ermitteln (Cache im Datenordner, sonst online)
    orte_aufloesen(zeilen, log=log)

    # Kopfdaten dauerhaft je Karte merken
    ks["name"] = name
    ks["personal_nr"] = personal_nr
    ks["abteilung"] = abteilung

    bekannt = {(b.get("von"), b.get("bis")) for b in ks.get("blaetter", [])}
    erstellt = []
    max_tag = date.fromisoformat(letzte) if letzte else None

    for (von, bis), gruppe in gruppiere_nach_periode(zeilen):
        ergaenzung = (von.isoformat(), bis.isoformat()) in bekannt
        pfad = _neuer_pfad(info["nachname"], von, bis)
        _schreibe_blatt(pfad, gruppe, von, bis, name, abteilung, personal_nr)
        ks.setdefault("blaetter", []).append({
            "datei": pfad.name,
            "von": von.isoformat(),
            "bis": bis.isoformat(),
            "zeilen": len(gruppe),
            "ergaenzung": ergaenzung,
            "erstellt": datetime.now().isoformat(timespec="seconds"),
        })
        log("Spesenzettel erstellt: %s" % pfad.name)
        log("   Zeitraum %s – %s, %d Einträge%s"
            % (_fmt(von), _fmt(bis), len(gruppe),
               ", Ergänzung zu bereits erstelltem Blatt" if ergaenzung else ""))
        erstellt.append(pfad)
        echte = [z for z in gruppe if not z.get("leer")]
        letzter_tag = (echte or gruppe)[-1]["tag"]
        if max_tag is None or letzter_tag > max_tag:
            max_tag = letzter_tag

    ks["letzte_zeile"] = max_tag.isoformat()
    save_state(st)
    log("Abrechnungsstand gespeichert: abgerechnet bis %s" % _fmt(max_tag))
    return erstellt
