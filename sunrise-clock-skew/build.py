"""Rasterize current IANA time zones (timezone-boundary-builder 2026f, full tzid set)
to a 0.25 deg grid and tabulate each zone's UTC offset for every day of 2026.

Usage: python build.py path/to/combined.json
Outputs: data/tz.png (zone index in R + G*256, 0 = sea) and data/tz.json.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw

RES = 4  # cells per degree
W, H = 360 * RES, 180 * RES
YEAR = 2026
# tzdb's Asia/Urumqi (UTC+6) is informal Xinjiang time; the official clock is Beijing time.
OVERRIDE = {"Asia/Urumqi": "Asia/Shanghai"}

out = Path(__file__).parent / "data"
out.mkdir(exist_ok=True)
feats = json.load(open(sys.argv[1], encoding="utf-8"))["features"]

grid = np.zeros((H, W), np.uint16)
names = []


def px(ring):
    return [((x + 180) * RES, (90 - y) * RES) for x, y in ring]


# pass 1 outlines every zone so sub-cell islands survive; pass 2 fills interiors on top
for f in feats:
    names.append(f["properties"]["tzid"])
for outline in (True, False):
    for i, f in enumerate(feats, 1):
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        mask = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(mask)
        for p in polys:
            d.polygon(px(p[0]), fill=255, outline=255 if outline else None)
        for p in polys:
            for hole in p[1:]:
                d.polygon(px(hole), fill=0)
        grid[np.asarray(mask) > 0] = i

# offset change points per zone: [[dayIndex, minutes], ...], offset taken at local noon
zones = []
for n in names:
    tz = ZoneInfo(OVERRIDE.get(n, n))
    pts = []
    for day in range(365):
        t = datetime(YEAR, 1, 1, 12, tzinfo=tz) + timedelta(days=day)
        m = int(t.utcoffset().total_seconds() // 60)
        if not pts or pts[-1][1] != m:
            pts.append([day, m])
    zones.append({"id": n, "off": pts})

rgb = np.zeros((H, W, 3), np.uint8)
rgb[..., 0] = grid & 255
rgb[..., 1] = grid >> 8
Image.fromarray(rgb, "RGB").save(out / "tz.png", optimize=True)
json.dump({"res": RES, "year": YEAR, "zones": zones}, open(out / "tz.json", "w"), separators=(",", ":"))

assert len(names) < 65535
# self-check: Kashgar and Shanghai share Beijing time; Vigo and Belgrade share CET
def zone_at(lat, lon):
    return zones[grid[int((90 - lat) * RES), int((lon + 180) * RES)] - 1]

assert zone_at(39.47, 75.99)["off"][0][1] == zone_at(31.23, 121.47)["off"][0][1] == 480
assert zone_at(42.24, -8.72)["off"][0][1] == zone_at(44.8, 20.46)["off"][0][1] == 60
print(len(names), "zones;", (grid > 0).mean().round(3), "of cells on land")
