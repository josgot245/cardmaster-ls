# -*- coding: utf-8 -*-
"""CardMaster LS — Spesenzettel-Generator, Fenster-Oberflaeche.

Start:   py spesenzettel_gui.py     (oder „CardMaster LS starten.bat“)

Ablauf:
  1. Startseite: Datenquelle waehlen
       • „Karte auslesen (USB)“ – Fahrerkarte ueber den Kartenleser einlesen
         (inkl. Gen-2-Anwendung mit GNSS-Orten), .ddd-Download erzeugen und
         auswerten
       • „.ddd-Datei oeffnen …“ – bereits vorhandenen Karten-Download auswerten
     Dort stehen auch die Kopfdaten und der Heimatort.
  2. Kartendaten ansehen: Tage, Verstöße, Ereignisse und Rechtsgrundlagen.
  3. Es werden alle Fahrten angezeigt, die noch auf keinem Spesenzettel
     standen — fuer jede abzurechnende Periode (16. bis 15. des Folgemonats)
     wird ein Blatt erstellt. GNSS-Orte werden im Hintergrund in Ortsnamen
     uebersetzt (einmalig online, danach dauerhaft gespeichert).
  4. „Spesenzettel erstellen (PDF)“ – befuellt das gescannte Originalformular.

Der Abrechnungsstand wird je Fahrerkarte in spesen_state.json gespeichert:
Wird die Karte eines anderen Fahrers gelesen, gilt deren eigener Stand
(bei einer neuen Karte werden alle gespeicherten Fahrten angeboten).
"""
import contextlib
import io
import os
import sys
import threading
import traceback
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import assets
import kartendaten
import spesen_lib
import kartendaten_gui
import stil

try:
    import fahrerkarte          # benoetigt pyscard
