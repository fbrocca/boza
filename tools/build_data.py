"""Merge all extracted cases and locations into the files the map page loads.

    python3 tools/build_data.py <data_dir>

Reads   data/cases.json       Board of Zoning Appeals hearings (extract_cases.py)
        data/planning.json    Planning Commission -> Committee -> Council cases
                              (extract_planning.py)
        data/parcels.json, data/geocode-cache.json, data/geocode-overrides.json
        minutes/index.csv     links to the Town's copy of BOZA minutes
Writes  data/properties.json  one entry per parcel, each with its cases and
                              each case with its timeline of events
        data/minutes-text.json minutes text per event, loaded on demand
"""
import collections
import csv
import json
import math
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEXT_CAP = 9000  # characters of minutes text kept per event; the PDF link has the rest


def load(path, default):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def dist_m(a, b):
    return math.hypot((a["lat"] - b["lat"]) * 111000, (a["lng"] - b["lng"]) * 93500)


def locate(tms, address, pid, parcels, geo, overrides):
    """Pick the best location for a property. Returns (loc, source, parcel)."""
    o = overrides.get(pid) or overrides.get(address)
    if o:
        return o, "manual", None
    par = parcels.get(tms) if tms else None
    g = geo.get(address) or {}
    pt, census = g.get("county"), g.get("census")
    if par and pt:
        if dist_m(par, pt) <= 300:
            return par, "parcel", par
        return pt, "address point (TMS in minutes did not match)", None
    if par:
        if census and dist_m(par, census) > 1500:
            return census, "street estimate (TMS in minutes did not match)", None
        return par, "parcel", par
    if pt:
        return pt, "address point", None
    if census:
        return census, "street estimate", None
    return None, None, None


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def is_street(s):
    return bool(s) and bool(re.match(r"^[1-9]\d*", s))


def clean_request(req, case):
    """Drop the case number, TMS list and 'PUBLIC HEARING' that repeat the card header."""
    req = re.sub(r"\b(?:R|SP)\s?-\s?\d{1,3}\s?-\s?\d{2,4}\b[\s.,:—–-]*", "", req)
    req = re.sub(r"^\W*(?:PUBLIC HEARING|SKETCH PLAN|Sketch Plan|(?:Re)?[Zz]oning Case)\W*", "", req)
    req = re.sub(r",?\s*TMS\s*(?:No[s]?\.?|#)?\s*[\d\s,&-]+(?:and\s+[\d-]+)?[.,]?", " ", req)
    req = re.sub(r"^\W*PUBLIC HEARING\W*", "", req, flags=re.I)
    return re.sub(r"\s+", " ", req).strip(" ,.")


def cap(text):
    return text if len(text) <= TEXT_CAP else text[:TEXT_CAP].rsplit(" ", 1)[0] + " …\n\n[Truncated. Open the PDF for the full minutes.]"


def boza_cases(hearings, town):
    """Group BOZA hearings by case number into cases with a timeline."""
    by_case = collections.defaultdict(list)
    for h in hearings:
        by_case[h["case"]].append(h)
    # Items without an address/TMS (extension requests) inherit them from the case.
    for hs in by_case.values():
        tms = next((h["tms"] for h in hs if h["tms"]), None)
        addr = next((h["address"] for h in hs if h["address"]), "")
        for h in hs:
            h["tms"] = h["tms"] or tms
            h["address"] = h["address"] or addr
    out = []
    for cid, hs in by_case.items():
        # A case number can (rarely) cover two parcels; split by parcel.
        groups = collections.defaultdict(list)
        for h in sorted(hs, key=lambda h: (h["date"], h["page"])):
            groups[h["tms"] or h["address"]].append(h)
        for hs2 in groups.values():
            last = hs2[-1]
            out.append({
                "board": "boza", "case": cid, "kind": last["kind"],
                "request": next((h["request"] for h in reversed(hs2) if h["request"]), ""),
                "status": last["decision"] if last["decision"] != "Unknown" else "See minutes",
                "tms": [last["tms"]] if last["tms"] else [], "address": last["address"],
                "events": [{
                    "body": "Board of Zoning Appeals", "date": h["date"],
                    "decision": h["decision"] if h["decision"] != "Unknown" else "See minutes",
                    "item": h["item"] if h["item"] != "hearing" else None, "note": h.get("note"),
                    "page": h["page"], "pdf": f"minutes/{h['date']}.pdf", "town": town.get(h["date"]),
                    "text": h["text"],
                } for h in hs2],
            })
    return out


RECOMMENDS = ("Rezoning", "Annexation and zoning", "PD / development agreement amendment")
AS_RECOMMENDATION = {"Approved": "Recommended approval", "Approved with conditions": "Recommended approval",
                     "Denied": "Recommended denial"}


