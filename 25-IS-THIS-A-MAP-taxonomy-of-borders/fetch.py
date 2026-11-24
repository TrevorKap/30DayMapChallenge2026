import json, time, requests
A="https://en.wikipedia.org/w/api.php"; H={"User-Agent":"30DayMapChallenge/1.0 (cakapuvari@gmail.com)"}
def q(**p):
    p.update(format="json")
    for k in range(5):
        try:
            r=requests.get(A,params=p,headers=H,timeout=20); r.raise_for_status(); return r.json()
        except requests.RequestException: time.sleep(2*k+1)
    return {"query":{"pages":{"0":{}}}}
def members(cat,depth=0,seen=None):
    seen=seen if seen is not None else set(); out=[]
    j=q(action="query",list="categorymembers",cmtitle=cat,cmlimit=500)
    for m in j["query"]["categorymembers"]:
        if m["ns"]==0: out.append(m["title"])
        elif m["ns"]==14 and depth<2 and m["title"] not in seen:
            seen.add(m["title"]); out+=members(m["title"],depth+1,seen)
    return out
titles=sorted(set(members("Category:Neighborhoods in Los Angeles")))
print(len(titles))
docs={}
for t in titles:
    j=q(action="query",prop="extracts|coordinates",explaintext=1,titles=t,redirects=1)
    p=list(j["query"]["pages"].values())[0]
    c=p.get("coordinates",[{}])[0]
    if "extract" in p and "lat" in c and len(p["extract"])>1500:
        docs[t]={"text":p["extract"],"lat":c["lat"],"lon":c["lon"]}
    time.sleep(.05)
print(len(docs)); json.dump(docs,open("data/corpus.json","w"))
