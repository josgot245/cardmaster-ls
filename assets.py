# -*- coding: utf-8 -*-
"""Grafiken aus dem Asset-Paket fuer die Oberflaeche laden.

Die Bilder liegen als PNG mit transparentem Hintergrund im Ordner
``assets`` neben den Skripten. In der installierten .exe liefert
PyInstaller den Ordner mit aus, sodass APP_DIR auch dort darauf zeigt.
Fehlt ein Bild, liefert :func:`lade` einfach ``None`` – die Oberflaeche
funktioniert dann ohne Grafik weiter.
"""
import tkinter as tk
from pathlib import Path

import spesen_lib

_bilder = {}


def ordner():
    """Ordner mit den Grafikdateien."""
    return Path(spesen_lib.APP_DIR) / "assets"


def lade(name):
    """Bild ``assets/<name>.png`` als PhotoImage (oder None).

    Die Referenz wird dauerhaft gehalten, damit tkinter die Grafik nicht
    einsammelt.
    """
    if name in _bilder:
        return _bilder[name]
    bild = None
    pfad = ordner() / ("%s.png" % name)
    if pfad.is_file():
        try:
            bild = tk.PhotoImage(file=str(pfad))
        except tk.TclError:
            bild = None
    _bilder[name] = bild
    return bild


def setze_fenster_icon(fenster):
    """Fenster-/Taskleistensymbol setzen. True, wenn ein Symbol gefunden."""
    for basis in (ordner(), Path(spesen_lib.APP_DIR)):
        for name in ("cardmaster.ico", "spesenzettel.ico"):
            pfad = basis / name
            if not pfad.is_file():
                continue
            try:
                fenster.iconbitmap(str(pfad))
                return True
            except tk.TclError:
                continue
    return False
