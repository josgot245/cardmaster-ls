# -*- coding: utf-8 -*-
"""Ansicht „Kartendaten“: Tagesgrafik, Kreisdiagramm und Verstöße.

Links die Liste aller Tage der Fahrerkarte, rechts der gewählte Tag:
  * 24-Stunden-Balken mit Ruhe/Bereitschaft/Arbeit/Fahrt
  * Kreisdiagramm der Zeitanteile
  * Verstöße, Hinweise, Ereignisse und Störungen des Tages
"""
import math
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import assets
import kartendaten
import spesen_daten
import stil

# Neutrales Dunkelgrau für Beschriftungen in den Diagrammen – ersetzt das
# Marken-Navy, das dort zu blau wirkte.
GRAPHIT = "#3B3F45"

# „Unbekannt“ (noch nicht ausgelesene Zeit) wird hell dargestellt und mit
# roten Schrägstrichen schraffiert – so bleibt der Rest neutral und die
# Lücke ist trotzdem deutlich zu erkennen.
UNBEKANNT = "#E6E9EE"
SCHRAFFUR = "#B91D21"


def _winkel_drin(w, lo, hi):
    """Prüfen, ob der Winkel w im Bereich lo..hi (Grad) liegt."""
    if hi - lo >= 359.999:
        return True
    while w < lo:
        w += 360.0
    while w >= lo + 360.0:
        w -= 360.0
    return w <= hi


def _schraffiere_rechteck(c, x1, y1, x2, y2, abstand=5, farbe=SCHRAFFUR,
                          breite=1, tags=None):
    """Rechteck mit diagonalen Linien (y = x + c) schraffieren."""
    for c0 in range(int(y1 - x2) - abstand, int(y2 - x1) + abstand + 1, abstand):
        xa = max(x1, y1 - c0)
        xb = min(x2, y2 - c0)
        if xb - xa < 1:
            continue
        c.create_line(xa, xa + c0, xb, xb + c0, fill=farbe, width=breite,
                      tags=tags)


def _schraffiere_bogen(c, cx, cy, r_aussen, ring, start, extent,
                       abstand=5, farbe=SCHRAFFUR, breite=1):
    """Ringsegment (Kreisbogen) mit diagonalen Linien schraffieren."""
    r_innen = r_aussen - ring
    lo, hi = (start, start + extent) if extent >= 0 else (start + extent, start)
    x_min, x_max = cx - r_aussen, cx + r_aussen
    y_min, y_max = cy - r_aussen, cy + r_aussen
    schritt = 2.0
    c_start = int(y_min - x_max) - abstand
    c_ende = int(y_max - x_min) + abstand
    for c0 in range(c_start, c_ende + 1, abstand):
        lauf = []
        x = x_min
        while x <= x_max:
            y = x + c0
            drin = False
            if y_min <= y <= y_max:
                dx, dy = x - cx, y - cy
                r = math.hypot(dx, dy)
                if r_innen <= r <= r_aussen:
                    drin = _winkel_drin(math.degrees(math.atan2(-dy, dx)),
                                        lo, hi)
            if drin:
                lauf.append((x, y))
            elif lauf:
                c.create_line(lauf[0][0], lauf[0][1], lauf[-1][0], lauf[-1][1],
                              fill=farbe, width=breite)
                lauf = []
            x += schritt
        if lauf:
            c.create_line(lauf[0][0], lauf[0][1], lauf[-1][0], lauf[-1][1],
                          fill=farbe, width=breite)


# --------------------------------------------------------- Zeilen des Tages
# Eine Zeile je Tätigkeit, links das offizielle Piktogramm nach
# VO (EU) 2016/799, Anhang I C, Anlage 3 (VDO/DTCO): Lenkrad, gekreuzte
# Hämmer, Quadrat mit Diagonale, Bett, Fragezeichen. Reihenfolge wie im
# VDO-Menü und auf der Vorlage: Lenkzeit – Arbeit – Bereitschaft – Ruhe.
# Der dritte Wert ist die Aktivitätsart im Minutenprofil
# (0 Ruhe, 1 Bereitschaft, 2 Arbeit, 3 Fahrt, -1 unbekannt).
ZEIT_ZEILEN = (
    ("Fahrt", "Fahrtzeit", 3),
    ("Arbeit", "Arbeitszeit", 2),
    ("Bereitschaft", "Bereitschaftszeit", 1),
    ("Ruhe", "Ruhezeit", 0),
    ("Unbekannt", "Unbekannt", kartendaten.UNBEKANNT),
)


def _dauer(minuten):
    """Dauer in Minuten als '1h36min' bzw. '45min'."""
    minuten = int(round(minuten))
    h, m = divmod(minuten, 60)
    if h and m:
        return "%dh%02dmin" % (h, m)
    if h:
        return "%dh" % h
    return "%dmin" % m


