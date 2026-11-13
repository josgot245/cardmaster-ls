# -*- coding: utf-8 -*-
"""Ansicht „Kartendaten“: Tagesgrafik, Kreisdiagramm und Verstöße.

Links die Liste aller Tage der Fahrerkarte, rechts der gewählte Tag:
  * 24-Stunden-Balken mit Ruhe/Bereitschaft/Arbeit/Fahrt
  * Kreisdiagramm der Zeitanteile
  * Verstöße, Hinweise, Ereignisse und Störungen des Tages
"""
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import assets
import kartendaten
import spesen_daten
import stil


class KartendatenTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=(16, 14))
        self._tage = []
        self._je_tag = {}
        self._auswahl = None
        self._info = None
        self._hover_id = None

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
                  font=(stil.SCHRIFT, 12, "bold")).grid(row=0, column=0,
                                                       sticky="w")
        self.hinweis_var = tk.StringVar(value="")
        ttk.Label(kopf, textvariable=self.hinweis_var,
                  foreground=stil.GEDAEMPFT,
                  font=stil.schrift(8)).grid(row=1, column=0, sticky="w")

        # --- Tagesliste ---------------------------------------------------
        links = ttk.LabelFrame(self, text="Tage", padding=(10, 8))
        links.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
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
                  font=(stil.SCHRIFT, 14, "bold")).grid(row=0, column=0,
                                                       sticky="w")
        self.gesamt_var = tk.StringVar(value="")
        ttk.Label(kopf_rechts, textvariable=self.gesamt_var,
                  foreground=stil.ROT,
                  font=(stil.SCHRIFT, 16, "bold")).grid(row=0, column=1,
                                                       sticky="e")
        self.summe_var = tk.StringVar(value="")
        ttk.Label(rechts, textvariable=self.summe_var,
                  foreground=stil.GEDAEMPFT,
                  font=stil.schrift(9)).grid(row=1, column=0, sticky="w",
                                             pady=(0, 6))

        self.zeit_canvas = tk.Canvas(rechts, height=146, highlightthickness=0,
                                     background=stil.WEISS)
        self.zeit_canvas.grid(row=2, column=0, sticky="ew")
        self.zeit_canvas.bind("<Configure>", lambda e: self._zeichne_zeit())
        self.zeit_canvas.bind("<Motion>", self._hover)
        self.zeit_canvas.bind("<Leave>", lambda e: self._hover_loeschen())

        self.kreis_canvas = tk.Canvas(rechts, height=228, highlightthickness=0,
                                      background=stil.WEISS)
        self.kreis_canvas.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        self.kreis_canvas.bind("<Configure>", lambda e: self._zeichne_kreis())

        meld = ttk.LabelFrame(rechts, padding=(10, 8))
        meld.grid(row=4, column=0, sticky="nsew")
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
                  font=(stil.SCHRIFT, 10, "bold")).pack(side="left")

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
        for t in reversed(self._tage):
            s = t["summen"]
            unvoll = s["unbekannt"] > 0
            datum = "%s %s" % (kartendaten.WOCHENTAGE[t["tag"].weekday()],
                               t["tag"].strftime("%d.%m.%Y"))
            if unvoll:
                datum += " *"
            iid = t["tag"].isoformat()
            tags = []
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
        if self._auswahl is None:
            return

        s = self._auswahl["summen"]
        profil = self._auswahl["profil"]
        breite = max(260, c.winfo_width() - 28)
        links, y0, hoehe = 14, 30, 46

        # Stundenraster unter dem Balken (0, 2, 4 … 24)
        for stunde in range(0, 25):
            x = links + breite * stunde / 24.0
            if stunde % 2 == 0:
                c.create_line(x, y0 + hoehe, x, y0 + hoehe + 6,
                              fill="#C9D0DC")
                c.create_text(x, y0 + hoehe + 15,
                              text="%02d" % stunde,
                              font=stil.schrift(7), fill=stil.GEDAEMPFT)

        # Aktivitätsbalken: ein durchgehender 24-Stunden-Streifen
        for von, bis, art in self._laeufe(profil):
            if art < 0:
                farbe = "#ECEEF3"
            else:
                farbe = kartendaten.FARBEN[art]
            x1 = links + breite * von / 1440.0
            x2 = links + breite * bis / 1440.0
            c.create_rectangle(x1, y0, x2, y0 + hoehe,
                               fill=farbe, outline="")

        # Verstöße als rote Markierung über dem Balken
        for m in self._auswahl["verstoesse"]:
            if not m.get("zeit"):
                continue
            try:
                h, mi = m["zeit"].split(":")
                minute = int(h) * 60 + int(mi)
            except ValueError:
                continue
            x = links + breite * minute / 1440.0
            c.create_polygon(x, y0 - 8, x - 5, y0 - 1, x + 5, y0 - 1,
                             fill=stil.ROT, outline="")

        c.create_rectangle(links, y0, links + breite, y0 + hoehe,
                           outline=stil.RAND)

        # Legende mit den Zeitanteilen des Tages
        eintraege = [
            (s["ruhe"], kartendaten.FARBEN[0], "Ruhe"),
            (s["bereit"], kartendaten.FARBEN[1], "Bereitschaft"),
            (s["arbeit"], kartendaten.FARBEN[2], "Arbeit"),
            (s["lenk"], kartendaten.FARBEN[3], "Fahrt"),
        ]
        if s["unbekannt"]:
            eintraege.append((s["unbekannt"], "#ECEEF3", "Unbekannt"))
        schrift = tkfont.Font(font=stil.schrift(8))
        x, y = links, y0 + hoehe + 36
        for wert, farbe, name in eintraege:
            text = "%s %s" % (name, kartendaten.hmm(wert))
            breite_text = schrift.measure(text) + 24
            if x > links and x + breite_text > links + breite:
                x, y = links, y + 20
            c.create_rectangle(x, y - 5, x + 10, y + 5,
                               fill=farbe, outline=stil.RAND)
            c.create_text(x + 16, y, anchor="w", text=text,
                          font=stil.schrift(8), fill=stil.TEXT)
            x += breite_text + 14

        if s["unbekannt"]:
            c.create_text(links + breite, y + 20, anchor="e",
                          text="* nach dem letzten Auslesen unbekannt",
                          font=stil.schrift(7), fill=stil.GRAU)

    def _hover(self, event):
        c = self.zeit_canvas
        if self._auswahl is None:
            return
        breite = max(260, c.winfo_width() - 28)
        links = 14
        x = event.x - links
        if x < 0 or x > breite:
            self._hover_loeschen()
            return
        profil = self._auswahl["profil"]
        minute = min(1439, max(0, int(x / breite * 1440)))
        art = profil[minute]
        start = minute
        while start > 0 and profil[start - 1] == art:
            start -= 1
        ende = minute + 1
        while ende < 1440 and profil[ende] == art:
            ende += 1
        name = "Unbekannt" if art < 0 else kartendaten.ARTEN[art]
        ende_text = "24:00" if ende >= 1440 else kartendaten.uhr(ende)
        text = "%s–%s  %s (%s)" % (
            kartendaten.uhr(start), ende_text, name,
            kartendaten.hmm(ende - start))
        c.delete("hover")
        xp = links + breite * minute / 1440.0
        c.create_line(xp, 30, xp, 76, fill=stil.NAVY,
                      dash=(2, 2), tags="hover")
        c.create_text(c.winfo_width() - 8, 8, anchor="ne", text=text,
                      font=stil.schrift(8, True), fill=stil.NAVY,
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
                 (s["unbekannt"], "#ECEEF3", "Unbekannt")]

        # Kreis und Legende als eine Gruppe mittig im verfügbaren Platz
        # anordnen (der Canvas ist so breit wie die rechte Seite).
        r, luecke = 94, 38
        schrift = tkfont.Font(font=stil.schrift(9))
        texte = ["%-13s %5s h   %3d %%"
                 % (name, kartendaten.hmm(wert),
                    round(100 * wert / 1440.0))
                 for wert, _farbe, name in werte]
        legende = max(schrift.measure(t) for t in texte) + 22
        breite = max(c.winfo_width(), 470)
        hoehe = max(c.winfo_height(), 228)
        gruppe = 2 * r + luecke + legende
        links = max(6, int((breite - gruppe) / 2))
        cx = links + r
        cy = int(hoehe / 2)

        winkel = 90.0
        for wert, farbe, _name in werte:
            if wert <= 0:
                continue
            ausdehnung = -360.0 * wert / 1440.0
            c.create_arc(cx - r, cy - r, cx + r, cy + r,
                         start=winkel, extent=ausdehnung,
                         fill=farbe, outline=stil.WEISS, width=2)
            winkel += ausdehnung
        c.create_oval(cx - r, cy - r, cx + r, cy + r,
                      outline=stil.RAND)
        c.create_text(cx, cy - 8, text="24 h",
                      font=(stil.SCHRIFT, 13, "bold"), fill=stil.NAVY)
        c.create_text(cx, cy + 12, text="Tagesanteile",
                      font=stil.schrift(7), fill=stil.GRAU)

        # Legende
        x = cx + r + luecke
        y = cy - 76
        for (wert, farbe, name), text in zip(werte, texte):
            c.create_rectangle(x, y, x + 14, y + 14,
                               fill=farbe, outline=stil.RAND)
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
        for m in meldungen:
            self.meld_tree.insert(
                "", "end",
                values=(m["zeit"] or "", m["art"], m["text"],
                        m.get("recht") or ""),
                tags=[m["schwere"]])


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
                  font=(stil.SCHRIFT, 12, "bold")).grid(row=0, column=0,
                                                       sticky="w")
        self.hinweis_var = tk.StringVar(value="")
        ttk.Label(kopf, textvariable=self.hinweis_var,
                  foreground=stil.GEDAEMPFT,
                  font=stil.schrift(8)).grid(row=1, column=0, sticky="w")

        tabelle = ttk.LabelFrame(self, text="Kennzahlen der geladenen Karte",
                                 padding=(10, 8))
        tabelle.grid(row=1, column=0, sticky="nsew")
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

        ttk.Label(self, text="Rechtsgrundlagen und Grenzwerte",
                  foreground=stil.NAVY,
                  font=(stil.SCHRIFT, 10, "bold")).grid(row=2, column=0,
                                                       sticky="w",
                                                       pady=(12, 4))
        text = tk.Text(self, height=10, wrap="word", relief="flat",
                       background=stil.PANEL, foreground=stil.TEXT,
                       font=stil.schrift(8), padx=12, pady=10,
                       borderwidth=0, insertbackground=stil.NAVY,
                       selectbackground=stil.AUSWAHL,
                       selectforeground=stil.ROT_DUNKEL)
        text.grid(row=3, column=0, sticky="nsew")
        tbalken = ttk.Scrollbar(self, orient="vertical", command=text.yview)
        tbalken.grid(row=3, column=1, sticky="ns")
        text.configure(yscrollcommand=tbalken.set)
        text.tag_configure("titel", font=(stil.SCHRIFT, 9, "bold"),
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
        for z in zahlen:
            self.tree.insert(
                "", "end", tags=[z["status"]],
                values=(namen.get(z["status"], z["status"]),
                        z["name"], z["wert"], z["grenze"],
                        z["recht"] or ""))
        if any(z["status"] == "rot" for z in zahlen):
            self.hinweis_var.set(
                self.hinweis_var.get() +
                "  Rote Zeilen bitte vor der Abrechnung prüfen.")
