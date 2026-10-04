"""Collapse a CSV log into runs of identical annunciator/unit bytes (bytes 10, 18 high nibble, 19-21)."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nk61p_protocol import decode  # noqa: E402

rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
segs = []
for r in rows:
    b = bytes.fromhex(r["raw"].replace(" ", ""))
    sig = (b[10], b[18] & 0xF0, b[19], b[20], b[21])
    if not segs or segs[-1]["sig"] != sig:
        segs.append({"sig": sig, "t0": float(r["elapsed_s"]), "n": 0, "displays": [], "frame": b})
    s = segs[-1]
    s["n"] += 1
    s["t1"] = float(r["elapsed_s"])
    d = decode(b)
    if not s["displays"] or s["displays"][-1] != d.display:
        s["displays"].append(d.display)

for s in segs:
    d = decode(s["frame"])
    b10, b18, b19, b20, b21 = s["sig"]
    shown = " ".join(s["displays"][:4]) + (" ..." if len(s["displays"]) > 4 else "")
    print(f"{s['t0']:7.1f}-{s['t1']:6.1f} n={s['n']:<3} b10={b10:02x} b18={b18:02x} b19={b19:02x} "
          f"b20={b20:02x} b21={b21:02x} | {shown:<32} | {d.prefix}{d.unit} {' '.join(d.flags)} {d.unknown_bits or ''}")
