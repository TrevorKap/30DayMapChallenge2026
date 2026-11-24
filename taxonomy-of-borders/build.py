"""Semantic map of Los Angeles: neighborhoods and the words written about them
placed on a plane where distance = similarity of usage, not meters."""
import json, re, numpy as np
from collections import Counter
from scipy.ndimage import gaussian_filter
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.manifold import TSNE
from sklearn.preprocessing import normalize

K, NTERMS, G = 3, 700, (160, 120)
docs = json.load(open("data/corpus.json"))
nb = re.compile(r"(is|are) an? ([\w\-, ]{0,60})?(neighbou?rhood|community|district|suburb|area|enclave|region)", re.I)
docs = {n: d for n, d in docs.items() if nb.search(d["text"][:300]) and not re.search(r"school|station|tunnel|building|church|museum|theat|stadium|earthquake|fire|crash|collision|shooting|park|street|bridge|hotel|hospital|library|center|college|univers", n, re.I)}
docs = {n: d for n, d in docs.items() if re.search(r", (Los Angeles|California)(, California)?$", n) and not re.search(r"Courts|Gardens|Plaza|Estate|Jail", n)}
names = sorted(docs)
# paragraph-level contexts, so words are positioned by co-occurrence, not by article
paras, owner = [], []
for n in names:
    for p in re.split(r"\n+", docs[n]["text"]):
        if len(p) > 120 and not p.startswith("="):
            paras.append(p); owner.append(n)
# neighborhood names and generic place words would just spell out the map
nameWords = {w.lower() for n in names for w in re.findall(r"[A-Za-z]+", n)}
stop = list(ENGLISH_STOP_WORDS | nameWords | {"los", "angeles", "california", "la", "city", "district", "neighborhood", "area", "located", "known", "county", "census", "according", "population", "used", "built", "year", "years", "including", "include", "included", "following", "later", "early", "large", "main", "major", "long", "named", "called", "time", "times", "site", "places", "near", "moved", "held", "opened", "began", "closed", "served", "established", "considered", "present", "average", "miles", "feet", "million", "people", "june", "september", "july", "august", "march", "april", "october", "november", "december", "january", "february", "local", "service", "program", "residents", "includes", "designed", "land", "property", "following", "first", "second", "also", "many", "several", "since", "became", "part", "street", "avenue", "boulevard", "road"})
vec = TfidfVectorizer(stop_words=stop, token_pattern=r"[A-Za-z]{4,}", lowercase=True, min_df=6, max_df=0.25, sublinear_tf=True)
X = vec.fit_transform(paras)
terms = np.array(vec.get_feature_names_out())
df = np.asarray((X > 0).sum(0)).ravel()
keep = np.argsort(-df)[:NTERMS]
terms, Xk = terms[keep], X[:, keep]
# latent space shared by terms (columns) and neighborhoods (summed paragraph rows)
svd = TruncatedSVD(40, random_state=1).fit(X)
T = normalize(svd.components_.T[keep])
rows = np.zeros((len(names), X.shape[1]))
idx = {n: i for i, n in enumerate(names)}
Xc = X.tocsr()
for i, o in enumerate(owner):
    rows[idx[o]] += Xc[i].toarray().ravel()
D = normalize(svd.transform(normalize(rows)))
allv = np.vstack([T, D])
xy = TSNE(2, metric="cosine", perplexity=25, init="pca", random_state=3, max_iter=2000).fit_transform(allv)
xy = (xy - xy.min(0)) / (xy.max(0) - xy.min(0))
tx, dx = xy[:len(terms)], xy[len(terms):]

km = KMeans(K, n_init=20, random_state=4).fit(tx)
lab = km.labels_
# nearest-cluster for neighborhoods, by their location in the plane
dlab = km.predict(dx)

# territory fields: smoothed point density per cluster, border where leader changes
gx, gy = G
F = np.zeros((K, gy, gx))
for (x, y), c in zip(tx, lab):
    F[c, min(gy-1, int(y*gy)), min(gx-1, int(x*gx))] += 1
for (x, y), c in zip(dx, dlab):
    F[c, min(gy-1, int(y*gy)), min(gx-1, int(x*gx))] += 1.5
F = np.stack([gaussian_filter(f, 6, truncate=20) for f in F])  # wide, so every cell of the plane (and county) has a leader
margin = []
for c in range(K):
    o = np.delete(F, c, 0).max(0)
    margin.append(np.round((F[c] - o)/(F[c] + o + 1e-300)*1000).astype(int).ravel().tolist())  # relative lead, so far corners still have a winner

# distinguishing words per territory (by frequency inside vs. outside)
freq = np.asarray(Xk.sum(0)).ravel()
top = []
for c in range(K):
    ids = np.where(lab == c)[0]
    top.append([terms[i] for i in ids[np.argsort(-freq[ids])][:8]])

# physical vs semantic distance
lat = np.array([docs[n]["lat"] for n in names]); lon = np.array([docs[n]["lon"] for n in names])
def km_d(i, j):
    return 111.2*np.hypot(lat[i]-lat[j], (lon[i]-lon[j])*np.cos(np.radians(34)))
sem = D @ D.T
phys = np.array([[km_d(i, j) for j in range(len(names))] for i in range(len(names))])
iu = np.triu_indices(len(names), 1)
rho = spearmanr(sem[iu], phys[iu])[0]
places = []
for i, n in enumerate(names):
    order = np.argsort(-sem[i]); order = [j for j in order if j != i][:3]
    places.append({"n": n, "x": round(float(dx[i, 0]), 4), "y": round(float(dx[i, 1]), 4), "lat": round(float(lat[i]), 4), "lon": round(float(lon[i]), 4), "c": int(dlab[i]),
                   "near": [[names[j], round(float(phys[i, j]), 1)] for j in order],
                   "w": [terms[k] for k in np.argsort(-(T @ D[i]))[:5]]})
out = {"county": json.load(open("data/county.json")), "K": K, "grid": [gx, gy], "margin": margin, "top": top, "rho": round(float(rho), 3),
       "terms": [{"t": t, "x": round(float(x), 4), "y": round(float(y), 4), "c": int(c), "f": int(df[k])} for t, (x, y), c, k in zip(terms, tx, lab, keep)],
       "places": places, "paras": len(paras)}
json.dump(out, open("data/semantic.json", "w"), separators=(",", ":"))
print(len(names), "places", len(terms), "terms", len(paras), "paras", "rho", rho)
for c in range(K):
    print(c, (lab == c).sum(), top[c], [p["n"] for p in places if p["c"] == c][:6], sum(p["c"] == c for p in places))

# inline the data so index.html also works opened from disk (fetch is blocked on file://)
h = open("index.html", encoding="utf-8").read()
h = re.sub(r'<script id="data">.*?</script>', lambda m: '<script id="data">window.DATA=' + open("data/semantic.json", encoding="utf-8").read() + ';</script>', h, flags=re.S)
open("index.html", "w", encoding="utf-8").write(h)
