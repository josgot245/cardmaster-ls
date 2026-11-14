# CardMaster LS

CardMaster LS liest die digitale **Fahrerkarte** (Tachographenkarte) über einen
USB-Kartenleser aus, erzeugt daraus einen `.ddd`-Download (z. B. für TachoPlus)
und befüllt automatisch den **Spesenzettel „Reisekostenabrechnung"** auf dem
gescannten Originalformular. Zusätzlich werden die Kartendaten des gewählten
Tages mit Tagesgrafik, Kreisdiagramm sowie **Verstößen und Ereignissen** nach
VO (EG) 561/2006, FPersV und ArbZG angezeigt.

Die Oberfläche erscheint in den Firmenfarben (Navy `#242E45`, Rot `#9C1006`,
Grün `#94C11C`) auf hellen Flächen.

> Aktuelle Version: **1.4.4**

## Funktionen

- **Karte auslesen** über PC/SC-Kartenleser, inkl. Gen-2-Karten mit GNSS-Positionen
- **`.ddd`-Download** erzeugen und alternativ vorhandene `.ddd`-Dateien öffnen
- **Spesenzettel (PDF)** automatisch auf das gescannte Formular drucken
  (Datum, Zeiten, Reiseweg, Fahrzeug, km, exakte Dauer — ohne Rundung)
- **Tageszeilen je Kalendertag** bei gesetztem Heimatort; Nächte außerhalb des
  Wohnorts (ca. 8 km) werden um 00:00 geteilt
- **Ortsnamen** automatisch über OpenStreetMap (Nominatim), dauerhaft gecacht
  (`ortscache.json`)
- **Abrechnungsstand je Fahrerkarte** (`spesen_state.json`), Ergänzungsblätter
  als `…_2.pdf`
- **Kartendaten ansehen**: 24-Stunden-Zeitstrahl, Kreisdiagramm, Verstöße/Events
- **Rechtsgrundlagen**: Kennzahlen und Vorschriften (Lenk-, Ruhe-, Arbeitszeit)
- **Installer** (Inno Setup) mit wählbarem Installationsordner sowie
  Desktop- und Startmenü-Verknüpfung

## Installation

Fertiges Setup starten:

```
installer\Ausgabe\CardMaster-Setup-1.4.4.exe
```

Keine Administratorrechte nötig. Die Installation enthält alles Erforderliche
(inkl. Python). Nur der USB-Kartenleser mit Fahrerkarte wird zum Auslesen
benötigt.

Standardmäßig liegen Abrechnungsstand, Ortscache und Einstellungen im Ordner
`Dokumente\CardMaster LS`. `.ddd`-Downloads und fertige PDFs können dort bleiben
oder im Programm unter **Speicherorte** getrennt geändert werden. Der
Datenordner bleibt bei einer Deinstallation erhalten.

Die ausführliche **Anleitung** steht in
[`ANLEITUNG CardMaster LS.txt`](ANLEITUNG%20CardMaster%20LS.txt).

## Bedienung (Kurz)

1. Fahrerkarte einstecken und **„Karte auslesen (USB-Kartenleser)"** klicken —
   `.ddd`-Download wird erzeugt und ausgewertet.
2. Kopfdaten prüfen; optional **Heimatort** eintragen und **„Prüfen"** wählen
   (wird je Fahrerkarte gespeichert).
3. **„Spesenzettel erstellen (PDF)"** befüllt das Formular `Spesen.pdf`.
   Pro Abrechnungszeitraum (16. bis 15. des Folgemonats) entsteht ein Blatt.
4. Über **„Kartendaten ansehen"** die Tagesauswertung unabhängig vom
   Spesenzettel öffnen.

## Starten ohne Installation (Entwicklung)

```
py spesenzettel_gui.py
```

oder `CardMaster LS starten.bat`. Kommandozeile:
`py spesenzettel.py [datei.ddd] [--alle]`.

## Selbst bauen

1. `installer_bauen.bat` starten (erzeugt `CardMaster LS.exe` via PyInstaller,
   inkl. Icon und Setup-Grafiken aus `assets`).
2. Setup kompilieren:

   ```
   "C:\Users\joshu\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\cardmaster.iss
   ```

## Projektstruktur

| Datei | Zweck |
| --- | --- |
| `spesenzettel_gui.py` | Fenster-Oberfläche (Programmeinstieg) |
| `kartendaten_gui.py` | „Kartendaten ansehen" und „Rechtsgrundlagen" |
| `kartendaten.py` | Tagesauswertung, Verstoßprüfungen, Kennzahlen |
| `spesen_lib.py` | gemeinsame Logik (Auswertung, Zeiträume, Orte, PDF) |
| `spesen_daten.py` | Rohdaten aus der `.ddd` (EF 0506/0505, Gen-2/GNSS) |
| `fahrerkarte.py` | Karten-Download über USB (eigenständig nutzbar) |
| `stil.py` | zentrale Farben, Schriftfamilien, Größen, ttk-Stile |
| `assets.py`, `assets/` | Grafiken (Firmen-/Produktlogo, Symbole) |
| `Spesen.pdf` | gescanntes Blanko-Formular (Vorlage) |
| `spesenzettel.py` | Kommandozeilen-Einstieg |
| `installer/` | Inno-Setup-Skript, Icon-/Grafik-Generatoren, Version |
| `installer_bauen.bat` | eigenständige `CardMaster LS.exe` bauen |
| `sampledata/` | Beispiel-`.ddd`-Dateien zum Testen |

## Hinweis

Die Verstoßprüfungen sind eine **Kontrollhilfe** und ersetzen keine rechtliche
Bewertung. Keine Steuerberatung — Verpflegungspauschalen und Beträge bitte
selbst prüfen bzw. mit dem Arbeitgeber abstimmen.

## Entwicklungshinweise

- Python 3.14, PyInstaller, Inno Setup 6 (per winget).
- Persönliche Fahrerkarten-Daten (`.DDD`), Caches (`ortscache.json`,
  `spesen_state.json`) und Build-Artefakte sind per `.gitignore`
  ausgeschlossen.
