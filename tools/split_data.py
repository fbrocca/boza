"""Write small per-page data files at deploy, so pages don't download the whole record.

    python3 tools/split_data.py <site_dir>

  <site_dir>/data/minutes/<property id>.json  minutes text for one property's hearings ({event id: text}),
                                             fetched by the map when someone opens a minutes excerpt
                                             (instead of the 3.3 MB data/minutes-text.json)
  <site_dir>/data/cases-lite.json            every case with only the fields the neighborhood pages use
                                             (instead of the 3.3 MB data/properties.json)
"""
import collections
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
CASE_FIELDS = ("board", "kind", "status", "date", "first", "case", "units")


def main(site):
    texts = json.load(open(os.path.join(DATA, "minutes-text.json")))
    by_prop = collections.defaultdict(dict)
    for eid, t in texts.items():
        if t:
            by_prop[eid.split("~", 1)[0]][eid] = t
    out = os.path.join(site, "data", "minutes")
    os.makedirs(out, exist_ok=True)
    for pid, d in by_prop.items():
        with open(os.path.join(out, f"{pid}.json"), "w") as f:
            json.dump(d, f, separators=(",", ":"))
    props = json.load(open(os.path.join(DATA, "properties.json")))["properties"]
    lite = [{"id": p["id"], "address": p["address"], "lat": p.get("lat"), "lng": p.get("lng"),
             "cases": [{k: c[k] for k in CASE_FIELDS if c.get(k) is not None} for c in p["cases"]]} for p in props]
    with open(os.path.join(site, "data", "cases-lite.json"), "w") as f:
        json.dump({"properties": lite}, f, separators=(",", ":"))
    size = os.path.getsize(os.path.join(site, "data", "cases-lite.json"))
    print(f"split: minutes text for {len(by_prop)} properties; cases-lite.json {size / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv[1])
