"""Paris POI hot spots: OSM POIs per interest -> DBSCAN (haversine) -> cluster hulls.
Method after Milan Janosov's "Identifying topical hot spots in urban areas".
Outputs data/points.geojson, data/hotspots.geojson.
"""
import json, os, time, requests, numpy as np
from scipy.spatial import ConvexHull
from sklearn.cluster import DBSCAN

R = 6371008.8
# eps (m) / min_samples chosen by a grid sweep: >~150 m eps chains the whole centre into one blob
CATS = {
    "culture":   dict(q=['["tourism"~"^(museum|gallery)$"]', '["amenity"~"^(theatre|cinema|arts_centre)$"]'], eps=130, min=8),
    "nightlife": dict(q=['["amenity"~"^(bar|pub|nightclub)$"]'],eps=130, min=12),
    "books":     dict(q=['["shop"~"^(books|antiques)$"]'],eps=130, min=6),
}
OVERPASS = "https://overpass-api.de/api/interpreter"

def overpass(q):
    for wait in (0, 20, 40, 80, 160):  # public endpoint 429s under load
        time.sleep(wait)
        r = requests.post(OVERPASS, data={"data": q}, timeout=240, headers={"User-Agent": "30DayMappingChallenge-paris-poi"})
        if r.status_code not in (429, 504): break
    r.raise_for_status(); return r.json()["elements"]

def xy(e):
    return (e["lon"], e["lat"]) if e["type"] == "node" else (e["center"]["lon"], e["center"]["lat"])

area = "area(3600007444)->.p;"  # Paris (commune), OSM relation 7444
places = [(xy(e), e["tags"]["name"]) for e in overpass(
    f'[out:json][timeout:120];{area}node(area.p)["place"~"^(suburb|quarter|neighbourhood)$"]["name"];out;')]
pl_xy = np.radians([[p[0][1], p[0][0]] for p in places])

pts, hulls = [], []
for cat, c in CATS.items():
    els = overpass(f'[out:json][timeout:180];{area}(' + ''.join(f'nwr(area.p){f};' for f in c["q"]) + ');out center tags;')
    seen, rows = set(), []
    for e in els:  # dedupe stacked features (e.g. node + building way for the same venue)
        lon, lat = xy(e); k = (round(lon, 5), round(lat, 5), e["tags"].get("name"))
        if k not in seen: seen.add(k); rows.append((lon, lat, e["tags"].get("name")))
    ll = np.radians([[r[1], r[0]] for r in rows])
    lab = DBSCAN(eps=c["eps"] / R, min_samples=c["min"], metric="haversine", algorithm="ball_tree").fit_predict(ll)
    print(cat, len(rows), "POIs,", lab.max() + 1, "hot spots,", (lab < 0).sum(), "noise")
    for (lon, lat, nm), l in zip(rows, lab):
        pts.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                    "properties": {"cat": cat, "name": nm, "hot": int(l >= 0)}})
    for l in range(lab.max() + 1):
        m = lab == l; cl = np.array([[rows[i][0], rows[i][1]] for i in np.where(m)[0]])
        cen = cl.mean(0)
        # hull of cluster points, each padded by a small ring so lines/pairs still get an area
        pad = c["eps"] / 2; k = np.cos(np.radians(cen[1]))
        ring = np.array([[np.cos(a), np.sin(a)] for a in np.linspace(0, 2 * np.pi, 12, endpoint=False)])
        cloud = (cl[:, None, :] + ring[None] * [pad / (111320 * k), pad / 110540]).reshape(-1, 2)
        h = cloud[ConvexHull(cloud).vertices]
        d = np.arccos(np.clip(np.sin(np.radians(cen[1])) * np.sin(pl_xy[:, 0]) + np.cos(np.radians(cen[1])) * np.cos(pl_xy[:, 0]) * np.cos(pl_xy[:, 1] - np.radians(cen[0])), -1, 1))
        area_km2 = ConvexHull(cl * [111.32 * k, 110.54]).volume if len(cl) > 2 else 0
        hulls.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[*[[round(x, 6), round(y, 6)] for x, y in h], [round(h[0][0], 6), round(h[0][1], 6)]]]},
                      "properties": {"cat": cat, "n": int(m.sum()), "near": places[int(d.argmin())][1],
                                     "lon": round(cen[0], 6), "lat": round(cen[1], 6), "km2": round(float(area_km2), 3)}})

os.makedirs("data", exist_ok=True)
json.dump({"type": "FeatureCollection", "features": pts}, open("data/points.geojson", "w"), separators=(",", ":"))
json.dump({"type": "FeatureCollection", "features": hulls}, open("data/hotspots.geojson", "w"), separators=(",", ":"))
for cat in CATS:
    print(cat, sorted([(f["properties"]["n"], f["properties"]["near"]) for f in hulls if f["properties"]["cat"] == cat], reverse=True)[:12])
