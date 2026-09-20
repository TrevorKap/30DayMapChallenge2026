"""London viewshed pipeline.
  python build_viewshed.py fetch   # EA LiDAR composite DSM/DTM -> 20 m grids (cached, ~15 min)
  python build_viewshed.py build   # ray-cast viewsheds, reproject to Web Mercator PNGs + manifest
Env: VS_CACHE = tile cache dir (default ./_tiles)
"""
import io, json, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, requests
from PIL import Image
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get("VS_CACHE", os.path.join(HERE, "_tiles"))
OUT = os.path.join(HERE, "data")
EA = "https://environment.data.gov.uk/spatialdata/lidar-composite-{}-2m/wcs"
COV = {"dsm": ("digital-surface-model-last-return-dsm", "f083c5dc-504f-4428-9811-a1b2519fa279__Lidar_Composite_Elevation_LZ_DSM_2m"),
       "dtm": ("digital-terrain-model-dtm", "09ea3b37-df3a-4e8b-ac69-fb0842227b04__Lidar_Composite_Elevation_DTM_2m")}

# Domain in British National Grid (EPSG:27700), 20 m cells
E0, E1, N0, N1, CELL, TILE = 510000, 552000, 162000, 198000, 20, 2000
W, H = (E1 - E0) // CELL, (N1 - N0) // CELL
K_REFRACT, R_EARTH = 0.13, 6371000.0
PCTS = (50, 75, 90)  # DSM cell height percentiles cached by fetch; analysis uses the median
TARGET_M = 10  # "visible" = the top of a structure this tall (about three storeys) standing in the cell can be seen

# id, name, lat, lon, kind, eye height above ground (m), clear radius around the viewpoint (m)
VIEWPOINTS = [
    ("primrose", "Primrose Hill", 51.5395, -0.1608, "hill", 1.7, 30),
    ("parliament", "Parliament Hill", 51.5600, -0.1533, "hill", 1.7, 30),
    ("alexandra", "Alexandra Palace", 51.5930, -0.1305, "hill", 1.7, 30),
    ("greenwich", "Greenwich Park", 51.4770, -0.0006, "hill", 1.7, 30),
    ("crystal", "Crystal Palace", 51.4230, -0.0752, "hill", 1.7, 30),
    ("shooters", "Shooters Hill", 51.4735, 0.0700, "hill", 1.7, 30),
    ("shard", "The Shard", 51.5045, -0.0865, "tower", 244, 70),
    ("skygarden", "Sky Garden", 51.5111, -0.0836, "tower", 155, 50),
    ("eye", "London Eye", 51.5033, -0.1196, "tower", 135, 80),
    ("stpauls", "St Paul's Golden Gallery", 51.5138, -0.0984, "tower", 85, 40),
    ("canary", "One Canada Square", 51.5049, -0.0195, "tower", 235, 60),
]


def fetch_tile(kind, e, n):
    f = os.path.join(CACHE, f"{'dsmp' if kind == 'dsm' else kind}_{e}_{n}.npy")
    if os.path.exists(f):
        return
    slug, cid = COV[kind]
    p = {"service": "WCS", "version": "2.0.1", "request": "GetCoverage", "coverageId": cid,
         "format": "image/tiff", "subset": [f"E({e},{e+TILE})", f"N({n},{n+TILE})"]}
    n_px = TILE // CELL
    if kind == "dtm":
        p["scalesize"] = f"i({n_px}),j({n_px})"  # smooth surface, server-side 20 m is fine
    for attempt in range(6):
        try:
            r = requests.get(EA.format(slug), params=p, timeout=240)
            r.raise_for_status()
            a = np.array(Image.open(io.BytesIO(r.content)), dtype=np.float32)
            break
        except Exception:
            time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"tile {kind} {e} {n} failed")
    a[~np.isfinite(a) | (a < -50)] = np.nan
    if kind == "dsm":  # 10x10 blocks of 2 m px -> p50/p75/p90 of the hundred heights, stacked
        b = a.reshape(n_px, 10, n_px, 10).transpose(0, 2, 1, 3).reshape(n_px, n_px, 100)
        b = np.where(np.isnan(b), -1e9, b)
        a = np.stack([np.partition(b, q, axis=-1)[..., q] for q in PCTS])
        a[a < -1e8] = np.nan
    np.save(f, a.astype(np.float32))


