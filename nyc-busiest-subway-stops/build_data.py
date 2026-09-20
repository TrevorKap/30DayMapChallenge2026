"""Bake 2025 MTA ridership by station complex + subway line geometry into data/*.geojson."""
import json, re, urllib.parse, urllib.request

def get(url, **params):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{q}", timeout=120) as r:
        return json.load(r)

rows = get("https://data.ny.gov/resource/5wq4-mkjj.json", **{
    "$select": "station_complex_id,station_complex,borough,avg(latitude) as lat,avg(longitude) as lon,sum(ridership) as total",
    "$where": "transit_timestamp >= '2025-01-01T00:00:00' AND transit_timestamp < '2026-01-01T00:00:00'",
    "$group": "station_complex_id,station_complex,borough",
    "$order": "total DESC", "$limit": 1000})

feats = []
for i, r in enumerate(rows, 1):
    m = re.match(r"(.*?)\s*\(([^)]*)\)\s*$", r["station_complex"])
    name, routes = (m.group(1), m.group(2).split(",")) if m else (r["station_complex"], [])
    feats.append({"type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(float(r["lon"]), 5), round(float(r["lat"]), 5)]},
        "properties": {"rank": i, "id": r["station_complex_id"], "name": name, "routes": routes,
                       "borough": r["borough"], "riders": int(float(r["total"]))}})
json.dump({"type": "FeatureCollection", "features": feats}, open("data/stations.geojson", "w"))

def thin(seg, tol=0.00015):  # ~15 m: drop vertices closer than tol to the last kept one, keep the endpoint
    out = [seg[0]]
    for x, y in seg[1:-1]:
        if abs(x - out[-1][0]) + abs(y - out[-1][1]) >= tol:
            out.append([x, y])
    out.append(seg[-1])
    return [[round(x, 5), round(y, 5)] for x, y in out]

lines = get("https://data.ny.gov/resource/s692-irgq.json", **{"$limit": 200})
lf = []
for r in lines:
    if r["service"] in ("SIR", "5 Peak"):  # SIR isn't subway; 5 Peak duplicates 5
        continue
    g = r["geometry"]
    g["coordinates"] = [thin(seg) for seg in g["coordinates"]]
    lf.append({"type": "Feature", "geometry": g, "properties": {"service": r["service"][0] if r["service"].startswith("S") else r["service"], "name": r["service_name"]}})
json.dump({"type": "FeatureCollection", "features": lf}, open("data/lines.geojson", "w"))
print(len(feats), "stations,", len(lf), "line features")
for f in feats[:10]:
    p = f["properties"]; print(p["rank"], p["name"], p["routes"], f"{p['riders']:,}")
