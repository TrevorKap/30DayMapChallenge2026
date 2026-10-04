"""Fetch Miami street network from Overpass, emit compact graph JSON for in-browser Dijkstra.
Output data/graph.json: {b:[minLon,minLat], n:[dLon,dLat,...] (1e-5 deg int deltas from b, flat), e:[a,b,meters,...]}
"""
import json, math, requests, networkx as nx

BBOX = (25.700, -80.305, 25.860, -80.120)  # S,W,N,E
Q = f"""[out:json][timeout:180];
way["highway"]["highway"!~"motorway|motorway_link|trunk|trunk_link|construction|proposed|raceway|bus_guideway|elevator|corridor|steps"]
["foot"!="no"]["access"!~"private|no"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
out body; >; out skel qt;"""
r = requests.post("https://overpass-api.de/api/interpreter", data={"data": Q}, timeout=240,
                  headers={"User-Agent": "30DayMappingChallenge-miami-isochrone"})
r.raise_for_status()
els = r.json()["elements"]
nodes = {e["id"]: (e["lon"], e["lat"]) for e in els if e["type"] == "node"}

def hav(a, b):
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))

G = nx.Graph()
for e in els:
    if e["type"] != "way": continue
    ns = [n for n in e["nodes"] if n in nodes]
    for a, b in zip(ns, ns[1:]):
        G.add_edge(a, b, w=hav(nodes[a], nodes[b]))
G = G.subgraph(max(nx.connected_components(G), key=len)).copy()
# contract degree-2 shape vertices (straight-line render between intersections)
for n in [n for n in G if G.degree(n) == 2]:
    a, c = G.neighbors(n)
    if a != c and not G.has_edge(a, c):
        G.add_edge(a, c, w=G[a][n]["w"] + G[n][c]["w"]); G.remove_node(n)
print("nodes", G.number_of_nodes(), "edges", G.number_of_edges())

ids = list(G.nodes); idx = {n: i for i, n in enumerate(ids)}
b0 = (min(nodes[n][0] for n in ids), min(nodes[n][1] for n in ids))
flat = []
for n in ids:
    flat += [round((nodes[n][0] - b0[0]) * 1e5), round((nodes[n][1] - b0[1]) * 1e5)]
edges = []
for a, b, d in G.edges(data=True):
    edges += [idx[a], idx[b], round(d["w"], 1)]
json.dump({"b": b0, "n": flat, "e": edges}, open("data/graph.json", "w"), separators=(",", ":"))