except (ImportError, SystemExit):
    fahrerkarte = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CardMaster LS – Fahrerkarte")
        ax, ay, aw, ah = stil.arbeitsflaeche(self)
        self.minsize(min(1080, max(640, aw - 40)),
                     min(720, max(460, ah - 40)))
        stil.anwenden(self)
        stil.skalierung_setzen(self)
        self._fenster_icon()
        self._update_thread = None            # Hintergrund-Update-Prüfung
        self._update_url = spesen_lib.RELEASES_SEITE
        self.ddd_ordner_var = tk.StringVar()  # Speicherorte (Einstellungen)
        self.pdf_ordner_var = tk.StringVar()
        self.leser_var = tk.StringVar()        # Kartenleser-Auswahl
        self.leser_hinweis_var = tk.StringVar()
        self._oberflaeche()
        stil.hand_cursor(self)
        self.info = None                      # Ergebnis von spesen_lib.lade_ddd
        self.kartenstaende = spesen_lib.load_state()["karten"]
        self._orte_thread = None              # Hintergrund-Suche Ortsnamen
        self._heim = None                     # Heimatort/Wohnort (lat, lon)
        self._heim_text = ""                  # zuletzt geprüfter Heimatort-Text
        self._fern_cache = None               # zuletzt erzeugte Tageszeilen
        self._nacht_im_lkw = None             # Nahverkehr: Nächte im Lkw
        self._fenster_platzieren()
        self.protocol("WM_DELETE_WINDOW", self._beenden)
        # Beim Start einmalig nach einer neueren Version suchen.
        if spesen_lib.update_pruefen_aktiv():
            self.after(800, self.update_suchen)

    def _fenster_platzieren(self):
        """Letzte Fenstergröße/-position wiederherstellen, sonst mittig.

        Gespeicherte Geometrien werden an die aktuelle Arbeitsfläche
        angepasst (z. B. nach Wechsel auf einen kleineren Bildschirm).
        """
        gespeichert = (spesen_lib.lade_einstellungen().get("fenster")
                       or {}).get("geometry")
        if gespeichert:
            angepasst = stil.geometry_einpassen(gespeichert, self)
            if angepasst:
                try:
                    self.geometry(angepasst)
                    return
                except tk.TclError:
                    pass
        ax, ay, aw, ah = stil.arbeitsflaeche(self)
        breite = max(min(640, aw - 20), min(1180, aw - 40))
        hoehe = max(min(460, ah - 20), min(800, ah - 40))
        self.update_idletasks()
        self.geometry("%dx%d+%d+%d"
                      % (breite, hoehe,
                         ax + (aw - breite) // 2,
                         ay + (ah - hoehe) // 3))

    def _beenden(self):
        """Fenstergröße/-position merken und schließen."""
        try:
            werte = spesen_lib.lade_einstellungen()
            werte["fenster"] = {"geometry": self.winfo_geometry()}
            spesen_lib.speichere_einstellungen(werte)
        except OSError:
            pass
        self.destroy()

    def _fenster_icon(self):
        """Fenster- und Taskleistensymbol (cardmaster.ico)."""
        assets.setze_fenster_icon(self)

    def _kopfleiste(self):
        """Dunkle Kopfleiste mit sanftem Verlauf, Logo und Programmnamen."""
        firmen = assets.lade("kopf_firmenlogo")
        produkt = assets.lade("kopf_produktlogo")

        kopf = tk.Canvas(self, height=68, highlightthickness=0, bd=0,
                         background=stil.NAVY)
        kopf.grid(row=0, column=0, sticky="ew")
        self.kopf_canvas = kopf

        # Weiße Logo-Platte links
        self._kopf_platte = None
        if firmen is not None or produkt is not None:
            platte = tk.Frame(kopf, background=stil.WEISS, padx=12, pady=7)
            if firmen is not None:
                tk.Label(platte, image=firmen, background=stil.WEISS,
                         borderwidth=0).pack(side="left")
            if firmen is not None and produkt is not None:
                tk.Frame(platte, background=stil.RAND, width=1).pack(
                    side="left", fill="y", padx=12, pady=3)
            if produkt is not None:
                tk.Label(platte, image=produkt, background=stil.WEISS,
                         borderwidth=0).pack(side="left")
            self._kopf_platte = kopf.create_window(16, 34, window=platte,
                                                   anchor="w")

        # Rechts: Produktname, Untertitel und Versions-Kennzeichen
        rechts = tk.Frame(kopf, background=stil.NAVY)
        tk.Label(rechts, text="CardMaster LS", background=stil.NAVY,
                 foreground=stil.WEISS,
                 font=stil.schrift(stil.PT_GROSS, True)).pack(anchor="e")
        zeile = tk.Frame(rechts, background=stil.NAVY)
        zeile.pack(anchor="e")
        tk.Label(zeile, text="Fahrerkarte · Spesen · Rechtsgrundlagen",
                 background=stil.NAVY, foreground="#B9C2D6",
                 font=stil.schrift(stil.PT_KLEIN)).pack(side="left")
        tk.Label(zeile, text=" v%s " % spesen_lib.VERSION,
                 background=stil.NAVY_HELL, foreground=stil.WEISS,
                 font=stil.schrift(stil.PT_MINI, True)).pack(
            side="left", padx=(8, 0))
        self._kopf_rechts = kopf.create_window(0, 34, window=rechts, anchor="e")

        kopf.bind("<Configure>", self._kopf_zeichnen)
        tk.Frame(self, background=stil.GRUEN, height=3).grid(
            row=1, column=0, sticky="ew")
        return True

    def _kopf_zeichnen(self, ereignis=None):
        """Farbverlauf der Kopfleiste zeichnen und Elemente ausrichten."""
        kopf = self.kopf_canvas
        breite = ereignis.width if ereignis else kopf.winfo_width()
        hoehe = ereignis.height if ereignis else kopf.winfo_height()
        if breite <= 1 or hoehe <= 1:
            return
        # Nur neu zeichnen, wenn sich die Breite wirklich geändert hat.
        if getattr(self, "_kopf_breite", None) != breite:
            stil.verlauf(kopf, breite, hoehe, stil.NAVY, stil.NAVY_HELL)
            self._kopf_breite = breite
        if self._kopf_rechts is not None:
            kopf.coords(self._kopf_rechts, breite - 18, hoehe / 2)
        if self._kopf_platte is not None:
            kopf.coords(self._kopf_platte, 16, hoehe / 2)

    def _oberflaeche(self):
        zeile = 0
        if self._kopfleiste():
            zeile = 2

        notiz = ttk.Notebook(self)
        notiz.grid(row=zeile, column=0, sticky="nsew",
                   padx=16, pady=(14, 16))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(zeile, weight=1)
        self.notiz = notiz

        # Erste Ansicht: Startseite mit Datenquelle und Kopfdaten
        self.tab_start = ttk.Frame(notiz)
        bild_start = assets.lade("tab_start")
        extra = {"image": bild_start, "compound": "left"} \
            if bild_start is not None else {}
        notiz.add(self.tab_start, text=" Start", **extra)
        self._startseite(self.tab_start)

        # Kartendaten mit Tagesgrafik und Kreisdiagramm
        self.tab_karten = kartendaten_gui.KartendatenTab(notiz)
        bild_karten = assets.lade("tab_kartendaten")
        extra = {"image": bild_karten, "compound": "left"} \
            if bild_karten is not None else {}
        notiz.add(self.tab_karten, text=" Kartendaten ansehen", **extra)

        # Rechtsgrundlagen und Kennzahlen
        self.tab_recht = kartendaten_gui.RechtsgrundlagenTab(notiz)
        bild_recht = assets.lade("tab_recht")
        extra = {"image": bild_recht, "compound": "left"} \
            if bild_recht is not None else {}
        notiz.add(self.tab_recht, text=" Rechtsgrundlagen", **extra)

        # Spesenzettel (Reisekostenabrechnung)
        self.tab_spesen = ttk.Frame(notiz)
        bild_spesen = assets.lade("tab_spesen")
        extra = {"image": bild_spesen, "compound": "left"} \
            if bild_spesen is not None else {}
        notiz.add(self.tab_spesen, text=" Spesenzettel", **extra)
        self._spesenseite(self.tab_spesen)

        # Einstellungen (Updates und Speicherorte)
        self.tab_einst = ttk.Frame(notiz)
        bild_einst = assets.lade("tab_einstellungen")
        extra = {"image": bild_einst, "compound": "left"} \
            if bild_einst is not None else {}
        notiz.add(self.tab_einst, text=" Einstellungen", **extra)
        self._einstellungen_seite(self.tab_einst)

        self.log("Bereit. Karte einstecken und „Karte auslesen“ wählen, "
                 "oder eine vorhandene .ddd-Datei öffnen.")

    def _startseite(self, rahmen):
        rahmen.columnconfigure(0, weight=1)
        rahmen.rowconfigure(2, weight=1)

        ttk.Label(rahmen, text="Fahrerkarte und Spesenzettel",
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_HERO, True)).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 2))
        ttk.Label(rahmen, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_TEXT),
                  text="Karte auslesen oder einen vorhandenen Karten-Download "
                       "öffnen. Daraus entstehen Kartendaten, Verstöße und "
                       "die Reisekostenabrechnung.").grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        # --- Zwei Spalten: links Eingaben, rechts Übersicht/Protokoll ----
        spalten = ttk.Frame(rahmen)
        spalten.grid(row=2, column=0, sticky="nsew", padx=16)
        spalten.columnconfigure(0, weight=3)
        spalten.columnconfigure(1, weight=2)
        spalten.rowconfigure(0, weight=1)

        links = ttk.Frame(spalten)
        links.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        links.columnconfigure(0, weight=1)

        # --- Datenquelle -------------------------------------------------
        quelle_karte = stil.Karte(links, titel="Datenquelle", padding=(16, 12))
        quelle_karte.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        quelle = quelle_karte.innen
        quelle.columnconfigure(3, weight=1)
        self.btn_karte = ttk.Button(
            quelle, text="Karte auslesen (USB-Kartenleser)",
            image=assets.lade("btn_karte"), compound="left",
            style="Primaer.TButton", command=self.karte_auslesen)
        self.btn_karte.grid(row=0, column=0)
        self.btn_ddd = ttk.Button(
            quelle, text=".ddd-Datei öffnen …",
            image=assets.lade("btn_oeffnen"), compound="left",
            command=self.ddd_oeffnen)
        self.btn_ddd.grid(row=0, column=1, padx=8)
        if fahrerkarte is None:
            self.btn_karte.state(["disabled"])
            ttk.Label(quelle, text="pyscard fehlt – Kartenlesen nicht möglich",
                      foreground=stil.ROT).grid(row=0, column=2, padx=8)

        # Fortschritt (nur während Auslesen/Erstellen sichtbar)
        self.fortschritt = ttk.Progressbar(quelle, mode="indeterminate",
                                           length=220)
        self.fortschritt.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.fortschritt.grid_remove()
        self.fortschritt_var = tk.StringVar(value="")
        self.fortschritt_label = ttk.Label(
            quelle, textvariable=self.fortschritt_var,
            foreground=stil.GEDAEMPFT, font=stil.schrift(stil.PT_KLEIN))
        self.fortschritt_label.grid(row=1, column=1, columnspan=3, sticky="w",
                                    padx=(10, 0), pady=(10, 0))
        self.fortschritt_label.grid_remove()

        self.info_var = tk.StringVar(
            value="Noch keine Daten geladen — Karte auslesen oder .ddd öffnen.")
        ttk.Label(links, textvariable=self.info_var, justify="left",
                  wraplength=640, foreground=stil.TEXT).grid(
            row=1, column=0, sticky="w", pady=(0, 8))

        # --- Kopfdaten ----------------------------------------------------
        kopf_karte = stil.Karte(links, titel="Kopfdaten für das Formular",
                                padding=(16, 12))
        kopf_karte.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        kopf = kopf_karte.innen
        kopf.columnconfigure(1, weight=1)
        ttk.Label(kopf, text="Name:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(kopf, textvariable=self.name_var).grid(
            row=0, column=1, sticky="ew", padx=(4, 16))
        ttk.Label(kopf, text="Abteilung:").grid(row=0, column=2, sticky="w")
        self.abt_var = tk.StringVar()
        ttk.Entry(kopf, textvariable=self.abt_var, width=8).grid(
            row=0, column=3, sticky="w", padx=(4, 16))
        ttk.Label(kopf, text="Pers.-Nr.:").grid(row=0, column=4, sticky="w")
        self.pnr_var = tk.StringVar()
        ttk.Entry(kopf, textvariable=self.pnr_var, width=10).grid(
            row=0, column=5, sticky="w", padx=4)

        # Heimatort: mit Heimatort entsteht je Tag eine Zeile
        # „Heimatort – Zwischenort – Heimatort“. Ob Nah- oder Fernverkehr
        # gilt, wird auf der Seite „Spesenzettel“ gewählt.
        ttk.Label(kopf, text="Heimatort (PLZ oder Ort):").grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.heimat_var = tk.StringVar()
        ttk.Entry(kopf, textvariable=self.heimat_var, width=30).grid(
            row=1, column=1, sticky="w", padx=(4, 8), pady=(6, 0))
        self.btn_heim = ttk.Button(kopf, text="Prüfen",
                                   command=self.heimat_pruefen)
        self.btn_heim.grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.heim_var = tk.StringVar(value="")
        ttk.Label(kopf, textvariable=self.heim_var, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN)).grid(
            row=1, column=3, columnspan=3, sticky="w", padx=(12, 0),
            pady=(6, 0))
        ttk.Label(kopf, foreground=stil.GEDAEMPFT, font=stil.schrift(stil.PT_KLEIN),
                  wraplength=620,
                  text="Mit Heimatort entsteht für jeden Tag eine Zeile "
                       "„Heimatort – Zwischenort – Heimatort“. Ob Nah- oder "
                       "Fernverkehr gilt, wird auf der Seite „Spesenzettel“ "
                       "gewählt; im Nahverkehr wird bei Nächten außerhalb "
                       "des Heimatorts nachgefragt.").grid(
            row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))

        links.rowconfigure(3, weight=1)

        # --- rechte Spalte: Übersicht, Wechsel, Protokoll ----------------
        rechts = ttk.Frame(spalten)
        rechts.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        rechts.columnconfigure(0, weight=1)
        rechts.rowconfigure(2, weight=1)

        uebersicht_karte = stil.Karte(rechts, titel="Übersicht",
                                      padding=(16, 12))
        uebersicht_karte.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        uebersicht = uebersicht_karte.innen
        uebersicht.columnconfigure(0, weight=1)

        # Leerer Zustand: Symbol, Hinweis und Hauptknopf
        self.leer_rahmen = ttk.Frame(uebersicht)
        self.leer_rahmen.grid(row=0, column=0, sticky="w")
        bild_karte = (assets.lade("icon_fahrerkarte_transparent")
                      or assets.lade("icon_fahrerkarte"))
        if bild_karte is not None:
            ttk.Label(self.leer_rahmen, image=bild_karte).pack(
                side="left", padx=(0, 14))
        leer_rechts = ttk.Frame(self.leer_rahmen)
        leer_rechts.pack(side="left")
        ttk.Label(leer_rechts, text="Noch keine Karte geladen",
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_UNTERTITEL, True)).pack(anchor="w")
        ttk.Label(leer_rechts, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_TEXT), wraplength=300,
                  text="Karte einstecken und „Karte auslesen“ wählen — oder "
                       "einen vorhandenen .ddd-Download öffnen."
                  ).pack(anchor="w", pady=(2, 8))
        ttk.Button(leer_rechts, text="Karte auslesen",
                   image=assets.lade("btn_karte"), compound="left",
                   style="Primaer.TButton",
                   command=self.karte_auslesen).pack(anchor="w")

        # Kennzahl-Kacheln (nach dem Laden), 2 × 2
        self.kachel_rahmen = ttk.Frame(uebersicht)
        self.kachel_rahmen.grid(row=0, column=0, sticky="ew")
        self.kacheln = {}
        for spalte in range(2):
            self.kachel_rahmen.columnconfigure(spalte, weight=1)
        for index, (schluessel, beschriftung) in enumerate((
                ("fahrer", "Fahrer"), ("tage", "Tage"),
                ("verstoesse", "Verstöße"), ("offen", "Offene Fahrten"))):
            self._kachel_bauen(self.kachel_rahmen, index // 2, index % 2,
                               schluessel, beschriftung)
        self.kachel_rahmen.grid_remove()

        self.uebersicht_var = tk.StringVar(value="")
        ttk.Label(uebersicht, textvariable=self.uebersicht_var,
                  justify="left", wraplength=400, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN)).grid(
            row=1, column=0, sticky="w", pady=(8, 0))

        wechsel_karte = stil.Karte(rechts, titel="Ansicht wechseln",
                                   padding=(16, 12))
        wechsel_karte.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        wechsel = wechsel_karte.innen
        ttk.Button(wechsel, text="Kartendaten ansehen",
                   image=assets.lade("tab_kartendaten"), compound="left",
                   command=lambda: self.notiz.select(self.tab_karten)).grid(
            row=0, column=0)
        ttk.Button(wechsel, text="Rechtsgrundlagen",
                   image=assets.lade("tab_recht"), compound="left",
                   command=lambda: self.notiz.select(self.tab_recht)).grid(
            row=0, column=1, padx=8)
        ttk.Button(wechsel, text="Spesenzettel",
                   image=assets.lade("tab_spesen"), compound="left",
                   command=lambda: self.notiz.select(self.tab_spesen)).grid(
            row=0, column=2)

        # --- Protokoll ----------------------------------------------------
        proto_karte = stil.Karte(rechts, titel="Protokoll", padding=(10, 8))
        proto_karte.grid(row=2, column=0, sticky="nsew")
        proto = proto_karte.innen
        proto.columnconfigure(0, weight=1)
        proto.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            proto, height=5, state="disabled", wrap="word",
            font=stil.schrift_fest(stil.PT_TEXT), background=stil.PANEL,
            foreground=stil.TEXT, relief="flat", borderwidth=0,
            padx=10, pady=8, insertbackground=stil.NAVY,
            selectbackground=stil.AUSWAHL, selectforeground=stil.ROT_DUNKEL)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_balken = ttk.Scrollbar(proto, orient="vertical",
                                   command=self.log_text.yview)
        log_balken.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_balken.set)
        self.log_text.tag_configure("zeit", foreground=stil.GRAU)
        self.log_text.tag_configure("info", foreground=stil.TEXT)
        self.log_text.tag_configure("warn", foreground="#8A5A00")
        self.log_text.tag_configure("fehler", foreground=stil.ROT)
        self.log_text.tag_configure("ok", foreground="#2E6B2E")

    def _kachel_bauen(self, parent, zeile, spalte, schluessel, beschriftung):
        """Eine Kennzahl-Kachel (kleine Beschriftung, großer Wert)."""
        rahmen = tk.Frame(parent, background=stil.WEISS,
                          highlightbackground=stil.RAND, highlightthickness=1,
                          padx=12, pady=8)
        rahmen.grid(row=zeile, column=spalte, sticky="nsew",
                    padx=(0, 8), pady=(0, 8))
        tk.Label(rahmen, text=beschriftung.upper(), background=stil.WEISS,
                 foreground=stil.GEDAEMPFT,
                 font=stil.schrift(stil.PT_MINI, True)).pack(anchor="w")
        wert = tk.Label(rahmen, text="—", background=stil.WEISS,
                        foreground=stil.NAVY, anchor="w",
                        font=stil.schrift(stil.PT_GROSS, True))
        wert.pack(anchor="w")
        self.kacheln[schluessel] = wert

    # ------------------------------------------------------- Einstellungen

    def _einstellungen_seite(self, rahmen):
        """Eigener Reiter: Update-Prüfung, Kartenleser und Speicherorte."""
        rahmen.columnconfigure(0, weight=1)
        rahmen.rowconfigure(5, weight=1)

        ttk.Label(rahmen, text="Einstellungen",
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_HERO, True)).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 2))
        ttk.Label(rahmen, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_TEXT),
                  text="Updates prüfen, Kartenleser wählen und festlegen, wo "
                       "Karten-Downloads und Spesenzettel gespeichert werden.").grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        # --- Updates ------------------------------------------------------
        updates_karte = stil.Karte(rahmen, titel="Updates", padding=(16, 12))
        updates_karte.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        self._update_leiste(updates_karte.innen)

        # --- Kartenleser --------------------------------------------------
        # Bei mehreren angeschlossenen Lesern kann ein bestimmter gewählt
        # werden; „automatisch“ nimmt den ersten Leser mit Karte.
        leser_karte = stil.Karte(rahmen, titel="Kartenleser", padding=(16, 12))
        leser_karte.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))
        leser = leser_karte.innen
        leser.columnconfigure(1, weight=1)
        ttk.Label(leser, text="Verwenden:").grid(row=0, column=0, sticky="w")
        self.leser_combo = ttk.Combobox(leser, textvariable=self.leser_var,
                                        state="readonly", width=52)
        self.leser_combo.grid(row=0, column=1, sticky="w", padx=(6, 8))
        self.leser_combo.bind("<<ComboboxSelected>>", self.leser_gewaehlt)
        ttk.Button(leser, text="Suchen", command=self._leser_aktualisieren).grid(
            row=0, column=2)
        ttk.Label(leser, textvariable=self.leser_hinweis_var,
                  foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN), wraplength=760).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))

        # --- Speicherorte -------------------------------------------------
        # Standard bleibt Dokumente\CardMaster LS; .ddd-Downloads und
        # Spesenzettel-PDFs koennen getrennt umgestellt werden.
        orte_karte = stil.Karte(rahmen, titel="Speicherorte", padding=(16, 12))
        orte_karte.grid(row=4, column=0, sticky="new", padx=16)
        orte = orte_karte.innen
        orte.columnconfigure(1, weight=1)
        for zeile, beschriftung, variable, schluessel in (
                (0, ".ddd-Downloads:", self.ddd_ordner_var, "ddd_ordner"),
                (1, "Spesenzettel (PDF):", self.pdf_ordner_var,
                 "pdf_ordner")):
            ttk.Label(orte, text=beschriftung).grid(
                row=zeile, column=0, sticky="w", pady=(0, 3))
            ttk.Label(orte, textvariable=variable,
                      foreground=stil.TEXT).grid(
                row=zeile, column=1, sticky="w", padx=(4, 8), pady=(0, 3))
            ttk.Button(orte, text="Ändern …",
                       command=lambda s=schluessel: self.ordner_waehlen(s)
                       ).grid(row=zeile, column=2, pady=(0, 3))
            ttk.Button(orte, text="Standard",
                       command=lambda s=schluessel: self.ordner_standard(s)
                       ).grid(row=zeile, column=3, padx=(4, 0), pady=(0, 3))
        ttk.Label(orte, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN), wraplength=760,
                  text="Abrechnungsstand, Ortscache und Einstellungen "
                       "bleiben im Datenordner Dokumente\\CardMaster LS."
                  ).grid(row=2, column=0, columnspan=4, sticky="w",
                         pady=(5, 0))
        self._ordner_anzeigen()
        self._leser_aktualisieren()

    # --------------------------------------------------------- Kartenleser

    def _leser_aktualisieren(self):
        """Angeschlossene Kartenleser suchen und in die Auswahl übernehmen."""
        if fahrerkarte is None:
            self.leser_combo["values"] = ["(automatisch)"]
            self.leser_var.set("(automatisch)")
            self.leser_hinweis_var.set("pyscard fehlt – Kartenlesen nicht "
                                       "möglich.")
            return
        gefunden = fahrerkarte.leser_liste()
        self.leser_combo["values"] = ["(automatisch)"] + gefunden
        gemerkt = spesen_lib.kartenleser_name()
        if gemerkt and gemerkt in gefunden:
            self.leser_var.set(gemerkt)
        else:
            self.leser_var.set("(automatisch)")
        if gefunden:
            self.leser_hinweis_var.set(
                "%d Kartenleser gefunden. „automatisch“ nimmt den ersten "
                "Leser mit eingelegter Karte." % len(gefunden))
        else:
            self.leser_hinweis_var.set(
                "Kein Kartenleser gefunden. USB-Leser anschließen und erneut "
                "auf „Suchen“ klicken.")

    def leser_gewaehlt(self, _ereignis=None):
        """Gewählten Kartenleser dauerhaft merken."""
        wahl = self.leser_var.get()
        name = "" if wahl in ("", "(automatisch)") else wahl
        try:
            spesen_lib.setze_kartenleser(name)
        except OSError as e:
            self.log("Leser-Auswahl nicht gespeichert: %s" % e)
            return
        self.log("Kartenleser: %s" % (name or "automatisch"))

    def _leser_waehlen(self, leser):
        """Auswahldialog, wenn mehrere Leser angeschlossen sind.

        Rückgabe: Name des gewählten Lesers oder None bei Abbruch.
        """
        dialog = tk.Toplevel(self)
        dialog.title("Kartenleser wählen")
        dialog.transient(self)
        dialog.resizable(False, False)
        stil.anwenden(dialog)
        rahmen = ttk.Frame(dialog, padding=16)
        rahmen.pack(fill="both", expand=True)
        ttk.Label(rahmen, wraplength=420,
                  text="Mehrere Kartenleser gefunden. Bitte den Leser mit "
                       "der eingelegten Fahrerkarte wählen:").pack(anchor="w")
        var = tk.StringVar(value=leser[0])
        auswahl = ttk.Combobox(rahmen, textvariable=var, values=leser,
                               state="readonly", width=52)
        auswahl.pack(fill="x", pady=(10, 12))
        merken_var = tk.BooleanVar(value=True)
        tk.Checkbutton(rahmen, text="Auswahl merken", variable=merken_var,
                       background=stil.WEISS, activebackground=stil.WEISS,
                       foreground=stil.TEXT, selectcolor=stil.WEISS,
                       borderwidth=0, highlightthickness=0,
                       font=stil.schrift(stil.PT_KLEIN)).pack(anchor="w")
        ergebnis = {"wahl": None}

        def ok():
            ergebnis["wahl"] = var.get()
            if merken_var.get():
                try:
                    spesen_lib.setze_kartenleser(ergebnis["wahl"])
                except OSError:
                    pass
            dialog.destroy()

        knopf = ttk.Frame(rahmen)
        knopf.pack(anchor="e", pady=(14, 0))
        ttk.Button(knopf, text="Abbrechen",
                   command=dialog.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(knopf, text="Weiter", style="Primaer.TButton",
                   command=ok).pack(side="right")
        dialog.bind("<Return>", lambda _e: ok())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.update_idletasks()
        stil.fenster_einpassen(
            dialog, max(380, min(dialog.winfo_reqwidth(), 620)),
            max(200, min(dialog.winfo_reqheight(), 400)),
            parent=self, rand=20)
        auswahl.focus_set()
        dialog.grab_set()
        self.wait_window(dialog)
        return ergebnis["wahl"]

    # ------------------------------------------------------------- Updates

    def _update_leiste(self, parent):
        """Update-Status mit Knöpfen (im Einstellungen-Reiter)."""
        self.update_frame = tk.Frame(parent, background=stil.WEISS)
        self.update_frame.grid(row=0, column=0, sticky="ew")
        self.update_frame.columnconfigure(1, weight=1)
        self.update_punkt = tk.Label(
            self.update_frame, text="●", background=stil.WEISS,
            foreground=stil.GEDAEMPFT, font=stil.schrift(stil.PT_TEXT))
        self.update_punkt.grid(row=0, column=0, padx=(0, 6), pady=(0, 4))
        self.update_var = tk.StringVar(
            value="Version %s" % spesen_lib.VERSION)
        self.update_label = tk.Label(
            self.update_frame, textvariable=self.update_var,
            background=stil.WEISS, foreground=stil.TEXT, anchor="w",
            justify="left", wraplength=560,
            font=stil.schrift(stil.PT_TEXT))
        self.update_label.grid(row=0, column=1, columnspan=2, sticky="w",
                               pady=(0, 4))
        self.btn_update = ttk.Button(self.update_frame,
                                     text="Zum Download",
                                     style="Akzent.TButton",
                                     command=self.update_oeffnen)
        self.btn_update.grid(row=1, column=1, sticky="w", padx=(0, 8),
                             pady=(4, 0))
        self.btn_update.grid_remove()
        ttk.Button(self.update_frame, text="Nach Updates suchen",
                   command=lambda: self.update_suchen(manuell=True)).grid(
            row=1, column=2, sticky="w", pady=(4, 0))
        self.update_pruef_var = tk.BooleanVar(
            value=spesen_lib.update_pruefen_aktiv())
        tk.Checkbutton(
            self.update_frame,
            text="beim Start automatisch nach Updates suchen",
            variable=self.update_pruef_var,
            command=self.update_pruefen_umschalten,
            background=stil.WEISS, activebackground=stil.WEISS,
            foreground=stil.TEXT, selectcolor=stil.WEISS,
            font=stil.schrift(stil.PT_KLEIN), borderwidth=0,
            highlightthickness=0).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def update_suchen(self, manuell=False):
        """Im Hintergrund nach einer neueren Version auf GitHub suchen."""
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        if manuell:
            self.update_var.set("Suche nach Updates …")
            self.update_punkt.configure(foreground=stil.GEDAEMPFT)
        self._update_thread = threading.Thread(
            target=self._update_lauf, args=(manuell,), daemon=True)
        self._update_thread.start()

    def _update_lauf(self, manuell):
        info, fehler = spesen_lib.pruefe_update()
        self.after(0, self._update_fertig, info, fehler, manuell)

    def _update_fertig(self, info, fehler, manuell):
        if info:
            self._update_url = info.get("seite") or spesen_lib.RELEASES_SEITE
            self.update_var.set(
                "Neue Version %s verfügbar%s — Sie nutzen %s."
                % (info.get("version", "?"),
                   self._update_details(info), spesen_lib.VERSION))
            self.update_frame.configure(highlightbackground=stil.ROT,
                                        highlightcolor=stil.ROT)
            self.update_punkt.configure(foreground=stil.ROT)
            self.update_label.configure(foreground=stil.ROT_DUNKEL)
            self.btn_update.grid()
            self.log("Neue Version verfügbar: %s%s (%s)"
                     % (info.get("version", "?"), self._update_details(info),
                        self._update_url))
        elif fehler:
            if manuell:
                niedrig = str(fehler).lower()
                if ("certificate" in niedrig or "ssl" in niedrig
                        or "zertifikat" in niedrig):
                    self.update_var.set(
                        "Update-Prüfung: Zertifikatsproblem — bitte die "
                        "Release-Seite im Browser öffnen.")
                else:
                    self.update_var.set(
                        "Update-Prüfung nicht möglich (%s)." % fehler)
            else:
                self.update_var.set("Version %s" % spesen_lib.VERSION)
            self.update_punkt.configure(foreground=stil.GRAU)
        else:
            self.update_var.set("Version %s — aktuell." % spesen_lib.VERSION)
            self.update_punkt.configure(foreground=stil.GRUEN)
            if manuell:
                self.log("Update-Prüfung: Version %s ist aktuell."
                         % spesen_lib.VERSION)

    @staticmethod
    def _update_details(info):
        """Zusatzangaben zum Release: ' (16.11.2026, 26,6 MB)'."""
        teile = []
        datum = spesen_lib._datum_anzeigen(info.get("datum"))
        if datum:
            teile.append(datum)
        setup = info.get("setup") or {}
        groesse = setup.get("groesse_text")
        if groesse:
            teile.append(groesse)
        return " (%s)" % ", ".join(teile) if teile else ""

    def update_oeffnen(self):
        """Die Veröffentlichungsseite mit dem Setup im Browser öffnen."""
        try:
            os.startfile(self._update_url)
        except OSError as e:
            messagebox.showerror("Update", str(e))

    def update_pruefen_umschalten(self):
        """Automatische Update-Prüfung ein- oder ausschalten."""
        aktiv = bool(self.update_pruef_var.get())
        try:
            spesen_lib.setze_update_pruefen(aktiv)
        except OSError as e:
            self.log("Einstellung nicht gespeichert: %s" % e)
            return
        self.log("Automatische Update-Prüfung: %s"
                 % ("an" if aktiv else "aus"))

    # ---------------------------------------------------------- Speicherorte

    def _ordner_anzeigen(self):
        """Aktuelle Speicherorte in der Oberfläche anzeigen."""
        self.ddd_ordner_var.set(str(spesen_lib.ddd_ordner()))
        self.pdf_ordner_var.set(str(spesen_lib.pdf_ordner()))
        if hasattr(self, "datei_var"):
            self.datei_var.set(
                "Spesenzettel: %s   ·   .ddd-Downloads: %s"
                % (spesen_lib.pdf_ordner(), spesen_lib.ddd_ordner()))

    def ordner_waehlen(self, schluessel):
        """Ordner für .ddd-Downloads oder Spesenzettel-PDFs auswählen."""
        aktuell = (spesen_lib.ddd_ordner() if schluessel == "ddd_ordner"
                   else spesen_lib.pdf_ordner())
        pfad = filedialog.askdirectory(
            title="Speicherort wählen", initialdir=str(aktuell),
            mustexist=False)
        if not pfad:
            return
        try:
            neu = spesen_lib.setze_ordner(schluessel, pfad)
        except OSError as e:
            messagebox.showerror("Speicherort", str(e))
            return
        self._ordner_anzeigen()
        self.log("Speicherort geändert: %s" % neu)

    def ordner_standard(self, schluessel):
        """Speicherort auf Dokumente\\CardMaster LS zurücksetzen."""
        try:
            neu = spesen_lib.setze_ordner(schluessel, "")
        except OSError as e:
            messagebox.showerror("Speicherort", str(e))
            return
        self._ordner_anzeigen()
        self.log("Speicherort auf Standard zurückgesetzt: %s" % neu)

    def _spesenseite(self, rahmen):
        rahmen.columnconfigure(0, weight=1)
        rahmen.rowconfigure(3, weight=1)

        kopf = ttk.Frame(rahmen)
        kopf.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))
        kopf.columnconfigure(0, weight=1)
        ttk.Label(kopf, text="Spesenzettel (Reisekostenabrechnung)",
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_TITEL, True)).grid(row=0, column=0,
                                                       sticky="w")
        ttk.Button(kopf, text="Zur Startseite",
                   command=lambda: self.notiz.select(self.tab_start)).grid(
            row=0, column=1, sticky="e")
        self.spesen_info_var = tk.StringVar(
            value="Datenquelle und Kopfdaten auf der Startseite. "
                  "Zeitraum je Blatt: 16. bis 15. des Folgemonats.")
        ttk.Label(rahmen, textvariable=self.spesen_info_var,
                  foreground=stil.GEDAEMPFT, font=stil.schrift(stil.PT_TEXT),
                  wraplength=980).grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 8))

        # --- Fahrten ------------------------------------------------------
        fahrten_karte = stil.Karte(
            rahmen, titel="Noch nicht abgerechnete Fahrten", padding=(16, 12))
        fahrten_karte.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        fahrten = fahrten_karte.innen
        fahrten.columnconfigure(0, weight=1)
        fahrten.rowconfigure(1, weight=1)
        self.fahrten_frame = fahrten

        # Zeitraum-Auswahl: genau eine Abrechnungsperiode oder alle offenen
        steuer = ttk.Frame(fahrten)
        steuer.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        zeile1 = ttk.Frame(steuer)
        zeile1.pack(fill="x")
        zeile2 = ttk.Frame(steuer)
        zeile2.pack(fill="x", pady=(5, 0))
        ttk.Label(zeile1, text="Zeitraum:").pack(side="left")
        self.zeitraum_var = tk.StringVar()
        self.zeitraum_combo = ttk.Combobox(
            zeile1, textvariable=self.zeitraum_var, state="readonly",
            width=30, values=["Alle offenen Zeiträume"])
        self.zeitraum_combo.pack(side="left", padx=(6, 0))
        self.zeitraum_combo.bind("<<ComboboxSelected>>",
                                 lambda e: self._tabelle_aktualisieren())
        ttk.Label(zeile1, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN),
                  text="(16. bis 15. des Folgemonats)").pack(
            side="left", padx=(8, 0))
        self._zeitraum_map = {"Alle offenen Zeiträume": None}

        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            zeile1,
            text="Abrechnungsstand ignorieren (Ergänzungsblatt)",
            variable=self.force_var,
            command=self._tabelle_aktualisieren).pack(side="left", padx=(16, 0))

        # Abrechnungsart: Nah- oder Fernverkehr. Sie bestimmt, wie Nächte
        # außerhalb des Heimatorts behandelt werden (siehe unten).
        ttk.Label(zeile2, text="Abrechnungsart:").pack(side="left")
        self.verkehr_var = tk.StringVar(value="fernverkehr")
        ttk.Radiobutton(zeile2, text="Fernverkehr (Nacht im Lkw)",
                        value="fernverkehr", variable=self.verkehr_var,
                        command=self._verkehrsart_geaendert).pack(
            side="left", padx=(6, 0))
        ttk.Radiobutton(zeile2, text="Nahverkehr (täglich zuhause)",
                        value="nahverkehr", variable=self.verkehr_var,
                        command=self._verkehrsart_geaendert).pack(
            side="left", padx=(10, 0))
        ttk.Label(zeile2, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN),
                  text="(Nahverkehr: fragt je Nacht nach, wenn der Lkw "
                       "nicht am Heimatort stand)").pack(
            side="left", padx=(8, 0))

        spalten = (("nr", "#", 36, "center"),
                   ("datum", "Datum", 90, "center"),
                   ("beginn", "Beginn", 62, "center"),
                   ("ende", "Ende", 62, "center"),
                   ("std", "Std.", 56, "e"),
                   ("km", "km", 58, "e"),
                   ("start", "Start", 150, "w"),
                   ("ziel", "Ziel", 150, "w"),
                   ("fzg", "Fahrzeug", 110, "w"))
        self.tree = ttk.Treeview(fahrten, show="headings",
                                 height=9, columns=[s[0] for s in spalten])
        for sid, titel, breite, anker in spalten:
            self.tree.heading(sid, text=titel)
            self.tree.column(sid, width=breite, anchor=anker)
        self.tree.grid(row=1, column=0, sticky="nsew")
        balken = ttk.Scrollbar(fahrten, orient="vertical",
                               command=self.tree.yview)
        balken.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=balken.set)
        stil.zebra_konfigurieren(self.tree)

        self.summe_var = tk.StringVar(value="")
        ttk.Label(fahrten, textvariable=self.summe_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # --- Aktionen -----------------------------------------------------
        aktion = ttk.Frame(rahmen)
        aktion.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.btn_erstellen = ttk.Button(
            aktion, text="Spesenzettel erstellen (PDF)",
            image=assets.lade("btn_erstellen"), compound="left",
            style="PrimaerRot.TButton", command=self.erstellen,
            state="disabled")
        self.btn_erstellen.grid(row=0, column=0)
        self.oeffnen_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(aktion, text="PDF nach dem Erstellen öffnen",
                        variable=self.oeffnen_var).grid(
            row=0, column=1, padx=16)
        self.btn_ordner = ttk.Button(
            aktion, text="Ordner öffnen", image=assets.lade("btn_ordner"),
            compound="left", command=self.ordner_oeffnen)
        self.btn_ordner.grid(row=0, column=2, padx=(16, 0))
        self.btn_hilfe = ttk.Button(
            aktion, text="Anleitung", image=assets.lade("btn_hilfe"),
            compound="left", command=self.anleitung_oeffnen)
        self.btn_hilfe.grid(row=0, column=3, padx=(8, 0))
        self.datei_var = tk.StringVar()
        ttk.Label(aktion, textvariable=self.datei_var,
                  foreground=stil.GEDAEMPFT, font=stil.schrift(stil.PT_KLEIN)).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(5, 0))
        self._ordner_anzeigen()

    # ------------------------------------------------------------ Protokoll

    def log(self, text):
        try:
            self.after(0, self._log_einfuegen, str(text))
        except RuntimeError:
            pass

    def _log_einfuegen(self, text):
        """Eine Protokollzeile mit Zeitstempel und Farbstufe anhängen."""
        zeit = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "[%s] " % zeit, ("zeit",))
        self.log_text.insert("end", "%s\n" % text, (self._log_stufe(text),))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _log_stufe(text):
        """Farbstufe einer Protokollzeile anhand des Textanfangs bestimmen."""
        oben = text.lstrip().upper()
        if oben.startswith("FEHLER") or "TRACEBACK" in oben:
            return "fehler"
        if oben.startswith("WARN") or oben.startswith("ACHTUNG"):
            return "warn"
        if oben.startswith("OK") or "FERTIG" in oben or "ERSTELLT" in oben:
            return "ok"
        return "info"

    # --------------------------------------------------------- Datenquelle

    def _fortschritt_an(self, text="Bitte warten …"):
        """Dünnen Fortschrittsbalken mit Statustext einblenden."""
        try:
            self.fortschritt_var.set(text)
            self.fortschritt.grid()
            self.fortschritt_label.grid()
            self.fortschritt.start(14)
            self.update_idletasks()
        except tk.TclError:
            pass

    def _fortschritt_aus(self):
        """Fortschrittsbalken wieder ausblenden."""
        try:
            self.fortschritt.stop()
            self.fortschritt.grid_remove()
            self.fortschritt_label.grid_remove()
            self.fortschritt_var.set("")
        except tk.TclError:
            pass

    def _busy(self, an, text=""):
        zustand = "disabled" if an else "!disabled"
        self.btn_karte.state([zustand])
        self.btn_ddd.state([zustand])
        self.btn_heim.state([zustand])
        self.btn_erstellen.state(
            ["disabled"] if an or not self._anzeige() else ["!disabled"])
        if an:
            self._fortschritt_an(text or "Bitte warten …")
        else:
            self._fortschritt_aus()
        if text:
            self.log(text)

    def karte_auslesen(self):
        """Kartenleser bestimmen und das Auslesen im Hintergrund starten."""
        if fahrerkarte is None:
            messagebox.showerror(
                "Karte auslesen",
                "Das Modul 'pyscard' fehlt. Bitte einmalig installieren:\n"
                "py -m pip install pyscard")
            return
        leser = fahrerkarte.leser_liste()
        if not leser:
            messagebox.showerror(
                "Karte auslesen",
                "Kein Kartenleser gefunden. Bitte den USB-Kartenleser "
                "anschließen und die Fahrerkarte einstecken.")
            return
        if len(leser) == 1:
            wahl = leser[0]
        else:
            gemerkt = spesen_lib.kartenleser_name()
            if gemerkt in leser:
                wahl = gemerkt
            else:
                wahl = self._leser_waehlen(leser)
                if not wahl:
                    return
        self._busy(True, "Karte wird ausgelesen — bitte warten …")
        threading.Thread(target=self._karte_lesen, args=(wahl,),
                         daemon=True).start()

    def _karte_lesen(self, leser=None):
        """Fahrerkarte im Hintergrund auslesen (blocking, eigener Thread)."""
        try:
            if not fahrerkarte.leser_liste():
                raise RuntimeError(
                    "Kein Kartenleser gefunden. USB-Leser anschließen und "
                    "Karte einstecken.")

            protokoll = io.StringIO()
            with contextlib.redirect_stdout(protokoll):
                karte = fahrerkarte.oeffne_karte(leser)
                try:
                    bloecke, meta = fahrerkarte.download(karte)
                    # Gen-2-Anwendung (GNSS-Orte) mit auslesen; scheitert
                    # sie, bleibt der Download als Gen-1-Datei gültig.
                    fahrerkarte.download_g2(karte, bloecke, meta)
                finally:
                    karte.close()
                ident = fahrerkarte.parse_identification(meta["ident_raw"])
                ddd = fahrerkarte.build_ddd(bloecke)

            self.log("Kartenleser: %s (%s)"
                     % (karte.reader, karte.protokoll or "?"))
            for zeile in protokoll.getvalue().splitlines():
                if zeile.strip():
                    self.log(zeile.strip())

            self.log("Karte gelesen: %s %s (%s)"
                     % (ident["vorname"], ident["nachname"],
                        ident["kartennummer"]))
            sicher = (ident["vorname"] + ident["nachname"]).replace(" ", "")
            name = "C_%s_%s_%s.DDD" % (
                datetime.now().strftime("%Y%m%d_%H%M"), sicher,
                ident["kartennummer"])
            pfad = spesen_lib.ddd_ordner() / name
            pfad.write_bytes(ddd)
            self.log(".ddd-Download gespeichert: %s (%d Byte)"
                     % (pfad.name, len(ddd)))
            self.after(0, self.geladen, str(pfad))
        except Exception as e:
            self.log("FEHLER beim Karten-Auslesen: %s" % e)
            self.after(0, lambda: messagebox.showerror(
                "Karte auslesen", str(e)))
        finally:
            self.after(0, self._busy, False)

    def ddd_oeffnen(self):
        pfad = filedialog.askopenfilename(
            title=".ddd-Datei öffnen",
            initialdir=str(spesen_lib.ddd_ordner()),
            filetypes=[("Fahrerkarten-Download", "*.ddd *.DDD"),
                       ("Alle Dateien", "*.*")])
        if pfad:
            self.geladen(pfad)

    # -------------------------------------------------------------- Anzeige

    def geladen(self, pfad):
        """.ddd auswerten und Oberflaeche fuellen."""
        try:
            info = spesen_lib.lade_ddd(pfad)
        except Exception as e:
            self.log("Fehler beim Auswerten von %s: %s" % (Path(pfad).name, e))
            messagebox.showerror(".ddd auswerten", str(e))
            return

        if self.info and self.info["kartennummer"] != info["kartennummer"]:
            self.log("Andere Fahrerkarte erkannt: %s (%s) — eigener "
                     "Abrechnungsstand wird verwendet."
                     % (info["name"], info["kartennummer"]))

        self.info = info
        self.kartenstaende = spesen_lib.load_state()["karten"]
        ks = self.kartenstaende.get(info["kartennummer"], {})

        self.name_var.set(ks.get("name") or info["name"])
        self.abt_var.set(ks.get("abteilung", ""))
        self.pnr_var.set(ks.get("personal_nr", ""))

        # Heimatort (Wohnort) je Karte: einmal geprüft, gilt er auch beim
        # nächsten Lesen der Karte wieder.
        heim = ks.get("heimat") or {}
        if heim.get("lat") is None:
            # Kein Heimatort für diese Kartennummer gespeichert: von einer
            # anderen Karte desselben Fahrers übernehmen. So bleibt der
            # Wohnort erhalten, wenn die Karte neu gelesen wird und dabei
            # eine andere Kartennummer gemeldet wird.
            for andere_nr, andere in self.kartenstaende.items():
                if andere_nr == info["kartennummer"]:
                    continue
                if (andere.get("name") or "").strip().lower() != \
                        (info.get("name") or "").strip().lower():
                    continue
                h = andere.get("heimat") or {}
                if h.get("lat") is not None:
                    heim = h
                    spesen_lib.speichere_heimat(
                        info["kartennummer"], h.get("text", ""),
                        (h["lat"], h["lon"]))
                    self.log("Heimatort von Karte %s übernommen: %s"
                             % (andere_nr, h.get("text", "")))
                    break
        self._fern_cache = None
        self._nacht_im_lkw = None
        self.verkehr_var.set(ks.get("verkehrsart") or "fernverkehr")
        self._heim = None
        self._heim_text = ""
        self.heimat_var.set("")
        self.heim_var.set("")
        if heim.get("lat") is not None:
            self._heim = (heim["lat"], heim["lon"])
            self._heim_text = heim.get("text", "")
            self.heimat_var.set(self._heim_text)
            self.heim_var.set(
                "Heimatort: %s (%.4f, %.4f) — Tageszeilen"
                % (self._heim_text, heim["lat"], heim["lon"]))
        else:
            self.heim_var.set(
                "Kein Heimatort — Touren (Start–Ziel). Für „Heimatort – "
                "Zwischenort – Heimatort“ Wohnort eintragen und „Prüfen“.")

        zeilen = [
            "Karte %s — %s — gültig bis %s%s"
            % (info["kartennummer"], info["name"],
               spesen_lib._fmt(info["gueltig_bis"]) if info["gueltig_bis"]
               else "?",
               " — Generation 2 (GNSS-Orte)" if info.get("gen2") else ""),
            "%d Fahrten gespeichert, letzte: %s · %d Fahrzeuge"
            % (len(info["touren"]),
               spesen_lib._fmt(info["touren"][-1]["tag"])
               if info["touren"] else "—",
               len(info["fahrzeuge"])),
        ]
        if ks.get("letzte_zeile"):
            zeilen.append("Abgerechnet bis: %s · %d Blatt bereits erstellt"
                          % (spesen_lib._fmt(date.fromisoformat(ks["letzte_zeile"])),
                             len(ks.get("blaetter", []))))
        else:
            zeilen.append("Diese Karte wurde noch nicht abgerechnet.")
        self.info_var.set("\n".join(zeilen))

        self.log("Geladen: %s (%d Fahrten%s)"
                 % (Path(pfad).name, len(info["touren"]),
                    ", Gen-2 mit GNSS-Orten" if info.get("gen2") else ""))
        self._tabelle_aktualisieren()
        self._orte_suchen()
        self.tab_karten.setze_info(info)
        self.tab_recht.setze_info(info)
        self._uebersicht_aktualisieren()
        self.notiz.select(self.tab_start)

    def _uebersicht_aktualisieren(self):
        """Kacheln bzw. Leerzustand auf der Startseite auffrischen."""
        if not self.info:
            self.kachel_rahmen.grid_remove()
            self.leer_rahmen.grid()
            self.uebersicht_var.set("")
            return

        info = self.info
        self.leer_rahmen.grid_remove()
        self.kachel_rahmen.grid()

        tage = self.tab_karten._tage
        verstoesse = sum(len(t["verstoesse"]) for t in tage) if tage else 0
        offen = [t for t in self._anzeige() if not t.get("leer")]

        self._kachel_setzen("fahrer", info.get("name") or "—")
        self._kachel_setzen("tage", str(len(tage)) if tage else "0")
        self._kachel_setzen("verstoesse", str(verstoesse),
                            farbe=stil.ROT if verstoesse else "#2E6B2E")
        self._kachel_setzen("offen", str(len(offen)),
                            farbe=stil.ROT if offen else stil.NAVY)

        zeilen = ["Karte %s" % (info.get("kartennummer") or "?")]
        if tage:
            hinweise = sum(1 for t in tage for m in t["meldungen"]
                           if m["art"] == "Hinweis")
            zeilen.append(
                "Kartendaten: %d Tage (%s – %s) · %d Hinweise"
                % (len(tage), tage[0]["tag"].strftime("%d.%m.%Y"),
                   tage[-1]["tag"].strftime("%d.%m.%Y"), hinweise))
        else:
            zeilen.append("Kartendaten: keine Tagesaktivitäten gespeichert")
        if info.get("gen2"):
            zeilen.append("Generation 2 · GNSS-Orte verfügbar")
        zeilen.append("Fahrten: %d gespeichert · %d Fahrzeuge"
                      % (len(info.get("touren") or []),
                         len(info.get("fahrzeuge") or [])))
        ks = self.kartenstaende.get(info["kartennummer"], {})
        if ks.get("letzte_zeile"):
            zeilen.append(
                "Abrechnung: bis %s · %d Blatt erstellt"
                % (spesen_lib._fmt(date.fromisoformat(ks["letzte_zeile"])),
                   len(ks.get("blaetter", []))))
        else:
            zeilen.append("Abrechnung: noch kein Blatt erstellt")
        self.uebersicht_var.set("   ·   ".join(zeilen))
        self.spesen_info_var.set(
            "Karte %s — %s · Datenquelle und Kopfdaten auf der Startseite."
            % (info.get("kartennummer", "?"), info.get("name", "")))

    def _kachel_setzen(self, schluessel, wert, farbe=None):
        """Wert einer Kennzahl-Kachel setzen (optional mit Farbe)."""
        label = self.kacheln.get(schluessel)
        if label is None:
            return
        label.configure(text=wert, foreground=farbe or stil.NAVY)

    def _orte_suchen(self):
        """Ortsnamen im Hintergrund ermitteln (eine Anfrage je 1,1 s),
        Tabelle danach aktualisieren."""
        if not self.info:
            return
        if self._orte_thread and self._orte_thread.is_alive():
            return
        zeilen = list(self._anzeige())
        if not zeilen:
            return
        self._orte_thread = threading.Thread(
            target=self._orte_loesen, args=(zeilen,), daemon=True)
        self._orte_thread.start()

    def _orte_loesen(self, zeilen):
        try:
            spesen_lib.orte_aufloesen(zeilen, log=self._ort_log)
        except Exception as e:
            self.log("FEHLER beim Ermitteln der Ortsnamen: %s" % e)
        try:
            self.after(0, self._tabelle_aktualisieren)
        except RuntimeError:
            pass

    def _ort_log(self, text):
        """Logzeile der Ortsnamen-Suche: ausgeben und Tabelle auffrischen."""
        self.log(text)
        try:
            self.after(0, self._tabelle_aktualisieren)
        except RuntimeError:
            pass

    def _tageszeilen(self):
        """Tageszeilen für den geprüften Heimatort (einmal berechnet)."""
        if self._fern_cache is None:
            try:
                self._fern_cache = spesen_lib.fernverkehr_zeilen(
                    self.info, self._heim, log=self.log,
                    heimat_text=spesen_lib.heimat_anzeigename(
                        self._heim_text, self._heim, log=self.log),
                    nacht_im_lkw=self._nacht_im_lkw)
            except Exception as e:
                self.log("FEHLER bei den Tageszeilen: %s" % e)
                self._fern_cache = []
        return self._fern_cache

    def _basiszeilen(self):
        """Alle Zeilen der Karte (Tageszeilen oder Touren), ohne Filter."""
        if not self.info:
            return []
        if self._heim is not None:
            return list(self._tageszeilen())
        return list(self.info["touren"])

    def _gewaehlter_zeitraum(self):
        """(von, bis) der Zeitraum-Auswahl oder None (alle offenen)."""
        return self._zeitraum_map.get(self.zeitraum_var.get())

    def _anzeige(self):
        zeilen = self._basiszeilen()
        if not zeilen:
            return []
        zeitraum = self._gewaehlter_zeitraum()
        if zeitraum is not None:
            return spesen_lib.leere_raender_entfernen(
                [z for z in zeilen
                 if spesen_lib.abrechnungsperiode(z["tag"]) == zeitraum])
        letzte = self.kartenstaende.get(
            self.info["kartennummer"], {}).get("letzte_zeile")
        if self.force_var.get() or not letzte:
            return zeilen
        return spesen_lib.leere_raender_entfernen(
            spesen_lib.neue_fahrten(zeilen, letzte))

    def _perioden_aktualisieren(self):
        """Auswahlliste der Abrechnungszeiträume (16.–15.) füllen."""
        zeilen = self._basiszeilen()
        perioden = sorted({spesen_lib.abrechnungsperiode(z["tag"])
                           for z in zeilen if not z.get("leer")})
        werte = ["Alle offenen Zeiträume"]
        self._zeitraum_map = {werte[0]: None}
        for von, bis in reversed(perioden):
            label = "%s – %s" % (spesen_lib._fmt(von), spesen_lib._fmt(bis))
            werte.append(label)
            self._zeitraum_map[label] = (von, bis)
        alt = self.zeitraum_var.get()
        self.zeitraum_combo["values"] = werte
        self.zeitraum_var.set(alt if alt in self._zeitraum_map else werte[0])

    def _verkehrsart_geaendert(self):
        """Nah-/Fernverkehr gewechselt: merken und Vorschau neu berechnen."""
        art = self.verkehr_var.get()
        self._nacht_im_lkw = None
        self._fern_cache = None
        if self.info:
            try:
                spesen_lib.speichere_kartenwert(
                    self.info["kartennummer"], "verkehrsart", art)
            except OSError as e:
                self.log("Einstellung nicht gespeichert: %s" % e)
        self.log("Abrechnungsart: %s"
                 % ("Fernverkehr" if art == "fernverkehr" else "Nahverkehr"))
        self._tabelle_aktualisieren()

    def _naechte_fragen(self, naechte):
        """Nahverkehr: je Nacht fragen, ob sie im Lkw verbracht wurde.

        Rückgabe: dict {(vortag, folgetag): True/False} oder None, wenn
        die Rückfrage abgebrochen wurde. Die Liste ist scrollbar, damit der
        Dialog auch bei vielen Nächten vollständig auf dem Bildschirm bleibt.
        """
        fenster = tk.Toplevel(self)
        fenster.title("Nächte außerhalb des Heimatorts")
        fenster.transient(self)
        fenster.resizable(True, True)
        fenster.grab_set()
        stil.anwenden(fenster)
        stil.hand_cursor(fenster)

        rahmen = ttk.Frame(fenster, padding=(16, 14))
        rahmen.pack(fill="both", expand=True)
        rahmen.columnconfigure(0, weight=1)
        rahmen.rowconfigure(1, weight=1)

        ttk.Label(rahmen, justify="left", wraplength=470,
                  text="Der Lkw stand in diesen Nächten nicht am Heimatort "
                       "(%s).\nBitte die Nächte abwählen, die zuhause "
                       "verbracht wurden." % (self._heim_text or "?")
                  ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        # Nur die Nächte werden gescrollt; Kopfzeile und Knöpfe bleiben
        # immer sichtbar.
        listen_rahmen = ttk.Frame(rahmen)
        listen_rahmen.grid(row=1, column=0, sticky="nsew")
        listen_rahmen.columnconfigure(0, weight=1)
        listen_rahmen.rowconfigure(0, weight=1)
        canvas = tk.Canvas(listen_rahmen, highlightthickness=0,
                           background=stil.WEISS)
        canvas.grid(row=0, column=0, sticky="nsew")
        leiste = ttk.Scrollbar(listen_rahmen, orient="vertical",
                               command=canvas.yview)
        leiste.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=leiste.set)
        inhalt = ttk.Frame(canvas)
        fenster_id = canvas.create_window((0, 0), window=inhalt, anchor="nw")

        def breite_anpassen(_e=None):
            canvas.itemconfigure(fenster_id, width=canvas.winfo_width())

        def bereich_anpassen(_e=None):
            begrenzung = canvas.bbox("all")
            if not begrenzung:
                return
            canvas.configure(scrollregion=begrenzung)
            if begrenzung[3] > canvas.winfo_height() + 1:
                leiste.grid()
            else:
                leiste.grid_remove()

        def scrollen(e):
            canvas.yview_scroll(-int(e.delta / 120), "units")

        canvas.bind("<Configure>", breite_anpassen)
        inhalt.bind("<Configure>", bereich_anpassen)
        for widget in (canvas, inhalt):
            widget.bind("<MouseWheel>", scrollen)

        eintraege = []
        for n in naechte:
            var = tk.BooleanVar(value=True)
            knopf = ttk.Checkbutton(
                inhalt,
                text="Nacht %s → %s" % (spesen_lib._fmt(n["vor"]),
                                        spesen_lib._fmt(n["nach"])),
                variable=var)
            knopf.pack(anchor="w", pady=1)
            knopf.bind("<MouseWheel>", scrollen)
            eintraege.append((n, var))

        ergebnis = {"ok": False}

        def uebernehmen():
            ergebnis["ok"] = True
            fenster.destroy()

        knoepfe = ttk.Frame(rahmen)
        knoepfe.grid(row=2, column=0, sticky="e", pady=(12, 0))
        ttk.Button(knoepfe, text="Übernehmen", style="Akzent.TButton",
                   command=uebernehmen).pack(side="right")
        ttk.Button(knoepfe, text="Abbrechen",
                   command=fenster.destroy).pack(side="right", padx=(0, 8))
        fenster.bind("<Escape>", lambda _e: fenster.destroy())

        # Listenhöhe so bemessen, dass Kopf und Knöpfe immer mit draufpassen.
        _ax, _ay, _aw, bildschirm_h = stil.arbeitsflaeche(self)
        listen_hoehe = max(120, min(len(naechte) * 26 + 10,
                                    bildschirm_h - 250))
        canvas.configure(width=470, height=listen_hoehe)
        fenster.update_idletasks()
        stil.fenster_einpassen(
            fenster, max(380, min(fenster.winfo_reqwidth(), 540)),
            max(220, min(fenster.winfo_reqheight(), bildschirm_h - 40)),
            parent=self, rand=20)
        fenster.update_idletasks()
        bereich_anpassen()
        fenster.wait_window()
        if not ergebnis["ok"]:
            return None
        return {(n["vor"].isoformat(), n["nach"].isoformat()): bool(var.get())
                for n, var in eintraege}

    def heimat_pruefen(self):
        """Heimatort (Wohnort) in Koordinaten übersetzen (im Hintergrund)."""
        text = self.heimat_var.get().strip()
        if not text:
            if self._heim is not None and not messagebox.askyesno(
                    "Heimatort entfernen",
                    "Der gespeicherte Heimatort „%s“ wird entfernt.\n\n"
                    "Danach werden nur noch Fahrten (Start–Ziel) "
                    "abgerechnet.\n\nFortsetzen?" % self._heim_text):
                self.heimat_var.set(self._heim_text)
                return
            self._heim = None
            self._heim_text = ""
            self._fern_cache = None
            self.heim_var.set("Kein Heimatort — Touren (Nahverkehr)")
            if self.info:
                spesen_lib.speichere_heimat(
                    self.info["kartennummer"], "", None)
            self._tabelle_aktualisieren()
            self._orte_suchen()
            return
        self.btn_heim.state(["disabled"])
        self.heim_var.set("Suche „%s“ …" % text)

        def lauf():
            try:
                heim = spesen_lib.heimatort_aufloesen(text, log=self.log)
            except Exception as e:
                self.after(0, self._heim_fehler, text, str(e))
                return
            self.after(0, self._heim_fertig, text, heim)

        threading.Thread(target=lauf, daemon=True).start()

    def _heim_fertig(self, text, heim):
        self.btn_heim.state(["!disabled"])
        if heim is None:
            self._heim = None
            self._heim_text = ""
            self._fern_cache = None
            self.heim_var.set("„%s“ nicht gefunden — bitte Ort oder PLZ "
                              "prüfen." % text)
            self._tabelle_aktualisieren()
            return
        self._heim = heim
        self._heim_text = text
        self._fern_cache = None
        self.heim_var.set(
            "Heimatort: %s (%.4f, %.4f) — Tageszeilen"
            % (text, heim[0], heim[1]))
        if self.info:
            spesen_lib.speichere_heimat(
                self.info["kartennummer"], text, heim)
        self.log("Heimatort gespeichert: %s (%.4f, %.4f)"
                 % (text, heim[0], heim[1]))
        self._tabelle_aktualisieren()
        self._orte_suchen()

    def _heim_fehler(self, text, meldung):
        self.btn_heim.state(["!disabled"])
        niedrig = meldung.lower()
        if ("certificate" in niedrig or "ssl" in niedrig
                or "zertifikat" in niedrig):
            self.heim_var.set(
                "„%s“: Zertifikatsproblem — bitte Koordinaten eingeben "
                "(z. B. 53.55, 8.58) oder die IT kontaktieren." % text)
        else:
            self.heim_var.set("„%s“ nicht ermittelbar: %s" % (text, meldung))
        self.log("FEHLER beim Prüfen des Heimatorts: %s" % meldung)

    def _tabelle_aktualisieren(self):
        self._perioden_aktualisieren()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        zeilen = self._anzeige()
        nr = 0
        for position, t in enumerate(zeilen, start=1):
            tags = stil.zebra_tags(position)
            if t.get("leer"):
                self.tree.insert("", "end", values=(
                    "", "", "", "", "", "", "", "", ""), tags=tags)
                continue
            nr += 1
            self.tree.insert("", "end", values=(
                nr, spesen_lib._fmt(t["tag"]), t["beginn"], t["ende"],
                t["dauer"], t["km"],
                spesen_lib.ortstext(t, "start"),
                spesen_lib.ortstext(t, "ziel"),
                t.get("fahrzeug", "")), tags=tags)
        if self._heim is not None:
            self.fahrten_frame.configure(
                text="Noch nicht abgerechnete Tage (Heimatort %s)"
                     % (self._heim_text or "?"))
            self.tree.heading("start", text="Ort (Schicht)")
            self.tree.heading("ziel", text="")
        else:
            self.fahrten_frame.configure(text="Noch nicht abgerechnete Fahrten")
            self.tree.heading("start", text="Start")
            self.tree.heading("ziel", text="Ziel")
        echte = [t for t in zeilen if not t.get("leer")]
        self._kachel_setzen("offen", str(len(echte)),
                            farbe=stil.ROT if echte else stil.NAVY)
        if echte and self.info:
            von, bis = spesen_lib.abrechnungsperiode(echte[0]["tag"])
            einheit = "Tage" if self._heim is not None else "Fahrten"
            self.summe_var.set(
                "%d %s · %d km · Zeitraum %s – %s"
                % (len(echte), einheit, sum(t["km"] for t in echte),
                   spesen_lib._fmt(von), spesen_lib._fmt(bis)))
            self.btn_erstellen.state(["!disabled"])
        else:
            if self._heim is not None:
                self.summe_var.set(
                    "Keine neuen Tage — alles bereits abgerechnet."
                    if self.info else "")
            else:
                self.summe_var.set(
                    "Keine neuen Fahrten — alles bereits abgerechnet."
                    if self.info else "")
            self.btn_erstellen.state(["disabled"])

    # -------------------------------------------------------------- Aktion

    def ordner_oeffnen(self):
        ordner = spesen_lib.pdf_ordner()
        try:
            ordner.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        os.startfile(str(ordner))

    def anleitung_oeffnen(self):
        """Kurzanleitung (Textdatei) im Standardprogramm öffnen."""
        for pfad in (spesen_lib.APP_DIR / "ANLEITUNG CardMaster LS.txt",
                     spesen_lib.BASE / "ANLEITUNG CardMaster LS.txt"):
            if pfad.is_file():
                try:
                    os.startfile(str(pfad))
                    return
                except OSError as e:
                    messagebox.showerror("Anleitung", str(e))
                    return
        messagebox.showinfo(
            "Anleitung",
            "Die Anleitung „ANLEITUNG CardMaster LS.txt“ wurde nicht "
            "gefunden.")

    def erstellen(self):
        if not self.info:
            return
        name = self.name_var.get().strip()
        abteilung = self.abt_var.get().strip()
        personal_nr = self.pnr_var.get().strip()
        heimat = self.heimat_var.get().strip()
        if not name:
            messagebox.showwarning("Kopfdaten", "Bitte einen Namen eintragen.")
            return
        if heimat != self._heim_text:
            messagebox.showwarning(
                "Heimatort",
                "Der Heimatort wurde geändert. Bitte zuerst „Prüfen“ "
                "wählen, damit Vorschau und Spesenzettel übereinstimmen.")
            return
        if self._heim is not None and self.force_var.get() \
                and self._gewaehlter_zeitraum() is None:
            perioden = sorted({spesen_lib.abrechnungsperiode(t["tag"])
                               for t in self._basiszeilen()
                               if not t.get("leer")})
            if len(perioden) > 1:
                zeilen = ["• %s – %s" % (spesen_lib._fmt(von),
                                         spesen_lib._fmt(bis))
                          for von, bis in perioden[:10]]
                if len(perioden) > len(zeilen):
                    zeilen.append("… und %d weitere"
                                  % (len(perioden) - len(zeilen)))
                if not messagebox.askyesno(
                        "Ergänzungsblätter",
                        "Der Abrechnungsstand wird ignoriert. Es würden %d "
                        "Blätter erstellt:\n\n%s\n\nFortsetzen?"
                        % (len(perioden), "\n".join(zeilen))):
                    return
        nacht_im_lkw = None
        if self._heim is not None and self.verkehr_var.get() == "nahverkehr":
            if self._nacht_im_lkw is None:
                naechte = spesen_lib.naechte_ausser_heimat(
                    self.info, self._heim, log=self.log)
                if naechte:
                    self._nacht_im_lkw = self._naechte_fragen(naechte)
                    if self._nacht_im_lkw is None:
                        return
                    self._fern_cache = None
                    self._tabelle_aktualisieren()
            nacht_im_lkw = self._nacht_im_lkw
        self._fortschritt_an("Spesenzettel wird erstellt …")
        try:
            dateien = spesen_lib.erstelle_spesenzettel(
                self.info, name, abteilung, personal_nr,
                force=self.force_var.get(), log=self.log,
                heimat=self._heim_text,
                zeitraum=self._gewaehlter_zeitraum(),
                nacht_im_lkw=nacht_im_lkw)
        except Exception as e:
            self.log("FEHLER beim Erstellen: %s" % e)
            self.log(traceback.format_exc())
            messagebox.showerror("Spesenzettel erstellen", str(e))
            return
        finally:
            self._fortschritt_aus()
        self.kartenstaende = spesen_lib.load_state()["karten"]
        self._tabelle_aktualisieren()
        self._uebersicht_aktualisieren()
        if dateien and self.oeffnen_var.get():
            for pfad in dateien:
                os.startfile(str(pfad))


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--test":
        return _selbsttest(argv[1] if len(argv) > 1 else None)
    stil.dpi_aktivieren()
    app = App()
    app.mainloop()


