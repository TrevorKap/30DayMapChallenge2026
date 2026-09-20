"""Download 3-hourly Kp (GFZ Potsdam, CC BY 4.0) 1932-2026 -> kp.npz"""
import json, urllib.request, numpy as np
t, k = [], []
for y in range(1932, 2027, 8):
    url = f"https://kp.gfz.de/app/json/?start={y}-01-01T00:00:00Z&end={min(y+8,2027)}-01-01T00:00:00Z&index=Kp"
    d = json.load(urllib.request.urlopen(url, timeout=120))
    t += d["datetime"]; k += d["Kp"]; print(y, len(t))
t = np.array(t, dtype="datetime64[m]"); k = np.array(k, dtype="float32")
_, i = np.unique(t, return_index=True)          # chunk boundaries overlap by one sample
np.savez_compressed("kp.npz", t=t[i].astype("int64"), k=k[i])
