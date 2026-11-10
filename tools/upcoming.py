"""Read the agendas the Town has posted for meetings that haven't happened yet
and write data/upcoming.json for the "Coming up" panel and map pins.

    python3 tools/upcoming.py

Agendas go up about a week ahead. For each board we take meetings dated today
or later that have no minutes yet, read the agenda PDF (pdftotext -layout),
and keep the zoning items: case number, address / TMS, request. Items are put
on the map from our own properties (same case or TMS) or else the county
parcel layer. Committee and Council agendas keep only zoning-related items.
Nothing beyond the public agenda text is stored.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
import fetch_minutes as fm  # noqa: E402
import parcels  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "upcoming.json")

BODIES = [  # key, AgendaCenter category, label, section header inside a combined PDF
    ("boza", 8, "Board of Zoning Appeals", None),
    ("pc", 1, "Planning Commission", None),
    ("pcom", 17, "Planning Committee", r"^\s*PLANNING COMMITTEE\s*$"),
    ("council", 4, "Town Council", r"^\s*(SPECIAL\s+)?TOWN COUNCIL MEETING\s*$"),
    ("hdpc", 16, "Historic District Preservation Commission", None),
    ("drb", 11, "Design Review Board", None),
]
CASE = re.compile(r"\b(SP|[AVSR])\s?[-–]\s?(\d{1,3})\s?[-–]\s?(\d{2,4})\b")
TMS = re.compile(r"TMS\s*(?:No\.?|#)?\s*#?\s*(\d{3})-?(\d{2})-?(\d{2})-?(\d{3})")
MARK = re.compile(r"^\s{0,14}(\d{1,2}|[a-z])\.\s+(\S.*)$")
SECTION = re.compile(r"^\s{0,6}[A-Z]\.\s+(\S.*)$")
JUNK = re.compile(r"Title VI|accessib|Telephone|legaldept|languages other|Civil\s*Rights|related statutes|"
                  r"meetings are conducted|provided in|please contact|Page \d+ of \d+|www\.tompsc|"
                  r"^\s*(Planning Commission Agenda|[A-Z][a-z]+ \d{1,2}, \d{4})\s*$|hyperlink|may take a",
                  re.I)
STOP = re.compile(r"RESOURCE LINKS|^\s*NOTE:|CORRESPONDENCE RECEIVED AFTER", re.I)
BOILER = re.compile(r"^(call to order|roll call|approval of|public comment|general (public )?comment|"
                    r"general correspondence|correspondence$|adjourn|explanation of|administration of|"
                    r"planning commission recommendations update|review of planning commission recommendations|"
                    r"deferred from|discussion of items for next|consent motions?$|business$|executive session|"
                    r"post executive session)", re.I)
NOISE = re.compile(r"^(staff\s*report|public correspondence|correspondence|extension request|"
                   r"consent motion approved|approved|denied|deferred|withdrawn( by staff)?)$", re.I)
STATUS = re.compile(r"\b(WITHDRAWN(?: BY STAFF)?|REQUEST FOR DEFERRAL|DEFERRED)\b", re.I)
ZONING = re.compile(r"zoning|\bzone\b|rezon|planned development|\bPD\b|annex|sketch plan|land use|chapter 156|"
                    r"subdivision|density|\b[RV]-\d{1,3}-\d{2}", re.I)
TIME = re.compile(r"\b(\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?)", re.I)
DEADLINE = re.compile(r"(?:no later than|received after)\s+(?:the end of business,?\s*)?(?:[\d:]+\s*[AP]\.?M\.?,?\s*)?"
                      r"(?:on\s+)?((?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
                      re.I | re.S)
EMAIL = re.compile(r"\b(?!legaldept)[\w.]+@tompsc\.com\b", re.I)


def today_et():
    return datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def agenda_text(url):
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "a.pdf")
        with open(pdf, "wb") as f:
            f.write(fm.get(url))
        return subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout


def section(text, header):
    """Slice one committee's agenda out of the combined Committees of Council PDF."""
    if not header:
        return text
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.match(header, ln, re.I) and i + 8 < len(lines) and any("AGENDA" in x for x in lines[i:i + 8]):
            out = []
            for x in lines[i:]:
                if "Title VI" in x:
                    break
                out.append(x)
            return "\n".join(out)
    return None


