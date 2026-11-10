"""Merge all extracted cases and locations into the files the map page loads.

    python3 tools/build_data.py <data_dir>

Reads   data/cases.json       Board of Zoning Appeals hearings (extract_cases.py)
        data/planning.json    Planning Commission -> Committee -> Council cases
                              (extract_planning.py)
        data/parcels.json, data/geocode-cache.json, data/geocode-overrides.json
        minutes/index.csv     links to the Town's copy of BOZA minutes
        data/agenda-docs.json case documents linked from each agenda (agenda_docs.py)
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


BOZA_OUTCOME = {"approved": "Approved", "approved_with_conditions": "Approved with conditions", "denied": "Denied",
                "withdrawn": "Withdrawn", "deferred": "Deferred", "upheld": "Upheld", "reversed": "Reversed"}
COUNCIL_OUTCOME = {"adopted": "Adopted by Council", "denied": "Denied by Council",
                   "first_reading_only": "Passed first reading", "withdrawn": "Withdrawn", "deferred": "Deferred"}
PC_OUTCOME = {"recommended_approval": "Recommended approval", "recommended_denial": "Recommended denial",
              "withdrawn": "Withdrawn", "deferred": "Deferred"}
FACT_KEYS = ("type", "relief", "magnitude", "magnitude_pct", "vote", "key_factor", "evidence", "hardship", "reasons_given",
             "self_created_raised", "public_opposition", "public_support", "revised_or_reduced", "comp_plan",
             "zone_from", "zone_to", "quality")


def apply_facts(c, f):
    """Use the outcome read from the minutes (case-facts.json) when it is known."""
    if not f:
        return
    if c["board"] == "boza":
        st = BOZA_OUTCOME.get(f.get("outcome"))
    else:
        st = COUNCIL_OUTCOME.get(f.get("council_outcome")) or PC_OUTCOME.get(f.get("outcome"))
    if st and st != c["status"]:
        c["auto_status"] = c["status"]
        c["status"] = st
        if c["board"] == "boza" and c["events"]:
            c["events"][-1]["decision"] = st
    c["facts"] = {k: f[k] for k in FACT_KEYS if f.get(k) not in (None, [], "")}
    c["reviewed"] = 1


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
            "fact_key": "pc:" + (c["case"] or c["events"][0]["date"]) + ":" + (c["tms"][0] if c["tms"] else ""),
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


def design_cases(cases):
    """HDPC / DRB projects (extract_design.py): decided by the board itself, no case numbers."""
    unk = lambda d: d if d != "Unknown" else "See minutes"
    return [{
        "board": "design", "case": None, "kind": c["kind"], "request": c["request"],
        "status": unk(c["status"]), "tms": c["tms"], "address": c["label"],
        "events": [{"body": e["body"], "date": e["date"], "decision": unk(e["decision"]),
                    "page": e["page"], "town": e["town"], "text": e["text"]} for e in c["events"]],
    } for c in cases]


TMS_ANY = re.compile(r"(?<!\d)(\d{3})-?(\d{2})-?(\d{2})-?(\d{3})(?!\d)")
HOUSE = re.compile(r"(?<![\d-])(\d{1,5})\s+([A-Za-z]{3,})")


GENERAL_DOC = re.compile(r"overlay|guideline|\bDG\b|parking|ordinance|\bcode\b|workshop|training|meeting|"
                         r"update|discussion|policy|agenda|minutes|bylaws|calendar", re.I)


def item_matches(doc, prop):
    """A HDPC/DRB agenda document: does it belong to this property?

    If the document's own name gives a TMS or a street address, that must match the
    property. Otherwise the property must be the first one named in its agenda item
    (items often list several properties, e.g. a consent list)."""
    tms = {t.replace("-", "") for t in [prop.get("tms")] + prop.get("other_tms", []) if t}
    m = re.match(r"(\d+)\s+(\w+)", prop.get("address", ""))
    house = (m.group(1), m.group(2).lower()) if m else None
    def same_house(h):
        return bool(house) and h.group(1) == house[0] and h.group(2).lower()[:4] == house[1][:4]
    label = doc.get("label", "")
    lt = TMS_ANY.search(label)
    if lt:
        return "".join(lt.groups()) in tms
    lh = HOUSE.search(label)
    if lh:
        return same_house(lh)
    # No address or TMS in the document's name. HDPC discussion items attach general documents
    # (guidelines, overlay district, parking) next to addresses, so only DRB project documents
    # ("Starbucks", "Chase Bank SUB") are matched this way, and never obviously general ones.
    if doc.get("body") != "drb" or GENERAL_DOC.search(label):
        return False
    item = doc.get("item", "")
    it, ih = TMS_ANY.search(item), HOUSE.search(item)
    first = min([x for x in (it, ih) if x], key=lambda x: x.start(), default=None)
    if first is it and it:
        return "".join(it.groups()) in tms
    return bool(ih) and same_house(ih)


CASE_IN_NAME = re.compile(r"\b(?:[AVSR]|SP)\s?[-–]\s?\d{1,3}\s?[-–]\s?\d{2,4}\b")
DOC_GENERIC = set("""staff report reports application applications plan plans sketch presentation correspondence
amendment request combined final draft document documents rezoning zoning case review update placeholder
road street drive lane avenue boulevard court highway north south circle parcel parcels planning commission
board appeals boza submittal letter letters comments written exhibit narrative proposed public hearing
with from this that page pages copy revised""".split())


def doc_words(text):
    return {w for w in re.findall(r"[a-z]{4,}", text.lower().replace("’", "'"))} - DOC_GENERIC


def retype(doc):
    """Same rules as agenda_docs.doc_type, applied to links cached before a rule changed."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from agenda_docs import doc_type
    return doc_type(doc["label"]) if doc["type"] in ("Document", "Correspondence") else doc["type"]


