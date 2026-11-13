# -*- coding: utf-8 -*-
"""Übernimmt das bisherige Programm-Icon (cardmaster.ico).

Aufruf:  py installer\\installer_icon.py

Das alte Icon liegt unverändert unter ``cardmaster.ico`` im Projektordner
und wird an die beiden Stellen kopiert, an denen Windows es erwartet:

  assets\\cardmaster.ico     Fenster- und Taskleistensymbol der App
  installer\\cardmaster.ico  Symbol der .exe und des Setups

Die Datei im Projektordner ist die Quelle und wird nicht überschrieben.
"""
import shutil
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent
ASSETS = BASE.parent / "assets"
QUELLE = BASE.parent / "cardmaster.ico"
ZIELE = (ASSETS / "cardmaster.ico", BASE / "cardmaster.ico")


def main():
    if not QUELLE.is_file():
        raise SystemExit("Altes Icon nicht gefunden: %s" % QUELLE)
    for ziel in ZIELE:
        shutil.copyfile(QUELLE, ziel)
        print("%s  %d Byte  %s" % (
            ziel, ziel.stat().st_size,
            Image.open(ziel).info.get("sizes")))


if __name__ == "__main__":
    main()
