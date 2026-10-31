"""Geocode case addresses.

    python3 tools/geocode.py <data/geocode-cache.json> <cases.json> [more.json ...]

Two sources, both cached in the same file:
  county: Charleston County address points (exact building/lot location)
  census: US Census Geocoder batch API (interpolated along the street)

Only street addresses (those starting with a house number) are sent. Results
are cached, so re-runs only look up new addresses. A miss is cached as null;
delete the entry to retry it. Locations the geocoder cannot resolve
(intersections, tracts, subdivisions) can be pinned by hand in
data/geocode-overrides.json, which build_data.py applies on top of the cache.

API: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
"""
import csv
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
COUNTY_URL = ("https://gisccapps.charlestoncounty.org/arcgis/rest/services/LOCATORS/"
              "AddressStreetCompositeLocator_Pro/GeocodeServer/findAddressCandidates")
CITY, STATE = "Mount Pleasant", "SC"
# Loose bounding box around the Town; anything outside is a false match.
BBOX = (32.70, 33.00, -80.00, -79.65)  # lat_min, lat_max, lng_min, lng_max


def street_addresses(cases):
    seen = set()
    for c in cases:
        a = re.sub(r"\s+", " ", c.get("address") or c.get("label") or "").strip()
        if re.match(r"^\d+[A-Za-z]?\s+\S", a) and a.lower() not in seen:
            seen.add(a.lower())
            yield a


def batch(addresses):
    rows = io.StringIO()
    w = csv.writer(rows)
    for i, a in enumerate(addresses):
        w.writerow([i, a.replace("’", "'"), CITY, STATE, ""])
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\n"
        "Public_AR_Current\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"addressFile\"; "
        "filename=\"addresses.csv\"\r\nContent-Type: text/csv\r\n\r\n"
        + rows.getvalue() + f"\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        BATCH_URL, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        text = r.read().decode("utf-8", "replace")
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6 or row[2] != "Match":
            continue
        lng, lat = (float(v) for v in row[5].split(","))
        if BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lng <= BBOX[3]:
            out[int(row[0])] = {"lat": round(lat, 6), "lng": round(lng, 6),
                                "matched": row[4], "quality": row[3].lower()}
    return out


def county(address):
    q = urllib.parse.urlencode({
        "SingleLine": f"{address.replace('’', chr(39))}, {CITY}, {STATE}",
        "outSR": 4326, "maxLocations": 3, "outFields": "Addr_type,Score", "f": "json"})
    with urllib.request.urlopen(COUNTY_URL + "?" + q, timeout=60) as r:
        cands = json.load(r).get("candidates", [])
    for c in cands:
        if c["attributes"].get("Addr_type") == "PointAddress" and c["score"] >= 90:
            lat, lng = c["location"]["y"], c["location"]["x"]
            if BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lng <= BBOX[3]:
                return {"lat": round(lat, 6), "lng": round(lng, 6), "matched": c["address"],
                        "quality": "address point"}
    return None


def main(cache_path, *case_paths):
    cases = [c for p in case_paths for c in json.load(open(p, encoding="utf-8"))]
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    # Migrate the old flat format ({address: census_hit}) to {address: {census, county}}.
    cache = {a: (v if isinstance(v, dict) and ("census" in v or "county" in v) else {"census": v})
             for a, v in cache.items()}
    addrs = list(street_addresses(cases))
    todo = [a for a in addrs if "census" not in cache.get(a, {})]
    print(f"census: {len(todo)} addresses to geocode")
    for start in range(0, len(todo), 500):
        chunk = todo[start:start + 500]
        hits = batch(chunk)
        for i, a in enumerate(chunk):
            cache.setdefault(a, {})["census"] = hits.get(i)
    todo = [a for a in addrs if "county" not in cache.get(a, {})]
    print(f"county: {len(todo)} addresses to geocode")
    with ThreadPoolExecutor(6) as pool:
        for a, hit in zip(todo, pool.map(county, todo)):
            cache.setdefault(a, {})["county"] = hit
    json.dump(dict(sorted(cache.items())), open(cache_path, "w"), indent=1, ensure_ascii=False)
    for src in ("county", "census"):
        print(f"{src}: {sum(1 for v in cache.values() if v.get(src))}/{len(cache)} matched")


if __name__ == "__main__":
    main(*sys.argv[1:])