def verified(doc, case, prop):
    """Keep a document link only when its assignment can be checked."""
    if doc["case"] is None:
        return True  # meeting-wide staff report, named only by board and date
    if CASE_IN_NAME.search(doc["url"].rsplit("/", 1)[-1].replace(" ", "-")) or CASE_IN_NAME.search(doc["label"].replace(" ", "-")):
        return True  # the document is named after the case
    # Assigned by position on the agenda: only if its name mentions this property.
    subject = doc_words(" ".join([prop["address"], prop.get("name", "")]))
    return bool(doc_words(doc["label"]) & subject)


def main(out_dir):
    hearings = load(os.path.join(out_dir, "cases.json"), [])
    planning = load(os.path.join(out_dir, "planning.json"), [])
    design = load(os.path.join(out_dir, "design.json"), [])
    geo = load(os.path.join(out_dir, "geocode-cache.json"), {})
    parcels = load(os.path.join(out_dir, "parcels.json"), {})
    agenda_docs = load(os.path.join(out_dir, "agenda-docs.json"), {})
    body_key = {"Board of Zoning Appeals": "boza", "Planning Commission": "pc",
                "Historic District Preservation Commission": "hdpc", "Design Review Board": "drb"}
    overrides = {k: v for k, v in load(os.path.join(out_dir, "geocode-overrides.json"), {}).items()
                 if not k.startswith("_")}
    town = {}
    with open(os.path.join(ROOT, "minutes", "index.csv")) as f:
        for row in csv.DictReader(f):
            town[row["date"]] = row["source_minutes"]

    stats = collections.Counter()
    cases = boza_cases(hearings, town) + planning_cases(planning) + design_cases(design)
    facts = load(os.path.join(out_dir, "case-facts.json"), {})
    zoning = load(os.path.join(out_dir, "zoning.json"), {})
    sales = load(os.path.join(out_dir, "sales.json"), {})
    boza_facts = collections.defaultdict(list)
    for k, v in facts.items():
        if k.startswith("boza:"):
            boza_facts[k.split(":")[1]].append((k.split(":")[2], v))
    for c in cases:
        if c["board"] == "boza":
            cands = boza_facts.get(c["case"], [])
            last = max(e["date"] for e in c["events"])
            f = next((v for d, v in cands if d == last), cands[0][1] if len(cands) == 1 else None)
        else:
            f = facts.get(c.pop("fact_key", None) or "")
        apply_facts(c, f)
        if c.get("reviewed"):
            stats["reviewed"] += 1
        if c.get("auto_status"):
            stats["corrected"] += 1
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
        z = zoning.get(p["tms"]) if p["tms"] else None
        if z:
            p["zoning"] = {k: v for k, v in z.items() if v not in (None, [], False, "")}
        sale = sales.get(p["tms"]) if p["tms"] else None
        if sale:  # last recorded transfer + county appraisal (tools/sales.py)
            p["sale"] = {k: sale[k] for k in ("price", "date", "deed", "land", "building", "appraisal", "nominal") if k in sale}
        for c in p["cases"]:
            c.pop("tms"), c.pop("address")
            c["events"].sort(key=lambda e: e["date"])
            c["date"] = c["events"][-1]["date"]
            c["first"] = c["events"][0]["date"]
            for k, e in enumerate(c["events"]):
                e["id"] = f"{p['id']}~{c['board']}~{c['case'] or c['first']}~{k}"
                docs = agenda_docs.get(f"{body_key.get(e['body'])}/{e['date']}", [])
                mine = [d for d in docs if c["case"] and d["case"] == c["case"] and verified(d, c, p)]
                if c["board"] == "design":
                    bk = body_key.get(e["body"])
                    mine = [d for d in docs if d.get("item") and item_matches({**d, "body": bk}, p)]
                wide = [d for d in docs if d["case"] is None and not d.get("item")]
                if mine or wide:
                    e["docs"] = ([{"t": retype(d), "u": d["url"], "l": d["label"]} for d in mine] +
                                 [{"t": d["type"], "u": d["url"], "l": d["label"], "all": 1} for d in wide])
                    stats["events_with_docs"] += 1
                texts[e["id"]] = cap(e.pop("text") or "")
                for f in [f for f, v in e.items() if v in (None, "")]:
                    del e[f]
        p["cases"].sort(key=lambda c: c["date"], reverse=True)
        p["date"] = p["cases"][0]["date"]
        out.append(p)
    out.sort(key=lambda p: p["date"], reverse=True)

    n_events = collections.Counter(e["body"] for p in out for c in p["cases"] for e in c["events"])
    meta = {"properties": len(out), "mapped": stats["mapped"], "events_with_docs": stats["events_with_docs"],
            "reviewed": stats["reviewed"], "corrected": stats["corrected"],
            "cases": {b: sum(1 for p in out for c in p["cases"] if c["board"] == b) for b in ("boza", "planning", "design")},
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
