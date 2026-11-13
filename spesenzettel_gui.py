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
        self.minsize(1080, 720)
        stil.anwenden(self)
        self._fenster_icon()
        self._oberflaeche()
        self.info = None                      # Ergebnis von spesen_lib.lade_ddd
        self.kartenstaende = spesen_lib.load_state()["karten"]
        self._orte_thread = None              # Hintergrund-Suche Ortsnamen
        self._heim = None                     # Heimatort/Wohnort (lat, lon)
        self._heim_text = ""                  # zuletzt geprüfter Heimatort-Text
        self._fern_cache = None               # zuletzt erzeugte Tageszeilen

    def _fenster_icon(self):
        """Fenster- und Taskleistensymbol (cardmaster.ico)."""
        assets.setze_fenster_icon(self)

    def _kopfleiste(self):
        """Dunkle Kopfleiste mit Firmen-/Produktlogo und Programmnamen."""
        firmen = assets.lade("kopf_firmenlogo")
        produkt = assets.lade("kopf_produktlogo")
        if firmen is None and produkt is None:
            return False

        kopf = tk.Frame(self, background=stil.NAVY)
        kopf.grid(row=0, column=0, sticky="ew")
        kopf.columnconfigure(1, weight=1)

        if firmen is not None or produkt is not None:
            platte = tk.Frame(kopf, background=stil.WEISS,
                              padx=12, pady=7)
            platte.grid(row=0, column=0, sticky="w",
                        padx=(16, 0), pady=11)
            if firmen is not None:
                tk.Label(platte, image=firmen, background=stil.WEISS,
                         borderwidth=0).pack(side="left")
            if firmen is not None and produkt is not None:
                tk.Frame(platte, background=stil.RAND, width=1).pack(
                    side="left", fill="y", padx=12, pady=3)
            if produkt is not None:
                tk.Label(platte, image=produkt, background=stil.WEISS,
                         borderwidth=0).pack(side="left")

        rechts = tk.Frame(kopf, background=stil.NAVY)
        rechts.grid(row=0, column=2, sticky="e", padx=18)
        tk.Label(rechts, text="CardMaster LS", background=stil.NAVY,
                 foreground=stil.WEISS,
                 font=(stil.SCHRIFT, 16, "bold")).pack(anchor="e")
        tk.Label(rechts,
                 text="Fahrerkarte · Spesen · Rechtsgrundlagen",
                 background=stil.NAVY, foreground="#B9C2D6",
                 font=(stil.SCHRIFT, 8)).pack(anchor="e")

        # schmale Markenlinie unter der Kopfleiste
        tk.Frame(self, background=stil.GRUEN, height=3).grid(
            row=1, column=0, sticky="ew")
        return True

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

        self.log("Bereit. Karte einstecken und „Karte auslesen“ wählen, "
                 "oder eine vorhandene .ddd-Datei öffnen.")

    def _startseite(self, rahmen):
        rahmen.columnconfigure(0, weight=1)
        rahmen.rowconfigure(6, weight=1)

        ttk.Label(rahmen, text="Fahrerkarte und Spesenzettel",
                  foreground=stil.NAVY,
                  font=(stil.SCHRIFT, 17, "bold")).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 2))
        ttk.Label(rahmen, foreground=stil.GEDAEMPFT,
                  font=stil.schrift(9),
                  text="Karte auslesen oder einen vorhandenen Karten-Download "
                       "öffnen. Daraus entstehen Kartendaten, Verstöße und "
                       "die Reisekostenabrechnung.").grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        # --- Datenquelle -------------------------------------------------
        quelle = ttk.LabelFrame(rahmen, text="Datenquelle",
                                padding=(14, 10))
        quelle.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        quelle.columnconfigure(3, weight=1)
        self.btn_karte = ttk.Button(
            quelle, text="Karte auslesen (USB-Kartenleser)",
            image=assets.lade("btn_karte"), compound="left",
            style="Akzent.TButton", command=self.karte_auslesen)
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

        self.info_var = tk.StringVar(
            value="Noch keine Daten geladen — Karte auslesen oder .ddd öffnen.")
        ttk.Label(rahmen, textvariable=self.info_var, justify="left",
                  wraplength=1000, foreground=stil.TEXT).grid(
            row=3, column=0, sticky="w", padx=16, pady=(0, 8))

        # --- Kopfdaten ----------------------------------------------------
        kopf = ttk.LabelFrame(rahmen, text="Kopfdaten für das Formular",
                              padding=(14, 10))
        kopf.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
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

        # Heimatort: ohne Angabe werden die Touren wie bisher abgerechnet.
        # Mit Heimatort entstehen Tageszeilen; Nächte außerhalb des
        # Heimatorts bekommen den 00:00-Schnitt (Fernverkehr).
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
                  font=stil.schrift(8)).grid(
            row=1, column=3, columnspan=3, sticky="w", padx=(12, 0),
            pady=(6, 0))
        ttk.Label(kopf, foreground=stil.GEDAEMPFT, font=stil.schrift(8),
                  wraplength=900,
                  text="Ohne Heimatort: Touren wie bisher (Nahverkehr). "
                       "Mit Heimatort: eine Zeile je Tag; hat der Lkw "
                       "nachts nicht am Heimatort gestanden, wird der Tag "
                       "um 00:00 geteilt (Fernverkehr).").grid(
            row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))

        # --- Speicherorte -------------------------------------------------
        # Standard bleibt Dokumente\CardMaster LS; .ddd-Downloads und
        # Spesenzettel-PDFs koennen getrennt umgestellt werden.
        orte = ttk.LabelFrame(rahmen, text="Speicherorte",
                              padding=(14, 10))
        orte.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 8))
        orte.columnconfigure(1, weight=1)
        self.ddd_ordner_var = tk.StringVar()
        self.pdf_ordner_var = tk.StringVar()
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
        ttk.Label(orte, foreground=stil.GEDAEMPFT, font=stil.schrift(8),
                  text="Abrechnungsstand, Ortscache und Einstellungen "
                       "bleiben im Datenordner Dokumente\\CardMaster LS."
                  ).grid(row=2, column=0, columnspan=4, sticky="w",
                         pady=(5, 0))
        self._ordner_anzeigen()

        # --- Übersicht und Wechsel zu den Ansichten ----------------------
        unten = ttk.Frame(rahmen)
        unten.grid(row=6, column=0, sticky="nsew", padx=16)
        unten.columnconfigure(0, weight=1)
        unten.rowconfigure(1, weight=1)

        uebersicht = ttk.LabelFrame(unten, text="Übersicht",
                                    padding=(14, 10))
        uebersicht.grid(row=0, column=0, sticky="nsew", padx=(0, 8),
                        pady=(0, 8))
        self.uebersicht_var = tk.StringVar(
            value="Noch keine Karte geladen.")
        ttk.Label(uebersicht, textvariable=self.uebersicht_var,
                  justify="left", wraplength=520,
                  font=stil.schrift(9)).grid(
            row=0, column=0, sticky="w")

        wechsel = ttk.LabelFrame(unten, text="Ansicht wechseln",
                                 padding=(14, 10))
        wechsel.grid(row=0, column=1, sticky="ne", pady=(0, 8))
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
        proto = ttk.LabelFrame(unten, text="Protokoll", padding=(8, 6))
        proto.grid(row=1, column=0, columnspan=2, sticky="nsew")
        proto.columnconfigure(0, weight=1)
        proto.rowconfigure(0, weight=1)
        unten.rowconfigure(1, weight=1)
        self.log_text = tk.Text(
            proto, height=5, state="disabled", wrap="word",
            font=(stil.SCHRIFT_FEST, 9), background=stil.PANEL,
            foreground=stil.TEXT, relief="flat", borderwidth=0,
            padx=10, pady=8, insertbackground=stil.NAVY,
            selectbackground=stil.AUSWAHL, selectforeground=stil.ROT_DUNKEL)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_balken = ttk.Scrollbar(proto, orient="vertical",
                                   command=self.log_text.yview)
        log_balken.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_balken.set)

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
                  font=(stil.SCHRIFT, 15, "bold")).grid(row=0, column=0,
                                                       sticky="w")
        ttk.Button(kopf, text="Zur Startseite",
                   command=lambda: self.notiz.select(self.tab_start)).grid(
            row=0, column=1, sticky="e")
        self.spesen_info_var = tk.StringVar(
            value="Datenquelle und Kopfdaten auf der Startseite. "
                  "Zeitraum je Blatt: 16. bis 15. des Folgemonats.")
        ttk.Label(rahmen, textvariable=self.spesen_info_var,
                  foreground=stil.GEDAEMPFT, font=stil.schrift(9),
                  wraplength=980).grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 8))

        # --- Fahrten ------------------------------------------------------
        fahrten = ttk.LabelFrame(rahmen, text="Noch nicht abgerechnete Fahrten",
                                 padding=(14, 10))
        fahrten.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        fahrten.columnconfigure(0, weight=1)
        fahrten.rowconfigure(0, weight=1)
        self.fahrten_frame = fahrten

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
        self.tree.grid(row=0, column=0, sticky="nsew")
        balken = ttk.Scrollbar(fahrten, orient="vertical",
                               command=self.tree.yview)
        balken.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=balken.set)

        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            fahrten,
            text="Abrechnungsstand ignorieren — alle gespeicherten Fahrten "
                 "neu erstellen (Ergänzungsblatt)",
            variable=self.force_var,
            command=self._tabelle_aktualisieren).grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.summe_var = tk.StringVar(value="")
        ttk.Label(fahrten, textvariable=self.summe_var).grid(
            row=2, column=0, sticky="w")

        # --- Aktionen -----------------------------------------------------
        aktion = ttk.Frame(rahmen)
        aktion.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.btn_erstellen = ttk.Button(
            aktion, text="Spesenzettel erstellen (PDF)",
            image=assets.lade("btn_erstellen"), compound="left",
            style="Akzent.TButton", command=self.erstellen, state="disabled")
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
                  foreground=stil.GEDAEMPFT, font=stil.schrift(8)).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(5, 0))
        self._ordner_anzeigen()

    # ------------------------------------------------------------ Protokoll

    def log(self, text):
        try:
            self.after(0, self._log_einfuegen, str(text))
        except RuntimeError:
            pass

    def _log_einfuegen(self, text):
        zeit = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "[%s] %s\n" % (zeit, text))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # --------------------------------------------------------- Datenquelle

    def _busy(self, an, text=""):
        zustand = "disabled" if an else "!disabled"
        self.btn_karte.state([zustand])
        self.btn_ddd.state([zustand])
        self.btn_heim.state([zustand])
        self.btn_erstellen.state(
            ["disabled"] if an or not self._anzeige() else ["!disabled"])
        if text:
            self.log(text)

    def karte_auslesen(self):
        self._busy(True, "Karte wird ausgelesen — bitte warten …")
        threading.Thread(target=self._karte_lesen, daemon=True).start()

    def _karte_lesen(self):
        """Fahrerkarte im Hintergrund auslesen (blocking, eigener Thread)."""
        try:
            from smartcard.System import readers
            if not readers():
                raise RuntimeError(
                    "Kein Kartenleser gefunden. USB-Leser anschließen und "
                    "Karte einstecken.")

            protokoll = io.StringIO()
            with contextlib.redirect_stdout(protokoll):
                karte = fahrerkarte.oeffne_karte()
                try:
                    bloecke, meta = fahrerkarte.download(karte)
                    # Gen-2-Anwendung (GNSS-Orte) mit auslesen; scheitert
                    # sie, bleibt der Download als Gen-1-Datei gültig.
                    fahrerkarte.download_g2(karte, bloecke, meta)
                finally:
                    karte.close()
                ident = fahrerkarte.parse_identification(meta["ident_raw"])
                ddd = fahrerkarte.build_ddd(bloecke)

            self.log("Kartenleser: %s" % karte.reader)
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
        self._fern_cache = None
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
        """Kurzstatistik auf der Startseite."""
        if not self.info:
            self.uebersicht_var.set("Noch keine Karte geladen.")
            return
        info = self.info
        zeilen = ["Fahrer: %s · Karte %s"
                  % (info.get("name", "?"),
                     info.get("kartennummer", "?"))]
        tage = self.tab_karten._tage
        if tage:
            verstoesse = sum(len(t["verstoesse"]) for t in tage)
            hinweise = sum(1 for t in tage for m in t["meldungen"]
                           if m["art"] == "Hinweis")
            zeilen.append(
                "Kartendaten: %d Tage (%s – %s) · %d Verstöße · %d Hinweise"
                % (len(tage), tage[0]["tag"].strftime("%d.%m.%Y"),
                   tage[-1]["tag"].strftime("%d.%m.%Y"),
                   verstoesse, hinweise))
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
        self.uebersicht_var.set("\n".join(zeilen))
        self.spesen_info_var.set(
            "Karte %s — %s · Datenquelle und Kopfdaten auf der Startseite."
            % (info.get("kartennummer", "?"), info.get("name", "")))

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
                        self._heim_text, self._heim, log=self.log))
            except Exception as e:
                self.log("FEHLER bei den Tageszeilen: %s" % e)
                self._fern_cache = []
        return self._fern_cache

    def _anzeige(self):
        if not self.info:
            return []
        if self._heim is not None:
            zeilen = list(self._tageszeilen())
        else:
            zeilen = list(self.info["touren"])
        letzte = self.kartenstaende.get(
            self.info["kartennummer"], {}).get("letzte_zeile")
        if self.force_var.get() or not letzte:
            return zeilen
        return spesen_lib.leere_raender_entfernen(
            spesen_lib.neue_fahrten(zeilen, letzte))

    def heimat_pruefen(self):
        """Heimatort (Wohnort) in Koordinaten übersetzen (im Hintergrund)."""
        text = self.heimat_var.get().strip()
        if not text:
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
        self.heim_var.set("„%s“ nicht ermittelbar: %s" % (text, meldung))
        self.log("FEHLER beim Prüfen des Heimatorts: %s" % meldung)

    def _tabelle_aktualisieren(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        zeilen = self._anzeige()
        nr = 0
        for t in zeilen:
            if t.get("leer"):
                self.tree.insert("", "end", values=(
                    "", "", "", "", "", "", "", "", ""))
                continue
            nr += 1
            self.tree.insert("", "end", values=(
                nr, spesen_lib._fmt(t["tag"]), t["beginn"], t["ende"],
                t["dauer"], t["km"],
                spesen_lib.ortstext(t, "start"),
                spesen_lib.ortstext(t, "ziel"),
                t.get("fahrzeug", "")))
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
        if self._heim is not None and self.force_var.get():
            perioden = sorted({spesen_lib.abrechnungsperiode(t["tag"])
                               for t in self._tageszeilen()})
            if len(perioden) > 1 and not messagebox.askyesno(
                    "Ergänzungsblätter",
                    "Der Abrechnungsstand wird ignoriert. Es würden %d "
                    "Blätter erstellt:\n\n%s\n\nFortsetzen?"
                    % (len(perioden), "\n".join(
                        "• %s – %s" % (spesen_lib._fmt(von),
                                      spesen_lib._fmt(bis))
                        for von, bis in perioden))):
                return
        try:
            dateien = spesen_lib.erstelle_spesenzettel(
                self.info, name, abteilung, personal_nr,
                force=self.force_var.get(), log=self.log,
                heimat=self._heim_text)
        except Exception as e:
            self.log("FEHLER beim Erstellen: %s" % e)
            self.log(traceback.format_exc())
            messagebox.showerror("Spesenzettel erstellen", str(e))
            return
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
    app = App()
    app.mainloop()


def _selbsttest(ddd_pfad):
    """Ohne Fenster laufen lassen (fuer Pruefung der installierten .exe).

    Schreibt das Ergebnis nach Dokumente/CardMaster LS/selbsttest.txt.
    """
    bericht = ["Selbsttest %s" % datetime.now().isoformat(timespec="seconds"),
               "Programm : %s" % sys.executable,
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