def _selbsttest(ddd_pfad):
    """Ohne Fenster laufen lassen (fuer Pruefung der installierten .exe).

    Schreibt das Ergebnis nach Dokumente/CardMaster LS/selbsttest.txt.
    """
    bericht = ["Selbsttest %s" % datetime.now().isoformat(timespec="seconds"),
               "Programm : %s" % sys.executable,
               "Version  : %s" % spesen_lib.VERSION,
               "Formular : %s (%s)" % (spesen_lib.FORMULAR,
                                       "vorhanden"
                                       if spesen_lib.FORMULAR.is_file()
                                       else "FEHLT"),
               "Daten in : %s" % spesen_lib.DATA_DIR,
               "PDF in   : %s" % spesen_lib.pdf_ordner(),
               ".ddd in  : %s" % spesen_lib.ddd_ordner()]
    protokoll = []

    def log(text):
        protokoll.append(str(text))

    try:
        if not ddd_pfad:
            kandidaten = []
            for ordner in (spesen_lib.ddd_ordner(), spesen_lib.DATA_DIR):
                kandidaten += sorted(ordner.glob("*.ddd"))
                kandidaten += sorted(ordner.glob("*.DDD"))
            if not kandidaten:
                raise RuntimeError("keine .ddd-Datei im Datenordner")
            ddd_pfad = str(kandidaten[-1])
        bericht.append("Eingabe  : %s" % ddd_pfad)
        info = spesen_lib.lade_ddd(ddd_pfad)
        bericht.append("Karte    : %s (%s), %d Fahrten%s"
                       % (info["kartennummer"], info["name"],
                          len(info["touren"]),
                          ", Gen-2" if info.get("gen2") else ""))
        noetig = ("kopf_firmenlogo", "kopf_produktlogo", "tab_start",
                  "tab_kartendaten", "tab_recht", "tab_spesen",
                  "btn_karte", "btn_oeffnen", "btn_erstellen",
                  "btn_ordner", "btn_hilfe", "btn_beenden",
                  "klein_verstoss", "klein_alterung")
        vorhanden = [n for n in noetig
                     if (assets.ordner() / ("%s.png" % n)).is_file()]
        bericht.append("Grafiken : %d von %d Oberflaechen-Bildern (%s)"
                       % (len(vorhanden), len(noetig),
                          "vollstaendig" if len(vorhanden) == len(noetig)
                          else "unvollstaendig"))
        anleitung = spesen_lib.APP_DIR / "ANLEITUNG CardMaster LS.txt"
        bericht.append("Anleitung: %s (%s)"
                       % (anleitung, "vorhanden"
                          if anleitung.is_file() else "FEHLT"))
        pfad = Path(ddd_pfad)
        try:
            ende = datetime.fromtimestamp(pfad.stat().st_mtime)
        except (OSError, ValueError):
            ende = None
        tage = kartendaten.tage_auswerten(
            info.get("aktivitaet") or [], info.get("ereignisse") or [],
            info.get("stoerungen") or [], ende_am=ende)
        if tage:
            verstoesse = sum(len(t["verstoesse"]) for t in tage)
            bericht.append("Tage     : %d (%s bis %s), %d Verstoesse"
                           % (len(tage),
                              tage[0]["tag"].strftime("%d.%m.%Y"),
                              tage[-1]["tag"].strftime("%d.%m.%Y"),
                              verstoesse))
        st = spesen_lib.load_state()
        ks = st["karten"].get(info["kartennummer"], {})
        heimat = (ks.get("heimat") or {}).get("text", "")
        if heimat:
            bericht.append("Heimatort: %s (Tageszeilen)" % heimat)
        dateien = spesen_lib.erstelle_spesenzettel(
            info, ks.get("name") or info["name"],
            ks.get("abteilung", ""), ks.get("personal_nr", ""),
            log=log, heimat=heimat)
        for p in dateien:
            bericht.append("PDF      : %s (%d Byte)" % (p, p.stat().st_size))
        if not dateien:
            bericht.append("PDF      : nichts Neues (Abrechnungsstand "
                           "aktuell) – OK")
        bericht.append("ERGEBNIS : OK")
        code = 0
    except Exception as e:
        bericht.append("FEHLER   : %s" % e)
        bericht.extend("Log      : %s" % z for z in protokoll[-20:])
        bericht.append(traceback.format_exc())
        bericht.append("ERGEBNIS : FEHLER")
        code = 1
    try:
        spesen_lib.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (spesen_lib.DATA_DIR / "selbsttest.txt").write_text(
            "\n".join(bericht), encoding="utf-8")
    except OSError:
        pass
    return code


if __name__ == "__main__":
    main()
