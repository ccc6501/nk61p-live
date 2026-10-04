"""Tests against frames captured from a real NK61P (see research/frames.log)."""
import unittest

from nk61p_protocol import FrameSplitter, decode


def f(hexstr):
    return bytes.fromhex(hexstr)


IDLE_VDC = f("aa 55 52 24 01 10 5f 5f df 5f 24 00 00 00 00 00 00 00 20 01 00 08")
V_5195 = f("aa 55 52 24 01 10 3d 3f 86 3d 24 ff ff ff ff ff ff 03 20 01 00 08")
V_NEG = f("aa 55 52 24 01 10 36 3f 86 3d 2c ff ff ff ff ff ff 03 20 01 00 08")
REL_ON_5V = f("aa 55 52 24 01 10 5f 5f df 5f 24 ff ff ff ff ff ff 03 80 01 00 08")  # REL pressed at 5.19 V
VAC = f("aa 55 52 24 01 10 3d 36 b6 5f 22 0f 00 00 00 00 00 00 20 01 00 08")
MV = f("aa 55 52 24 01 10 5f df 5f 5f 04 00 00 00 00 00 00 00 20 01 00 0a")
OHM_OL = f("aa 55 52 24 01 10 00 58 df 00 20 ff ff ff ff ff ff ff 2f 01 00 50")
OHM_47K = f("aa 55 52 24 01 10 3d bf 07 36 20 ff ff ff ff ff 3f 00 20 01 00 50")
DIODE = f("aa 55 52 24 01 10 00 58 df 00 21 ff ff ff 7f 00 00 00 00 01 00 08")

# From the guided mode sweep (logs/nk61p_20261003_235359.csv), checked against LCD photos.
MANUAL_RANGE = f("aa 55 52 24 01 10 06 5f df 5f 24 00 00 00 00 00 00 00 00 01 00 08")
MAX = f("aa 55 52 24 01 10 6b 5f df 5f 24 00 00 00 00 00 00 00 00 03 00 08")
MIN = f("aa 55 52 24 01 10 6b 5f df 5f 2c 00 00 00 00 00 00 00 00 09 00 08")
MAXMIN = f("aa 55 52 24 01 10 3d 5f df 5f 24 00 00 00 00 00 00 00 00 0f 00 08")
DUTY = f("aa 55 52 24 01 10 df 5f 00 00 00 00 00 00 00 00 00 00 20 21 00 00")
HZ = f("aa 55 52 24 01 10 2f 7d df 7f 20 ff ff ff ff ff ff ff 2f 01 00 80")
CAP_NF = f("aa 55 52 24 01 10 06 6b df 5f 20 00 00 00 00 00 00 00 20 01 c0 00")
TEMP_C = f("aa 55 52 24 01 10 6b 6b 00 00 00 00 00 00 00 00 00 00 00 01 01 00")
TEMP_F = f("aa 55 52 24 01 10 06 07 00 00 00 00 00 00 00 00 00 00 00 01 02 00")
HFE = f("aa 55 52 24 01 10 5f 00 00 00 00 00 00 00 00 00 00 00 00 41 00 00")
UA_DC = f("aa 55 52 24 01 10 df 5f 00 00 24 00 00 00 00 00 00 00 20 01 00 05")
UA_AC = f("aa 55 52 24 01 10 df 5f 00 00 22 00 00 00 00 00 00 00 20 01 00 05")
MA_DC = f("aa 55 52 24 01 10 5f df 5f 00 24 00 00 00 00 00 00 00 20 01 00 06")
A_DC = f("aa 55 52 24 01 10 5f 5f df 5f 24 00 00 00 00 00 00 00 20 01 00 04")
CONT_OL = f("aa 55 52 24 01 10 80 58 5f 00 60 ff ff ff ff ff ff ff 0f 01 00 40")
OHM_SHORT = f("aa 55 52 24 01 10 fd 5f 00 00 20 00 00 00 00 00 00 00 20 01 00 40")


