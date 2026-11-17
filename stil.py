# -*- coding: utf-8 -*-
"""Gemeinsames Erscheinungsbild (Farben, Schriften, ttk-Stile).

Die Farben orientieren sich an den Firmenfarben von LS Logistik:
  * Dunkelblau  #242E45  (Kopfleiste, Überschriften)
  * Rot         #9C1006  (Akzent, aktive Registerkarte, Aktionen)
  * Grün        #94C11C  (schmale Akzentlinie)
  * helle Flächen und dezente Rahmen für einen aufgeräumten Look.

Schriften: bevorzugt wird die moderne Windows-11-Schrift „Segoe UI
Variable Text“; fehlt sie (z. B. unter Windows 10), wird automatisch auf
„Segoe UI“ und danach auf weitere Systemschriften zurückgefallen. Die
Größen folgen einer festen Staffel (``PT_*``), damit Überschriften,
Fließtext und Hinweise überall gleich groß sind.

Alle Fenster rufen beim Start :func:`anwenden` auf. Die Stile gelten
danach für alle ttk-Widgets der Anwendung.
"""
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ------------------------------------------------------------------ Farben
NAVY = "#242E45"
NAVY_HELL = "#33415C"
ROT = "#9C1006"
ROT_DUNKEL = "#7A0C05"
ROT_HELL = "#F7E9E7"
GRUEN = "#94C11C"
WEISS = "#FFFFFF"
SEITE = "#FFFFFF"
HINTERGRUND = "#F4F6FA"
RAND = "#DDE2EB"
TEXT = "#242E45"
GEDAEMPFT = "#6B7385"
GRAU = "#878898"
TAB_INAKTIV = "#EEF1F6"
AUSWAHL = "#F5E6E3"
PANEL = "#F7F8FB"
ZEBRA = "#F5F7FB"      # abwechselnde Zeilenfarbe in Tabellen
SCHATTEN = "#E4E8F0"   # dezenter Schatten unter den Karten

FARBEN = {
    "navy": NAVY,
    "navy_hell": NAVY_HELL,
    "rot": ROT,
    "rot_dunkel": ROT_DUNKEL,
    "rot_hell": ROT_HELL,
    "gruen": GRUEN,
    "weiss": WEISS,
    "seite": SEITE,
    "hintergrund": HINTERGRUND,
    "rand": RAND,
    "text": TEXT,
    "gedaempft": GEDAEMPFT,
    "grau": GRAU,
    "panel": PANEL,
}

# --------------------------------------------------------- Schriftgrößen
# Feste Staffel in Punkten – gleiche Elemente sind überall gleich groß.
PT_MINI = 7         # Achsenbeschriftung, Fußnoten
PT_KLEIN = 8        # Hinweise, Untertitel, Metadaten
PT_TEXT = 9         # Fließtext, Tabellenzellen, Beschriftungen
PT_ABSCHNITT = 11   # Abschnitts- und Gruppenüberschriften
PT_UNTERTITEL = 13  # Bereichsüberschrift (z. B. gewählter Tag)
PT_TITEL = 15       # Seitenüberschrift
PT_GROSS = 16       # Produktname, große Kennzahl
PT_HERO = 17        # Überschrift der Startseite

# ------------------------------------------------------- Schriftfamilien
# Bevorzugt die modernere Windows-11-Schrift; fehlt sie, wird der Reihe
# nach auf die nächste vorhandene Familie zurückgefallen.
UI_FAMILIEN = ("Segoe UI Variable Text", "Segoe UI", "Tahoma", "Verdana")
FEST_FAMILIEN = ("Cascadia Mono", "Consolas", "Courier New")
STANDARD_UI = "Segoe UI"
STANDARD_FEST = "Consolas"

# Veraltete Namen – nur noch für Rückwärtskompatibilität vorhanden.
SCHRIFT = STANDARD_UI
SCHRIFT_FEST = STANDARD_FEST

_familien = {}
_bilder = {}   # Referenzen auf Laufzeit-Grafiken (verhindert Freigabe)


def _erste_familie(kandidaten, standard):
    """Erste vorhandene Familie; ``(name, gemerkt)`` zurückgeben.

    ``gemerkt`` ist ``False``, wenn noch kein Fenster existiert und die
    Auswahl daher später erneut versucht werden soll.
    """
    try:
        vorhanden = set(tkfont.families())
    except (tk.TclError, RuntimeError, AttributeError):
        return standard, False
    for name in kandidaten:
        if name in vorhanden:
            return name, True
    return standard, True


def familie():
    """Bevorzugte Schriftfamilie der Oberfläche."""
    if "ui" not in _familien:
        name, gemerkt = _erste_familie(UI_FAMILIEN, STANDARD_UI)
        if not gemerkt:
            return name
        _familien["ui"] = name
    return _familien["ui"]


