"""Assign every mapped property to a neighborhood and write data/neighborhoods.json.

    python3 tools/neighborhoods.py

Boundaries come from the Town of Mount Pleasant's GIS:
  1. Old Village Historic District (OV-HD overlay)            -> "Old Village"
  2. Neighborhood Preservation Overlay neighborhoods (NP-OD)    -> e.g. "Old Mount Pleasant", "Shemwood"
  3. Town subdivisions with recorded plats (959 polygons)       -> e.g. "I'On", "Park West"
  4. Mixed-use and community overlays (corridors, Ten Mile)     -> e.g. "Belle Hall area"
First match wins, in that order. Properties outside all of them are "Other areas".
Sections of one subdivision ("Rivertowne_High Marsh") are merged under one name.
Boundaries are simplified (~5 m) and kept only for neighborhoods that have cases.
"""
import json
import os
import re
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "neighborhoods.json")
SHAPES = os.path.join(ROOT, "data", "neighborhood-shapes.json")
TOWN = "https://maps.tompsc.com/arcgis/rest/services"
SUBDIV = f"{TOWN}/Town_Subdivisions_with_Plats/MapServer/0/query"
OVERLAY = f"{TOWN}/Parcel_Search_New/MPSC_Zoning_New/MapServer/0/query"
UA = {"User-Agent": "boza-archive (+https://github.com/fbrocca/boza)"}
MIN_CASES = 3
NAME_FIX = {"Ion": "I'On"}  # GIS spelling vs the neighborhood's own  # neighborhoods with fewer cases are listed but get no page of their own


def query(url, where, fields):
    feats, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"where": where, "outFields": fields, "outSR": 4326, "returnGeometry": "true",
                                    "maxAllowableOffset": 0.00005, "geometryPrecision": 5, "f": "json",
                                    "resultOffset": offset, "resultRecordCount": 1000})
        with urllib.request.urlopen(urllib.request.Request(url + "?" + q, headers=UA), timeout=120) as r:
            d = json.load(r)
        if "error" in d:
            raise RuntimeError(d["error"])
        feats += d["features"]
        if not d.get("exceededTransferLimit"):
            return feats
        offset += len(d["features"])


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("’", "").replace("'", "")).strip("-")


def inside(lng, lat, rings):
    hit = False
    for ring in rings:
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            if (y0 > lat) != (y1 > lat) and lng < (x1 - x0) * (lat - y0) / (y1 - y0) + x0:
                hit = not hit
    return hit


def bbox(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return [min(xs), min(ys), max(xs), max(ys)]


def main():
    layers = []  # (priority, name, source, rings)
    for f in query(OVERLAY, "NAME IN ('OV-HD','NP-OD','MU-OD','10 Mile')", "NAME,LABEL"):
        a, rings = f["attributes"], f["geometry"]["rings"]
        if a["NAME"] == "OV-HD":
            layers.append((0, "Old Village", "Old Village Historic District", rings))
        elif a["NAME"] == "NP-OD":
            layers.append((1, a["LABEL"].strip(), "Neighborhood Preservation Overlay", rings))
        elif a["NAME"] == "10 Mile":
            layers.append((3, "Ten Mile community", "Ten Mile Community Overlay", rings))
        else:
            name = re.sub(r"\s+(C|N|R)?MU-OD$|\s+RC-OD$", "", a["LABEL"].replace("’", "'")).strip()
            layers.append((3, f"{name} area", "Mixed-use overlay district", rings))
    for f in query(SUBDIV, "1=1", "FULLNAME,SUBDIVISION_NAME"):
        a = f["attributes"]
        name = re.sub(r"\s+", " ", (a.get("FULLNAME") or a.get("SUBDIVISION_NAME") or "").split("_")[0]).strip()
        name = NAME_FIX.get(name, name)
        if name and f.get("geometry"):
            layers.append((2, name, "Town subdivision boundary", f["geometry"]["rings"]))
    layers.sort(key=lambda t: t[0])
    boxes = [bbox(r) for *_, r in layers]

    props = json.load(open(os.path.join(ROOT, "data", "properties.json")))["properties"]
    assign, hoods = {}, {}
    for p in props:
        if not p.get("lat"):
            continue
        hit = None
        for (pri, name, src, rings), (x0, y0, x1, y1) in zip(layers, boxes):
            if x0 <= p["lng"] <= x1 and y0 <= p["lat"] <= y1 and inside(p["lng"], p["lat"], rings):
                hit = (name, src)
                break
        name, src = hit or ("Other areas", None)
        s = slug(name)
        assign[p["id"]] = s
        h = hoods.setdefault(s, {"slug": s, "name": name, "source": src, "cases": 0, "props": 0})
        h["props"] += 1
        h["cases"] += len(p["cases"])

    # boundaries for neighborhoods with pages (merge all polygons sharing the name)
    for s, h in hoods.items():
        h["page"] = h["cases"] >= MIN_CASES and s != "other-areas"
        if not h["page"]:
            continue
        rings = [r for pri, name, src, rs in layers if slug(name) == s and src == h["source"] for r in rs]
        h["rings"] = [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings]
        h["bbox"] = [round(v, 5) for v in bbox(rings)] if rings else None
    shapes = {s: h.pop("rings") for s, h in hoods.items() if "rings" in h}
    data = {"hoods": sorted(hoods.values(), key=lambda h: -h["cases"]), "assign": assign}
    with open(OUT, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    with open(SHAPES, "w") as f:  # boundaries, loaded only by neighborhood pages
        json.dump(shapes, f, separators=(",", ":"))
    n_page = sum(h["page"] for h in hoods.values())
    print(f"{len(assign)} properties in {len(hoods)} neighborhoods; {n_page} with pages; "
          f"{hoods.get('other-areas', {}).get('props', 0)} properties in Other areas")


if __name__ == "__main__":
    main()