class DecodeTests(unittest.TestCase):
    def test_idle_dc_volts(self):
        r = decode(IDLE_VDC)
        self.assertEqual(r.display, "0.000")
        self.assertEqual(r.value, 0.0)
        self.assertEqual((r.prefix, r.unit), ("", "V"))
        self.assertTrue({"DC", "AUTO", "USB"} <= set(r.flags))
        self.assertEqual(r.mode, "DC V")
        self.assertEqual(r.bar, 0)
        self.assertEqual(r.unknown_bits, {})

    def test_usb_5v_reading(self):
        r = decode(V_5195)
        self.assertEqual(r.display, "5.195")
        self.assertAlmostEqual(r.value, 5.195)
        self.assertEqual(r.bar, 50)

    def test_negative(self):
        r = decode(V_NEG)
        self.assertEqual(r.display, "-5.194")
        self.assertAlmostEqual(r.value, -5.194)

    def test_rel(self):
        r = decode(REL_ON_5V)
        self.assertIn("REL", r.flags)
        self.assertNotIn("AUTO", r.flags)
        self.assertEqual(r.display, "0.000")
        self.assertEqual(r.bar, 50)   # the bar keeps showing the absolute value

    def test_ac(self):
        r = decode(VAC)
        self.assertEqual(r.mode, "AC V")
        self.assertAlmostEqual(r.value, 0.445)

    def test_millivolts(self):
        r = decode(MV)
        self.assertEqual(r.display, "00.00")
        self.assertEqual(r.mode, "DC mV")
        self.assertEqual(r.base_value, 0.0)

    def test_ohms_overload(self):
        r = decode(OHM_OL)
        self.assertTrue(r.overload)
        self.assertIsNone(r.value)
        self.assertEqual((r.prefix, r.unit), ("M", "Ω"))
        self.assertEqual(r.bar, 60)

    def test_ohms_value(self):
        r = decode(OHM_47K)
        self.assertEqual(r.display, "47.95")
        self.assertAlmostEqual(r.base_value, 47.95e6)

    def test_diode(self):
        r = decode(DIODE)
        self.assertEqual(r.mode, "Diode")
        self.assertTrue(r.overload)

    def test_manual_range_drops_auto(self):
        r = decode(MANUAL_RANGE)
        self.assertNotIn("AUTO", r.flags)
        self.assertIn("USB", r.flags)

    def test_max_min_cycle(self):
        maxmin_flags = {"MAX", "MIN", "MAXMIN"}
        self.assertEqual(maxmin_flags & set(decode(MAX).flags), {"MAX"})
        self.assertEqual(maxmin_flags & set(decode(MIN).flags), {"MIN"})
        self.assertTrue({"MAX", "MIN", "MAXMIN"} <= set(decode(MAXMIN).flags))

    def test_duty_cycle(self):
        r = decode(DUTY)
        self.assertEqual((r.unit, r.mode), ("%", "Duty %"))
        self.assertNotIn("BAR", r.flags)

    def test_frequency(self):
        r = decode(HZ)
        self.assertEqual((r.prefix, r.unit, r.display), ("", "Hz", "8.063"))

    def test_capacitance(self):
        r = decode(CAP_NF)
        self.assertEqual(r.mode, "Capacitance nF")
        self.assertAlmostEqual(r.base_value, 0.021e-9)

    def test_temperature(self):
        c, f_ = decode(TEMP_C), decode(TEMP_F)
        self.assertEqual((c.display, c.unit, c.mode), ("22", "°C", "Temp °C"))
        self.assertEqual((f_.display, f_.unit), ("71", "°F"))

    def test_hfe(self):
        r = decode(HFE)
        self.assertEqual((r.display, r.unit, r.mode), ("0", "hFE", "hFE"))

    def test_current_modes(self):
        self.assertEqual(decode(UA_DC).mode, "DC µA")
        self.assertEqual(decode(UA_AC).mode, "AC µA")
        self.assertEqual(decode(MA_DC).mode, "DC mA")
        self.assertEqual(decode(A_DC).mode, "DC A")
        self.assertEqual(decode(UA_DC).prefix, "u")

    def test_continuity_and_short(self):
        self.assertEqual(decode(CONT_OL).mode, "Continuity")
        self.assertTrue(decode(CONT_OL).overload)
        r = decode(OHM_SHORT)
        self.assertEqual((r.display, r.unit), ("0.6", "Ω"))

    def test_sweep_has_no_unmapped_bits(self):
        for frame in (MANUAL_RANGE, MAX, MIN, MAXMIN, DUTY, HZ, CAP_NF, TEMP_C, TEMP_F, HFE,
                      UA_DC, UA_AC, MA_DC, A_DC, CONT_OL, OHM_SHORT, REL_ON_5V, DIODE):
            self.assertEqual(decode(frame).unknown_bits, {}, frame.hex(" "))

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            decode(b"\x00" * 22)


class SplitterTests(unittest.TestCase):
    def test_resync_across_chunks(self):
        s = FrameSplitter()
        stream = b"\x12\x34" + IDLE_VDC + V_5195[:7]
        frames = list(s.feed(stream))
        frames += list(s.feed(V_5195[7:] + b"\xaa"))
        self.assertEqual(frames, [IDLE_VDC, V_5195])


if __name__ == "__main__":
    unittest.main()
