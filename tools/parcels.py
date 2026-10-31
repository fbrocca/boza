"""Fetch parcel boundaries by TMS number from Charleston County GIS.

    python3 tools/parcels.py <cases.json> <data/parcels.json>

The county parcel layer (ProVal/Parcels) is keyed by PID, which is the TMS
number without dashes. For each TMS in the cases we store the lot outline
(simplified) and a point inside it for the map pin. TMS numbers retired since
the hearing (lots split or combined) are cached as null and fall back to the
street-address geocode.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

URL = ("https://gisccapps.charlestoncounty.org/arcgis/rest/services/"
       "ProVal/Parcels/MapServer/0/query")


def centroid(ring):
    """Area centroid of a polygon ring; falls back to the vertex mean."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        f = x0 * y1 - x1 * y0
        a += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(a) < 1e-14:
        n = len(ring)
        return sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n
    return cx / (3 * a), cy / (3 * a)


def inside(pt, ring):
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def ring_area(ring):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))) / 2


def label_point(ring):
    c = centroid(ring)
    if inside(c, ring):
        return c
    # Concave lot: scan horizontal lines for the widest interior span.
    ys = sorted(p[1] for p in ring)
    best, best_w = None, -1
    for k in range(1, 20):
        y = ys[0] + (ys[-1] - ys[0]) * k / 20
        xs = sorted(x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1])
                    if (y0 > y) != (y1 > y))
        for i in range(0, len(xs) - 1, 2):
            if xs[i + 1] - xs[i] > best_w:
                best_w, best = xs[i + 1] - xs[i], ((xs[i] + xs[i + 1]) / 2, y)
    return best or c


def fetch(pids):
    q = urllib.parse.urlencode({
        "where": "PID IN (" + ",".join(f"'{p}'" for p in pids) + ")",
        "outFields": "PID,ACRES_CAL", "outSR": 4326, "returnGeometry": "true",
        "geometryPrecision": 6, "maxAllowableOffset": 0.000005, "f": "json",
    })
    with urllib.request.urlopen(URL + "?" + q, timeout=120) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["features"]


def main(cases_path, out_path):
    cases = json.load(open(cases_path, encoding="utf-8"))
    cache = json.load(open(out_path)) if os.path.exists(out_path) else {}
    tms = sorted({c["tms"] for c in cases if c["tms"]} - set(cache))
    print(f"{len(tms)} parcels to fetch ({len(cache)} cached)")
    for i in range(0, len(tms), 80):
        chunk = tms[i:i + 80]
        got = {}
        for f in fetch([t.replace("-", "") for t in chunk]):
            rings = [r for r in f["geometry"]["rings"] if len(r) > 2]
            if not rings:
                continue
            main_ring = max(rings, key=ring_area)
            lng, lat = label_point([tuple(p) for p in main_ring[:-1]])
            got[f["attributes"]["PID"]] = {
                "lat": round(lat, 6), "lng": round(lng, 6),
                "acres": round(f["attributes"]["ACRES_CAL"] or 0, 3),
                "rings": [[[round(y, 6), round(x, 6)] for x, y in r] for r in rings],
            }
        for t in chunk:
            cache[t] = got.get(t.replace("-", ""))
        print(f"  {i + len(chunk)}/{len(tms)}: {len(got)} found")
    json.dump(dict(sorted(cache.items())), open(out_path, "w"), separators=(",", ":"))
    print(f"parcels: {sum(1 for v in cache.values() if v)}/{len(cache)} found")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
