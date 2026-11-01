"""Extract property-specific zoning actions from Planning Commission, Planning
Committee and Town Council minutes, and link them into one timeline per case.

    python3 tools/extract_planning.py <sources_dir> > data/planning.json

<sources_dir> holds one folder per body (pc, pcom, council) of minutes text
files named YYYY-MM-DD-<agendaID>.txt (from `pdftotext -layout`).

Output: a list of cases. Each case has its Planning Commission item (case
number, kind, request, parcel numbers, address, recommendation) and the
Planning Committee and Town Council events matched to it, plus a final status.

Matching, in order of confidence:
  committee -> case: case number (R-12-26), else TMS, else street address
  council   -> case: TMS, else street address, else street name + zoning
                     districts, always within 18 months after the hearing
Council readings of the same ordinance are tied by ordinance number.
"""
import collections
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_cases import clean_lines, decide, reflow  # noqa: E402
from event_check import belongs  # noqa: E402

BODIES = {"pc": "Planning Commission", "pcom": "Planning Committee", "council": "Town Council"}
BASE = "https://sc-mountpleasant2.civicplus.com/AgendaCenter/ViewFile/Minutes/"

CASE_ID = re.compile(r"\b(R|SP)\s?-\s?(\d{1,3})\s?-\s?(\d{2,4})\b")
TMS_FULL = re.compile(r"(\d{3})\s?-\s?(\d{2})\s?-\s?(\d{2})\s?-\s?(\d{3})")
ITEM = re.compile(r"^\s{0,12}(?:\(?[A-Za-z]\)|[A-Za-z]\.|\(\d{1,2}\)|\d{1,2}\.)\s+(?=\S)")
SUFFIX = (r"Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|Way|"
          r"Circle|Cir|Highway|Hwy|Place|Pl|Parkway|Pkwy|Trail|Row|Point|Bluff|Landing|Run|"
          r"Terrace|Retreat|Loop|Alley|Square|Crossing|Island")
ADDRESS = re.compile(
    r"(?<![\d,])(\d{1,5}[A-Z]?(?!,\d)(?:\s*(?:,|&|and)\s*\d{1,5}[A-Z]?)*)\s+((?:[NSEW]\.?\s+|North\s+|South\s+|"
    r"East\s+|West\s+|Old\s+)?(?:[A-Z][\w’'.]*\s+){0,4}?(?:" + SUFFIX + r")\b\.?"
    r"(?:\s+\d{1,3}(?:\s?[NS]\b|\s+North\b|\s+South\b)?)?(?:\s+(?:North|South|N|S)\b)?)")
ZONE = r"([A-Z]{1,3}\d?(?:-\d[A-Z]?)?)"
FROM_TO = re.compile(r"from\s+" + ZONE + r"\b.{0,80}?\bto\s+" + ZONE + r"\b", re.S)
TO_ONLY = re.compile(r"(?:annex and |to )?zone\s+(?:as\s+)?" + ZONE + r"\b")
STOPWORDS = {"road", "rd", "street", "st", "avenue", "ave", "drive", "dr", "lane", "ln",
             "boulevard", "blvd", "court", "ct", "way", "circle", "highway", "hwy", "north",
             "south", "the", "and", "of", "pd", "tract", "phase", "parcel", "old", "mount",
             "pleasant", "place", "point", "east", "west", "landing", "island"}


def norm_case(m):
    y = m.group(3)[-2:]
    return f"{m.group(1)}-{int(m.group(2)):02d}-{y}"


def all_tms(text):
    """Every TMS in text, including shorthand lists like '561-00-00-102, 112, & 141'."""
    out = []
    flat = re.sub(r"\s+", " ", text)
    for m in TMS_FULL.finditer(flat):
        base = "-".join(m.groups())
        out.append(base)
        tail = re.match(r"((?:\s*(?:,|&|and)\s*(?:&\s*)?\d{3}\b(?!-))+)", flat[m.end():])
        if tail:
            out += [base[:-3] + n for n in re.findall(r"\d{3}", tail.group(1))]
    return list(dict.fromkeys(out))


