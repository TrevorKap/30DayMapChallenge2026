"""Build the Cape Town constraint & opportunity model.

Inputs (all public, no auth):
  - Mapzen/Terrarium elevation tiles on AWS (global, ~30 m over South Africa)
  - ESA WorldCover 2021 (10 m land cover, AWS open data COG)
  - OpenStreetMap via Overpass: metro boundary, protected areas, water, rail + MyCiTi stops,
    parks/schools/cemeteries (land that is spoken for), commercial/industrial land, brownfield, runways
Model, per ~46 x 56 m cell:
  CONSTRAINT = 1 - prod(1 - cap_i * factor_i)   (protected, slope, flood/water table, coast, fire, airport)
  OPPORTUNITY = land availability (undeveloped, inside the urban matrix, not spoken for)
                x location (rail / MyCiTi access + nearby jobs)
Outputs -> data/{combined,constraints,opportunities}.png, data/grid.json, data/meta.json
"""
import base64, io, json, math, os, tempfile, time
import numpy as np
import requests
from PIL import Image, ImageChops, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter, label, binary_opening, uniform_filter, map_coordinates
import tifffile, zarr

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(tempfile.gettempdir(), "capetown_co_cache")
os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "30DayMappingChallenge2026-capetown/1.0 (cakapuvari@gmail.com)"}
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
WC_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_S36E018_Map.tif"
WC_ORIGIN = (18.0, -33.0)              # lon, lat of the tile's top-left corner
WC_PX = 1 / 12000                      # WorldCover pixel, degrees
K = 6                                  # 6 WorldCover px per model cell
DEG = K * WC_PX                        # 0.0005 deg cell

CAPS = dict(prot=1.00, slope=0.90, flood=0.80, coast=0.70, fire=0.55, air=0.60)   # max weight of each constraint
C_LO, C_T = 0.30, 0.40                 # constraint tint starts / "constrained" threshold
O_T = 0.28                             # opportunity threshold (after scaling)
NAMES_SKIP = ("Cape Floral", "Boland Mountain", "Biosphere", "Marine", "Controlled Zone")   # umbrella / sea designations
LANDMARKS = {
    "Table Mountain": (18.4098, -33.9628), "Lion's Head": (18.3893, -33.9359), "Cape Town CBD": (18.4222, -33.9248),
    "Salt River": (18.4645, -33.9285), "Paarden Eiland": (18.4700, -33.9055), "Century City": (18.5110, -33.8930),
    "Bellville": (18.6300, -33.9000), "Cape Town Airport": (18.6017, -33.9715), "Philippi": (18.5950, -34.0000),
    "Khayelitsha": (18.6663, -34.0393), "Mitchells Plain": (18.6200, -34.0500), "Muizenberg": (18.4700, -34.1080),
    "Hout Bay": (18.3590, -34.0490), "Table View": (18.4900, -33.8200), "Somerset West": (18.8430, -34.0780),
}