def stage_fetch():
    os.makedirs(CACHE, exist_ok=True)
    jobs = [(k, e, n) for k in ("dtm", "dsm") for e in range(E0, E1, TILE) for n in range(N0, N1, TILE)]
    done = 0
    with ThreadPoolExecutor(6) as ex:
        for _ in ex.map(lambda j: fetch_tile(*j), jobs):
            done += 1
            if done % 25 == 0:
                print(f"{done}/{len(jobs)}", flush=True)
    print("fetch done")


def load_grid(kind, q=50):
    g = np.full((H, W), np.nan, np.float32)
    t = TILE // CELL
    for e in range(E0, E1, TILE):
        for n in range(N0, N1, TILE):
            a = np.load(os.path.join(CACHE, f"{'dsmp' if kind == 'dsm' else kind}_{e}_{n}.npy"))
            if kind == "dsm":
                a = a[PCTS.index(q)]
            r0 = (N1 - n - TILE) // CELL  # tile rows run north -> south
            g[r0:r0 + t, (e - E0) // CELL:(e - E0) // CELL + t] = a
    return g


def viewshed(Z, Zt, cx, cy, eye, r0_cells, rng_cells=2000, step=0.5):
    """Ray-march from cell (cx,cy). Z = obstacle surface, Zt = height of the thing we test for visibility. Returns bool grid."""
    vis = np.zeros(Z.shape, bool)
    n_rays = int(2 * math.pi * rng_cells)
    steps = np.arange(r0_cells, rng_cells, step, dtype=np.float32)
    d_m = steps * CELL
    curv = (d_m ** 2) * (1 - K_REFRACT) / (2 * R_EARTH)  # earth-curvature drop, refraction-corrected
    for s in range(0, n_rays, 400):
        th = np.arange(s, min(s + 400, n_rays), dtype=np.float32) * (2 * math.pi / n_rays)
        x = np.rint(cx + np.cos(th)[:, None] * steps).astype(np.int32)
        y = np.rint(cy - np.sin(th)[:, None] * steps).astype(np.int32)
        ok = (x >= 0) & (x < W) & (y >= 0) & (y < H)
        yi, xi = np.clip(y, 0, H - 1), np.clip(x, 0, W - 1)
        obst = (np.where(ok, Z[yi, xi], -1e4) - curv - eye) / d_m
        targ = (np.where(ok, Zt[yi, xi], -1e4) - curv - eye) / d_m
        blocked_by = np.maximum.accumulate(obst, axis=1)  # tallest angle so far, including this cell
        blocked_by = np.concatenate([np.full((len(th), 1), -9, np.float32), blocked_by[:, :-1]], axis=1)  # ...excluding this cell
        seen = (targ >= blocked_by) & ok
        vis[y[seen], x[seen]] = True
    return vis


def stage_build():
    dsm, dtm = load_grid("dsm", 50), load_grid("dtm")
    print("nan dsm/dtm:", np.isnan(dsm).mean(), np.isnan(dtm).mean())
    dtm = np.where(np.isnan(dtm), np.nanmedian(dtm), dtm)
    dsm = np.maximum(np.where(np.isnan(dsm), dtm, dsm), dtm)  # water/no-return cells fall back to bare earth
    to_bng = Transformer.from_crs(4326, 27700, always_xy=True)
    to_ll = Transformer.from_crs(27700, 4326, always_xy=True)
    masks = {"built": np.zeros((H, W), np.uint16), "bare": np.zeros((H, W), np.uint16)}
    yy, xx = np.mgrid[0:H, 0:W]
    vps = []
    for i, (vid, name, lat, lon, kind, h, clear_m) in enumerate(VIEWPOINTS):
        e, n = to_bng.transform(lon, lat)
        cx, cy = int((e - E0) // CELL), int((N1 - n) // CELL)
        if kind == "hill":  # snap to the local summit (bare earth) within 200 m
            r = 10
            sub = dtm[cy - r:cy + r + 1, cx - r:cx + r + 1]
            dy, dx = np.unravel_index(np.argmax(sub), sub.shape)
            cx, cy = cx - r + dx, cy - r + dy
        ground = float(dtm[cy - 1:cy + 2, cx - 1:cx + 2].mean())
        eye = ground + h
        lon2, lat2 = to_ll.transform(E0 + (cx + .5) * CELL, N1 - (cy + .5) * CELL)
        row = {"id": vid, "name": name, "kind": kind, "lat": round(lat2, 5), "lon": round(lon2, 5),
               "ground_m": round(ground, 1), "eye_above_ground_m": h}
        for mode, Z in (("built", dsm), ("bare", dtm)):
            t = time.time()
            Zt = np.maximum(Z, dtm + TARGET_M)
            vis = viewshed(Z, Zt, cx + .5, cy + .5, eye, clear_m / CELL)
            masks[mode][vis] |= np.uint16(1 << i)
            dist = np.hypot(xx[vis] - cx, yy[vis] - cy) * CELL / 1000
            row[mode] = {"km2": round(vis.sum() * CELL * CELL / 1e6, 1), "far_km": round(float(dist.max()), 1)}
            print(f"{name:26s} {mode:5s} ground {ground:6.1f}m  visible {row[mode]['km2']:7.1f} km2  far {row[mode]['far_km']:5.1f} km  ({time.time()-t:.1f}s)", flush=True)
        vps.append(row)

    # ---- reproject to a Web Mercator display grid (nearest cell), pack 11 bits -> R,G; G bit 7 = inside domain
    to_3857 = Transformer.from_crs(27700, 3857, always_xy=True)
    from_3857 = Transformer.from_crs(3857, 27700, always_xy=True)
    ts = np.linspace(0, 1, 50)
    ring = [(E0 + t * (E1 - E0), N0) for t in ts] + [(E1, N0 + t * (N1 - N0)) for t in ts] + \
           [(E1 - t * (E1 - E0), N1) for t in ts] + [(E0, N1 - t * (N1 - N0)) for t in ts]
    mx, my = to_3857.transform(*zip(*ring))
    px = 32.0
    x0, x1 = math.floor(min(mx) / px) * px, math.ceil(max(mx) / px) * px
    y0, y1 = math.floor(min(my) / px) * px, math.ceil(max(my) / px) * px
    Wd, Hd = int((x1 - x0) / px), int((y1 - y0) / px)
    gx, gy = np.meshgrid(x0 + (np.arange(Wd) + .5) * px, y1 - (np.arange(Hd) + .5) * px)
    be, bn = from_3857.transform(gx.ravel(), gy.ravel())
    col = np.floor((be - E0) / CELL).astype(int)
    row_ = np.floor((N1 - bn) / CELL).astype(int)
    inside = (col >= 0) & (col < W) & (row_ >= 0) & (row_ < H)
    col, row_ = np.clip(col, 0, W - 1), np.clip(row_, 0, H - 1)
    os.makedirs(OUT, exist_ok=True)
    popcount = np.array([bin(v).count("1") for v in range(1 << len(VIEWPOINTS))])
    hist, disp = {}, {}
    for mode, m in masks.items():
        v = np.where(inside, m[row_, col], 0).astype(np.uint16)
        img = np.zeros((Hd * Wd, 4), np.uint8)
        img[:, 0], img[:, 1], img[:, 2], img[:, 3] = v & 255, ((v >> 8) & 15) | (inside * 128), 0, 255
        Image.fromarray(img.reshape(Hd, Wd, 4), "RGBA").save(os.path.join(OUT, f"vis_{mode}.png"), optimize=True)
        hist[mode] = np.bincount(popcount[v[inside]], minlength=len(VIEWPOINTS) + 1).tolist()
    lo = Transformer.from_crs(3857, 4326, always_xy=True)
    corners = [lo.transform(x0, y1), lo.transform(x1, y1), lo.transform(x1, y0), lo.transform(x0, y0)]  # TL TR BR BL
    json.dump({"viewpoints": vps, "img": {"w": Wd, "h": Hd, "x0": x0, "y1": y1, "px": px, "corners": [[round(a, 5), round(b, 5)] for a, b in corners]},
               "domain_km2": round(W * H * CELL * CELL / 1e6), "target_m": TARGET_M, "display_cells": int(inside.sum()), "exposure_hist": hist,
               "built_at": time.strftime("%Y-%m-%d")}, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
    print("done", Wd, Hd)


if __name__ == "__main__":
    {"fetch": stage_fetch, "build": stage_build}[sys.argv[1]]()
