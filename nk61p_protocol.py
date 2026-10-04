"""Decoder for the NKTECH NK61P "USB Link" serial stream.

Reverse-engineered from captures (CH340 USB-serial, 2400 baud 8N1). The meter
streams a 22-byte frame several times per second that mirrors its LCD:

  0-1   aa 55          sync
  2-5   52 24 01 10    constant (model id?)
  6-9   digits, 7-segment, byte 9 = leftmost; bit 7 = decimal point LEFT of digit
  10    DC, AC, minus, diode, continuity, bar-graph-visible
  11-17 bar graph segments 1-56 (LSB first)
  18    low nibble = bar segments 57-60, high nibble = AUTO / REL icons
  19    USB, MAX, MIN, %, hFE
  20    °C, °F, F (farads), n
  21    µ, m, k, M, A, V, Ω, Hz

Every flag below was confirmed against a photo of the LCD taken in that mode.
HOLD never showed up in the stream. Anything not in the tables is reported
back as `unknown_bits` so it can be mapped later.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FRAME_LEN = 22
SYNC = b"\xaa\x55"

# Segment bits: a=0x01 b=0x02 c=0x04 d=0x08 f=0x10 g=0x20 e=0x40, dp=0x80
SEGMENTS = {
    0x5F: "0", 0x06: "1", 0x6B: "2", 0x2F: "3", 0x36: "4",
    0x3D: "5", 0x7D: "6", 0x07: "7", 0x7F: "8", 0x3F: "9",
    0x00: " ", 0x58: "L", 0x20: "-",
}

# (byte index, bit mask) -> annunciator name
FLAGS = {
    (10, 0x01): "DIODE",
    (10, 0x02): "AC",
    (10, 0x04): "DC",
    (10, 0x08): "MINUS",
    (10, 0x20): "BAR",        # analog bar graph shown (off in Temp, hFE, %)
    (10, 0x40): "CONTINUITY",
    (18, 0x20): "AUTO",
    (18, 0x80): "REL",
    (19, 0x01): "USB",
    (19, 0x02): "MAX",
    (19, 0x04): "MAXMIN",     # lit alongside MAX and MIN on the third MAX/MIN press
    (19, 0x08): "MIN",
    (19, 0x20): "PERCENT",
    (19, 0x40): "HFE",
    (20, 0x01): "DEG_C",
    (20, 0x02): "DEG_F",
    (20, 0x40): "FARAD",
    (20, 0x80): "n",
    (21, 0x01): "u",
    (21, 0x02): "m",
    (21, 0x04): "A",
    (21, 0x08): "V",
    (21, 0x10): "M",
    (21, 0x20): "k",
    (21, 0x40): "OHM",
    (21, 0x80): "HZ",
}

_KNOWN_MASK: dict[int, int] = {}
for (_idx, _bit) in FLAGS:
    _KNOWN_MASK[_idx] = _KNOWN_MASK.get(_idx, 0) | _bit
_KNOWN_MASK[18] = _KNOWN_MASK.get(18, 0) | 0x0F  # bar graph nibble

PREFIX = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}
UNITS = [("OHM", "Ω"), ("FARAD", "F"), ("HZ", "Hz"), ("V", "V"), ("A", "A"),
         ("PERCENT", "%"), ("HFE", "hFE"), ("DEG_C", "°C"), ("DEG_F", "°F")]
FLAG_BYTES = (10, 18, 19, 20, 21)


@dataclass
class Reading:
    display: str            # exactly what the LCD shows, e.g. "-5.195" or "0.L"
    value: float | None     # display value in displayed units; None when OL / unparseable
    base_value: float | None  # value scaled to the base SI unit (prefix applied)
    prefix: str             # "", "m", "k", ...
    unit: str               # "V", "Ω", ...
    flags: list[str]
    overload: bool
    bar: int                # analog bar segments lit, 0-60
    unknown_bits: dict[str, str] = field(default_factory=dict)
    raw: str = ""

    @property
    def mode(self) -> str:
        if "CONTINUITY" in self.flags:
            return "Continuity"
        if "DIODE" in self.flags:
            return "Diode"
        if self.unit in ("%", "hFE"):
            return "Duty %" if self.unit == "%" else "hFE"
        if self.unit in ("°C", "°F"):
            return f"Temp {self.unit}"
        prefix = "µ" if self.prefix == "u" else self.prefix   # stored as ASCII "u" for CSV safety
        if self.unit == "F":
            return f"Capacitance {prefix}F"
        coupling = "AC" if "AC" in self.flags else "DC" if "DC" in self.flags else ""
        return f"{coupling} {prefix}{self.unit}".strip()


def decode_digits(frame: bytes) -> str:
    text = ""
    for i in (9, 8, 7, 6):
        b = frame[i]
        if b & 0x80:
            text += "."
        text += SEGMENTS.get(b & 0x7F, "?")
    return text


def decode(frame: bytes) -> Reading:
    if len(frame) != FRAME_LEN or not frame.startswith(SYNC):
        raise ValueError(f"not an NK61P frame: {frame.hex(' ')}")

    digits = decode_digits(frame).strip()
    flags = [name for (idx, bit), name in FLAGS.items() if frame[idx] & bit]
    minus = "MINUS" in flags
    overload = "L" in digits

    prefix = next((p for p in PREFIX if p in flags), "")
    scale = PREFIX.get(prefix, 1.0)
    unit = next((u for f, u in UNITS if f in flags), "")
    if "DIODE" in flags:
        unit = "V"
    if "CONTINUITY" in flags:
        unit = "Ω"

    value = None
    if not overload and "?" not in digits:
        try:
            value = float(digits.replace(" ", ""))
            if minus:
                value = -value
        except ValueError:
            value = None
    base_value = value * scale if value is not None else None

    bar = sum(bin(x).count("1") for x in frame[11:18]) + bin(frame[18] & 0x0F).count("1")

    unknown = {}
    for idx in FLAG_BYTES:
        extra = frame[idx] & ~_KNOWN_MASK.get(idx, 0) & 0xFF
        if extra:
            unknown[f"b{idx}"] = f"0x{extra:02x}"

    display = ("-" if minus else "") + digits
    return Reading(display=display, value=value, base_value=base_value,
                   prefix=prefix, unit=unit, flags=flags, overload=overload,
                   bar=bar, unknown_bits=unknown, raw=frame.hex(" "))


class FrameSplitter:
    """Accumulates serial bytes and yields complete frames, resyncing on SYNC."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes):
        self._buf += data
        while True:
            i = self._buf.find(SYNC)
            if i < 0:
                self._buf = self._buf[-1:]  # keep a possible lone 0xaa
                return
            if len(self._buf) - i < FRAME_LEN:
                self._buf = self._buf[i:]
                return
            frame = self._buf[i:i + FRAME_LEN]
            self._buf = self._buf[i + FRAME_LEN:]
            yield frame