def familie_fest():
    """Bevorzugte Festbreiten-Schriftfamilie (Protokoll, Zahlen)."""
    if "fest" not in _familien:
        name, gemerkt = _erste_familie(FEST_FAMILIEN, STANDARD_FEST)
        if not gemerkt:
            return name
        _familien["fest"] = name
    return _familien["fest"]


def schrift(groesse=PT_TEXT, fett=False):
    """Schrift-Tupel für tkinter-Widgets."""
    return (familie(), groesse, "bold") if fett else (familie(), groesse)


def schrift_fest(groesse=PT_TEXT, fett=False):
    """Festbreiten-Schrift-Tupel (Protokoll, ausgerichtete Zahlen)."""
    fam = familie_fest()
    return (fam, groesse, "bold") if fett else (fam, groesse)


def _stile(wurzel):
    art = ttk.Style(wurzel)
    try:
        art.theme_use("clam")
    except tk.TclError:
        pass

    ui = familie()
    fest = familie_fest()

    # Grundschriften (auch für tk-Widgets ohne eigenen font-Parameter)
    for name, groesse, fett in (
            ("TkDefaultFont", PT_TEXT, False),
            ("TkTextFont", PT_TEXT, False),
            ("TkMenuFont", PT_TEXT, False),
            ("TkHeadingFont", PT_TEXT, True),
            ("TkCaptionFont", PT_TEXT, False),
            ("TkTooltipFont", PT_KLEIN, False)):
        try:
            tkfont.nametofont(name).configure(
                family=ui, size=groesse,
                weight="bold" if fett else "normal")
        except tk.TclError:
            pass
    try:
        tkfont.nametofont("TkFixedFont").configure(family=fest, size=PT_TEXT)
    except tk.TclError:
        pass

    # ---------------------------------------------------------- Flächen
    art.configure(".", background=SEITE, foreground=TEXT,
                  font=(ui, PT_TEXT))
    for stil_name in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton",
                      "TLabelframe", "TLabelframe.Label"):
        art.configure(stil_name, background=SEITE, foreground=TEXT)
    art.configure("Karte.TFrame", background=HINTERGRUND)
    art.configure("TLabelframe", bordercolor=RAND, lightcolor=RAND,
                  darkcolor=RAND, borderwidth=1, relief="solid")
    art.configure("TLabelframe.Label", foreground=NAVY,
                  font=(ui, PT_ABSCHNITT, "bold"))
    art.configure("TSeparator", background=RAND)
    art.configure("TLabel", font=(ui, PT_TEXT))

    # ---------------------------------------------------------- Knöpfe
    art.configure(
        "TButton", background=WEISS, foreground=NAVY,
        bordercolor=RAND, lightcolor=RAND, darkcolor=RAND,
        borderwidth=1, relief="solid", padding=(12, 7),
        font=(ui, PT_TEXT))
    art.map(
        "TButton",
        background=[("disabled", PANEL), ("pressed", "#E3E8F1"),
                    ("active", "#EEF1F7")],
        foreground=[("disabled", GRAU)],
        bordercolor=[("disabled", RAND)])
    art.configure(
        "Akzent.TButton", background=WEISS, foreground=ROT,
        bordercolor=ROT, lightcolor=ROT, darkcolor=ROT,
        borderwidth=1, relief="solid", padding=(14, 7),
        font=(ui, PT_TEXT, "bold"))
    art.map(
        "Akzent.TButton",
        background=[("disabled", PANEL), ("pressed", "#F2D8D4"),
                    ("active", ROT_HELL)],
        foreground=[("disabled", "#B9A5A2")],
        bordercolor=[("disabled", "#DCC7C3")],
        lightcolor=[("disabled", "#DCC7C3")],
        darkcolor=[("disabled", "#DCC7C3")])

    # Gefüllte Hauptknöpfe: klare Hierarchie – ein auffälliger Hauptknopf,
    # der Rest bleibt ruhig (weiß mit Rahmen).
    art.configure(
        "Primaer.TButton", background=NAVY, foreground=WEISS,
        bordercolor=NAVY, lightcolor=NAVY, darkcolor=NAVY,
        borderwidth=0, relief="flat", padding=(16, 8),
        font=(ui, PT_TEXT, "bold"))
    art.map(
        "Primaer.TButton",
        background=[("disabled", PANEL), ("pressed", "#1B2438"),
                    ("active", NAVY_HELL)],
        foreground=[("disabled", GRAU)])
    art.configure(
        "PrimaerRot.TButton", background=ROT, foreground=WEISS,
        bordercolor=ROT, lightcolor=ROT, darkcolor=ROT,
        borderwidth=0, relief="flat", padding=(16, 8),
        font=(ui, PT_TEXT, "bold"))
    art.map(
        "PrimaerRot.TButton",
        background=[("disabled", PANEL), ("pressed", ROT_DUNKEL),
                    ("active", "#B4170A")],
        foreground=[("disabled", GRAU)])

    # ---------------------------------------------------------- Eingaben
    for stil_name in ("TEntry", "TCombobox", "TSpinbox"):
        art.configure(stil_name, fieldbackground=WEISS, foreground=TEXT,
                      bordercolor=RAND, lightcolor=RAND, darkcolor=RAND,
                      insertcolor=NAVY, padding=(6, 5), font=(ui, PT_TEXT))
        art.map(stil_name,
                bordercolor=[("focus", ROT)],
                lightcolor=[("focus", ROT)],
                darkcolor=[("focus", ROT)])
    art.configure("TCheckbutton", indicatorbackground=WEISS,
                  indicatorforeground=ROT, padding=(2, 3))
    art.map("TCheckbutton",
            background=[("active", SEITE)],
            indicatorbackground=[("selected", ROT),
                                 ("active", ROT_HELL)],
            indicatorforeground=[("selected", WEISS)])

    # ---------------------------------------------------------- Registerkarten
    art.configure("TNotebook", background=SEITE, borderwidth=0,
                  bordercolor=SEITE, lightcolor=SEITE, darkcolor=SEITE,
                  tabmargins=(0, 0, 0, 0))
    art.configure("TNotebook.Tab", background=TAB_INAKTIV,
                  foreground=NAVY_HELL, bordercolor=TAB_INAKTIV,
                  lightcolor=TAB_INAKTIV, darkcolor=TAB_INAKTIV,
                  padding=(20, 10), font=(ui, PT_TEXT, "bold"))
    art.map("TNotebook.Tab",
            background=[("selected", SEITE), ("active", "#F3F5F9")],
            foreground=[("selected", ROT), ("active", NAVY)],
            bordercolor=[("selected", RAND)],
            lightcolor=[("selected", SEITE)],
            darkcolor=[("selected", SEITE)],
            expand=[("selected", (0, 0, 0, 0))])

    # Roter Unterstrich am aktiven Reiter. Der Strich ist ein Bildelement
    # im Reiter-Layout; scheitert das, bleiben die Reiter unverändert.
    try:
        strich_rot = tk.PhotoImage(width=64, height=3, master=wurzel)
        strich_rot.put(ROT, to=(0, 0, 64, 3))
        strich_leer = tk.PhotoImage(width=64, height=3, master=wurzel)
        strich_leer.put(TAB_INAKTIV, to=(0, 0, 64, 3))
        art.element_create("ReiterStrich", "image", strich_leer,
                           ("selected", strich_rot), border=0, sticky="we")
        art.layout("Notebook.Tab", [
            ("Notebook.tab", {"sticky": "nswe", "children": [
                ("Notebook.padding", {"side": "top", "sticky": "nswe",
                                      "children": [
                    ("Notebook.focus", {"side": "top", "sticky": "nswe",
                                        "children": [
                        ("Notebook.label", {"side": "top",
                                            "sticky": ""})]})]}),
                ("ReiterStrich", {"side": "bottom", "sticky": "we"})]})
        ])
        _bilder["reiter_strich"] = (strich_rot, strich_leer)
    except tk.TclError:
        pass

    # ---------------------------------------------------------- Tabellen
    art.configure("Treeview", background=WEISS, fieldbackground=WEISS,
                  foreground=TEXT, borderwidth=0, relief="flat",
                  rowheight=28, font=(ui, PT_TEXT))
    art.map("Treeview",
            background=[("selected", AUSWAHL)],
            foreground=[("selected", ROT_DUNKEL)])
    art.configure("Treeview.Heading", background=TAB_INAKTIV,
                  foreground=NAVY, bordercolor=RAND,
                  lightcolor=TAB_INAKTIV, darkcolor=TAB_INAKTIV,
                  relief="flat", borderwidth=0, padding=(8, 7),
                  font=(ui, PT_TEXT, "bold"))
    art.map("Treeview.Heading",
            background=[("active", "#E4E9F2")])
    try:
        art.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    except tk.TclError:
        pass

    # ---------------------------------------------------------- Sonstiges
    art.configure("TScrollbar", background="#D9DEE8", troughcolor=PANEL,
                  bordercolor=PANEL, arrowcolor=GEDAEMPFT,
                  lightcolor="#D9DEE8", darkcolor="#D9DEE8",
                  relief="flat", arrowsize=14)
    art.map("TScrollbar",
            background=[("active", "#C3CAD8"), ("pressed", "#AEB7C8")])
    art.configure("TProgressbar", background=ROT,
                  troughcolor=PANEL, bordercolor=PANEL,
                  lightcolor=ROT, darkcolor=ROT)


