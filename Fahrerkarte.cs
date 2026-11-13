using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace Fahrerkarte
{
    internal struct ScardIoRequest
    {
        public int Protocol;
        public int PciLength;
    }

    internal static class WinScard
    {
        [DllImport("winscard.dll")]
        internal static extern int SCardEstablishContext(int scope, IntPtr reserved1, IntPtr reserved2, out IntPtr context);

        [DllImport("winscard.dll")]
        internal static extern int SCardReleaseContext(IntPtr context);

        [DllImport("winscard.dll", CharSet = CharSet.Ansi)]
        internal static extern int SCardListReaders(IntPtr context, IntPtr groups, byte[] readers, ref int length);

        [DllImport("winscard.dll", CharSet = CharSet.Ansi)]
        internal static extern int SCardConnect(IntPtr context, string reader, int shareMode, int preferredProtocols, out IntPtr card, out int activeProtocol);

        [DllImport("winscard.dll")]
        internal static extern int SCardDisconnect(IntPtr card, int disposition);

        [DllImport("winscard.dll")]
        internal static extern int SCardGetAttrib(IntPtr card, int attribute, byte[] buffer, ref int length);

        [DllImport("winscard.dll")]
        internal static extern int SCardTransmit(IntPtr card, ref ScardIoRequest sendPci, byte[] sendBuffer, int sendLength, IntPtr receivePci, byte[] receiveBuffer, ref int receiveLength);
    }

    /// <summary>
    /// Verbindung zu einer Karte in einem bestimmten Leser.
    /// </summary>
    internal sealed class CardChannel : IDisposable
    {
        private IntPtr _context;
        private IntPtr _card;
        private int _protocol;

        public string Reader { get; private set; }

        public CardChannel(string reader)
        {
            Reader = reader;
            int rc = WinScard.SCardEstablishContext(0, IntPtr.Zero, IntPtr.Zero, out _context);
            if (rc != 0)
                throw new Exception("SCardEstablishContext fehlgeschlagen (0x" + rc.ToString("X8") + ")");
            rc = WinScard.SCardConnect(_context, reader, 2, 3, out _card, out _protocol);
            if (rc != 0)
            {
                WinScard.SCardReleaseContext(_context);
                _context = IntPtr.Zero;
                throw new Exception("Keine Karte im Leser '" + reader + "' (0x" + rc.ToString("X8") + ")");
            }
        }

        public byte[] GetAtr()
        {
            int len = 64;
            byte[] buf = new byte[64];
            int rc = WinScard.SCardGetAttrib(_card, 0x00090303, buf, ref len);
            if (rc != 0)
                return new byte[0];
            byte[] atr = new byte[len];
            Array.Copy(buf, atr, len);
            return atr;
        }

        /// <summary>Sendet eine APDU und liefert die Antwort inkl. Statuswort.</summary>
        public byte[] Exchange(byte[] apdu)
        {
            ScardIoRequest send = new ScardIoRequest();
            send.Protocol = _protocol;
            send.PciLength = 8;
            byte[] recv = new byte[2048];
            int recvLen = recv.Length;
            int rc = WinScard.SCardTransmit(_card, ref send, apdu, apdu.Length, IntPtr.Zero, recv, ref recvLen);
            if (rc != 0)
                throw new Exception("SCardTransmit fehlgeschlagen (0x" + rc.ToString("X8") + ")");
            byte[] resp = new byte[recvLen];
            Array.Copy(recv, resp, recvLen);
            return resp;
        }

        /// <summary>Wie Exchange, behandelt aber automatisch GET RESPONSE (61xx) und 6Cxx.</summary>
        public byte[] ExchangeAuto(byte[] apdu, bool apduHasLe)
        {
            byte[] resp = Exchange(apdu);
            if (resp.Length == 2 && resp[0] == 0x6C)
            {
                int n = apdu.Length + (apduHasLe ? 0 : 1);
                byte[] retry = new byte[n];
                Array.Copy(apdu, retry, apdu.Length);
                retry[n - 1] = resp[1];
                resp = Exchange(retry);
            }
            while (resp.Length >= 2 && resp[resp.Length - 2] == 0x61)
            {
                int le = resp[resp.Length - 1];
                if (le == 0) le = 256;
                byte[] getResp = new byte[] { 0x00, 0xC0, 0x00, 0x00, (byte)le };
                byte[] part = Exchange(getResp);
                if (part.Length < 2)
                    break;
                byte[] merged = new byte[resp.Length - 2 + part.Length];
                Array.Copy(resp, merged, resp.Length - 2);
                Array.Copy(part, 0, merged, resp.Length - 2, part.Length);
                resp = merged;
            }
            return resp;
        }

        public void Dispose()
        {
            if (_card != IntPtr.Zero)
            {
                WinScard.SCardDisconnect(_card, 0);
                _card = IntPtr.Zero;
            }
            if (_context != IntPtr.Zero)
            {
                WinScard.SCardReleaseContext(_context);
                _context = IntPtr.Zero;
            }
        }
    }

    internal static class HexUtil
    {
        public static string Hex(byte[] data, int index, int count)
        {
            if (data == null)
                return "";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < count && index + i < data.Length; i++)
            {
                if (i > 0)
                    sb.Append(' ');
                sb.Append(data[index + i].ToString("X2"));
            }
            return sb.ToString();
        }

        public static string Hex(byte[] data)
        {
            return data == null ? "" : Hex(data, 0, data.Length);
        }

        public static string Sw(byte[] resp)
        {
            if (resp == null || resp.Length < 2)
                return "????";
            return resp[resp.Length - 2].ToString("X2") + resp[resp.Length - 1].ToString("X2");
        }

        public static byte[] Data(byte[] resp)
        {
            if (resp == null || resp.Length < 2)
                return new byte[0];
            byte[] d = new byte[resp.Length - 2];
            Array.Copy(resp, d, d.Length);
            return d;
        }

        public static void Dump(byte[] data, string title)
        {
            Console.WriteLine();
            Console.WriteLine(title + " (" + (data == null ? 0 : data.Length) + " Bytes)");
            if (data == null)
                return;
            for (int i = 0; i < data.Length; i += 16)
            {
                StringBuilder hex = new StringBuilder();
                StringBuilder ascii = new StringBuilder();
                for (int j = 0; j < 16 && i + j < data.Length; j++)
                {
                    byte b = data[i + j];
                    hex.Append(b.ToString("X2")).Append(' ');
                    char c = (b >= 0x20 && b < 0x7F) ? (char)b : '.';
                    ascii.Append(c);
                }
                Console.WriteLine("  " + i.ToString("X4") + ": " + hex.ToString().PadRight(48) + " " + ascii.ToString());
            }
        }
    }

    internal static class Apdu
    {
        public static byte[] Select(byte[] data, byte p1, byte p2)
        {
            byte[] a = new byte[5 + data.Length];
            a[0] = 0x00;
            a[1] = 0xA4;
            a[2] = p1;
            a[3] = p2;
            Array.Copy(data, 0, a, 4, data.Length);
            a[a.Length - 1] = 0x00; // Le
            return a;
        }

        public static byte[] ReadBinary(int offset, int le)
        {
            return new byte[] { 0x00, 0xB0, (byte)(offset >> 8), (byte)(offset & 0xFF), (byte)le };
        }

        public static byte[] ReadRecord(int record, byte p2)
        {
            return new byte[] { 0x00, 0xB2, (byte)record, p2, 0x00 };
        }
    }

    internal static class Program
    {
        private static byte[] ReadWholeBinary(CardChannel card, int maxBytes)
        {
            List<byte> all = new List<byte>();
            int offset = 0;
            while (offset < maxBytes)
            {
                byte[] resp = card.ExchangeAuto(Apdu.ReadBinary(offset, 240), true);
                string sw = HexUtil.Sw(resp);
                if (sw != "9000" && !sw.StartsWith("62"))
                    break;
                byte[] d = HexUtil.Data(resp);
                if (d.Length == 0)
                    break;
                all.AddRange(d);
                if (d.Length < 240)
                    break;
                offset += d.Length;
            }
            return all.ToArray();
        }

        private static List<byte[]> ParseDirAids(byte[] d)
        {
            List<byte[]> aids = new List<byte[]>();
            if (d == null)
                return aids;
            for (int i = 0; i + 1 < d.Length; i++)
            {
                if (d[i] != 0x4F || d[i + 1] < 1 || d[i + 1] > 16 || i + 2 + d[i + 1] > d.Length)
                    continue;
                byte[] aid = new byte[d[i + 1]];
                Array.Copy(d, i + 2, aid, 0, d[i + 1]);
                aids.Add(aid);
                i += 1 + d[i + 1];
            }
            return aids;
        }

        private static void Main()
        {
            Console.OutputEncoding = Encoding.UTF8;
            Console.WriteLine("=== Fahrerkarte Probe ===");
            Console.WriteLine();

            IntPtr ctx = IntPtr.Zero;
            int rc = WinScard.SCardEstablishContext(0, IntPtr.Zero, IntPtr.Zero, out ctx);
            if (rc != 0)
            {
                Console.WriteLine("Smartcard-Dienst nicht erreichbar (0x" + rc.ToString("X8") + ")");
                return;
            }
            int len = 0;
            WinScard.SCardListReaders(ctx, IntPtr.Zero, null, ref len);
            if (len <= 2)
            {
                Console.WriteLine("Keine Kartenleser gefunden.");
                WinScard.SCardReleaseContext(ctx);
                return;
            }
            byte[] buf = new byte[len];
            rc = WinScard.SCardListReaders(ctx, IntPtr.Zero, buf, ref len);
            string raw = Encoding.ASCII.GetString(buf, 0, len);
            string[] readers = raw.Split(new char[] { '\0' }, StringSplitOptions.RemoveEmptyEntries);
            WinScard.SCardReleaseContext(ctx);

            Console.WriteLine("Leser:");
            foreach (string r in readers)
                Console.WriteLine("  - " + r);

            CardChannel card = null;
            foreach (string r in readers)
            {
                try
                {
                    card = new CardChannel(r);
                    Console.WriteLine();
                    Console.WriteLine("Verbunden mit: " + r);
                    break;
                }
                catch (Exception ex)
                {
                    Console.WriteLine("  " + ex.Message);
                }
            }
            if (card == null)
            {
                Console.WriteLine();
                Console.WriteLine("Keine Karte im Leser gefunden. Karte einstecken und erneut starten.");
                return;
            }

            using (card)
            {
                Console.WriteLine("ATR: " + HexUtil.Hex(card.GetAtr()));
                Console.WriteLine();

                byte[] resp = card.ExchangeAuto(Apdu.Select(new byte[] { 0x3F, 0x00 }, 0x00, 0x0C), true);
                Console.WriteLine("SELECT MF: SW=" + HexUtil.Sw(resp));

                resp = card.ExchangeAuto(Apdu.Select(new byte[] { 0x2F, 0x00 }, 0x02, 0x0C), true);
                Console.WriteLine("SELECT EF.DIR: SW=" + HexUtil.Sw(resp));
                List<byte[]> dirAids = new List<byte[]>();
                if (HexUtil.Sw(resp) == "9000")
                {
                    byte[] dirData = ReadWholeBinary(card, 1024);
                    if (dirData.Length == 0)
                    {
                        List<byte> rec = new List<byte>();
                        for (int recNum = 1; recNum <= 16; recNum++)
                        {
                            byte[] rr = card.ExchangeAuto(Apdu.ReadRecord(recNum, 0x04), true);
                            if (HexUtil.Sw(rr) != "9000")
                                break;
                            rec.AddRange(HexUtil.Data(rr));
                        }
                        dirData = rec.ToArray();
                    }
                    HexUtil.Dump(dirData, "EF.DIR");
                    dirAids = ParseDirAids(dirData);
                }

                List<byte[]> candidates = new List<byte[]>();
                foreach (byte[] a in dirAids)
                    candidates.Add(a);
                candidates.Add(new byte[] { 0xFF, 0x54, 0x41, 0x43, 0x48, 0x4F });
                candidates.Add(new byte[] { 0xA0, 0x00, 0x00, 0x00, 0x63, 0x54, 0x41, 0x43, 0x48, 0x4F });

                byte[] tachoAid = null;
                foreach (byte[] aid in candidates)
                {
                    byte[] r = card.ExchangeAuto(Apdu.Select(aid, 0x04, 0x0C), true);
                    Console.WriteLine();
                    Console.WriteLine("SELECT AID " + HexUtil.Hex(aid) + ": SW=" + HexUtil.Sw(r));
                    if (HexUtil.Sw(r) == "9000")
                    {
                        tachoAid = aid;
                        break;
                    }
                }

                if (tachoAid == null)
                {
                    Console.WriteLine();
                    Console.WriteLine("Tachograph-Anwendung nicht gefunden.");
                    return;
                }

                Console.WriteLine();
                Console.WriteLine("--- EF-Scan innerhalb der Anwendung ---");
                List<int> efs = new List<int>();
                for (int id = 0x0002; id <= 0x0005; id++)
                    efs.Add(id);
                for (int id = 0x0500; id <= 0x0525; id++)
                    efs.Add(id);
                efs.Add(0xC100);
                efs.Add(0x2F06);

                foreach (int id in efs)
                {
                    byte[] fileId = new byte[] { (byte)(id >> 8), (byte)(id & 0xFF) };
                    byte[] r = card.ExchangeAuto(Apdu.Select(fileId, 0x02, 0x0C), true);
                    string sw = HexUtil.Sw(r);
                    if (sw != "9000")
                        continue;
                    Console.WriteLine();
                    Console.WriteLine("EF " + id.ToString("X4") + " vorhanden (SELECT 9000)");
                    byte[] rb = card.ExchangeAuto(Apdu.ReadBinary(0, 32), true);
                    Console.WriteLine("  READ BINARY : SW=" + HexUtil.Sw(rb) + "  " + HexUtil.Hex(HexUtil.Data(rb), 0, 32));
                    byte[] rr = card.ExchangeAuto(Apdu.ReadRecord(1, 0x04), true);
                    Console.WriteLine("  READ RECORD: SW=" + HexUtil.Sw(rr) + "  " + HexUtil.Hex(HexUtil.Data(rr), 0, 32));
                }
            }
            Console.WriteLine();
            Console.WriteLine("Probe abgeschlossen.");
        }
    }
}
