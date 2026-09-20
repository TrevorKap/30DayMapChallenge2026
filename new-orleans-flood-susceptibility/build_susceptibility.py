"""Build the New Orleans flood-susceptibility raster + hover grid.

Inputs (all public, no auth):
  - USGS 3DEP bare-earth elevation (NAVD88, metres), 10 m
  - NLCD 2021 land cover (open water) and percent impervious, 30 m
Model: weighted linear combination of four factors, each scaled 0..1 (1 = most susceptible).
Outputs -> data/susceptibility.png, data/grid.json, data/meta.json
"""
import base64, io, json, os, tempfile
import numpy as np
import requests
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter, label, uniform_filter

Image.MAX_IMAGE_PIXELS = None
W0, S0, E0, N0 = -90.20, 29.85, -89.85, 30.09      # lon/lat extent
NX, NY = 1750, 1200                                 # model grid (~19 x 22 m)
WEIGHTS = dict(elev=0.40, sink=0.15, water=0.25, imperv=0.20)
RAMP = ["#EAE4CC", "#D8BE78", "#C98A45", "#A8482F", "#5A1730"]   # low -> high
LANDMARKS = {
    "Lakeview": (-90.108, 30.005), "Gentilly": (-90.045, 30.000),
    "Lower Ninth Ward": (-90.010, 29.965), "New Orleans East": (-89.960, 30.020),
    "Mid-City": (-90.095, 29.975), "French Quarter": (-90.0645, 29.9584),
    "Garden District": (-90.085, 29.929), "Uptown": (-90.120, 29.930),
}
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(tempfile.gettempdir(), "nola_flood_cache")
os.makedirs(CACHE, exist_ok=True)
BBOX = f"{W0},{S0},{E0},{N0}"


def fetch(name, url, **params):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        r = requests.get(url, params=params, timeout=300)
        r.raise_for_status()
        open(path, "wb").write(r.content)
    return path


def nlcd(layer):
    p = fetch(layer + ".tif", "https://www.mrlc.gov/geoserver/mrlc_display/wms", service="WMS", version="1.1.1",
              request="GetMap", layers=layer, styles="", srs="EPSG:4326", bbox=BBOX, width=1170, height=800,
              format="image/geotiff")
    return Image.open(p)


# --- 3DEP DEM (server returns a tif href, then we download it) ---
j = requests.get("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage",
                 params=dict(bbox=BBOX, bboxSR=4326, imageSR=4326, size="3500,2400", format="tiff", pixelType="F32",
                             interpolation="RSP_BilinearInterpolation", f="json"), timeout=300).json() \
    if not os.path.exists(os.path.join(CACHE, "dem.tif")) else None
if j:
    fetch("dem.tif", j["href"])
dem = np.array(Image.open(os.path.join(CACHE, "dem.tif")), dtype=np.float32)
z = dem.reshape(NY, 2, NX, 2).mean((1, 3))                      # 10 m -> 20 m

# --- NLCD: open water mask (palette index 1) and impervious % (palette index = percent) ---
lc = np.array(nlcd("NLCD_2021_Land_Cover_L48")) == 1
water = np.array(Image.fromarray(lc).resize((NX, NY), Image.NEAREST))
# Surge water = large water bodies reaching the northern half of the study area (Lake Pontchartrain, Lake Borgne
# marshes, navigation canals). The Mississippi is left out: it runs above the city on its natural levee.
lab, _ = label(lc, structure=np.ones((3, 3)))
lat_of_row = N0 - (np.arange(lc.shape[0]) + 0.5) / lc.shape[0] * (N0 - S0)
keep = [i for i in range(1, lab.max() + 1)
        if (lab == i).sum() >= 1000 and lat_of_row[np.where((lab == i).any(1))[0].min()] >= 29.99]
surge = np.array(Image.fromarray(np.isin(lab, keep)).resize((NX, NY), Image.NEAREST))
imperv = np.array(nlcd("NLCD_2021_Impervious_L48").resize((NX, NY), Image.BILINEAR), dtype=np.float32) / 100
land = ~water


