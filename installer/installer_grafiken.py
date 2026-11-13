# -*- coding: utf-8 -*-
"""Erzeugt die Grafiken fuer den Inno-Setup-Assistenten aus den Assets.

Aufruf:  py installer\\installer_grafiken.py

Ergebnis (im Ordner installer):
  wizard_image.bmp   großes Bild links im Assistenten (164 x 314)
  wizard_small.bmp   kleines Bild oben rechts (55 x 55)

Die Bilder werden aus firmenlogo_transparent.png,
produktlogo_transparent.png und icon_fahrerkarte_transparent.png
zusammengesetzt. Nach Aenderungen an den Assets einfach neu ausfuehren.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
ASSETS = BASE.parent / "assets"

BLAU = (47, 111, 176)
DUNKELBLAU = (35, 86, 138)
GRAU = (85, 85, 85)
HELL = (238, 244, 250)


def _bild(name, breite):
    """Transparentes PNG aus den Assets auf die gewuenschte Breite bringen."""
    bild = Image.open(ASSETS / name).convert("RGBA")
    hoehe = max(1, round(bild.height * breite / bild.width))
    return bild.resize((breite, hoehe), Image.LANCZOS)


def _mitte(draw, text, font, y, farbe, breite):
    box = draw.textbbox((0, 0), text, font=font)
    x = (breite - (box[2] - box[0])) / 2 - box[0]
    draw.text((x, y), text, font=font, fill=farbe)


def _schrift(groesse, fett=False):
    for name in (("seguisb.ttf", "segoeuib.ttf") if fett
                 else ("segoeui.ttf",)):
        pfad = Path("C:/Windows/Fonts") / name
        if pfad.is_file():
            return ImageFont.truetype(str(pfad), groesse)
    return ImageFont.load_default()


def grosses_bild(ziel):
    breite, hoehe = 164, 314
    bild = Image.new("RGB", (breite, hoehe), "white")
    draw = ImageDraw.Draw(bild)

    # sanfter Verlauf von Weiss nach Hellblau
    for y in range(hoehe):
        t = y / (hoehe - 1)
        farbe = tuple(round(255 + (h - 255) * t) for h in HELL)
        draw.line([(0, y), (breite, y)], fill=farbe)

    produkt = _bild("produktlogo_transparent.png", 138)
    bild.paste(produkt, ((breite - produkt.width) // 2, 20), produkt)

    _mitte(draw, "Fahrerkarte & Spesenzettel", _schrift(9), 60, GRAU,
           breite)

    karte = _bild("icon_fahrerkarte_transparent.png", 64)
    bild.paste(karte, ((breite - karte.width) // 2, 92), karte)

    draw.line([(20, 178), (breite - 20, 178)], fill=(196, 208, 220))
    for i, text in enumerate(("Karte auslesen", "Spesenzettel erstellen",
                              "Verstöße prüfen")):
        _mitte(draw, text, _schrift(8), 190 + i * 15, GRAU, breite)

    firma = _bild("firmenlogo_transparent.png", 118)
    bild.paste(firma, ((breite - firma.width) // 2,
                       236 - firma.height // 2), firma)

    draw.rectangle([0, hoehe - 34, breite, hoehe], fill=DUNKELBLAU)
    _mitte(draw, "CardMaster LS", _schrift(11, fett=True),
           hoehe - 25, "white", breite)
    bild.save(ziel, "BMP")


def kleines_bild(ziel):
    breite = hoehe = 55
    bild = Image.new("RGB", (breite, hoehe), "white")
    draw = ImageDraw.Draw(bild)
    draw.rounded_rectangle([0, 0, breite - 1, hoehe - 1], radius=8,
                           fill=(244, 248, 252), outline=(196, 208, 220))
    karte = _bild("icon_fahrerkarte_transparent.png", 40)
    bild.paste(karte, ((breite - karte.width) // 2,
                       (hoehe - karte.height) // 2), karte)
    bild.save(ziel, "BMP")


if __name__ == "__main__":
    grosses_bild(BASE / "wizard_image.bmp")
    kleines_bild(BASE / "wizard_small.bmp")
    for name in ("wizard_image.bmp", "wizard_small.bmp"):
        pfad = BASE / name
        print("%s  %d Byte  %s" % (name, pfad.stat().st_size,
                                   Image.open(pfad).size))
