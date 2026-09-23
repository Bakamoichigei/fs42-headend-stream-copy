"""Byte-exact checks against the fixtures in PrevueCLI's CommandEncodingTests.swift."""
import datetime
import unittest

from fs42.prevue import protocol as P


def hx(s):
    return bytes.fromhex(s.replace(" ", ""))


class TestPrevueProtocol(unittest.TestCase):

    def test_box_and_reset(self):
        self.assertEqual(P.box_on("*"), hx("55AA412A0094"))
        self.assertEqual(P.box_off(), hx("55AABBBB00FF"))
        self.assertEqual(P.reset(), hx("55AA5200AD"))

    def test_title(self):
        self.assertEqual(P.title("    THIS IS A TEST FROM UNITED VIDEO   "), hx(
            "55AA542020202054484953204953204120544553542046524F4D20554E4954454420564944454F2020200080"))
        self.assertEqual(P.title("THIS IS A TEST FROM UNITED VIDEO", "center"), hx(
            "55AA541854484953204953204120544553542046524F4D20554E4954454420564944454F00B8"))

    def test_clock(self):
        # fixture: Friday, month index 2, day index 4, year 120, 07:00:00, DST -> Fri March 5 2020
        # (PrevueCLI's fixture is hand-built; Mar 5 2020 was really a Thursday, so build via frame)
        self.assertEqual(P.frame(ord("K"), bytes([5, 2, 4, 120, 7, 0, 0, 1, 0])),
                         hx("55 AA 4B 05 02 04 78 07 00 00 01 00 C9"))
        # the datetime encoder: Friday March 6 2020 07:00 -> 05 02 05 78 07 00 00 01 00
        body = hx("55 AA 4B 05 02 05 78 07 00 00 01 00")
        self.assertEqual(P.clock(datetime.datetime(2020, 3, 6, 7, 0, 0), dst=True),
                         body + bytes([P.checksum(body)]))

    def test_channels(self):
        chans = [dict(source_id="WPVI", number="6", call_letters="6ABC", flags=P.CH_HILITE),
                 dict(source_id="SOUP", number="7", call_letters="7SOUP", flags=P.CH_NONE)]
        self.assertEqual(P.channels(138, chans), hx(
            "55 AA 43 8A 12 02 57 50 56 49 11 36 01 36 41 42 43 12 01 53 4F 55 50 11 37 01 37 53 4F 55 50 00 6D"))

    def test_timeslot_mask(self):
        self.assertEqual(P.timeslot_mask([]), bytes([0xFF] * 6))
        self.assertEqual(P.timeslot_mask([2, 3, 4, 5, 6, 7, 8]), bytes([0x80] + [0xFF] * 5))
        self.assertEqual(P.timeslot_mask([45, 46, 47, 48]), bytes([0xFF] * 5 + [0xF0]))

    def test_program(self):
        self.assertEqual(P.program(138, 1, "WPVI", "Action News"), hx(
            "55 AA 50 01 8A 57 50 56 49 12 01 41 63 74 69 6F 6E 20 4E 65 77 73 00 1E"))

    def test_configuration(self):
        self.assertEqual(P.configuration(timezone=5), hx(
            "55 AA 46 42 45 33 33 36 36 4E 01 01 35 59 59 4E 4E 4E 59 41 4E 4E 00 00 93"))

    def test_new_look_configuration(self):
        self.assertEqual(P.new_look_configuration("grid", "S", 1), hx(
            "55 AA 66 00 00 36 32 43 30 31 30 38 30 38 47 4E 41 45 30 31 4E 4E 4E 4E 4E 4E 4C 32 39 30 36 "
            "59 59 59 32 33 33 36 30 36 30 31 35 31 30 30 59 4E 59 43 8E 38 53 4E 4E 4E 4E 31 00 15"))

    def test_local_ads(self):
        self.assertEqual(P.local_ads_reset(), hx("55 AA 4C 92 00 21"))
        self.assertEqual(P.local_ad(1, ["        BEFORE YOU VIEW, PREVUE!"]), hx(
            "55 AA 4C 01 20 20 20 20 20 20 20 20 42 45 46 4F 52 45 20 59 4F 55 20 56 49 45 57 2C 20 "
            "50 52 45 56 55 45 21 00 C9"))
        self.assertEqual(P.local_ad(2, [("PREVUE GUIDE", "center"), ("WE ARE WHAT'S ON", "center")]), hx(
            "55 AA 4C 02 18 50 52 45 56 55 45 20 47 55 49 44 45 18 57 45 20 41 52 45 20 57 48 41 54 27 53 "
            "20 4F 4E 00 D1"))
        self.assertEqual(P.local_ad(4, [("TARGET YOUR AUDIENCE WITH CABLE", "center"),
                                        ("TELEVISION. CALL COMCAST NOW AT", "center"),
                                        ("215-639-2330", "center")], (24, 48)), hx(
            "55 AA 4C 04 18 54 41 52 47 45 54 20 59 4F 55 52 20 41 55 44 49 45 4E 43 45 20 57 49 54 48 20 "
            "43 41 42 4C 45 18 54 45 4C 45 56 49 53 49 4F 4E 2E 20 43 41 4C 4C 20 43 4F 4D 43 41 53 54 20 "
            "4E 4F 57 20 41 54 18 32 31 35 2D 36 33 39 2D 32 33 33 30 14 18 30 00 F3"))
        self.assertEqual(P.color_local_ad(5, [("Always think ", None, None),
                                              ("Prevue ", None, ("grey", "yellow")),
                                              ("first!", None, ("lightBlue", "red"))]), hx(
            "55 AA 74 05 41 6C 77 61 79 73 20 74 68 69 6E 6B 20 03 36 33 50 72 65 76 75 65 20 03 35 34 "
            "66 69 72 73 74 21 00 91"))

    def test_dst(self):
        self.assertEqual(P.dst_raw((1996, 301, 2, 0), (1997, 96, 2, 0), "local"), hx(
            "55 AA 67 32 32 37 04 31 39 39 36 33 30 31 30 32 3A 30 30 13 31 39 39 37 30 39 36 30 32 3A 30 30 00 B4"))
        self.assertEqual(P.dst_raw((1996, 301, 2, 0), (1997, 96, 2, 0), "global"), hx(
            "55 AA 67 33 32 37 04 31 39 39 36 33 30 31 30 32 3A 30 30 13 31 39 39 37 30 39 36 30 32 3A 30 30 00 B5"))

    def test_time_helpers(self):
        t = datetime.datetime(2026, 9, 23, 5, 0)
        self.assertEqual(P.timeslot(t), 1)
        self.assertEqual(P.timeslot(datetime.datetime(2026, 9, 23, 4, 59)), 48)
        self.assertEqual(P.timeslot(datetime.datetime(2026, 9, 23, 20, 15)), 31)
        self.assertEqual(P.julian_day(datetime.datetime(2026, 9, 24, 2, 0)), 266 % 256)  # still Sept 23's listings day


if __name__ == "__main__":
    unittest.main()