def clean(s):
    return re.sub(r"\s+", " ", s.replace("ﬀ", "ff").replace("ﬁ", "fi").replace("ﬂ", "fl")).strip(" ,–-")


SUBMARK = re.compile(r"^\s*(?:([A-Z])\.|\((\d{1,2})\))\s+(\S.*)$")  # Council: "A. Final Reading", "(1) First Reading"


def blocks(text, nested=False):
    """Split the agenda into numbered / lettered items, remembering the lettered section each sits in.
    nested=True (Council and committee agendas): capital letters and (1) mark items, not sections."""
    out, cur, sect = [], None, ""
    for ln in text.splitlines():
        if STOP.search(ln):
            if cur:
                out.append(cur)
            cur = None
            continue
        if not ln.strip() or JUNK.search(ln):
            continue
        sm = SUBMARK.match(ln) if nested else None
        if sm:
            if cur:
                out.append(cur)
            cur = {"section": sect, "lines": [clean(sm.group(3))]}
            continue
        s = SECTION.match(ln)
        if s and not MARK.match(ln):
            if cur:
                out.append(cur)
            cur, sect = None, clean(s.group(1))
            continue
        m = MARK.match(ln)
        if m:
            if cur:
                out.append(cur)
            cur = {"section": sect, "lines": [clean(m.group(2))]}
        elif cur:
            cur["lines"].append(clean(ln))
    if cur:
        out.append(cur)
    return out


def parse_item(b, body):
    lines = [x for x in b["lines"] if x]
    text = " ".join(lines)
    if BOILER.match(lines[0]) or re.search(r"staff approval|minutes|public comment", b["section"], re.I):
        return None
    if body in ("pcom", "council") and not ZONING.search(text):
        return None
    status = None
    st = STATUS.search(text)
    if st:
        status = "deferral requested" if "DEFERRAL" in st.group(1).upper() else st.group(1).lower().split(" by")[0]
    lines = [STATUS.sub("", x).strip(" ,–-") for x in lines]
    lines = [x for x in lines if x and not NOISE.match(x)]
    if not lines:
        return None
    kind = None
    if re.fullmatch(r"[A-Z][A-Z &/-]{3,40}", lines[0]):  # e.g. "SKETCH PLAN", "PUBLIC HEARING"
        kind = lines.pop(0).title()
        if not lines:
            return None
    cm = CASE.search(text)
    case = f"{cm.group(1)}-{int(cm.group(2)):02d}-{cm.group(3)[-2:]}" if cm else None
    tm = TMS.search(text)
    tms = "-".join(tm.groups()) if tm else None
    first = re.sub(r"^(APPROVED|DENIED|DEFERRED|WITHDRAWN)\s+", "", lines[0], flags=re.I)
    title = re.sub(r"^(Case\s+)?" + (re.escape(cm.group(0)) if cm else "$^"), "", first).strip(" ,–-") or None
    address, rest = None, []
    for x in lines[1:] if title else lines:
        if tm and TMS.search(x) and address is None:
            a = clean(TMS.split(x)[0])
            a = re.sub(r"\s*(Survey Card.*|No Survey Card.*)$", "", a).strip(" ,–-")
            address = a or None
        elif case and x.strip() in (case, cm.group(0)):
            continue
        else:
            rest.append(x)
    if tm and TMS.search(lines[0]):  # "Belle Hall PD, Planned Development, TMS No. ..."
        title = clean(TMS.split(lines[0])[0]).strip(" ,–-")
    if not title and address:
        title, address = address, None
    request = clean(" ".join(rest))
    if not kind:
        kind = {"V": "Variance", "A": "Appeal", "S": "Special exception", "R": "Rezoning / PD", "SP": "Sketch plan"}.get(
            cm.group(1) if cm else "", {"hdpc": "Historic review", "drb": "Design review"}.get(body))
    if body in ("pcom", "council") and re.search(r"ordinance|reading", text, re.I):
        kind = "Ordinance"
    if not kind and not case and not tms:
        kind = "Discussion"
    if body in ("pcom", "council"):
        title, request = clean(text), ""
        title = STATUS.sub("", title).strip()
    return {"case": case, "tms": tms, "title": title, "address": address, "kind": kind,
            "request": request, "status": status}


