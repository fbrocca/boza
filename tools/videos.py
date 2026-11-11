"""Meeting recordings and the moment each case is discussed.

    python3 tools/videos.py

1. Recordings. The Town of Mount Pleasant's YouTube channel feed (15 most recent
   uploads) and Open Publica's meeting list (openpublica.com, free API, no key;
   independent machine transcripts of the Town's videos, back to Aug 2025) are
   matched by date and body to Town Council, Planning Committee and Planning
   Commission meetings, and kept in data/videos.json:
       {"2026-10-13": {"Town Council": "hpKfAKyaMO4"}, ...}
   Zoning Appeals, Historic District and Design Review meetings are not recorded
   on the channel.

2. Moments. For meetings Open Publica has transcribed (timestamped segments),
   each case heard that day is located by its house number + street, or its case
   number, and the start of the densest five minutes of mentions is stored in
   data/video-moments.json:
       {"<event id>": ["hpKfAKyaMO4", 3121], "_done": ["hpKfAKyaMO4", ...]}
   Transcripts are read, not stored. Each meeting is processed once.
Run daily.
"""
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "videos.json")
MOMENTS = os.path.join(ROOT, "data", "video-moments.json")
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCNhfTlBOB2AbKtELKzY7_yQ"
OPENPUBLICA = "https://api.openpublica.com/v1/meetings"
GOV = "mount_pleasant-south_carolina"
UA = {"User-Agent": "Mount Pleasant zoning map (+https://www.fabiobrocca.tech/boza/)"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
WINDOW = 300  # seconds: the densest five minutes of mentions is where the case is heard
LEAD_IN = 20  # start a little before the first mention in that window


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))


def bodies(title):
    t = title.lower()
    out = []
    if "town council" in t:
        out.append("Town Council")
    if "committee" in t:
        out.append("Planning Committee")
    if "planning commission" in t:
        out.append("Planning Commission")
    return out


def date_of(title):
    m = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", title, re.I)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


def youtube_feed():
    feed = get(FEED)
    for e in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)", e).group(1)
        title = html.unescape(re.search(r"<title>([^<]+)", e).group(1))
        if date_of(title):
            yield date_of(title), bodies(title), vid, None


def openpublica():
    q = urllib.parse.urlencode({"government_id": GOV, "limit": 100})
    for m in json.loads(get(f"{OPENPUBLICA}?{q}"))["data"]:
        vid = re.search(r"[?&]v=([\w-]{11})", m.get("source_url") or "")
        if vid and m.get("date"):
            yield m["date"], bodies(m.get("title") or ""), vid.group(1), m.get("transcript_url")


COMMON = {"highway", "north", "south", "road", "street", "drive", "avenue", "lane", "court", "boulevard", "point",
          "long", "rifle", "range", "park", "place", "creek", "island", "pleasant", "mount", "town", "coleman", "johnnie"}


def mention_patterns(p, c):
    """(strong, weak): strong = house number + street, case number, project name; weak = a distinctive
    street name alone, used only when nothing strong is found."""
    strong, weak = [], []
    m = re.match(r"^((?:\d{2,5}\s*(?:&|and|,)?\s*)+)([A-Za-z]{3,})", p["address"])
    if m:  # "1437 & 1439 Venning Road": each number, then the street within three words
        street = m.group(2).lower()
        for n in re.findall(r"\d{2,5}", m.group(1)):
            strong.append(re.compile(rf"\b{n}\b\W+(?:\w+\W+){{0,3}}{re.escape(street[:4])}", re.I))
        if len(street) >= 5 and street not in COMMON:
            weak.append(re.compile(rf"\b{re.escape(street)}", re.I))
    if c.get("case"):  # "R-30-26" is often read out as "R 30 26"
        a, b, y = c["case"].split("-")
        strong.append(re.compile(rf"\b{a}\W{{0,2}}{int(b)}\W{{0,2}}{y}\b", re.I))
    names = [p.get("name") or ("" if m else p["address"])]
    names += re.findall(r"\b((?:[A-Z][a-z]+\s){1,3})PD\b", c.get("request") or "")
    for nm in names:
        nm = re.sub(r"\s+(PD|Road|Drive|Street|Lane|Avenue)$", "", (nm or "").strip())
        if len(nm) >= 6 and not re.match(r"^\d", nm) and nm.lower() not in COMMON:
            strong.append(re.compile(re.escape(nm.lower()), re.I))
    return strong, weak


def moment(segments, pats):
    strong, weak = pats
    for group in (strong, weak):
        hits = [s["start"] for s in segments if any(pt.search(s["text"]) for pt in group)]
        if hits:  # densest five minutes of mentions; on a tie the later one (the hearing follows any summary)
            best = max(hits, key=lambda t: (sum(1 for h in hits if t <= h <= t + WINDOW), t))
            return max(0, int(best) - LEAD_IN)
    return None


def main():
    data = json.load(open(OUT)) if os.path.exists(OUT) else {}
    moments = json.load(open(MOMENTS)) if os.path.exists(MOMENTS) else {"_done": []}
    transcripts = {}
    sources = []
    for name, fn in (("YouTube feed", youtube_feed), ("Open Publica", openpublica)):
        try:
            sources += list(fn())
        except Exception as e:  # one source down: keep going with the other and the stored data
            print(f"{name} unavailable: {e}", file=sys.stderr)
    added = 0
    for day, bs, vid, turl in sources:
        for b in bs:
            if b not in data.setdefault(day, {}):  # first match wins if a meeting was uploaded twice
                data[day][b] = vid
                added += 1
        if turl:
            transcripts[vid] = turl
    with open(OUT, "w") as f:
        json.dump(dict(sorted(data.items())), f, indent=1)

    # Moments: cases heard at a transcribed meeting.
    props = json.load(open(os.path.join(ROOT, "data", "properties.json")))["properties"]
    by_vid = {}
    for day, bodies_ in data.items():
        for b, vid in bodies_.items():
            by_vid.setdefault(vid, []).append((day, b))
    found = 0
    for vid, turl in transcripts.items():
        if vid in moments["_done"]:
            continue
        try:
            segs = json.loads(get(turl)).get("segments", [])
        except Exception as e:
            print(f"transcript {vid} unavailable: {e}", file=sys.stderr)
            continue
        heard = 0
        for p in props:
            for c in p["cases"]:
                pats = None
                for e in c["events"]:
                    if (e["date"], e["body"]) in by_vid.get(vid, []):
                        heard += 1
                        pats = pats or mention_patterns(p, c)
                        t = moment(segs, pats)
                        if t is not None:
                            moments[e["id"]] = [vid, t]
                            found += 1
        # Minutes lag the video by weeks: revisit a meeting until its cases are in the data (or 90 days).
        meeting_day = min((d for d, _ in by_vid.get(vid, [])), default="")
        if heard or meeting_day < (datetime.date.today() - datetime.timedelta(days=90)).isoformat():
            moments["_done"].append(vid)
    with open(MOMENTS, "w") as f:
        json.dump(moments, f, indent=1)
    n = sum(len(v) for v in data.values())
    print(f"videos: {n} recordings on {len(data)} dates ({added} new); moments: {found} new, "
          f"{len(moments) - 1} total from {len(moments['_done'])} transcribed meetings")


if __name__ == "__main__":
    main()