def _symbol_lenkrad(c, cx, cy, r, farbe):
    """Lenkrad – Tätigkeit „Fahrt“."""
    c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=farbe, width=2)
    c.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=farbe, outline=farbe)
    c.create_line(cx, cy, cx - r + 1, cy, fill=farbe, width=2)
    c.create_line(cx, cy, cx + r - 1, cy, fill=farbe, width=2)
    c.create_line(cx, cy, cx, cy + r - 1, fill=farbe, width=2)


def _symbol_haemmer(c, cx, cy, r, farbe):
    """Gekreuzte Hämmer – Tätigkeit „Arbeit“."""
    c.create_line(cx - 0.9 * r, cy + 0.9 * r, cx + 0.5 * r, cy - 0.5 * r,
                  fill=farbe, width=2)
    c.create_line(cx + 0.9 * r, cy + 0.9 * r, cx - 0.5 * r, cy - 0.5 * r,
                  fill=farbe, width=2)
    c.create_line(cx + 0.25 * r, cy - r, cx + r, cy - 0.25 * r,
                  fill=farbe, width=3)
    c.create_line(cx - 0.25 * r, cy - r, cx - r, cy - 0.25 * r,
                  fill=farbe, width=3)


def _symbol_bereitschaft(c, cx, cy, r, farbe):
    """Quadrat mit Diagonale – Tätigkeit „Bereitschaft“."""
    s = 0.85 * r
    c.create_rectangle(cx - s, cy - s, cx + s, cy + s,
                       outline=farbe, width=2)
    c.create_line(cx - s, cy + s, cx + s, cy - s, fill=farbe, width=2)


def _symbol_bett(c, cx, cy, r, farbe):
    """Bett – Tätigkeit „Ruhe“."""
    # Kopfende
    c.create_line(cx - r, cy - 0.9 * r, cx - r, cy + 0.8 * r,
                  fill=farbe, width=2)
    # Liegefläche
    c.create_line(cx - r, cy + 0.8 * r, cx + r, cy + 0.8 * r,
                  fill=farbe, width=2)
    # Fußende
    c.create_line(cx + r, cy + 0.8 * r, cx + r, cy + 0.1 * r,
                  fill=farbe, width=2)
    # Kissen
    c.create_rectangle(cx - 0.75 * r, cy - 0.5 * r,
                       cx - 0.1 * r, cy + 0.1 * r,
                       fill=farbe, outline=farbe)


def _symbol_frage(c, cx, cy, farbe, schrift):
    """Fragezeichen – noch nicht ausgelesene Zeit („Unbekannt“)."""
    c.create_text(cx, cy, text="?", fill=farbe, font=schrift)


class KartendatenTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=(16, 14))
        self._tage = []
        self._je_tag = {}
        self._auswahl = None
        self._info = None
        self._hover_id = None
        self._zeit_geo = None

        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # --- Kopf ---------------------------------------------------------
        kopf = ttk.Frame(self)
        kopf.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        kopf.columnconfigure(0, weight=1)
        self.kopf_var = tk.StringVar(
            value="Noch keine Karte geladen — Karte auslesen oder .ddd öffnen.")
        ttk.Label(kopf, textvariable=self.kopf_var,
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_UNTERTITEL, True)).grid(
            row=0, column=0, sticky="w")
        self.hinweis_var = tk.StringVar(value="")
        ttk.Label(kopf, textvariable=self.hinweis_var,
                  foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN)).grid(row=1, column=0, sticky="w")

        # --- Tagesliste ---------------------------------------------------
        links_karte = stil.Karte(self, titel="Tage", padding=(10, 8))
        links_karte.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        links = links_karte.innen
        links.rowconfigure(0, weight=1)
        links.columnconfigure(0, weight=1)
        spalten = (("datum", "Datum", 112, "w"),
                   ("lenk", "Fahrt", 52, "e"),
                   ("arbeit", "Arbeit", 52, "e"),
                   ("ruhe", "Ruhe", 52, "e"),
                   ("km", "km", 52, "e"),
                   ("v", "V", 28, "center"))
        self.tage_tree = ttk.Treeview(
            links, show="headings", selectmode="browse", height=22,
            columns=[s[0] for s in spalten])
        for sid, titel, breite, anker in spalten:
            self.tage_tree.heading(sid, text=titel)
            self.tage_tree.column(sid, width=breite, anchor=anker,
                                  stretch=(sid == "datum"))
        self.tage_tree.grid(row=0, column=0, sticky="nsew")
        balken = ttk.Scrollbar(links, orient="vertical",
                               command=self.tage_tree.yview)
        balken.grid(row=0, column=1, sticky="ns")
        self.tage_tree.configure(yscrollcommand=balken.set)
        self.tage_tree.bind("<<TreeviewSelect>>", self._tag_gewaehlt)
        self.tage_tree.tag_configure("warn", foreground=stil.ROT)
        self.tage_tree.tag_configure("unvoll", foreground=stil.GRAU)
        stil.zebra_konfigurieren(self.tage_tree)

        # --- rechte Seite --------------------------------------------------
        rechts = ttk.Frame(self)
        rechts.grid(row=1, column=1, sticky="nsew")
        rechts.columnconfigure(0, weight=1)
        rechts.rowconfigure(4, weight=1)

        kopf_rechts = ttk.Frame(rechts)
        kopf_rechts.grid(row=0, column=0, sticky="ew")
        kopf_rechts.columnconfigure(0, weight=1)
        self.tag_var = tk.StringVar(value="")
        ttk.Label(kopf_rechts, textvariable=self.tag_var,
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_UNTERTITEL, True)).grid(row=0, column=0,
                                                       sticky="w")
        self.gesamt_var = tk.StringVar(value="")
        ttk.Label(kopf_rechts, textvariable=self.gesamt_var,
                  foreground=stil.ROT,
                  font=stil.schrift(stil.PT_GROSS, True)).grid(row=0, column=1,
                                                       sticky="e")
        self.summe_var = tk.StringVar(value="")
        ttk.Label(rechts, textvariable=self.summe_var,
                  foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_TEXT)).grid(row=1, column=0, sticky="w",
                                             pady=(0, 6))

        self.zeit_canvas = tk.Canvas(rechts, height=172, highlightthickness=0,
                                     background=stil.WEISS)
        self.zeit_canvas.grid(row=2, column=0, sticky="ew")
        self.zeit_canvas.bind("<Configure>", lambda e: self._zeichne_zeit())
        self.zeit_canvas.bind("<Motion>", self._hover)
        self.zeit_canvas.bind("<Leave>", lambda e: self._hover_loeschen())

        self.kreis_canvas = tk.Canvas(rechts, height=228, highlightthickness=0,
                                      background=stil.WEISS)
        self.kreis_canvas.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        self.kreis_canvas.bind("<Configure>", lambda e: self._zeichne_kreis())

        meld_karte = stil.Karte(rechts, titel="", padding=(10, 8))
        meld_karte.grid(row=4, column=0, sticky="nsew")
        meld = meld_karte.innen
        meld.rowconfigure(1, weight=1)
        meld.columnconfigure(0, weight=1)

        meld_kopf = ttk.Frame(meld)
        meld_kopf.grid(row=0, column=0, columnspan=2, sticky="w",
                       pady=(2, 4))
        bild_verstoss = assets.lade("klein_verstoss")
        if bild_verstoss is not None:
            ttk.Label(meld_kopf, image=bild_verstoss).pack(side="left",
                                                           padx=(0, 4))
        ttk.Label(meld_kopf, text="Verstöße und Ereignisse",
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_ABSCHNITT, True)).pack(side="left")

        self.meld_tree = ttk.Treeview(
            meld, show="headings", height=7,
            columns=("zeit", "art", "text", "recht"))
        for sid, titel, breite, anker in (("zeit", "Zeit", 58, "center"),
                                          ("art", "Art", 72, "w"),
                                          ("text", "Beschreibung", 400, "w"),
                                          ("recht", "Rechtsgrundlage", 210, "w")):
            self.meld_tree.heading(sid, text=titel)
            self.meld_tree.column(sid, width=breite, anchor=anker,
                                  stretch=(sid == "text"))
        self.meld_tree.grid(row=1, column=0, sticky="nsew")
        mbalken = ttk.Scrollbar(meld, orient="vertical",
                                command=self.meld_tree.yview)
        mbalken.grid(row=1, column=1, sticky="ns")
        self.meld_tree.configure(yscrollcommand=mbalken.set)
        self.meld_tree.tag_configure("rot", foreground=stil.ROT)
        self.meld_tree.tag_configure("gelb", foreground="#8A5A00")
        self.meld_tree.tag_configure("info", foreground=stil.GEDAEMPFT)
        self.meld_tree.tag_configure("ok", foreground="#2E6B2E")
        stil.zebra_konfigurieren(self.meld_tree)

    # ------------------------------------------------------------------ Daten

    def setze_info(self, info):
        """Karte geladen: Tage auswerten und Liste füllen."""
        self._info = info
        ende = None
        pfad = info.get("pfad")
        if pfad:
            try:
                ende = datetime.fromtimestamp(Path(pfad).stat().st_mtime)
            except (OSError, ValueError):
                ende = None
        self._tage = kartendaten.tage_auswerten(
            info.get("aktivitaet") or [],
            info.get("ereignisse") or [],
            info.get("stoerungen") or [],
            ende_am=ende)
        self._je_tag = {t["tag"]: t for t in self._tage}
        info["tage"] = self._tage

        for iid in self.tage_tree.get_children():
            self.tage_tree.delete(iid)

        if not self._tage:
            self.kopf_var.set("Karte %s — %s"
                              % (info.get("kartennummer", "?"),
                                 info.get("name", "")))
            self.hinweis_var.set("Auf der Karte sind keine Tagesaktivitäten "
                                 "gespeichert.")
            self._anzeige_leeren()
            return

        von, bis = self._tage[0]["tag"], self._tage[-1]["tag"]
        self.kopf_var.set(
            "Karte %s — %s · %d Tage (%s – %s)"
            % (info.get("kartennummer", "?"), info.get("name", ""),
               len(self._tage), von.strftime("%d.%m.%Y"),
               bis.strftime("%d.%m.%Y")))
        teile = []
        if info.get("gen2"):
            teile.append("Generation 2 (GNSS-Orte)")
        if info.get("fahrzeuge"):
            teile.append("Fahrzeuge: %s" % ", ".join(info["fahrzeuge"]))
        if info.get("letzter_download"):
            teile.append("letzter Download: %s"
                         % info["letzter_download"]
                         .astimezone(spesen_daten.BERLIN)
                         .strftime("%d.%m.%Y %H:%M"))
        self.hinweis_var.set(" · ".join(teile))

        neuester = None
        for position, t in enumerate(reversed(self._tage), start=1):
            s = t["summen"]
            unvoll = s["unbekannt"] > 0
            datum = "%s %s" % (kartendaten.WOCHENTAGE[t["tag"].weekday()],
                               t["tag"].strftime("%d.%m.%Y"))
            if unvoll:
                datum += " *"
            iid = t["tag"].isoformat()
            tags = stil.zebra_tags(position)
            if t["verstoesse"]:
                tags.append("warn")
            elif unvoll:
                tags.append("unvoll")
            self.tage_tree.insert(
                "", "end", iid=iid,
                values=(datum, kartendaten.hmm(s["lenk"]),
                        kartendaten.hmm(s["arbeit"]),
                        kartendaten.hmm(s["ruhe"]), t["km"],
                        len(t["verstoesse"]) or ""),
                tags=tags)
            if neuester is None:
                neuester = iid

        if neuester is not None:
            self.tage_tree.selection_set(neuester)
            self.tage_tree.focus(neuester)
            self.tage_tree.see(neuester)
            self._tag_gewaehlt()

    def _anzeige_leeren(self):
        self._auswahl = None
        self.tag_var.set("")
        self.gesamt_var.set("")
        self.summe_var.set("")
        self.zeit_canvas.delete("all")
        self.kreis_canvas.delete("all")
        for iid in self.meld_tree.get_children():
            self.meld_tree.delete(iid)

    # ------------------------------------------------------------- Auswahl

    def _tag_gewaehlt(self, _event=None):
        auswahl = self.tage_tree.selection()
        if not auswahl:
            return
        tag = date.fromisoformat(auswahl[0])
        t = self._je_tag.get(tag)
        if t is None:
            return
        self._auswahl = t

        self.tag_var.set(
            "%s, %s"
            % (kartendaten.WOCHENTAGE[tag.weekday()],
               tag.strftime("%d.%m.%Y")))
        s = t["summen"]
        self.gesamt_var.set("Gesamtarbeitszeit %s h"
                            % kartendaten.hmm(s["arbeitszeit"]))
        teile = [
            "Fahrt %s" % kartendaten.hmm(s["lenk"]),
            "Arbeit %s" % kartendaten.hmm(s["arbeit"]),
            "Bereitschaft %s" % kartendaten.hmm(s["bereit"]),
            "Ruhe %s" % kartendaten.hmm(s["ruhe"]),
        ]
        if s["unbekannt"]:
            teile.append("unbekannt %s" % kartendaten.hmm(s["unbekannt"]))
        teile.append("%d km" % t["km"])
        self.summe_var.set(" · ".join(teile))

        self._zeichne_zeit()
        self._zeichne_kreis()
        self._fuelle_meldungen()

    # ------------------------------------------------------------- Zeichnen

    @staticmethod
    def _laeufe(profil):
        """Minutenprofil in Abschnitte (von, bis, art) umwandeln."""
        laeufe = []
        start = 0
        art = profil[0]
        for i in range(1, len(profil)):
            if profil[i] != art:
                laeufe.append((start, i, art))
                start, art = i, profil[i]
        laeufe.append((start, len(profil), art))
        return laeufe

    def _zeichne_zeit(self):
        c = self.zeit_canvas
        c.delete("all")
        self._hover_id = None
        self._zeit_geo = None
        if self._auswahl is None:
            return

        s = self._auswahl["summen"]
        profil = self._auswahl["profil"]

        # Aufbau wie auf der Vorlage: Zeitangaben oben, darunter eine Zeile
        # je Tätigkeit. Links steht in jeder Zeile ein Symbol, daneben der
        # Name. Symbolspalte und Raster überschneiden sich nicht.
        links = 14
        titel_y = 13
        kopf_y = 30                 # Zeitangaben über dem Raster
        y0 = 46                     # Oberkante des Rasters
        zeilen_hoehe = 21
        anzahl = len(ZEIT_ZEILEN)
        y_ende = y0 + zeilen_hoehe * anzahl

        schrift_name = tkfont.Font(font=stil.schrift(stil.PT_KLEIN))
        symbol_breite = 22
        name_breite = max(schrift_name.measure(n) for n, _z, _a in ZEIT_ZEILEN)
        gitter_links = links + symbol_breite + 6 + name_breite + 12
        breite = max(200, c.winfo_width() - gitter_links - 24)
        rechts = gitter_links + breite

        # Überschrift der Grafik
        c.create_text(links, titel_y, anchor="w", text="Tagesverlauf",
                      font=stil.schrift(stil.PT_KLEIN, True), fill=GRAPHIT)

        # Hintergrund des Rasters
        c.create_rectangle(gitter_links, y0, rechts, y_ende,
                           fill="#F6F8FB", outline="")

        # Halbstundenlinien (hell) und Stundenlinien (kräftiger)
        for halb in range(1, 48, 2):
            x = gitter_links + breite * halb / 48.0
            c.create_line(x, y0, x, y_ende, fill="#EEF1F6")
        for stunde in range(0, 25):
            x = gitter_links + breite * stunde / 24.0
            if 0 < stunde < 24:
                c.create_line(x, y0, x, y_ende, fill="#E1E5ED")
            if stunde % 2 == 0:
                c.create_line(x, y0 - 4, x, y0, fill="#C9D0DC")
                text = "24:00" if stunde == 24 else "%02d:00" % stunde
                c.create_text(x, kopf_y, text=text,
                              font=stil.schrift(stil.PT_MINI),
                              fill=stil.GEDAEMPFT)

        # Zeilentrenner
        for i in range(anzahl + 1):
            y = y0 + i * zeilen_hoehe
            c.create_line(gitter_links, y, rechts, y, fill="#E4E8F0")

        # Balken je Tätigkeit in der eigenen Zeile
        for i, (_name, _zeit, art) in enumerate(ZEIT_ZEILEN):
            farbe = UNBEKANNT if art < 0 else kartendaten.FARBEN[art]
            ry0 = y0 + i * zeilen_hoehe + 3
            ry1 = y0 + (i + 1) * zeilen_hoehe - 3
            for von, bis, lauf_art in self._laeufe(profil):
                if lauf_art != art:
                    continue
                x1 = gitter_links + breite * von / 1440.0
                x2 = gitter_links + breite * bis / 1440.0
                if x2 - x1 < 0.6:
                    continue
                c.create_rectangle(x1, ry0, x2, ry1, fill=farbe,
                                   outline=stil.WEISS, width=1)
                if art < 0 and x2 - x1 > 4:
                    _schraffiere_rechteck(c, x1 + 1, ry0 + 1,
                                          x2 - 1, ry1 - 1, abstand=4)

        # Symbole und Namen in der linken Spalte
        for i, (name, _zeit, art) in enumerate(ZEIT_ZEILEN):
            cy = y0 + i * zeilen_hoehe + zeilen_hoehe / 2.0
            cx = links + symbol_breite / 2.0
            if art == 3:
                _symbol_lenkrad(c, cx, cy, 6, GRAPHIT)
            elif art == 2:
                _symbol_haemmer(c, cx, cy, 6, GRAPHIT)
            elif art == 1:
                _symbol_bereitschaft(c, cx, cy, 6, GRAPHIT)
            elif art == 0:
                _symbol_bett(c, cx, cy, 6, GRAPHIT)
            else:
                _symbol_frage(c, cx, cy, GRAPHIT,
                              stil.schrift(stil.PT_KLEIN, True))
            c.create_text(links + symbol_breite + 6, cy, anchor="w",
                          text=name, font=stil.schrift(stil.PT_KLEIN),
                          fill=stil.GEDAEMPFT)

        # Verstöße als rote Dreiecke über dem Raster
        for m in self._auswahl["verstoesse"]:
            if not m.get("zeit"):
                continue
            try:
                h, mi = m["zeit"].split(":")
                minute = int(h) * 60 + int(mi)
            except ValueError:
                continue
            x = gitter_links + breite * minute / 1440.0
            c.create_polygon(x, y0 - 1, x - 4, y0 - 8, x + 4, y0 - 8,
                             fill=stil.ROT, outline=stil.WEISS, width=1)

        c.create_rectangle(gitter_links, y0, rechts, y_ende, outline=stil.RAND)

        if s["unbekannt"]:
            c.create_text(rechts, y_ende + 12, anchor="e",
                          text="* nach dem letzten Auslesen unbekannt",
                          font=stil.schrift(stil.PT_MINI), fill=stil.GRAU)

        # Geometrie für die Hover-Abfrage merken
        self._zeit_geo = {
            "links": gitter_links, "breite": breite, "y0": y0,
            "zeilen_hoehe": zeilen_hoehe, "anzahl": anzahl,
        }

    def _hover(self, event):
        c = self.zeit_canvas
        geo = self._zeit_geo
        if self._auswahl is None or geo is None:
            return
        links, breite = geo["links"], geo["breite"]
        y0, zh, anzahl = geo["y0"], geo["zeilen_hoehe"], geo["anzahl"]

        x = event.x - links
        y = event.y - y0
        reihe = int(y // zh) if y >= 0 else -1
        if x < 0 or x > breite or reihe < 0 or reihe >= anzahl:
            self._hover_loeschen()
            return

        wert = ZEIT_ZEILEN[reihe][2]
        profil = self._auswahl["profil"]
        minute = min(1439, max(0, int(x / breite * 1440)))
        if profil[minute] != wert:
            self._hover_loeschen()
            return

        start = minute
        while start > 0 and profil[start - 1] == wert:
            start -= 1
        ende = minute + 1
        while ende < 1440 and profil[ende] == wert:
            ende += 1

        c.delete("hover")

        # Führungslinie über alle Zeilen und hervorgehobener Balken
        xp = links + breite * minute / 1440.0
        c.create_line(xp, y0, xp, y0 + zh * anzahl, fill=GRAPHIT,
                      dash=(2, 2), tags="hover")
        rx1 = links + breite * start / 1440.0
        rx2 = links + breite * ende / 1440.0
        ry0 = y0 + reihe * zh + 3
        ry1 = y0 + (reihe + 1) * zh - 3
        c.create_rectangle(rx1, ry0, rx2, ry1, outline=GRAPHIT, width=2,
                           tags="hover")

        # Infofeld zum Block, z. B. „Fahrtzeit 1h36min“
        _name, bezeichnung, _art = ZEIT_ZEILEN[reihe]
        zeile1 = "%s %s" % (bezeichnung, _dauer(ende - start))
        ende_text = "24:00" if ende >= 1440 else kartendaten.uhr(ende)
        zeile2 = "%s–%s Uhr" % (kartendaten.uhr(start), ende_text)

        schrift_fett = tkfont.Font(font=stil.schrift(stil.PT_KLEIN, True))
        schrift_kl = tkfont.Font(font=stil.schrift(stil.PT_MINI))
        bw = max(schrift_fett.measure(zeile1),
                 schrift_kl.measure(zeile2)) + 16
        bh = 32
        tx = event.x + 14
        if tx + bw > c.winfo_width() - 4:
            tx = event.x - bw - 14
        tx = max(4, tx)
        ty = event.y + 14
        if ty + bh > c.winfo_height() - 4:
            ty = event.y - bh - 14
        ty = max(4, ty)
        c.create_rectangle(tx, ty, tx + bw, ty + bh, fill=stil.WEISS,
                           outline=GRAPHIT, width=1, tags="hover")
        c.create_text(tx + 8, ty + 7, anchor="nw", text=zeile1,
                      font=stil.schrift(stil.PT_KLEIN, True), fill=GRAPHIT,
                      tags="hover")
        c.create_text(tx + 8, ty + 21, anchor="nw", text=zeile2,
                      font=stil.schrift(stil.PT_MINI), fill=stil.GEDAEMPFT,
                      tags="hover")

    def _hover_loeschen(self):
        if self._hover_id is not None:
            self.zeit_canvas.delete(self._hover_id)
            self._hover_id = None
        self.zeit_canvas.delete("hover")

    def _zeichne_kreis(self):
        c = self.kreis_canvas
        c.delete("all")
        if self._auswahl is None:
            return
        s = self._auswahl["summen"]
        werte = [(s["ruhe"], kartendaten.FARBEN[0], "Ruhe"),
                 (s["bereit"], kartendaten.FARBEN[1], "Bereitschaft"),
                 (s["arbeit"], kartendaten.FARBEN[2], "Arbeit"),
                 (s["lenk"], kartendaten.FARBEN[3], "Fahrt"),
                 (s["unbekannt"], UNBEKANNT, "Unbekannt")]

        # Ringdiagramm und Legende als eine Gruppe mittig im verfügbaren
        # Platz anordnen (der Canvas ist so breit wie die rechte Seite).
        r_aussen, ring, luecke = 96, 30, 36
        schrift = tkfont.Font(font=stil.schrift(stil.PT_TEXT))
        texte = ["%-13s %5s h   %3d %%"
                 % (name, kartendaten.hmm(wert),
                    round(100 * wert / 1440.0))
                 for wert, _farbe, name in werte]
        legende = max(schrift.measure(t) for t in texte) + 22
        breite = max(c.winfo_width(), 470)
        hoehe = max(c.winfo_height(), 228)
        gruppe = 2 * r_aussen + luecke + legende
        links = max(6, int((breite - gruppe) / 2))
        cx = links + r_aussen
        cy = int(hoehe / 2)
        r_mittel = r_aussen - ring / 2

        # Ringsegmente mit kleinen Lücken dazwischen
        winkel = 90.0
        for idx, (wert, farbe, _name) in enumerate(werte):
            if wert <= 0:
                continue
            ausdehnung = -360.0 * wert / 1440.0
            lueck = 1.8
            if abs(ausdehnung) > 3 * lueck:
                start = winkel - lueck / 2
                extent = ausdehnung + lueck
            else:
                start, extent = winkel, ausdehnung
            c.create_arc(cx - r_mittel, cy - r_mittel,
                         cx + r_mittel, cy + r_mittel,
                         start=start, extent=extent,
                         style=tk.ARC, outline=farbe, width=ring)
            if idx == 4:
                _schraffiere_bogen(c, cx, cy, r_aussen, ring, start, extent)
            winkel += ausdehnung

        # Mitte des Rings
        c.create_text(cx, cy - 9, text="24 h",
                      font=stil.schrift(stil.PT_UNTERTITEL, True),
                      fill=GRAPHIT)
        c.create_text(cx, cy + 11, text="Tagesanteile",
                      font=stil.schrift(stil.PT_MINI), fill=stil.GRAU)

        # Legende
        x = cx + r_aussen + luecke
        y = cy - 76
        for (wert, farbe, name), text in zip(werte, texte):
            c.create_rectangle(x, y, x + 14, y + 14,
                               fill=farbe, outline=stil.RAND)
            if name == "Unbekannt":
                _schraffiere_rechteck(c, x, y, x + 14, y + 14, abstand=5)
            c.create_text(x + 22, y + 7, anchor="w", text=text,
                          font=schrift, fill=stil.TEXT)
            y += 30

    def _fuelle_meldungen(self):
        for iid in self.meld_tree.get_children():
            self.meld_tree.delete(iid)
        if self._auswahl is None:
            return
        meldungen = self._auswahl["meldungen"]
        if not meldungen:
            self.meld_tree.insert(
                "", "end", values=("", "",
                                   "Keine Verstöße oder Auffälligkeiten "
                                   "an diesem Tag.", ""),
                tags=["ok"])
            return
        for nummer, m in enumerate(meldungen, start=1):
            self.meld_tree.insert(
                "", "end",
                values=(m["zeit"] or "", m["art"], m["text"],
                        m.get("recht") or ""),
                tags=stil.zebra_tags(nummer, [m["schwere"]]))


class RechtsgrundlagenTab(ttk.Frame):
    """Kennzahlen und Vorschriften für Lkw-Fahrer."""

    def __init__(self, master):
        super().__init__(master, padding=(16, 14))
        self._tage = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        kopf = ttk.Frame(self)
        kopf.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        kopf.columnconfigure(0, weight=1)
        self.kopf_var = tk.StringVar(
            value="Noch keine Karte geladen — Karte auslesen oder .ddd öffnen.")
        ttk.Label(kopf, textvariable=self.kopf_var,
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_UNTERTITEL, True)).grid(
            row=0, column=0, sticky="w")
        self.hinweis_var = tk.StringVar(value="")
        ttk.Label(kopf, textvariable=self.hinweis_var,
                  foreground=stil.GEDAEMPFT,
                  font=stil.schrift(stil.PT_KLEIN)).grid(row=1, column=0, sticky="w")

        tabelle_karte = stil.Karte(self, titel="Kennzahlen der geladenen Karte",
                                   padding=(10, 8))
        tabelle_karte.grid(row=1, column=0, sticky="nsew")
        tabelle = tabelle_karte.innen
        tabelle.rowconfigure(0, weight=1)
        tabelle.columnconfigure(0, weight=1)
        spalten = (("status", "Bewertung", 82, "center"),
                   ("name", "Prüfung", 235, "w"),
                   ("wert", "Ergebnis", 330, "w"),
                   ("grenze", "Grenzwert", 260, "w"),
                   ("recht", "Rechtsgrundlage", 235, "w"))
        self.tree = ttk.Treeview(tabelle, show="headings", height=11,
                                 columns=[s[0] for s in spalten])
        for sid, titel, breite, anker in spalten:
            self.tree.heading(sid, text=titel)
            self.tree.column(sid, width=breite, anchor=anker,
                             stretch=(sid in ("wert", "grenze")))
        self.tree.grid(row=0, column=0, sticky="nsew")
        balken = ttk.Scrollbar(tabelle, orient="vertical",
                               command=self.tree.yview)
        balken.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=balken.set)
        self.tree.tag_configure("rot", foreground=stil.ROT)
        self.tree.tag_configure("warn", foreground="#8A5A00")
        self.tree.tag_configure("ok", foreground="#2E6B2E")
        self.tree.tag_configure("info", foreground=stil.GEDAEMPFT)
        stil.zebra_konfigurieren(self.tree)

        ttk.Label(self, text="Rechtsgrundlagen und Grenzwerte",
                  foreground=stil.NAVY,
                  font=stil.schrift(stil.PT_ABSCHNITT, True)).grid(row=2, column=0,
                                                       sticky="w",
                                                       pady=(12, 4))
        text = tk.Text(self, height=10, wrap="word", relief="flat",
                       background=stil.PANEL, foreground=stil.TEXT,
                       font=stil.schrift(stil.PT_TEXT), padx=12, pady=10,
                       borderwidth=0, insertbackground=stil.NAVY,
                       selectbackground=stil.AUSWAHL,
                       selectforeground=stil.ROT_DUNKEL)
        text.grid(row=3, column=0, sticky="nsew")
        tbalken = ttk.Scrollbar(self, orient="vertical", command=text.yview)
        tbalken.grid(row=3, column=1, sticky="ns")
        text.configure(yscrollcommand=tbalken.set)
        text.tag_configure("titel", font=stil.schrift(stil.PT_ABSCHNITT, True),
                           foreground=stil.NAVY, spacing1=8, spacing3=2)
        text.tag_configure("text", spacing3=6, lmargin1=2)
        for titel, inhalt in kartendaten.RECHTSGRUNDLAGEN:
            text.insert("end", titel + "\n", "titel")
            text.insert("end", inhalt + "\n", "text")
        text.configure(state="disabled")

    def setze_info(self, info):
        """Karte geladen: Kennzahlen berechnen und anzeigen."""
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        tage = info.get("tage")
        if tage is None:
            from datetime import datetime
            from pathlib import Path

            ende = None
            pfad = info.get("pfad")
            if pfad:
                try:
                    ende = datetime.fromtimestamp(Path(pfad).stat().st_mtime)
                except (OSError, ValueError):
                    ende = None
            tage = kartendaten.tage_auswerten(
                info.get("aktivitaet") or [],
                info.get("ereignisse") or [],
                info.get("stoerungen") or [],
                ende_am=ende)
            info["tage"] = tage
        self._tage = tage

        if not tage:
            self.kopf_var.set("Karte %s — %s"
                              % (info.get("kartennummer", "?"),
                                 info.get("name", "")))
            self.hinweis_var.set("Keine Tagesaktivitäten auf der Karte.")
            return

        von, bis = tage[0]["tag"], tage[-1]["tag"]
        self.kopf_var.set(
            "Karte %s — %s · %d Tage (%s – %s)"
            % (info.get("kartennummer", "?"), info.get("name", ""),
               len(tage), von.strftime("%d.%m.%Y"), bis.strftime("%d.%m.%Y")))
        self.hinweis_var.set(
            "Berechnet aus den aufgezeichneten Aktivitäten. Zeiten außerhalb "
            "des Fahrzeugs (Pausen, andere Arbeiten) sind nicht enthalten.")

        namen = {"rot": "Verstoß", "warn": "Hinweis",
                 "ok": "in Ordnung", "info": "Info"}
        zahlen = kartendaten.kennzahlen(tage)
        for nummer, z in enumerate(zahlen, start=1):
            self.tree.insert(
                "", "end", tags=stil.zebra_tags(nummer, [z["status"]]),
                values=(namen.get(z["status"], z["status"]),
                        z["name"], z["wert"], z["grenze"],
                        z["recht"] or ""))
        if any(z["status"] == "rot" for z in zahlen):
            self.hinweis_var.set(
                self.hinweis_var.get() +
                "  Rote Zeilen bitte vor der Abrechnung prüfen.")
