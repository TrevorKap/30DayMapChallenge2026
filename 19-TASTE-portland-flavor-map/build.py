import json,math,collections,os
F=["spicy","sweet","savory","bitter","umami"]
# cuisine -> (spicy,sweet,savory,bitter,umami), spice 0-5
P={
'thai':((.35,.2,.15,.1,.2),4),'indian':((.5,.1,.3,.05,.05),4),'curry':((.5,.1,.3,.05,.05),4),'nepalese':((.5,.1,.3,.05,.05),4),'burmese':((.3,.1,.2,.1,.3),3),
'mexican':((.45,.1,.3,.05,.1),3),'tex-mex':((.4,.1,.35,.05,.1),3),'latin_american':((.35,.15,.35,.05,.1),3),'peruvian':((.3,.15,.3,.05,.2),2),'cuban':((.2,.2,.45,.05,.1),1),
'korean':((.45,.1,.15,.05,.25),4),'sichuan':((.6,.05,.1,.05,.2),5),'chinese':((.15,.15,.3,.05,.35),2),'asian':((.2,.15,.25,.05,.35),2),'mongolian_grill':((.1,.15,.35,.05,.35),1),
'vietnamese':((.15,.15,.2,.1,.4),2),'filipino':((.1,.25,.3,.05,.3),1),'japanese':((.05,.1,.2,.05,.6),1),'sushi':((.05,.05,.15,.05,.7),1),'ramen':((.05,.05,.2,.05,.65),1),'teriyaki':((.05,.35,.2,.05,.35),0),'poke':((.1,.1,.2,.05,.55),1),'hawaiian':((.05,.3,.35,.05,.25),0),'noodle':((.15,.1,.25,.05,.45),2),
'ethiopian':((.4,.05,.3,.15,.1),3),'cajun':((.4,.05,.4,.05,.1),3),'barbecue':((.2,.2,.5,.0,.1),2),'wings':((.4,.1,.4,.0,.1),3),'chicken':((.2,.1,.55,.0,.15),1),'curry':((.5,.1,.3,.05,.05),4),
'italian':((.05,.1,.5,.05,.3),0),'pizza':((.05,.1,.5,.05,.3),0),'pasta':((.05,.1,.5,.05,.3),0),'french':((.05,.3,.4,.1,.15),0),'spanish':((.1,.1,.45,.1,.25),1),'german':((.05,.1,.65,.1,.1),0),'irish':((.0,.1,.65,.15,.1),0),
'american':((.1,.1,.6,.05,.15),1),'burger':((.1,.1,.6,.0,.2),1),'sandwich':((.05,.1,.6,.1,.15),0),'steak_house':((.05,.05,.6,.05,.25),0),'diner':((.05,.2,.6,.05,.1),0),'southern':((.15,.2,.55,.0,.1),1),'regional':((.1,.1,.5,.1,.2),1),'fish_and_chips':((.0,.05,.7,.1,.15),0),'hot_dog':((.1,.1,.65,.0,.15),1),'fine_dining':((.05,.2,.4,.1,.25),0),'international':((.1,.1,.5,.1,.2),1),
'mediterranean':((.15,.1,.45,.1,.2),1),'greek':((.05,.1,.5,.1,.25),0),'middle_eastern':((.2,.1,.45,.1,.15),1),'lebanese':((.15,.1,.45,.1,.2),1),'persian':((.1,.2,.45,.1,.15),1),'kebab':((.2,.05,.55,.05,.15),2),'shawarma':((.2,.05,.55,.05,.15),2),
'seafood':((.1,.05,.4,.05,.4),1),'salad':((.0,.1,.4,.4,.1),0),'vegan':((.05,.1,.35,.3,.2),0),'vegetarian':((.05,.1,.35,.3,.2),0),'juice':((.0,.35,.1,.5,.05),0),'smoothie':((.0,.6,.1,.3,.0),0),
'breakfast':((.0,.35,.5,.1,.05),0),'brunch':((.0,.35,.5,.1,.05),0),'pancake':((.0,.7,.25,.05,.0),0),'bagel':((.0,.15,.7,.1,.05),0),'pretzel':((.0,.1,.8,.1,.0),0),
'coffee_shop':((.0,.2,.05,.7,.05),0),'coffee':((.0,.2,.05,.7,.05),0),'tea':((.0,.15,.0,.8,.05),0),'bubble_tea':((.0,.55,.0,.4,.05),0),
'ice_cream':((.0,.9,.0,.1,.0),0),'frozen_yogurt':((.0,.85,.05,.1,.0),0),'dessert':((.0,.9,.0,.1,.0),0),'donut':((.0,.85,.1,.05,.0),0),'bakery':((.0,.6,.3,.1,.0),0),'pastry':((.0,.7,.2,.1,.0),0),'chocolate':((.0,.6,.0,.4,.0),0),'confectionery':((.0,.95,.0,.05,.0),0),'cake':((.0,.9,.05,.05,.0),0),
}
A={'bar':((.05,.0,.3,.6,.05),0,'bar'),'pub':((.0,.0,.35,.6,.05),0,'pub'),'cafe':((.0,.2,.1,.6,.1),0,'cafe'),'restaurant':((.05,.1,.5,.1,.25),1,'restaurant'),'fast_food':((.1,.1,.6,.05,.15),1,'fast food'),'food_court':((.15,.1,.4,.05,.3),2,'food court'),
 'ice_cream':((.0,.9,.0,.1,.0),0,'ice cream'),'bakery':((.0,.6,.3,.1,.0),0,'bakery'),'confectionery':((.0,.95,.0,.05,.0),0,'sweets'),'pastry':((.0,.7,.2,.1,.0),0,'pastry'),'chocolate':((.0,.6,.0,.4,.0),0,'chocolate'),'coffee':((.0,.2,.05,.7,.05),0,'coffee'),'tea':((.0,.15,.0,.8,.05),0,'tea')}