def norm_street(s):
    s = s.lower().replace("’", "'")
    s = re.sub(r"\b(rd)\b\.?", "road", s)
    s = re.sub(r"\b(st)\b\.?", "street", s)
    s = re.sub(r"\b(ave)\b\.?", "avenue", s)
    s = re.sub(r"\b(dr)\b\.?", "drive", s)
    s = re.sub(r"\b(ln)\b\.?", "lane", s)
    s = re.sub(r"\b(blvd)\b\.?", "boulevard", s)
    s = re.sub(r"\b(hwy)\b\.?", "highway", s)
    s = re.sub(r"\b(ct)\b\.?", "court", s)
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


def address_keys(text):
    """{'913 bowman', ...}: house number + first street word, for matching."""
    keys = set()
    for m in ADDRESS.finditer(CASE_ID.sub(" ", re.sub(r"\s+", " ", text))):
        words = [w for w in norm_street(m.group(2)) if w not in ("n", "s", "e", "w", "north", "south", "old")]
        if not words:
            continue
        for num in re.findall(r"\d{1,5}", m.group(1)):
            keys.add(f"{num} {words[0]}")
    return keys


def street_words(text):
    return {w for w in norm_street(text) if len(w) > 2 and w not in STOPWORDS and not w.isdigit()}


GENERIC = set("""request amend amendment amending planned development district ordinance zone zoning rezone
parcel parcels acre acres located approximately tract land charleston county plat book page recorded office
identified residential business areawide commercial community conservation public institutional office
professional density medium low high town council planning commission committee mount pleasant road street
drive lane boulevard highway avenue court way north south east west the and for with from into within portion
corner known between subject further indicated proposal proposed property properties general district's
annex annexation providing pertaining specifically allowances unincorporated designation future land use
comprehensive plan settlement rod plats pd tms nos minutes first second final reading""".split())


def names(text):
    """Distinctive capitalised words (place and project names) for name-based matching."""
    words = re.findall(r"\b[A-Z][a-zA-Z’']{2,}\b", text)
    return {w.lower().replace("’", "'") for w in words} - GENERIC


MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def cited_pc_dates(text):
    out = set()
    for m in re.finditer(r"(" + MONTHS + r")\s+(\d{1,2}),\s+(\d{4})\s+Planning\s+Commission", text):
        try:
            out.add(datetime.datetime.strptime(" ".join(m.groups()), "%B %d %Y").date().isoformat())
        except ValueError:
            pass
    return out


def zones(text):
    flat = re.sub(r"\s+", " ", text)
    m = FROM_TO.search(flat)
    if m:
        return m.group(1), m.group(2)
    m = TO_ONLY.search(flat)
    return (None, m.group(1)) if m else (None, None)


CODE_TEXT = re.compile(r"Section\s+156|Chapter\s+156|Zoning\s+Code|Code\s+of\s+Ordinances|Comprehensive\s+Plan\b(?!.{0,80}located)", re.I)


def is_code_text(text):
    """Town-wide text amendments (zoning code, comprehensive plan text), not tied to a property."""
    flat = re.sub(r"\s+", " ", text)
    if not CODE_TEXT.search(flat[:400]):
        return False
    return not re.search(r"located (?:at|on|near|off|along|between)|\bPD\b|Planned Development|TMS", flat[:400])


def kind_of(text):
    t = text.lower()
    if "sketch plan" in t:
        return "Sketch plan"
    if "preliminary plat" in t or "final plat" in t:
        return "Subdivision plat"
    if "street name" in t:
        return "Street names"
    if "annex" in t:
        return "Annexation and zoning"
    if re.search(r"\bpd\b|planned development|development agreement|\bda\b", t) and "amend" in t:
        return "PD / development agreement amendment"
    if re.search(r"\b(re)?zon", t):
        return "Rezoning"
    if "vesting" in t or "extension" in t:
        return "Extension"
    return "Other"


