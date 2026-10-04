import requests,json
B="45.43,-122.84,45.65,-122.47"
Q={"food":f'[out:json][timeout:120];(nwr["amenity"~"restaurant|cafe|bar|pub|fast_food|ice_cream|food_court"]["name"]({B});nwr["shop"~"bakery|pastry|confectionery|chocolate|coffee|tea"]["name"]({B}););out center tags;',
"water":f'[out:json][timeout:120];(way["natural"="water"]({B});way["waterway"="river"]({B});relation["natural"="water"]["name"~"Willamette|Columbia"]({B}););out geom;',
"roads":f'[out:json][timeout:120];way["highway"~"motorway|trunk|primary"]({B});out geom;',
"hoods":f'[out:json][timeout:120];node["place"~"neighbourhood|suburb"]["name"]({B});out;'}
for k,q in Q.items():
    for u in ["https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter"]:
        try:
            r=requests.post(u,data={"data":q},headers={"User-Agent":"30DayMapChallenge-portland-taste/1.0"},timeout=150);r.raise_for_status();json.dump(r.json(),open(f"data/{k}.json","w"));print(k,len(r.json()["elements"]));break
        except Exception as e:print(k,u,e)