def nanfilter(a, f):  # filter that ignores water cells
    return f(np.where(land, a, 0.0)) / np.maximum(f(land.astype(np.float32)), 1e-6)


zs = nanfilter(z, lambda x: gaussian_filter(x, 1.5))
sink = nanfilter(zs, lambda x: uniform_filter(x, 61)) - zs      # depth below the ~1.2 km neighbourhood mean (m)
mpp_y = (N0 - S0) / NY * 111_200
mpp_x = (E0 - W0) / NX * 111_200 * np.cos(np.radians((S0 + N0) / 2))
dist = distance_transform_edt(~surge, sampling=(mpp_y, mpp_x))   # m to nearest surge water

f = dict(
    elev=np.clip((3.0 - zs) / 5.0, 0, 1),        # +3 m -> 0, -2 m and below -> 1
    sink=np.clip(sink / 1.0, 0, 1),              # 1 m or more below neighbours -> 1
    water=np.clip(1 - dist / 4000, 0, 1),        # on the shoreline -> 1, 4 km+ away -> 0
    imperv=np.clip(imperv, 0, 1),
)
S = sum(WEIGHTS[k] * f[k] for k in WEIGHTS)
lo, hi = np.percentile(S[land], [2, 98])
t = np.clip((S - lo) / (hi - lo), 0, 1)


def sample(a, lon, lat, r=2):
    c = int((lon - W0) / (E0 - W0) * NX); rw = int((N0 - lat) / (N0 - S0) * NY)
    return float(a[rw - r:rw + r + 1, c - r:c + r + 1].mean())


# --- colour-mapped PNG ---
stops = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in RAMP], dtype=np.float32)
pos = t * (len(RAMP) - 1)
i0 = np.minimum(pos.astype(int), len(RAMP) - 2)
rgb = stops[i0] + (stops[i0 + 1] - stops[i0]) * (pos - i0)[..., None]
alpha = np.where(land, 0.35 + 0.55 * t, 0.0) * 255
# 256-colour palette with alpha keeps the PNG ~4x smaller than RGBA with no visible banding on this ramp
Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA").quantize(256, method=Image.FASTOCTREE).save(
    os.path.join(HERE, "data", "susceptibility.png"), optimize=True)

# --- 100 m hover grid ---
B = 5
def blk(a): return a.reshape(NY // B, B, NX // B, B).mean((1, 3))
lf = blk(land.astype(np.float32))
def u8(a): return base64.b64encode(np.clip(np.round(a * 100), 0, 100).astype(np.uint8).tobytes()).decode()
grid = dict(
    w=NX // B, h=NY // B, bbox=[W0, S0, E0, N0],
    land=base64.b64encode((lf > 0.5).astype(np.uint8).tobytes()).decode(),
    t=u8(blk(t)), **{k: u8(blk(v)) for k, v in f.items()},
    elev_cm=base64.b64encode(np.round(blk(zs) * 100).astype("<i2").tobytes()).decode(),
)
json.dump(grid, open(os.path.join(HERE, "data", "grid.json"), "w"), separators=(",", ":"))

# --- neighbourhood check + sanity assertions ---
land_t = np.sort(t[land])
check = {n: dict(elev_m=round(sample(zs, *ll), 2), pct=round(float(np.searchsorted(land_t, sample(t, *ll)) / land_t.size * 100)))
         for n, ll in LANDMARKS.items()}
meta = dict(bbox=[W0, S0, E0, N0], weights=WEIGHTS, ramp=RAMP, landmarks=LANDMARKS, check=check,
            land_share=round(float(land.mean()), 3))
json.dump(meta, open(os.path.join(HERE, "data", "meta.json"), "w"), indent=1)
for n, v in check.items():
    print(f"{n:18s} elev {v['elev_m']:+.2f} m   susceptibility percentile {v['pct']}")
# known geography: natural-levee high ground must rank drier than the old backswamp
for dry in ("French Quarter", "Garden District", "Uptown"):
    for wet in ("Lakeview", "Gentilly", "Lower Ninth Ward"):
        assert check[dry]["pct"] < check[wet]["pct"], f"{dry} should rank below {wet}"
print("sanity checks passed")
