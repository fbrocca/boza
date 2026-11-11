"""Frequently raised questions, from coded minutes sentences.

    python3 tools/faq_build.py

Input: data/questions-coded.json, one record per question or concern sentence found in
the minutes (who raised it, topic, a plain restated question, the hearing it came from),
coded by AI readers against a fixed sheet and checked against the minutes text.
Output: data/faq.json

  groups: what boards ask, per type of request. For each topic: in how many hearings a
          board member raised it, out of hearings of that type with minutes; and up to
          three example questions (restated, no names) linked to a case.
  hoods:  what residents raise at hearings in each neighborhood (same shape).

Counts are hearings, not sentences, so one long exchange counts once. Minutes record
questions selectively, so counts understate how often a topic comes up.
"""
import collections
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
SKIP = {"procedural", "other"}
SETBACKS = {"front_setback", "side_setback", "rear_setback", "multiple_setbacks"}
LABEL = {
    "alternatives": "Alternatives to the request", "hardship_origin": "Where the hardship comes from",
    "size_dimensions": "Size and dimensions", "neighbors": "Neighbors and outreach", "trees": "Trees",
    "drainage_flooding": "Drainage and flooding", "traffic_access_parking": "Traffic, access and parking",
    "design_character": "Design and neighborhood character", "historic": "Historic fabric",
    "density_use": "Density and use", "environment": "Buffers, marsh and environment",
    "infrastructure_services": "Schools and infrastructure", "process_precedent": "Process and precedent",
    "conditions_construction": "Conditions and construction",
}


def group_of(board, kind, relief):
    if board == "Board of Zoning Appeals":
        out = ["boza:all"]
        if relief and kind == "Variance":
            out.append(f"boza:{relief}")
            if relief in SETBACKS:
                out.append("boza:setbacks")
        return out
    if board in ("Planning Commission", "Planning Committee", "Town Council"):
        if kind in ("Sketch plan", "Subdivision plat"):
            return ["planning:subdivision"]
        if kind in ("Rezoning", "Annexation and zoning", "PD / development agreement amendment"):
            return ["planning:rezoning"]
        return []
    if board == "Historic District Preservation Commission":
        return ["hdpc:all"]
    if board == "Design Review Board":
        return ["drb:all"]
    return []


def summarize(recs, hearings):
    by_topic = collections.defaultdict(list)
    for r in recs:
        by_topic[r["topic"]].append(r)
    out = []
    for topic, rs in by_topic.items():
        heard = len({r["event"] for r in rs})
        seen, ex = set(), []
        # distinct examples of middling length (the shortest tend to be trivia, the longest too specific)
        for r in sorted(rs, key=lambda r: (abs(len(r["q"].split()) - 9), r["q"])):
            key = r["q"].lower().rstrip("?")
            if key not in seen and len(ex) < 3:
                seen.add(key)
                ex.append({"q": r["q"], "pid": r["pid"], "case": r.get("case"), "date": r["date"]})
        out.append({"topic": topic, "label": LABEL.get(topic, topic), "hearings": heard, "examples": ex})
    out.sort(key=lambda t: -t["hearings"])
    return {"hearings": hearings, "topics": out}


def main():
    coded = json.load(open(os.path.join(DATA, "questions-coded.json")))
    props = json.load(open(os.path.join(DATA, "properties.json")))["properties"]
    texts = json.load(open(os.path.join(DATA, "minutes-text.json")))
    nb = json.load(open(os.path.join(DATA, "neighborhoods.json")))
    # hearings with minutes, per group (denominators)
    denom = collections.Counter()
    for p in props:
        for c in p["cases"]:
            if c["kind"] == "Staff approval":
                continue
            relief = (c.get("facts") or {}).get("relief")
            for e in c["events"]:
                if texts.get(e["id"]):
                    for g in group_of(e["body"], c["kind"], relief):
                        denom[g] += 1
    board_recs, hood_recs = collections.defaultdict(list), collections.defaultdict(list)
    for r in coded:
        if r["topic"] in SKIP:
            continue
        r["event"] = r["id"].split("#")[0]
        if r["role"] == "board":
            for g in group_of(r["board"], r["kind"], r.get("relief")):
                board_recs[g].append(r)
        elif r["role"] == "resident":
            h = nb["assign"].get(r["pid"])
            if h and h != "other-areas":
                hood_recs[h].append(r)
    hood_denom = collections.Counter()
    for p in props:
        h = nb["assign"].get(p["id"])
        for c in p["cases"]:
            for e in c["events"]:
                if h and texts.get(e["id"]) and c["kind"] != "Staff approval":
                    hood_denom[h] += 1
    out = {
        "note": "Counts are hearings where the topic was raised, out of hearings with minutes. Minutes record questions selectively.",
        "groups": {g: summarize(rs, denom[g]) for g, rs in board_recs.items() if len({r['event'] for r in rs}) >= 5},
        "hoods": {h: summarize(rs, hood_denom[h]) for h, rs in hood_recs.items() if len({r['event'] for r in rs}) >= 3},
    }
    with open(os.path.join(DATA, "faq.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"faq: {len(out['groups'])} request groups, {len(out['hoods'])} neighborhoods")


if __name__ == "__main__":
    main()