def meetings(src, body):
    d = os.path.join(src, body)
    if not os.path.isdir(d):
        return
    for name in sorted(os.listdir(d)):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(\d+)\.txt$", name)
        if m:
            y, mo, da, aid = m.groups()
            yield (f"{y}-{mo}-{da}", f"{BASE}_{mo}{da}{y}-{aid}",
                   open(os.path.join(d, name), encoding="utf-8", errors="replace").read())


def segments(text):
    """Split minutes into numbered/lettered items: (header, body, page)."""
    lines = clean_lines(text)
    heads = [i for i, (l, _) in enumerate(lines)
             if ITEM.match(l) and not re.match(r"^\s*\S+\s+(Mr|Ms|Mrs|Dr)\.", l)]
    out = []
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        hdr = []
        j = i
        while j < end and lines[j][0].strip() and len(hdr) < 10:
            s = lines[j][0].strip()
            if j > i and re.match(r"^(Mr|Ms|Mrs|Dr|Council Member|Mayor)\b", s):
                break
            hdr.append(s)
            j += 1
        header = ITEM.sub("", " ".join(hdr), count=1).strip()
        body = "\n".join(l for l, _ in lines[j:end])
        out.append((header, body, lines[i][1]))
    return out


def label_from(header, cid):
    flat = CASE_ID.sub(" ", re.sub(r"\s+", " ", header))
    m = re.search(r"located (?:at|on)\s+(.+?)(?:[.;(]|,|\s+TMS|\s+(?:and|to|an|consisting|containing|comprised)\b|$)", flat)
    if m and len(m.group(1)) < 70:
        return m.group(1).strip(" ,")
    a = ADDRESS.search(flat)
    if a:
        return (a.group(1) + " " + a.group(2)).strip(" ,.")
    if cid:
        after = re.split(CASE_ID, re.sub(r"\s+", " ", header), maxsplit=1)[-1]
        after = re.sub(r"^\W*PUBLIC HEARING\W*", "", after)
        chunk = re.split(r"[.,:—–-]\s|,", after.strip(" .,:—–-"), maxsplit=1)[0].strip()
        if (2 < len(chunk) < 50 and not chunk.isupper()
                and not re.match(r"(?i)request|review|amend|rezone|annex|public hearing", chunk)):
            return chunk
    return ""


def pc_cases(src):
    cases = []
    for date, url, text in meetings(src, "pc"):
        seen = {}
        for header, body, page in segments(text):
            m = CASE_ID.search(header[:60])
            tms = all_tms(header) or all_tms(body[:500])
            if not tms and not m:
                continue
            kind = kind_of(header)
            if is_code_text(header) or kind in ("Street names",) or (kind == "Other" and not m):
                continue
            cid = norm_case(m) if m else None
            decision = decide(body, False)
            if decision == "Unknown" and re.search(r"no recommendation", body, re.I):
                decision = "No recommendation"
            # The same item can appear in the agenda summary, in the discussion and in
            # an attached staff report. Keep the version with a motion, else the longest.
            key = cid or tuple(tms)
            score = (bool(re.search(r"\bmoved\b", body)), len(body))
            if key in seen:
                prev_score, prev = seen[key]
                if score <= prev_score:
                    continue
                cases.remove(prev)
            z_from, z_to = zones(header)
            req = re.sub(r"\s+", " ", header)
            req = re.sub(r"^(?:PUBLIC HEARING,?\s*)?(?:(?:Re)?[Zz]oning Case\s*)?", "", req)
            req = re.sub(r"\s*Staff Report\s*$", "", req)
            c = {
                "case": cid, "kind": kind, "tms": tms, "label": label_from(header, cid),
                "request": req, "zone_from": z_from, "zone_to": z_to,
                "addr_keys": sorted(address_keys(header)), "words": sorted(street_words(label_from(header, cid) or header[:120])),
                "names": sorted(names(header)),
                "events": [{"body": "Planning Commission", "date": date, "decision": decision,
                            "page": page, "town": url, "text": reflow(body)}],
            }
            seen[key] = (score, c)
            cases.append(c)
    # Same case number heard at several meetings (deferrals): merge.
    merged, by_id = [], {}
    for c in cases:
        if c["case"] and c["case"] in by_id:
            by_id[c["case"]]["events"] += c["events"]
            continue
        if c["case"]:
            by_id[c["case"]] = c
        merged.append(c)
    return merged


