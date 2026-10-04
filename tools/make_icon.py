"""Draws nk61p.ico (the desktop launcher icon): a dark meter body, grey-green LCD, red dial."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

d.rounded_rectangle((34, 8, 222, 248), radius=34, fill=(35, 38, 44), outline=(10, 11, 13), width=6)
d.rounded_rectangle((54, 30, 202, 104), radius=10, fill=(183, 191, 170))
# Three chunky 7-segment-ish bars standing in for digits
ink = (27, 31, 23)
for x in (72, 112, 152):
    d.rectangle((x, 46, x + 30, 54), fill=ink)
    d.rectangle((x, 64, x + 30, 72), fill=ink)
    d.rectangle((x, 82, x + 30, 90), fill=ink)
    d.rectangle((x + 24, 46, x + 30, 90), fill=ink)
d.ellipse((78, 124, 178, 224), fill=(196, 54, 44), outline=(10, 11, 13), width=5)
d.rounded_rectangle((120, 128, 136, 176), radius=6, fill=(241, 242, 244))

out = Path(__file__).resolve().parent.parent / "nk61p.ico"
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out)