# ---------------------------------------------------------------- fetch helpers
def overpass(name, body, area=True):
    p = os.path.join(CACHE, name + ".json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))["elements"]
    q = "[out:json][timeout:600][maxsize:2000000000];" + ("area(3600079604)->.a;" if area else "") + body
    for attempt in range(8):
        ep = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(ep, data={"data": q}, headers=UA, timeout=700)
            if r.status_code == 200:
                open(p, "wb").write(r.content)
                return r.json()["elements"]
            print("  overpass", ep.split("/")[2], r.status_code)
        except Exception as e:
            print("  overpass", ep.split("/")[2], "error", str(e)[:60])
        time.sleep(10)
    raise SystemExit(f"Overpass failed for {name}")


def stitch(ways):
    """Join way point-lists into rings by matching end points."""
    pool, rings = [list(w) for w in ways if len(w) > 1], []
    while pool:
        cur = pool.pop()
        while cur[0] != cur[-1]:
            for i, w in enumerate(pool):
                if w[0] == cur[-1]: cur += w[1:]
                elif w[-1] == cur[-1]: cur += w[::-1][1:]
                elif w[-1] == cur[0]: cur = w[:-1] + cur
                elif w[0] == cur[0]: cur = w[::-1][:-1] + cur
                else: continue
                pool.pop(i)
                break
            else:
                break            # open ring (clipped at the boundary): keep as is
        rings.append(cur)
    return rings


def pts(geom):
    return [(p["lon"], p["lat"]) for p in geom]


def polys(el):
    """(outer rings, inner rings) of a way or multipolygon relation, as (lon, lat) lists."""
    if el["type"] == "way" and el.get("geometry"):
        return [pts(el["geometry"])], []
    if el["type"] == "relation":
        m = [x for x in el.get("members", []) if x["type"] == "way" and x.get("geometry")]
        return (stitch([pts(x["geometry"]) for x in m if x.get("role") != "inner"]),
                stitch([pts(x["geometry"]) for x in m if x.get("role") == "inner"]))
    return [], []


# ---------------------------------------------------------------- boundary -> grid
bound = overpass("boundary", "rel(79604);out geom;", area=False)
outer = [r for e in bound for r in polys(e)[0]]
main = [p for r in outer for p in r if p[1] > -35]                 # drop the Prince Edward Islands
W0 = 18.0 + math.floor((min(p[0] for p in main) - 18.0) / DEG) * DEG
E0 = W0 + math.ceil((max(p[0] for p in main) - W0) / DEG / 4) * DEG * 4           # width multiple of 4 cells
N0 = -33.0 - math.floor((-33.0 - max(p[1] for p in main)) / DEG) * DEG
S0 = N0 - math.ceil((N0 - min(p[1] for p in main)) / DEG / 4) * DEG * 4
NX, NY = round((E0 - W0) / DEG), round((N0 - S0) / DEG)
LAT_C = N0 - (np.arange(NY) + 0.5) * DEG
LON_C = W0 + (np.arange(NX) + 0.5) * DEG
MPP_Y = DEG * 111_320
MPP_X = DEG * 111_320 * math.cos(math.radians((N0 + S0) / 2))
SAMP = (MPP_Y, MPP_X)
CELL_KM2 = MPP_X * MPP_Y / 1e6
print(f"grid {NX} x {NY} cells, {MPP_X:.0f} x {MPP_Y:.0f} m, bbox {W0:.4f},{S0:.4f},{E0:.4f},{N0:.4f}")


def px(ring):
    a = np.asarray(ring, dtype=np.float64)
    return list(zip(((a[:, 0] - W0) / DEG).tolist(), ((N0 - a[:, 1]) / DEG).tolist()))


def raster_polys(els):
    """Boolean mask of the union of polygon features (holes respected)."""
    img = Image.new("L", (NX, NY), 0)
    d = ImageDraw.Draw(img)
    for e in els:
        outs, ins = polys(e)
        outs, ins = [r for r in outs if len(r) >= 3], [r for r in ins if len(r) >= 3]
        if not ins:
            for r in outs: d.polygon(px(r), fill=1)
        else:
            t = Image.new("L", (NX, NY), 0)
            td = ImageDraw.Draw(t)
            for r in outs: td.polygon(px(r), fill=1)
            for r in ins: td.polygon(px(r), fill=0)
            img = ImageChops.lighter(img, t)
            d = ImageDraw.Draw(img)
    return np.array(img, dtype=bool)


def raster_lines(els, width=1):
    img = Image.new("L", (NX, NY), 0)
    d = ImageDraw.Draw(img)
    for e in els:
        if e["type"] == "way" and e.get("geometry"):
            d.line(px(pts(e["geometry"])), fill=1, width=width)
    return np.array(img, dtype=bool)


def raster_points(lonlat):
    m = np.zeros((NY, NX), bool)
    for lon, lat in lonlat:
        c, r = int((lon - W0) / DEG), int((N0 - lat) / DEG)
        if 0 <= c < NX and 0 <= r < NY: m[r, c] = True
    return m


def dist_m(mask):
    return distance_transform_edt(~mask, sampling=SAMP).astype(np.float32) if mask.any() else np.full((NY, NX), 1e5, np.float32)


metro = raster_polys([e for e in bound if e["type"] == "relation"])

# ---------------------------------------------------------------- OSM layers
print("fetching OSM layers (cached after the first run) ...")
prot_els = [e for e in overpass("protected", '(nwr["boundary"="protected_area"](area.a);nwr["leisure"="nature_reserve"](area.a););out geom;')
            if e["type"] != "node" and not any(s in e.get("tags", {}).get("name", "") for s in NAMES_SKIP)]
water_els = overpass("water", '(way["waterway"~"^(river|canal)$"](area.a);nwr["natural"~"^(water|wetland)$"](area.a););out geom;')
excl_els = (overpass("excl_leisure", 'nwr["leisure"~"^(park|pitch|golf_course|sports_centre|stadium|recreation_ground|garden|common|track|horse_riding)$"](area.a);out geom;')
            + overpass("excl_landuse", '(nwr["landuse"~"^(cemetery|military|recreation_ground|allotments|reservoir|landfill|quarry|railway|village_green)$"](area.a);nwr["military"](area.a););out geom;')
            + overpass("excl_amenity", '(nwr["amenity"~"^(school|college|university|hospital|kindergarten|place_of_worship|grave_yard)$"](area.a);nwr["aeroway"~"^(aerodrome|apron|runway|taxiway)$"](area.a););out geom;'))
jobs_els = overpass("jobs", 'nwr["landuse"~"^(industrial|commercial|retail)$"](area.a);out geom;')
brown_els = overpass("brown", 'nwr["landuse"~"^(brownfield|construction)$"](area.a);out geom;')
rail_els = overpass("rail_lines", 'way["railway"="rail"](area.a);out geom;')
runway_els = overpass("runways", 'way["aeroway"="runway"](area.a);out geom;')
place_els = overpass("places", 'node["place"~"^(suburb|neighbourhood|town|village)$"](area.a);out;')
station_els = overpass("stations", '(nwr["railway"~"^(station|halt)$"](area.a););out center tags;')
route_els = overpass("myciti_routes", 'rel["route"="bus"]["network"~"MyCiTi|IRT",i](area.a);out geom;')
print(f"  {len(prot_els)} protected, {len(water_els)} water, {len(excl_els)} spoken-for, {len(jobs_els)} job-land, "
      f"{len(brown_els)} brownfield, {len(rail_els)} rail ways, {len(station_els)} stations, {len(route_els)} MyCiTi routes")

rail_pts = [((e.get("lon") or e["center"]["lon"]), (e.get("lat") or e["center"]["lat"])) for e in station_els
            if e.get("tags", {}).get("railway") in ("station", "halt")]
brt_pts, brt_lines = set(), []
for e in route_els:
    for m in e.get("members", []):
        if m["type"] == "node" and m.get("role", "").startswith(("stop", "platform")): brt_pts.add((m["lon"], m["lat"]))
        elif m["type"] == "way" and m.get("geometry") and not m.get("role"): brt_lines.append(pts(m["geometry"]))
places = [(e["lon"], e["lat"], e["tags"].get("name"), e["tags"]["place"]) for e in place_els if e.get("tags", {}).get("name")]
stations = sorted({(e["tags"].get("name"), (e.get("lon") or e["center"]["lon"]), (e.get("lat") or e["center"]["lat"])) for e in station_els
                   if e.get("tags", {}).get("railway") in ("station", "halt") and e["tags"].get("name")})

# ---------------------------------------------------------------- land cover (WorldCover 10 m -> 6x6 block fractions)
tif = os.path.join(CACHE, "worldcover_S36E018.tif")
if not os.path.exists(tif):
    print("downloading WorldCover tile (61 MB) ...")
    with requests.get(WC_URL, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tif, "wb") as f:
            for chunk in r.iter_content(1 << 20): f.write(chunk)
za = zarr.open(tifffile.imread(tif, aszarr=True), mode="r")
za = za["0"] if isinstance(za, zarr.Group) else za
r0, c0 = round((WC_ORIGIN[1] - N0) / WC_PX), round((W0 - WC_ORIGIN[0]) / WC_PX)
wc = np.asarray(za[r0:r0 + NY * K, c0:c0 + NX * K]).reshape(NY, K, NX, K)


def frac(*codes):
    return np.isin(wc, codes).mean((1, 3), dtype=np.float32)


F = dict(tree=frac(10), shrub=frac(20), grass=frac(30), crop=frac(40), built=frac(50), bare=frac(60), water=frac(80), wetland=frac(90, 95))
del wc
lab, nlab = label(F["water"] >= 0.5)
sizes = np.bincount(lab.ravel())
ocean = np.isin(lab, np.where(sizes >= 100_000)[0][1:])            # water bodies bigger than ~250 km2 = the two seas
lake = (F["water"] >= 0.5) & ~ocean
land = metro & ~ocean & ~lake
print(f"land {land.sum() * CELL_KM2:,.0f} km2, built {F['built'][land].mean():.1%} of it")

# ---------------------------------------------------------------- elevation (Terrarium z12)
Z = 12
def tx(lon): return (np.asarray(lon) + 180) / 360 * 2 ** Z
def ty(lat): return (1 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2 * 2 ** Z
x0, x1, y0, y1 = int(tx(W0)), int(tx(E0)), int(ty(N0)), int(ty(S0))
mos = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.float32)
sess = requests.Session()
for x in range(x0, x1 + 1):
    for y in range(y0, y1 + 1):
        p = os.path.join(CACHE, f"terrarium_{Z}_{x}_{y}.png")
        if not os.path.exists(p):
            for attempt in range(5):
                r = sess.get(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png", timeout=60)
                if r.status_code == 200: break
                time.sleep(3)
            r.raise_for_status()
            open(p, "wb").write(r.content)
        a = np.array(Image.open(p).convert("RGB"), dtype=np.float32)
        mos[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
yy, xx = np.meshgrid((ty(LAT_C) - y0) * 256 - 0.5, (tx(LON_C) - x0) * 256 - 0.5, indexing="ij")
z = map_coordinates(mos, [yy, xx], order=1, mode="nearest").astype(np.float32)
del mos, yy, xx


def landfilter(a, f):                     # smoothing that ignores sea / lakes
    return f(np.where(land, a, 0.0)) / np.maximum(f(land.astype(np.float32)), 1e-6)


zs = landfilter(z, lambda x: gaussian_filter(x, 1.0))
gy, gx = np.gradient(zs, MPP_Y, MPP_X)
slope = np.hypot(gx, gy) * 100                                       # percent
sink = landfilter(zs, lambda x: uniform_filter(x, (21, 26))) - zs    # depth below the ~1.2 km neighbourhood mean (m)

# ---------------------------------------------------------------- constraint factors (0..1)
prot = raster_polys(prot_els) & land
f_slope = np.clip((slope - 10) / 15, 0, 1)                            # 10 % -> 0, 25 % (1:4) and steeper -> 1
wet = (F["wetland"] >= 0.3) | lake | raster_polys([e for e in water_els if e["type"] != "way" or e["tags"].get("waterway") is None]) | raster_lines([e for e in water_els if e["tags"].get("waterway")], 2)
d_water = dist_m(wet)
f_flood = np.clip(np.maximum(1 - d_water / 250, 0.6 * np.clip(sink / 3.0, 0, 1)), 0, 1)
d_ocean = dist_m(ocean)
f_coast = np.clip(np.maximum(np.clip((5 - zs) / 4, 0, 1) * np.clip(1 - d_ocean / 3500, 0, 1), 0.7 * np.clip(1 - d_ocean / 150, 0, 1)), 0, 1)
nat = uniform_filter(F["tree"] + F["shrub"], (15, 17))                # share of veld/bush/plantation within ~400 m
urban_near = uniform_filter(F["built"], (41, 51))                     # built-up share within ~1.2 km: fire is a constraint at the urban edge
f_fire = np.clip((nat - 0.30) / 0.45, 0, 1) * (0.75 + 0.25 * np.clip(slope / 25, 0, 1)) * np.clip(urban_near / 0.12, 0, 1)
f_air = np.clip(1 - (dist_m(raster_lines(runway_els, 2)) - 400) / 2000, 0, 1)
FACT = dict(prot=prot.astype(np.float32), slope=f_slope, flood=f_flood, coast=f_coast, fire=f_fire, air=f_air)
C = 1 - np.prod([1 - CAPS[k] * FACT[k] for k in CAPS], axis=0)

# ---------------------------------------------------------------- opportunity factors
d_rail = dist_m(raster_points(rail_pts))
d_brt = dist_m(raster_points(brt_pts))
s_rail, s_brt = np.clip(1 - d_rail / 1200, 0, 1), np.clip(1 - d_brt / 600, 0, 1)
o_transit = 1 - (1 - s_rail) * (1 - 0.8 * s_brt)
jobs = gaussian_filter(raster_polys(jobs_els).astype(np.float32), (1400 / MPP_Y, 1400 / MPP_X))
o_jobs = np.clip(jobs / np.percentile(jobs[land], 97), 0, 1)
loc = 0.55 * o_transit + 0.45 * o_jobs
spoken = raster_polys(excl_els) | prot | wet
brown = raster_polys(brown_els) & land
avail = (0.95 * F["bare"] + 0.80 * F["grass"] + 0.55 * F["shrub"] + 0.50 * F["crop"] + 0.20 * F["tree"])
ctx = np.clip((uniform_filter(F["built"], (11, 13)) - 0.10) / 0.30, 0, 1)   # inside the urban matrix, not out in the veld
o_land = np.where(spoken, 0, avail * ctx)
o_land = np.where(brown & ~prot, np.maximum(o_land, 0.9), o_land) * land
raw = o_land * loc
scale = np.percentile(raw[raw > 0], 96)
O = np.clip(raw / scale, 0, 1)
o_hi = O >= O_T
# a "site" is a blob at least ~3 ha and ~150 m across
o_hi = binary_opening(o_hi, structure=np.ones((3, 3)))            # >= ~140 x 170 m: drops rail / road verges
lab2, n2 = label(o_hi, structure=np.ones((3, 3)))
sz2 = np.bincount(lab2.ravel())
o_hi = o_hi & (sz2[lab2] >= 12)
print(f"opportunity cells {o_hi.sum() * CELL_KM2:,.1f} km2, of which constrained (C>={C_T}) {(o_hi & (C >= C_T)).sum() * CELL_KM2:,.1f} km2")

cls = np.zeros((NY, NX), np.uint8)              # 0 neutral, 1 constraint, 2 opportunity, 3 contested
cls[land & (C >= C_LO)] = 1
cls[land & o_hi & (C < C_T)] = 2
cls[land & o_hi & (C >= C_T)] = 3
strong_c = land & (C >= C_T)

# ---------------------------------------------------------------- top opportunity sites
site_mask = o_hi & (C < C_T) & land
site_mask = binary_opening(site_mask, structure=np.ones((3, 3)))
sl, ns = label(site_mask, structure=np.ones((3, 3)))
rows_i, cols_i = np.indices((NY, NX))
sites = []
for i in range(1, ns + 1):
    m = sl == i
    n = int(m.sum())
    if n < 12: continue                                              # >= ~3 ha
    r, c = rows_i[m].mean(), cols_i[m].mean()
    lon, lat = W0 + (c + 0.5) * DEG, N0 - (r + 0.5) * DEG
    sites.append(dict(score=float(O[m].sum()), ha=round(n * CELL_KM2 * 100, 1), o=round(float(O[m].mean()), 2), c=round(float(C[m].mean()), 2),
                      lon=round(lon, 5), lat=round(lat, 5),
                      rail_m=int(round(float(d_rail[m].min()), -1)), brt_m=int(round(float(d_brt[m].min()), -1))))
sites.sort(key=lambda s: -s["score"])


def near(lon, lat, items):
    best = min(items, key=lambda it: ((it[0] - lon) * MPP_X / DEG) ** 2 + ((it[1] - lat) * MPP_Y / DEG) ** 2)
    return best, math.hypot((best[0] - lon) * 111_320 * math.cos(math.radians(lat)), (best[1] - lat) * 111_320)


sub = [p for p in places if p[3] in ("suburb", "neighbourhood")] or places
top = []
for s in sites[:40]:
    pl, _ = near(s["lon"], s["lat"], [(p[0], p[1], p[2]) for p in sub])
    st, _ = near(s["lon"], s["lat"], [(a, b, n) for n, a, b in stations])
    s.update(name=pl[2], station=st[2])
    top.append(s)
# one site per suburb name so the list reads as places, not blobs; keep the biggest per name
seen, picked = set(), []
for s in top:
    if s["name"] in seen: continue
    seen.add(s["name"]); picked.append(s)
    if len(picked) == 12: break
for i, s in enumerate(picked, 1):
    s["rank"] = i; s.pop("score")

# ---------------------------------------------------------------- PNG layers
RUST, TEAL, OCHRE = (168, 72, 47), (31, 126, 116), (214, 158, 46)


def png(name, mask_alpha_rgb):
    out = np.zeros((NY, NX, 4), np.uint8)
    for m, rgb, a in mask_alpha_rgb:
        out[m, :3] = rgb
        out[m, 3] = (np.clip(a[m], 0, 1) * 255).astype(np.uint8)
    Image.fromarray(out).save(os.path.join(HERE, "data", name), optimize=True)


c_alpha = 0.14 + 0.76 * np.clip((C - C_LO) / (1 - C_LO), 0, 1)
o_alpha = 0.40 + 0.55 * O
png("constraints.png", [(land & (C >= C_LO), RUST, c_alpha)])
png("opportunities.png", [(land & o_hi, TEAL, o_alpha)])
png("combined.png", [(cls == 1, RUST, c_alpha), (cls == 2, TEAL, o_alpha), (cls == 3, OCHRE, 0.55 + 0.4 * np.maximum(O, C))])

# ---------------------------------------------------------------- probe grid (4x4 block means over land)
B = 4
def blk(a, dtype=np.float32):
    return a.reshape(NY // B, B, NX // B, B).mean((1, 3), dtype=np.float64)

lw = land.astype(np.float64)
lsum = blk(lw) * B * B
def lmean(a): return blk(np.where(land, a, 0.0)) * B * B / np.maximum(lsum, 1)
u8 = lambda a: np.clip(np.rint(a * 100), 0, 100).astype(np.uint8)
onehot = np.stack([blk((cls == k) & land) for k in range(4)])
grid = dict(w=NX // B, h=NY // B, bbox=[W0, S0, E0, N0],
            land=(blk(lw) >= 0.5).astype(np.uint8), cls=onehot.argmax(0).astype(np.uint8),
            C=u8(lmean(C)), O=u8(lmean(O)),
            **{f"c_{k}": u8(lmean(FACT[k])) for k in CAPS},
            o_transit=u8(lmean(o_transit)), o_jobs=u8(lmean(o_jobs)), o_land=u8(lmean(o_land)),
            slope=np.clip(np.rint(lmean(slope)), 0, 255).astype(np.uint8),
            d_rail=np.clip(np.rint(lmean(d_rail) / 25), 0, 255).astype(np.uint8),
            d_brt=np.clip(np.rint(lmean(d_brt) / 25), 0, 255).astype(np.uint8))
elev_dm = np.clip(np.rint(lmean(zs) * 10), -32000, 32000).astype("<i2")
enc = lambda a: base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()
out = {k: (enc(v) if isinstance(v, np.ndarray) else v) for k, v in grid.items()}
out["elev_dm"] = enc(elev_dm)
json.dump(out, open(os.path.join(HERE, "data", "grid.json"), "w"), separators=(",", ":"))

# ---------------------------------------------------------------- meta, land budget, sanity checks
def sample(a, lon, lat, r=1):
    c, rw = int((lon - W0) / DEG), int((N0 - lat) / DEG)
    return float(a[rw - r:rw + r + 1, c - r:c + r + 1].mean())


check = {n: dict(C=round(sample(C, *ll), 2), O=round(sample(O, *ll), 2), elev=round(sample(zs, *ll), 1), slope_pct=round(sample(slope, *ll), 1),
                 **{k: round(sample(FACT[k], *ll), 2) for k in ("slope", "flood", "coast", "fire", "air")})
         for n, ll in LANDMARKS.items()}
budget = dict(
    land_km2=round(float(land.sum() * CELL_KM2)),
    constraint=round(float(((cls == 1) & (C >= C_T)).sum() * CELL_KM2)),
    contested=round(float((cls == 3).sum() * CELL_KM2), 1),
    opportunity=round(float((cls == 2).sum() * CELL_KM2), 1),
    protected=round(float(prot.sum() * CELL_KM2)),
    built=round(float(F["built"][land].sum() * CELL_KM2)),
)
meta = dict(bbox=[W0, S0, E0, N0], cell_m=[round(MPP_X), round(MPP_Y)], caps=CAPS, thresholds=dict(c_lo=C_LO, c_t=C_T, o_t=O_T),
            colors=dict(rust="#A8482F", teal="#1F7E74", ochre="#D69E2E"), landmarks=LANDMARKS, check=check, budget=budget, sites=picked,
            rail=[[round(a, 5), round(b, 5)] for a, b in rail_pts], stations=[[n, round(a, 5), round(b, 5)] for n, a, b in stations])
json.dump(meta, open(os.path.join(HERE, "data", "meta.json"), "w"), indent=1)

# rail + BRT lines for display
def simp(l, step=3):
    return [[round(a, 5), round(b, 5)] for a, b in (l[::step] + [l[-1]])]
lines = dict(rail=[simp(pts(e["geometry"])) for e in rail_els if e.get("geometry")], brt=[simp(l) for l in brt_lines])
json.dump(lines, open(os.path.join(HERE, "data", "lines.json"), "w"), separators=(",", ":"))

print("budget", budget)
for n, v in check.items():
    print(f"{n:18s} C {v['C']:.2f}  O {v['O']:.2f}  elev {v['elev']:>6.1f} m  slope {v["slope_pct"]:>5.1f}%  " + "  ".join(f"{k} {v[k]:.2f}" for k in ("flood", "coast", "fire", "air")))
for s in picked:
    print(f"#{s['rank']:2d} {s['name']:<24s} {s['ha']:>6.1f} ha  O {s['o']:.2f}  C {s['c']:.2f}  rail {s['rail_m']} m  MyCiTi {s['brt_m']} m")
# known geography: the mountain must be far more constrained than the CBD, and the airport must carry the top noise score
assert check["Table Mountain"]["C"] > check["Cape Town CBD"]["C"] + 0.5, "mountain should outrank the CBD"
assert check["Cape Town Airport"]["air"] == max(v["air"] for v in check.values()), "airport should carry the strongest noise score"
print("sanity checks passed")
