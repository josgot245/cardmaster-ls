# -*- coding: utf-8 -*-
"""Validierung: TACHO-Anwendung waehlen, EF lesen (READ BINARY)."""
import sys

from smartcard.System import readers
from smartcard.scard import (
    SCardEstablishContext, SCardReleaseContext, SCardConnect,
    SCardDisconnect, SCardTransmit,
    SCARD_SCOPE_USER, SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0,
    SCARD_LEAVE_CARD, SCARD_PCI_T0,
)

TACHO_AID = [0xFF, 0x54, 0x41, 0x43, 0x48, 0x4F]  # 'TACHO'


def hexs(data):
    return " ".join("%02X" % b for b in data) if data else "(leer)"


def sw_of(resp):
    return "%02X%02X" % (resp[-2], resp[-1]) if len(resp) >= 2 else "????"


class Card:
    def __init__(self, reader):
        hr, self.ctx = SCardEstablishContext(SCARD_SCOPE_USER)
        assert hr == 0
        hr, self.hcard, self.proto = SCardConnect(
            self.ctx, reader, SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0)
        if hr != 0:
            raise RuntimeError("SCardConnect: 0x%08X" % hr)

    def close(self):
        SCardDisconnect(self.hcard, SCARD_LEAVE_CARD)
        SCardReleaseContext(self.ctx)

    def tx(self, apdu):
        """APDU senden, GET RESPONSE (61xx) automatisch ausfuehren."""
        hr, resp = SCardTransmit(self.hcard, SCARD_PCI_T0, list(apdu))
        if hr != 0:
            raise RuntimeError("SCardTransmit: 0x%08X" % hr)
        data, sw1, sw2 = resp[:-2], resp[-2], resp[-1]
        while sw1 == 0x61:
            hr, resp = SCardTransmit(self.hcard, SCARD_PCI_T0,
                                     [0x00, 0xC0, 0x00, 0x00, sw2 or 0x100])
            if hr != 0:
                raise RuntimeError("GET RESPONSE: 0x%08X" % hr)
            data += resp[:-2]
            sw1, sw2 = resp[-2], resp[-1]
        return data, (sw1 << 8) | sw2

    def select_aid(self):
        return self.tx([0x00, 0xA4, 0x04, 0x0C, len(TACHO_AID)] + TACHO_AID)

    def select_ef(self, fid):
        assert 0 <= fid <= 0xFFFF
        return self.tx([0x00, 0xA4, 0x02, 0x0C, 0x02, fid >> 8, fid & 0xFF])

    def read_binary(self, length):
        out = bytearray()
        while len(out) < length:
            want = min(200, length - len(out))
            offset = len(out)
            data, sw = self.tx([0x00, 0xB0, offset >> 8, offset & 0xFF, want])
            if sw != 0x9000:
                raise RuntimeError("READ BINARY @%d: SW=%04X" % (offset, sw))
            if not data:
                break
            out.extend(data)
        return bytes(out[:length])


def main():
    rs = readers()
    card = Card(str(rs[0]))
    try:
        data, sw = card.select_aid()
        print("SELECT TACHO-AID: SW=%04X" % sw)

        for name, fid, length in (
                ("EF 0501 ApplicationIdentification", 0x0501, 10),
                ("EF 0520 Identification", 0x0520, 143),
                ("EF 050E CardDownload", 0x050E, 4),
                ("EF 0521 DrivingLicenceInfo", 0x0521, 53),
                ("EF 0507 CurrentUsage", 0x0507, 19)):
            _, sw = card.select_ef(fid)
            print("\n%s: SELECT SW=%04X" % (name, sw))
            if sw != 0x9000:
                continue
            blob = card.read_binary(length)
            print("  %s" % hexs(blob))
    finally:
        card.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