def committee_items(src):
    items = []
    for date, url, text in meetings(src, "pcom"):
        for header, body, page in segments(text):
            m = CASE_ID.search(header[:80])
            tms = all_tms(header)
            if not m and not tms:
                continue
            items.append({"date": date, "town": url, "page": page,
                          "case": norm_case(m) if m else None, "tms": tms,
                          "addr_keys": address_keys(header), "header": re.sub(r"\s+", " ", header),
                          "names": names(header), "cited": cited_pc_dates(body[:3000]),
                          "decision": recommendation(body), "text": reflow(body)})
    return items


REC = re.compile(r"moved\s+(?:to|for)\s+(?:a\s+)?recommend\w*\s+(?:of\s+)?(?:to\s+(?:the\s+)?(?:Town\s+)?Council\s+)?"
                 r"(?:the\s+)?(approv\w*|den\w*|defer\w*)", re.I)


def recommendation(body):
    flat = re.sub(r"\s+", " ", body)
    recs = list(REC.finditer(flat))
    for k in range(len(recs) - 1, -1, -1):
        m = recs[k]
        stop = recs[k + 1].start() if k + 1 < len(recs) else len(flat)
        if re.search(r"motion (?:failed|died)|failed on a", flat[m.end():stop][:1500], re.I):
            continue
        v = m.group(1).lower()
        return ("Recommended approval" if v.startswith("approv") else
                "Recommended denial" if v.startswith("den") else "Deferred")
    d = decide(body, False)
    flat = re.sub(r"\s+", " ", body)
    if re.search(r"recommend\w*\s+(?:to\s+(?:Town\s+)?Council\s+)?(?:the\s+)?denial", flat, re.I) and d == "Denied":
        return "Recommended denial"
    if d in ("Approved", "Approved with conditions"):
        return "Recommended approval"
    if d == "Denied":
        return "Recommended denial"
    return d


READING = re.compile(r"(First|Second|Third|Final)\s+Reading\s*[:\-–]?\s*(?:of\s+)?An\s+Ordinance\s+(.+?)"
                     r"(?=(?:First|Second|Third|Final)\s+Reading\s*[:\-–]?\s*(?:of\s+)?An\s+Ordinance|$)",
                     re.S | re.I)
ORD_NO = re.compile(r"Ord(?:inance)?\.?\s*No\.?\s*(\d{4,6})")


def council_outcome(chunk):
    """Outcome of one council item from its own text, or None."""
    flat = re.sub(r"\s+", " ", chunk)
    if re.search(r"\[?\s*Item was withdrawn|withdrawn by (?:the )?applicant", flat, re.I):
        return "Withdrawn"
    motions = list(re.finditer(
        r"(?:Motion to (approve|deny|defer|table)|moved (?:for|to) (approv\w*|den\w*|defer\w*))"
        r".{0,400}?\b(carried|carries|passed|passes|failed|fails|voted in favor|unanimously)\b", flat, re.I))
    if motions:
        m = motions[-1]
        verb = (m.group(1) or m.group(2)).lower()
        ok = m.group(3).lower() not in ("failed", "fails")
        if verb.startswith(("defer", "table")):
            return "Deferred" if ok else None
        if verb.startswith("approv"):
            return "Approved" if ok else "Denied"
        return "Denied" if ok else "Approved"
    b = re.search(r"\[\s*(Approved|Deferred|Denied)", flat, re.I)
    if b:
        return b.group(1).title()
    if re.search(r"voted in favor (?:of denial|to deny)", flat, re.I):
        return "Denied"
    if re.search(r"SIGNED,?\s+SEALED,?\s+and\s+DELIVERED", flat, re.I):
        return "Approved"
    if re.search(r"\bmotion (?:carried|carries|passed)\b|All present voted in favor", flat, re.I):
        return "Approved"
    return None


