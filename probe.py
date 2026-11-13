# -*- coding: utf-8 -*-
"""Diagnose: Protokoll- und APDU-Matrix gegen die Karte im Leser."""
import sys

from smartcard.System import readers
from smartcard.scard import (
    SCardEstablishContext, SCardReleaseContext, SCardListReaders,
    SCardConnect, SCardDisconnect, SCardTransmit, SCardGetAttrib,
    SCARD_SCOPE_USER, SCARD_SHARE_SHARED,
    SCARD_PROTOCOL_T0, SCARD_PROTOCOL_T1,
    SCARD_ATTR_ATR_STRING, SCARD_LEAVE_CARD,
    SCARD_PCI_T0, SCARD_PCI_T1,
)


def hexs(data):
    return " ".join("%02X" % b for b in data) if data else "(leer)"


def sw_of(resp):
    if not resp or len(resp) < 2:
        return "????"
    return "%02X%02X" % (resp[-2], resp[-1])


def connect(reader, protocol):
    hresult, hcontext = SCardEstablishContext(SCARD_SCOPE_USER)
    if hresult != 0:
        raise RuntimeError("SCardEstablishContext: 0x%08X" % hresult)
    hresult, hcard, active = SCardConnect(
        hcontext, reader, SCARD_SHARE_SHARED, protocol)
    return hresult, hcontext, hcard, active


def disconnect(hcontext, hcard):
    SCardDisconnect(hcard, SCARD_LEAVE_CARD)
    SCardReleaseContext(hcontext)


def transmit(hcard, pci, apdu):
    hresult, resp = SCardTransmit(hcard, pci, list(apdu))
    if hresult != 0:
        return None, "Fehler 0x%08X" % hresult
    return resp, sw_of(resp)


def main():
    rs = readers()
    print("Leser:", [str(r) for r in rs])
    if not rs:
        return
    reader = str(rs[0])

    for pname, proto, pci in (
            ("T=0", SCARD_PROTOCOL_T0, SCARD_PCI_T0),
            ("T=1", SCARD_PROTOCOL_T1, SCARD_PCI_T1)):
        print("\n=== Verbindung mit Protokoll %s ===" % pname)
        hresult, hcontext, hcard, active = connect(reader, proto)
        if hresult != 0:
            print("  Verbindung fehlgeschlagen: 0x%08X" % hresult)
            continue
        active_name = {1: "T=0", 2: "T=1"}.get(active, str(active))
        print("  aktiv: %s" % active_name)

        hresult, atr = SCardGetAttrib(hcard, SCARD_ATTR_ATR_STRING)
        print("  ATR: %s" % (hexs(atr) if hresult == 0 else "n/a"))

        tacho_aid = [0xFF, 0x54, 0x41, 0x43, 0x48, 0x4F]  # 'TACHO'

        tests = [
            ("SELECT MF           (Fall 1)", [0x00, 0xA4, 0x00, 0x00]),
            ("SELECT MF           (Fall 2)", [0x00, 0xA4, 0x00, 0x00, 0x00]),
            ("SELECT 3F00 P2=0C   (Fall 3)", [0x00, 0xA4, 0x00, 0x0C, 0x02, 0x3F, 0x00]),
            ("SELECT 3F00 P2=0C   (Fall 4)", [0x00, 0xA4, 0x00, 0x0C, 0x02, 0x3F, 0x00, 0x00]),
            ("SELECT 3F00 P2=04   (Fall 4)", [0x00, 0xA4, 0x00, 0x04, 0x02, 0x3F, 0x00, 0x00]),
            ("SELECT 2F00 P2=0C   (Fall 3)", [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x2F, 0x00]),
            ("SELECT 2F00 P2=04   (Fall 4)", [0x00, 0xA4, 0x02, 0x04, 0x02, 0x2F, 0x00, 0x00]),
            ("SELECT AID P2=0C    (Fall 3)", [0x00, 0xA4, 0x04, 0x0C, 0x06] + tacho_aid),
            ("SELECT AID P2=0C    (Fall 4)", [0x00, 0xA4, 0x04, 0x0C, 0x06] + tacho_aid + [0x00]),
            ("SELECT AID P2=00    (Fall 4)", [0x00, 0xA4, 0x04, 0x00, 0x06] + tacho_aid + [0x00]),
            ("GET RESPONSE        (Fall 2)", [0x00, 0xC0, 0x00, 0x00, 0x00]),
            ("READ BINARY 32 ab 0 (Fall 2)", [0x00, 0xB0, 0x00, 0x00, 0x20]),
        ]
        for name, apdu in tests:
            resp, sw = transmit(hcard, pci, apdu)
            print("  %-28s SW=%s  %s" % (name, sw, hexs(resp)))
        disconnect(hcontext, hcard)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