def locate(items):
    props = json.load(open(os.path.join(ROOT, "data", "properties.json")))["properties"]
    by_tms, by_case, names = {}, {}, []
    for p in props:
        for t in [p.get("tms"), *(p.get("other_tms") or [])]:
            if t:
                by_tms[t] = p
        for c in p["cases"]:
            if c.get("case"):
                by_case.setdefault(c["case"], p)
        if any(c["board"] == "planning" for c in p["cases"]):
            n = re.sub(r"\s+(PD|Planned Development.*)$", "", p.get("name") or p["address"]).strip()
            if len(n) >= 8 and not re.match(r"^\d", n):
                names.append((n.lower(), p))
    need = []
    for it in items:
        p = by_case.get(it["case"]) or by_tms.get(it["tms"])
        if p and re.match(r"(staff approvals?|consent)", p["address"], re.I):
            p = None  # a property mislabelled with a section heading; don't send people to it
        if not p and not it["tms"]:
            hay = (it["title"] + " " + it["request"]).lower()
            p = next((q for n, q in names if n in hay), None)
        if p:
            it["property"] = p["id"]
            if p.get("lat"):
                it["lat"], it["lng"] = p["lat"], p["lng"]
        elif it["tms"]:
            need.append(it)
    if need:
        pids = sorted({it["tms"].replace("-", "") for it in need})
        try:
            feats = parcels.fetch(pids)
        except Exception as e:  # map service down: list the items without pins
            print("parcel lookup failed:", e, file=sys.stderr)
            feats = []
        pts = {}
        for f in feats:
            rings = f["geometry"].get("rings") or []
            if rings:
                ring = max(rings, key=parcels.ring_area)
                x, y = parcels.label_point(ring)
                pts[f["attributes"]["PID"]] = (round(y, 6), round(x, 6))
        for it in need:
            pt = pts.get(it["tms"].replace("-", ""))
            if pt:
                it["lat"], it["lng"] = pt


def main():
    today = today_et()
    years = sorted({int(today[:4]), int(today[:4]) + (1 if today[5:7] == "12" else 0)})
    meetings, cache = [], {}
    for key, cat, label, header in BODIES:
        rows = [r for y in years for r in fm.year_rows(y, cat)]
        for r in rows:
            if r["date"] < today or r["minutes"] or not r["agenda"]:
                continue
            if r["agenda"] not in cache:
                cache[r["agenda"]] = agenda_text(r["agenda"])
            full = cache[r["agenda"]]
            text = section(full, header)
            if text is None:
                continue
            items = [it for it in (parse_item(b, key) for b in blocks(text, nested=key in ("pcom", "council"))) if it]
            if not items:
                continue
            dl = DEADLINE.search(full)
            em = EMAIL.search(full)
            tm = TIME.search(text)
            meetings.append({
                "body": key, "label": label, "date": r["date"],
                "time": re.sub(r"\s+", "", tm.group(1)).lower().replace(".", "") if tm else None,
                "agenda": r["agenda"], "title": r["title"],
                "deadline": clean(dl.group(1)).title().replace("Th,", "th,") if dl else None,
                "email": em.group(0).lower() if em else None,
                "public_comment": bool(re.search(r"public comment", text, re.I)),
                "items": items,
            })
            print(f"{key} {r['date']}: {len(items)} items", file=sys.stderr)
    locate([it for m in meetings for it in m["items"]])
    meetings.sort(key=lambda m: (m["date"], m["time"] or ""))
    if os.path.exists(OUT) and json.load(open(OUT)).get("meetings") == meetings:
        print("no change", file=sys.stderr)
        return  # leave the file alone so the daily job doesn't commit noise
    data = {"updated": today, "meetings": meetings}
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