def anwenden(wurzel):
    """Farben und Stile auf ein Fenster (tk.Tk/tk.Toplevel) anwenden."""
    wurzel.configure(background=SEITE)
    _stile(wurzel)


# ------------------------------------------------- Bildschirm und Zeiger

def dpi_aktivieren():
    """Windows: scharfe Darstellung auf hochauflösenden Bildschirmen.

    Muss **vor** dem Erzeugen des Hauptfensters aufgerufen werden. Ohne
    diesen Aufruf skaliert Windows die Oberfläche unscharf hoch.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
    except ImportError:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # System-DPI-fähig
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _system_dpi():
    """Auflösung des Bildschirms in DPI (Standard 96)."""
    if sys.platform != "win32":
        return 96
    try:
        import ctypes
    except ImportError:
        return 96
    try:
        return int(ctypes.windll.user32.GetDpiForSystem()) or 96
    except (AttributeError, OSError):
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = int(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))  # LOGPIXELSY
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi or 96
    except (AttributeError, OSError):
        return 96


def skalierung_setzen(fenster):
    """tk-Skalierung an den Bildschirm anpassen (scharfe Schriften)."""
    dpi = _system_dpi()
    if dpi <= 0:
        return
    try:
        fenster.tk.call("tk", "scaling", dpi / 72.0)
    except tk.TclError:
        pass


def hand_cursor(fenster):
    """Hand-Cursor über Knöpfen und Auswahlfeldern (klassenweit)."""
    def an(e):
        try:
            e.widget.configure(cursor="hand2")
        except tk.TclError:
            pass

    def aus(e):
        try:
            e.widget.configure(cursor="")
        except tk.TclError:
            pass

    for klasse in ("TButton", "TRadiobutton", "TCheckbutton"):
        try:
            fenster.bind_class(klasse, "<Enter>", an, add="+")
            fenster.bind_class(klasse, "<Leave>", aus, add="+")
        except tk.TclError:
            pass


def zebra_konfigurieren(tree, farbe=None):
    """Abwechselnde Zeilenfarbe (Zebra) für eine Tabelle vorbereiten."""
    tree.tag_configure("zebra", background=farbe or ZEBRA)


def zebra_tags(nummer, weitere=None):
    """Tag-Liste für die Zeile ``nummer`` (1-basiert) – gerade = Zebra."""
    tags = list(weitere or [])
    if nummer % 2 == 0:
        tags.append("zebra")
    return tags


def _mische(farbe_a, farbe_b, anteil):
    """Zwei Hex-Farben mischen (anteil 0..1)."""
    a = farbe_a.lstrip("#")
    b = farbe_b.lstrip("#")
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (
        int(ra + (rb - ra) * anteil),
        int(ga + (gb - ga) * anteil),
        int(ba + (bb - ba) * anteil))


def verlauf(canvas, breite, hoehe, farbe_a, farbe_b, tag="verlauf"):
    """Waagerechten Farbverlauf auf ein Canvas zeichnen (für die Kopfleiste)."""
    canvas.delete(tag)
    if breite <= 0 or hoehe <= 0:
        return
    schritte = max(2, min(breite, 256))
    for i in range(schritte):
        x0 = int(i * breite / schritte)
        x1 = int((i + 1) * breite / schritte) + 1
        canvas.create_rectangle(
            x0, 0, x1, hoehe, width=0,
            fill=_mische(farbe_a, farbe_b, i / (schritte - 1)), tags=tag)
    canvas.tag_lower(tag)


# ------------------------------------------------------------------ Karten

class Karte(ttk.Frame):
    """Bereich in Karten-Optik: weißer Rahmen mit dezentem Schatten.

    Der Inhalt gehört in :attr:`innen` (ein ``ttk.LabelFrame``)::

        karte = stil.Karte(rahmen, titel="Datenquelle")
        karte.grid(row=0, column=0, sticky="ew")
        ttk.Button(karte.innen, text="…").grid(row=0, column=0)
    """

    def __init__(self, master, titel=None, padding=(16, 12)):
        super().__init__(master, style="Karte.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, minsize=3)
        self.rowconfigure(1, minsize=3)
        self.innen = ttk.LabelFrame(self, text=titel or "", padding=padding)
        self.innen.grid(row=0, column=0, sticky="nsew")
        # Schatten rechts und unten (3 px Versatz)
        tk.Frame(self, background=SCHATTEN).grid(
            row=0, column=1, sticky="ns", pady=(4, 0))
        tk.Frame(self, background=SCHATTEN, height=3).grid(
            row=1, column=0, sticky="ew", padx=(0, 4))
        tk.Frame(self, background=SCHATTEN, width=3, height=3).grid(
            row=1, column=1, sticky="nw")