def pc_decision(c, e):
    d = e["decision"]
    if e["body"] == "Planning Commission" and c["kind"] in RECOMMENDS:
        d = AS_RECOMMENDATION.get(d, d)
    return d if d != "Unknown" else "See minutes"


def planning_cases(cases):
    out = []
    for c in cases:
        out.append({
            "board": "planning", "case": c["case"], "kind": c["kind"], "request": clean_request(c["request"], c["case"]),
            "status": c["status"] if c["status"] != "Unknown" else "See minutes",
            "tms": c["tms"], "address": c["label"],
            "events": [{
                "body": e["body"], "date": e["date"],
                "decision": pc_decision(c, e),
                "ord": e.get("ord"), "page": e["page"], "town": e["town"], "text": e["text"],
            } for e in c["events"]],
        })
    return out


def main(out_dir):
    hearings = load(os.path.join(out_dir, "cases.json"), [])
    planning = load(os.path.join(out_dir, "planning.json"), [])
    geo = load(os.path.join(out_dir, "geocode-cache.json"), {})
    parcels = load(os.path.join(out_dir, "parcels.json"), {})
    overrides = {k: v for k, v in load(os.path.join(out_dir, "geocode-overrides.json"), {}).items()
                 if not k.startswith("_")}
    town = {}
    with open(os.path.join(ROOT, "minutes", "index.csv")) as f:
        for row in csv.DictReader(f):
            town[row["date"]] = row["source_minutes"]

    cases = boza_cases(hearings, town) + planning_cases(planning)
    props = collections.OrderedDict()
    skipped = []
    for c in cases:
        if c["tms"]:
            key = "tms-" + c["tms"][0]
        elif c["address"]:
            key = "addr-" + slug(c["address"])
        else:
            skipped.append(f"{c['board']}:{c['case']}")
            continue
        p = props.setdefault(key, {"id": key, "tms": c["tms"][0] if c["tms"] else None,
                                   "other_tms": [], "names": collections.Counter(), "cases": []})
        p["other_tms"] += [t for t in c["tms"][1:] if t not in p["other_tms"]]
        if c["address"]:
            p["names"][c["address"]] += 3 if c["board"] == "boza" else (2 if is_street(c["address"]) else 1)
        p["cases"].append(c)

    texts = {}
    stats = collections.Counter()
    out = []
    for p in props.values():
        names = [n for n, _ in p.pop("names").most_common()]
        street = next((n for n in names if is_street(n)), None)
        par = parcels.get(p["tms"]) if p["tms"] else None
        rev = re.sub(r"^0+\s+", "", (par or {}).get("address") or "")
        p["address"] = street or rev or (names[0] if names else "") or f"TMS {p['tms']}"
        if names and names[0] != p["address"] and not is_street(names[0]):
            p["name"] = names[0]
        lookup = street or p["address"]
        loc, src, parcel = locate(p["tms"], lookup, p["id"], parcels, geo, overrides)
        if loc:
            p["lat"], p["lng"], p["geo"] = loc["lat"], loc["lng"], src
            if parcel:
                p["rings"], p["acres"] = parcel["rings"], parcel.get("acres")
            stats["mapped"] += 1
        else:
            stats["unmapped"] += 1
        if not p["other_tms"]:
            del p["other_tms"]
        for c in p["cases"]:
            c.pop("tms"), c.pop("address")
            c["events"].sort(key=lambda e: e["date"])
            c["date"] = c["events"][-1]["date"]
            c["first"] = c["events"][0]["date"]
            for k, e in enumerate(c["events"]):
                e["id"] = f"{p['id']}~{c['board']}~{c['case'] or c['first']}~{k}"
                texts[e["id"]] = cap(e.pop("text") or "")
                for f in [f for f, v in e.items() if v in (None, "")]:
                    del e[f]
        p["cases"].sort(key=lambda c: c["date"], reverse=True)
        p["date"] = p["cases"][0]["date"]
        out.append(p)
    out.sort(key=lambda p: p["date"], reverse=True)

    n_events = collections.Counter(e["body"] for p in out for c in p["cases"] for e in c["events"])
    meta = {"properties": len(out), "mapped": stats["mapped"],
            "cases": {b: sum(1 for p in out for c in p["cases"] if c["board"] == b) for b in ("boza", "planning")},
            "events": dict(n_events),
            "first": min(c["first"] for p in out for c in p["cases"]),
            "last": max(p["date"] for p in out)}
    json.dump({"meta": meta, "properties": out}, open(os.path.join(out_dir, "properties.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    json.dump(texts, open(os.path.join(out_dir, "minutes-text.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(meta))
    print("skipped (no parcel or address):", len(skipped), skipped[:20])


if __name__ == "__main__":
    main(sys.argv[1])
