"""Merge extracted cases and geocodes into the files the map page loads.

    python3 tools/build_data.py <cases.json> <data>

Reads   data/parcels.json, data/geocode-cache.json,
        data/geocode-overrides.json (optional) and
        minutes/index.csv (for links to the Town's copy).
Writes  data/properties.json   one entry per parcel, with its hearings
        data/minutes-text.json minutes excerpt per hearing, loaded on demand
"""
import collections
import csv
import json
import math
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load(path, default):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def dist_m(a, b):
    return math.hypot((a["lat"] - b["lat"]) * 111000, (a["lng"] - b["lng"]) * 93500)


def locate(p, parcels, geo, overrides):
    """Pick the best location for a property. Returns (loc, source, rings)."""
    o = overrides.get(p["id"]) or overrides.get(p["address"])
    if o:
        return o, "manual", None
    par = parcels.get(p["tms"]) if p["tms"] else None
    g = geo.get(p["address"]) or {}
    pt, census = g.get("county"), g.get("census")
    if par and pt:
        if dist_m(par, pt) <= 300:
            return par, "parcel", par["rings"]
        return pt, "address point (TMS in minutes did not match)", None
    if par:
        # No address point to confirm it: trust the parcel unless Census strongly disagrees.
        if census and dist_m(par, census) > 1500:
            return census, "street estimate (TMS in minutes did not match)", None
        return par, "parcel", par["rings"]
    if pt:
        return pt, "address point", None
    if census:
        return census, "street estimate", None
    return None, None, None


def key_for(c):
    if c["tms"]:
        return "tms-" + c["tms"]
    return "addr-" + re.sub(r"[^a-z0-9]+", "-", c["address"].lower()).strip("-")


def main(cases_path, out_dir):
    cases = json.load(open(cases_path, encoding="utf-8"))
    cache = load(os.path.join(out_dir, "geocode-cache.json"), {})
    parcels = load(os.path.join(out_dir, "parcels.json"), {})
    overrides = load(os.path.join(out_dir, "geocode-overrides.json"), {})
    overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
    town = {}
    with open(os.path.join(ROOT, "minutes", "index.csv")) as f:
        for row in csv.DictReader(f):
            town[row["date"]] = row["source_minutes"]

    # Items without an address/TMS (e.g. extension requests) inherit them from
    # another hearing of the same case.
    by_case = collections.defaultdict(list)
    for c in cases:
        by_case[c["case"]].append(c)
    for c in cases:
        if not c["tms"] or not c["address"]:
            for o in by_case[c["case"]]:
                if o is not c and o["tms"] and o["address"]:
                    c["tms"] = c["tms"] or o["tms"]
                    c["address"] = c["address"] or o["address"]
                    break

    props = collections.OrderedDict()
    texts = {}
    unplaced = []
    for c in sorted(cases, key=lambda c: (c["date"], c["page"])):
        if not c["tms"] and not c["address"]:
            unplaced.append(c["case"])
            continue
        k = key_for(c)
        p = props.setdefault(k, {"id": k, "tms": c["tms"], "addresses": collections.Counter(),
                                 "hearings": []})
        if c["address"]:
            p["addresses"][c["address"]] += 1
        hid = f"{c['date']}-{c['case']}-{len(p['hearings'])}"
        p["hearings"].append({k2: v for k2, v in {
            "id": hid, "date": c["date"], "case": c["case"], "kind": c["kind"],
            "item": c["item"], "decision": c["decision"], "request": c["request"],
            "page": c["page"], "note": c.get("note"),
            "pdf": f"minutes/{c['date']}.pdf",
            "town": town.get(c["date"]),
        }.items() if v})
        texts[hid] = c["text"]

    out = []
    stats = collections.Counter()
    for p in props.values():
        addr = p.pop("addresses").most_common(1)
        p["address"] = addr[0][0] if addr else ""
        loc, src, rings = locate(p, parcels, cache, overrides)
        if loc:
            p["lat"], p["lng"], p["geo"] = loc["lat"], loc["lng"], src
            if rings:
                p["rings"] = rings
                p["acres"] = loc.get("acres")
            stats["mapped"] += 1
            stats[src] += 1
        else:
            stats["unmapped"] += 1
        p["hearings"].sort(key=lambda h: h["date"], reverse=True)
        out.append(p)
    out.sort(key=lambda p: p["hearings"][0]["date"], reverse=True)

    meta = {"hearings": sum(len(p["hearings"]) for p in out), "properties": len(out),
            "mapped": stats["mapped"], "first": min(c["date"] for c in cases),
            "last": max(c["date"] for c in cases)}
    json.dump({"meta": meta, "properties": out},
              open(os.path.join(out_dir, "properties.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    json.dump(texts, open(os.path.join(out_dir, "minutes-text.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(meta), "| skipped (no address):", unplaced)
    print("location sources:", {k: v for k, v in stats.items() if k not in ("mapped",)})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
