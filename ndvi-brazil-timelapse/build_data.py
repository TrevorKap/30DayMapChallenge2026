"""Fetch MODIS Terra monthly NDVI (NASA GIBS) for Brazil -> data/ndvi.bin.gz + data/manifest.json.

Stdlib only. GIBS tiles are 8-bit indexed PNGs whose palette index ("ref") maps
exactly to an NDVI value via the layer colormap, so we keep the raw index byte.
Run: python build_data.py
"""
import gzip, json, math, re, struct, urllib.request, zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

Z = 5                                    # 32x32 tiles world, 256px each -> ~4.7 km/px at the equator
LON_W, LON_E, LAT_N, LAT_S = -74.2, -34.4, 5.6, -34.0   # mainland Brazil + margin
START, END = (2023, 1), (2026, 8)
BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_L3_NDVI_Monthly/default"
OUT = Path(__file__).parent / "data"


def world_px(lon, lat):
    n = 256 * 2 ** Z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


X0, Y0 = (int(v) for v in world_px(LON_W, LAT_N))
X1, Y1 = (math.ceil(v) for v in world_px(LON_E, LAT_S))
W, H = X1 - X0, Y1 - Y0
TX = range(X0 // 256, (X1 - 1) // 256 + 1)
TY = range(Y0 // 256, (Y1 - 1) // 256 + 1)


def get(url):
    for _ in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
    raise RuntimeError(url)


def decode_indexed_png(data):
    """8-bit palette PNG -> bytearray of 256*256 palette indices."""
    p, idat, w = 8, [], 0
    while p < len(data):
        n, t = struct.unpack(">I4s", data[p:p + 8])
        if t == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", data[p + 8:p + 18])
            assert depth == 8 and ctype == 3, "expected 8-bit indexed PNG"
        elif t == b"IDAT":
            idat.append(data[p + 8:p + 8 + n])
        p += 12 + n
    raw = zlib.decompress(b"".join(idat))
    out, prev = bytearray(), bytearray(w)
    for y in range(h):
        f, row = raw[y * (w + 1)], bytearray(raw[y * (w + 1) + 1:(y + 1) * (w + 1)])
        if f == 1:
            for i in range(1, w): row[i] = (row[i] + row[i - 1]) & 255
        elif f == 2:
            for i in range(w): row[i] = (row[i] + prev[i]) & 255
        elif f == 3:
            for i in range(w): row[i] = (row[i] + (((row[i - 1] if i else 0) + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(w):
                a, b, c = (row[i - 1] if i else 0), prev[i], (prev[i - 1] if i else 0)
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += row
        prev = row
    return out


def frame(date):
    grid = bytearray(W * H)              # 0 = no data
    for ty in TY:
        for tx in TX:
            png = get(f"{BASE}/{date}/GoogleMapsCompatible_Level7/{Z}/{ty}/{tx}.png")
            if not png:
                continue
            t = decode_indexed_png(png)
            for r in range(256):
                gy = ty * 256 + r - Y0
                if not 0 <= gy < H:
                    continue
                c0 = max(0, X0 - tx * 256)
                c1 = min(256, X1 - tx * 256)
                gx = tx * 256 + c0 - X0
                grid[gy * W + gx: gy * W + gx + (c1 - c0)] = t[r * 256 + c0: r * 256 + c1]
    return date, bytes(grid)


def months():
    y, m = START
    while (y, m) <= END:
        yield f"{y}-{m:02d}-01"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def ref_to_ndvi():
    xml = get("https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_L3_NDVI.xml").decode()
    tbl = [None] * 256
    for lo, hi, ref in re.findall(r'value="\[([-\d.]+),([-\d.]+)\)"[^>]*?ref="(\d+)"', xml):
        tbl[int(ref)] = round((float(lo) + float(hi)) / 2, 4)
    return tbl


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    print(f"grid {W}x{H}, tiles {len(TX)}x{len(TY)}, origin px ({X0},{Y0}) z{Z}")
    dates = list(months())
    with ThreadPoolExecutor(6) as ex:
        frames = []
        for d, g in ex.map(frame, dates):
            ok = sum(1 for v in g if v > 2)
            print(d, "valid px:", ok, flush=True)
            frames.append((d, g, ok))
    frames = [(d, g) for d, g, ok in frames if ok > 0.05 * W * H]   # drop months GIBS doesn't publish
    with gzip.open(OUT / "ndvi.bin.gz", "wb", 9) as f:
        for _, g in frames:
            f.write(g)
    (OUT / "manifest.json").write_text(json.dumps({
        "z": Z, "x0": X0, "y0": Y0, "w": W, "h": H,
        "dates": [d for d, _ in frames], "ndvi": ref_to_ndvi(),
    }))
    print("frames:", len(frames), "size:", (OUT / "ndvi.bin.gz").stat().st_size // 1024, "KB")
