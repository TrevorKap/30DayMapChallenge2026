"""Aurora probability grid, Sep 2026 - Sep 2031.

Analog method: Solar Cycle 25 peaked Oct 2024, so the next 5 years are cycle years +1.93..+6.93.
Replay the same phase of cycles 17-24 (40 analog years) against the real 3-hourly Kp record and ask,
for every 1-degree cell: on how many dark local nights would Kp have been high enough to see aurora?

Run fetch_kp.py first (-> kp.npz), then `python build.py` (-> data.json).
"""
import json
import numpy as np

# SILSO smoothed sunspot maxima (cycle 17..24); cycle 25 = Oct 2024
MAXIMA = ["1937-04-15", "1947-05-15", "1958-03-15", "1968-11-15", "1979-12-15", "1989-11-15", "2001-11-15", "2014-04-15"]
C25_MAX, NOW = np.datetime64("2024-10-15"), np.datetime64("2026-09-19")
OFFSET_D = int((NOW - C25_MAX) / np.timedelta64(1, "D"))      # days since max at the start of the window
STEPS = 2922                                                   # 365.25 d * 8 three-hour intervals

# Visibility rule. Oval equatorward edge (deg geomagnetic lat) ~ 66.5 - 2.07*Kp (Starkov 1994 / NOAA rule of thumb);
# LEVELS = how far equatorward of that edge you may stand (3 deg ~ 330 km: faint glow low on the horizon). Needs sun < -12 deg.
LEVELS = [3.0, 0.0, -3.0]   # glow on the horizon / oval edge over you (clear display) / 3 deg inside the oval (overhead)
POLE_LAT, POLE_LON = np.radians(80.7), np.radians(-72.7)       # centred-dipole geomagnetic pole, ~2025
MLT_HALF = 4                                                   # oval is farthest equatorward within +-4 h of magnetic midnight

vec = lambda lat, lon: np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat) + 0 * lon], -1)
zm = vec(POLE_LAT, POLE_LON)                                   # dipole frame: z = magnetic axis, x toward geographic north
xm = np.array([0, 0, 1.0]) - zm[2] * zm
xm /= np.linalg.norm(xm)
ym = np.cross(zm, xm)
mlon = lambda v: np.arctan2(v @ ym, v @ xm)

d = np.load("kp.npz")
t, kp = d["t"].astype("datetime64[m]"), d["k"]

lats = np.arange(25, 90)
lons = np.arange(-180, 180)
la = np.radians(lats)
windows = []
for m in MAXIMA:
    i0 = np.searchsorted(t, np.datetime64(m) + np.timedelta64(OFFSET_D, "D"))
    for j in range(5):
        s = i0 + j * STEPS
        windows.append(slice(s, s + STEPS))

p_year = np.zeros((len(LEVELS), len(lats), len(lons)))
nights = np.zeros_like(p_year)
for li, lon in enumerate(lons):
    lo = np.radians(lon)
    mlat = np.degrees(np.arcsin(np.sin(la) * np.sin(POLE_LAT) + np.cos(la) * np.cos(POLE_LAT) * np.cos(lo - POLE_LON)))
    cell = vec(la, lo + 0 * la)[:, None, :]
    k_need = [np.maximum((66.5 - h - mlat) / 2.07, 0)[:, None] for h in LEVELS]
    for w in windows:
        tw, kw = t[w], kp[w]
        day = (tw.astype("datetime64[D]") - tw.astype("datetime64[Y]")).astype(int) + 1
        dec = np.arcsin(np.sin(np.radians(-23.44)) * np.cos(2 * np.pi / 365.24 * (day + 10)))
        ut = (tw - tw.astype("datetime64[D]")).astype(int) / 60 + 1.5           # interval midpoint, UT hours
        cosH = np.cos(np.radians(15 * (ut - 12) + lon))
        sin_alt = np.sin(la)[:, None] * np.sin(dec) + np.cos(la)[:, None] * np.cos(dec) * cosH
        sun = mlon(vec(dec, np.radians(-15 * (ut - 12))))                          # magnetic longitude of subsolar point
        mlt = (12 + np.degrees(mlon(cell) - sun) / 15) % 24                        # (lats, T)
        base = (sin_alt < np.sin(np.radians(-12))) & (np.abs(mlt - 24 * (mlt > 12)) <= MLT_HALF)
        night = np.floor((tw.astype("datetime64[D]").astype(int) * 24 + ut + lon / 15 - 12) / 24)  # local noon-to-noon night id
        starts = np.r_[0, np.flatnonzero(np.diff(night)) + 1]
        for q, kn in enumerate(k_need):
            n = np.logical_or.reduceat(base & (kw >= kn), starts, axis=1).sum(axis=1)
            nights[q, :, li] += n
            p_year[q, :, li] += n > 0
p_year /= len(windows)
nights /= len(windows)

frac = lambda th: float((np.concatenate([kp[w] for w in windows]) >= th).mean())
out = dict(lat0=int(lats[0]), lon0=int(lons[0]), nlat=len(lats), nlon=len(lons), levels=LEVELS,
           p=[np.round(x * 1000).astype(int).ravel().tolist() for x in p_year],
           n=[np.round(x * 10).astype(int).ravel().tolist() for x in nights],
           years=len(windows), kp5=frac(5), kp7=frac(7), kp8=frac(8), kpall5=float((kp >= 5).mean()))
json.dump(out, open("data.json", "w"), separators=(",", ":"))

for name, la_, lo_ in [("Fairbanks", 64.8, -147.7), ("Tromso", 69.6, 19), ("Reykjavik", 64.1, -21.9), ("Edinburgh", 55.95, -3.2),
                       ("Minneapolis", 44.98, -93.3), ("New York", 40.7, -74), ("London", 51.5, -0.1), ("Denver", 39.7, -105), ("Miami", 25.8, -80.2)]:
    a, b = int(round(la_)) - lats[0], int(round(lo_)) - lons[0]
    print(f"{name:12s} P(>=1/yr)={np.round(p_year[:, a, b], 2)}  nights/yr={np.round(nights[:, a, b], 1)}  5yr={np.round(1 - (1 - p_year[:, a, b]) ** 5, 2)}")
print("Kp>=5 share of intervals: analog", out["kp5"], "all-time", out["kpall5"], "| >=7", out["kp7"], ">=8", out["kp8"])
