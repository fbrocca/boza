"""Data for the landing page, written at deploy time.

    python3 tools/landing_data.py <site_dir>

  <site_dir>/data/summary.json  counts shown on the landing page
  <site_dir>/plat.svg           survey-style drawing of the lots that went before a Town
                                board around the Old Village and Coleman Boulevard; lots on
                                an agenda posted for an upcoming meeting are drawn in green
                                (class "soon")
"""
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
LAT0, LNG0 = 32.7902, -79.8655  # centre: Old Village and the Coleman Blvd corridor
W, H = 1200, 480                 # the frame's proportions on the page, so nothing is cropped
DLNG = 0.0165                    # half-width in degrees of longitude
KX = W / (2 * DLNG)              # pixels per degree of longitude
KY = KX / math.cos(math.radians(LAT0))  # true shapes: a degree of latitude is longer than one of longitude
DLAT = H / 2 / KY


def load(name, default):
    try:
        return json.load(open(os.path.join(DATA, name)))
    except (OSError, ValueError):
        return default


def main(site):
    props = load("properties.json", {"properties": [], "meta": {}})
    nb = load("neighborhoods.json", {"hoods": []})
    up = load("upcoming.json", {"meetings": []})
    questions = load("questions-coded.json", [])
    cases = props["meta"].get("cases", {})
    soon = {it.get("property") for m in up.get("meetings", []) for it in m["items"] if it.get("property")}
    summary = {
        "decisions": sum(cases.values()),
        "neighborhoods": sum(1 for h in nb["hoods"] if h.get("page")),
        "questions": sum(1 for q in questions if q.get("topic") not in ("procedural", "other")) or len(questions),
        "first": props["meta"].get("first"), "last": props["meta"].get("last"),
    }
    os.makedirs(os.path.join(site, "data"), exist_ok=True)
    json.dump(summary, open(os.path.join(site, "data", "summary.json"), "w"))

    def xy(lat, lng):
        return (lng - (LNG0 - DLNG)) * KX, ((LAT0 + DLAT) - lat) * KY
    paths, n = [], 0
    for p in props["properties"]:
        for ring in p.get("rings") or []:
            if not any(abs(a - LAT0) < DLAT and abs(b - LNG0) < DLNG for a, b in ring):
                continue
            # skip very large tracts (marsh, master parcels): they read as blobs, not lots
            xs, ys = zip(*(xy(a, b) for a, b in ring))
            if (max(xs) - min(xs)) * (max(ys) - min(ys)) > W * H * 0.02:
                continue
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys)) + "Z"
            cls = ' class="soon"' if p["id"] in soon else ""
            paths.append(f'<path{cls} d="{d}"><title>{p["address"]}</title></path>')
            n += 1
    with open(os.path.join(site, "plat.svg"), "w") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" '
                f'role="img" aria-label="{n} lots around the Old Village that went before a Town board">'
                + "".join(paths) + "</svg>")
    print(f"landing: {summary}, {n} lots drawn, {len(soon & {p['id'] for p in props['properties']})} on upcoming agendas")


if __name__ == "__main__":
    main(sys.argv[1])