def council_items(src):
    items = []
    for date, url, text in meetings(src, "council"):
        lines = clean_lines(text)
        flat = "\n".join(l for l, _ in lines)
        page_at = []
        pos = 0
        for l, p in lines:
            page_at.append((pos, p))
            pos += len(l) + 1
        pending = []
        for m in READING.finditer(flat):
            chunk = m.group(2)
            title = re.split(r"\n\s*\n|Motion|moved", chunk, maxsplit=1)[0]
            if not re.search(r"\b(re)?zon|annex|planned development|\bPD\b", title, re.I) or is_code_text(title):
                continue
            # The item's own number closes its title; earlier ones cite the ordinance being amended.
            ords = ORD_NO.findall(title) or ORD_NO.findall(chunk[:900])
            ordm = re.match(r"(\d+)", ords[-1]) if ords else None
            page = max([p for off, p in page_at if off <= m.start()] or [1])
            it = {"date": date, "town": url, "page": page, "reading": m.group(1).title(),
                  "ord": ordm.group(1) if ordm else None, "title": re.sub(r"\s+", " ", title).strip(),
                  "tms": all_tms(title), "addr_keys": address_keys(title),
                  "words": street_words(" ".join(re.findall(r"located (?:at|on|along)\s+([^.(]+)", title)) or title),
                  "zones": zones(title), "names": names(title), "cited": cited_pc_dates(chunk[:5000]),
                  "text": reflow(chunk[:4000])}
            # Cut the chunk at the next agenda item so unrelated motions don't leak in.
            body_start = len(title)
            nxt = re.search(r"\n\s*(?:\(\d{1,2}\)|\d{1,2}\.|[A-Z]\.|[IVX]{1,4}\.)\s+[A-Z]", chunk[body_start:])
            own = chunk[:body_start + nxt.start()] if nxt else chunk
            it["text"] = reflow(own[:4000])
            outcome = council_outcome(own)
            if outcome:
                it["outcome"] = outcome
                for p_ in pending:
                    p_.setdefault("outcome", outcome)
                pending = []
            else:
                pending.append(it)
            items.append(it)
        # Grouped motions: "Motion to approve first reading of Ordinances 26034 and 26035 ..."
        for gm in re.finditer(r"Motion to (approve|deny)[^.]{0,80}?Ordinances?\s+([\d ,and]+)[^.]*?\.(.{0,300})",
                              re.sub(r"\s+", " ", flat), re.I):
            res = "Approved" if gm.group(1).lower() == "approve" else "Denied"
            if re.search(r"failed", gm.group(3), re.I):
                res = "Denied" if res == "Approved" else "Approved"
            for n in re.findall(r"\d{4,6}", gm.group(2)):
                for it in items:
                    if it["date"] == date and it["ord"] == n:
                        it["outcome"] = res
    return items


