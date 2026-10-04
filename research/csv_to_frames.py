"""Convert a CSV log into the frames.log format that `nk61p.py --replay` plays back."""
import csv
import sys

with open(sys.argv[2], "w", encoding="utf-8") as out:
    for r in csv.DictReader(open(sys.argv[1], encoding="utf-8")):
        out.write(f"{float(r['elapsed_s']):7.1f}  {r['raw']}\n")