def stitch(role):
    ws=[[(p['lon'],p['lat']) for p in m['geometry']] for m in json.load(open('data/boundary.json'))[0]['members'] if m['type']=='way' and m['role']==role and m.get('geometry')]
    rings=[]
    while ws:
        r=ws.pop(0)
        while r[0]!=r[-1]:
            for i,w in enumerate(ws):
                if w[0]==r[-1]:r+=w[1:]
                elif w[-1]==r[-1]:r+=w[::-1][1:]
                else:continue
                ws.pop(i);break
            else:break
        rings.append(r)
    return rings
OUT,INN=stitch('outer'),stitch('inner')
def pip(x,y,r):
    c=False
    for (x1,y1),(x2,y2) in zip(r,r[1:]):
        if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1:c=not c
    return c
def in_city(x,y):return any(pip(x,y,r) for r in OUT) and not any(pip(x,y,r) for r in INN)
pts=[]
for e in json.load(open('data/food.json'))['elements']:
    t=e['tags'];k=t.get('amenity') or t.get('shop')
    if k not in A:continue
    lat=e.get('lat') or e['center']['lat'];lon=e.get('lon') or e['center']['lon']
    if not in_city(lon,lat):continue
    cs=[c.strip() for c in t.get('cuisine','').split(';') if c.strip() in P]
    if cs:
        v=[sum(P[c][0][i] for c in cs)/len(cs) for i in range(5)];sp=sum(P[c][1] for c in cs)/len(cs);lab=cs[0].replace('_',' ')
    else: v,sp,lab=A[k]
    if k in('bar','pub') and cs: v=[.6*a+.4*b for a,b in zip(v,A[k][0])] # beer lean
    s=sum(v);v=[x/s for x in v]
    # prominence proxy: OSM has no ratings, so reward well-documented venues
    w=1+.5*bool(t.get('website') or t.get('contact:website'))+.5*bool(t.get('opening_hours'))+.25*bool(t.get('phone') or t.get('contact:phone'))+.25*bool(t.get('addr:housenumber'))+.5*bool(t.get('outdoor_seating'))+.5*bool(t.get('takeaway') or t.get('delivery'))+1.5*bool(t.get('wikidata') or t.get('wikipedia'))+.25*bool(t.get('wheelchair'))+.25*bool(t.get('instagram') or t.get('contact:instagram') or t.get('contact:facebook'))
    w=min(w,4)
    pts.append([round(lon,5),round(lat,5),t['name'],lab,max(range(5),key=lambda i:v[i]),round(sp,1),A[k][2],[w*int(i==max(range(5),key=lambda j:v[j])) for i in range(5)],w])
