"""Fetch TeleGeography submarine cable data (public API) -> compact data.json."""
import json, re, urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://www.submarinecablemap.com/api/v3/"
get = lambda p: json.load(urllib.request.urlopen(urllib.request.Request(API + p, headers={"User-Agent": "mapping-challenge"}), timeout=60))

geo = get("cable/cable-geo.json")["features"]
lps = get("landing-point/landing-point-geo.json")["features"]
ids = sorted({f["properties"]["id"] for f in geo})
with ThreadPoolExecutor(16) as ex:
    detail = dict(zip(ids, ex.map(lambda i: get(f"cable/{i}.json"), ids)))

BIG = re.compile(r"Google|Meta\b|Facebook|Microsoft|Amazon|AWS", re.I)
r = lambda c: [round(c[0], 2), round(c[1], 2)]
cables, hub, by = [], {}, {}
for f in geo:  # a cable can span several geometry features (-0, -1, ...): merge by id
    p = f["properties"]; d = detail[p["id"]]
    lines = [[r(c) for c in line] for line in f["geometry"]["coordinates"]]
    if p["id"] in by:
        by[p["id"]]["g"] += lines; continue
    km = int(re.sub(r"\D", "", (d["length"] or "").split("km")[0]) or 0)
    hub[p["id"]] = [l["id"] for l in d["landing_points"]]
    by[p["id"]] = dict(
        id=p["id"], n=d["name"].replace("�", "–"), km=km, y=d["rfs_year"], pl=bool(d["is_planned"]),
        o=d["owners"] or "", big=bool(BIG.search(d["owners"] or "")), g=lines)
    cables.append(by[p["id"]])
pts = [dict(i=f["properties"]["id"], n=f["properties"]["name"], c=r(f["geometry"]["coordinates"])) for f in lps if f["geometry"]]
ix = {p["i"]: n for n, p in enumerate(pts)}
for c in cables:  # landing points as indices into pts
    c["l"] = sorted({ix[i] for i in hub[c["id"]] if i in ix})
for p in pts: del p["i"]
json.dump(dict(cables=cables, points=pts), open("submarine-cable-map/data.json", "w"), separators=(",", ":"))
print(len(cables), "cables", len(pts), "landing points", sum(c["km"] for c in cables if not c["pl"]), "km in service")