def days(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def match_score(case, it):
    """Higher is better; 0 = no match."""
    if case["case"] and it.get("case") == case["case"]:
        return 100
    if set(case["tms"]) & set(it["tms"]):
        return 80
    if set(case["addr_keys"]) & set(it["addr_keys"]):
        return 70
    words = set(case["words"]) & set(it.get("words") or street_words(it.get("header", "")))
    if words and it.get("zones") and case["zone_to"] and it["zones"][1] == case["zone_to"]:
        if not case["zone_from"] or not it["zones"][0] or it["zones"][0] == case["zone_from"]:
            return 50
    # Name match: shared place/project names, stronger when the item cites this case's PC meeting.
    shared = set(case.get("names", [])) & set(it.get("names", []))
    cites = case["events"][0]["date"] in it.get("cited", set())
    if len(shared) >= 2 or (shared and cites):
        return 30 + min(len(shared), 9) + (15 if cites else 0)
    return 0


COUNCIL_KINDS = ("Rezoning", "Annexation and zoning", "PD / development agreement amendment", "Other")


def link(cases, comm, council):
    def best(it, horizon):
        cands = []
        for c in cases:
            if c["kind"] not in COUNCIL_KINDS:
                continue
            first = c["events"][0]["date"]
            d = days(first, it["date"])
            if 0 <= d <= horizon:
                s = match_score(c, it)
                if s:
                    cands.append((s, -d, id(c), c))
        return max(cands)[3] if cands else None

    for it in comm:
        if it["decision"] == "Unknown" and not re.search(r"moved|motion", it["text"], re.I):
            continue  # agenda listing or exhibit fragment, not the discussion
        c = best(it, 365)
        if c:
            c["events"].append({"body": "Planning Committee", "date": it["date"], "decision": it["decision"],
                                "page": it["page"], "town": it["town"], "text": it["text"]})
    # Council: match each ordinance once (its earliest reading), then attach all readings.
    by_ord = collections.defaultdict(list)
    loose = []
    for it in council:
        (by_ord[it["ord"]] if it["ord"] else loose).append(it)
    groups = list(by_ord.values()) + [[x] for x in loose]
    for g in groups:
        g.sort(key=lambda x: x["date"])
        c = None
        for it in g:
            c = best(it, 550)
            if c:
                break
        if not c:
            continue
        # Fuzzy matches can attach another ordinance: require the Council text to name this case
        # (case no., TMS, house number, project/PD name, or same street and acreage).
        if not any(belongs(c["case"], c["tms"], c["request"], c["label"], it["title"] + " " + it["text"]) for it in g):
            continue
        for it in g:
            c["events"].append({"body": "Town Council", "date": it["date"],
                                "decision": f"{it['reading']} reading: {it.get('outcome', 'see minutes').lower()}",
                                "outcome": it.get("outcome"), "reading": it["reading"],
                                "ord": it["ord"], "page": it["page"], "town": it["town"], "text": it["text"]})


ORDER = {"Planning Commission": 0, "Planning Committee": 1, "Town Council": 2}


def final_status(c):
    council = [e for e in c["events"] if e["body"] == "Town Council"]
    if any(e.get("outcome") == "Denied" for e in council):
        return "Denied by Council"
    if any(e.get("outcome") == "Approved" and e["reading"] in ("Second", "Third", "Final") for e in council):
        return "Adopted by Council"
    if any(e.get("outcome") == "Approved" for e in council):
        return "Passed first reading"
    if council and council[-1].get("outcome") == "Withdrawn":
        return "Withdrawn"
    pc = [e for e in c["events"] if e["body"] == "Planning Commission"]
    last = pc[-1]["decision"] if pc else "Unknown"
    if c["kind"] in ("Sketch plan", "Subdivision plat", "Extension"):
        return last  # decided by the Commission itself
    if last in ("Withdrawn", "Deferred", "No recommendation"):
        return last
    return {"Approved": "Recommended approval", "Approved with conditions": "Recommended approval",
            "Denied": "Recommended denial"}.get(last, last)


def main(src):
    cases = pc_cases(src)
    link(cases, committee_items(src), council_items(src))
    for c in cases:
        c["events"].sort(key=lambda e: (e["date"], ORDER[e["body"]]))
        c["status"] = final_status(c)
        for k in ("addr_keys", "words", "names"):
            c.pop(k, None)
    json.dump(cases, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1])