print(len(pts),collections.Counter(F[p[4]] for p in pts))
# hex aggregation, pointy hexes, R metres
R=560;lat0=45.53;kx=111320*math.cos(math.radians(lat0));ky=110574;lon0=-122.66
def xy(p):return((p[0]-lon0)*kx,(p[1]-lat0)*ky)
def cube(x,y):
    q=(math.sqrt(3)/3*x-y/3)/R;r=(2/3*y)/R;s=-q-r
    rq,rr,rs=round(q),round(r),round(s);dq,dr,ds=abs(rq-q),abs(rr-r),abs(rs-s)
    if dq>dr and dq>ds:rq=-rr-rs
    elif dr>ds:rr=-rq-rs
    return rq,rr
GEN=('restaurant','cafe','bar','pub','fast food','food court','coffee shop','american','sandwich','regional','international','asian')
CITY=collections.Counter(p[3] for p in pts)
H=collections.defaultdict(list)
for p in pts:H[cube(*xy(p))].append(p)
hexes=[]
for (q,r),ps in H.items():
    n=len(ps)
    if n<3:continue
    cx=R*math.sqrt(3)*(q+r/2);cy=R*1.5*r
    m=[sum(p[7][i] for p in ps) for i in range(5)];sp=sum(p[5]*p[8] for p in ps)/sum(p[8] for p in ps)
    cc=collections.Counter(p[3] for p in ps if p[3] not in GEN)
    cc={c:v for c,v in cc.items() if v>=2}
    cc=collections.Counter({c:v/CITY[c] for c,v in cc.items()})
    ps2=sorted(ps,key=lambda p:-p[8]*(p[4]==max(range(5),key=lambda i:m[i])))
    hexes.append([round(lon0+cx/kx,5),round(lat0+cy/ky,5),n,[round(x,1) for x in m],round(sp,2),[c for c,_ in cc.most_common(3)],[p[2] for p in ps2[:3]]])
mx=max(h[2] for h in hexes)
def inside(h):
    r=R*min(1.12,.62+.8*math.sqrt(h[2]/mx));cx,cy=(h[0]-lon0)*kx,(h[1]-lat0)*ky
    for p in H[cube(cx,cy)]:
        dx,dy=abs(p[0]-h[0])*kx,abs(p[1]-h[1])*ky
        if dx<=r*math.sqrt(3)/2 and dy+dx/math.sqrt(3)<=r:return True
hexes=[h for h in hexes if inside(h)]
print(len(hexes))
# base layers
def simp(g,step=1):return [[round(p['lon'],4),round(p['lat'],4)] for p in g[::step]]
W=[];Rd=[]
for e in json.load(open('data/water.json'))['elements']:
    gs=[e['geometry']] if e['type']=='way' else [m['geometry'] for m in e.get('members',[]) if m.get('geometry')]
    for g in gs:
        if len(g)>3:W.append(simp(g))
if os.path.exists('data/roads.json'):
    for e in json.load(open('data/roads.json'))['elements']:Rd.append(simp(e['geometry']))
Hd=[]
if os.path.exists('data/hoods.json'):
    Hd=[[e['lon'],e['lat'],e['tags']['name']] for e in json.load(open('data/hoods.json'))['elements']]
bd=[[[round(a,4),round(b,4)] for a,b in r] for r in OUT]
out=dict(boundary=bd,F=F,pts=pts,hexes=hexes,water=W,roads=Rd,hoods=Hd,R=R,lat0=lat0,lon0=lon0)
json.dump(out,open('data/portland.json','w'),separators=(',',':'))
print(os.path.getsize('data/portland.json')//1024,'KB',len(W),len(Rd),len(Hd))
