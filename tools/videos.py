"""Meeting recordings from the Town of Mount Pleasant's YouTube channel.

    python3 tools/videos.py

Reads the channel's public feed (the 15 most recent uploads), matches each title
("October 13, 2026 - Mount Pleasant Special Town Council & Town Council Meetings")
to a date and the bodies it covers, and adds it to data/videos.json:

    {"2026-10-13": {"Town Council": "hpKfAKyaMO4"}, ...}

Entries are kept across runs, so coverage grows from the first run (feed reaches
back to July 2026). The channel carries Town Council, committee (incl. Planning
Committee) and Planning Commission meetings; Zoning Appeals, Historic District and
Design Review meetings are not on it. Run daily.
"""
import datetime
import html
import json
import os
import re
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "videos.json")
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCNhfTlBOB2AbKtELKzY7_yQ"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


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


def main():
    data = json.load(open(OUT)) if os.path.exists(OUT) else {}
    req = urllib.request.Request(FEED, headers={"User-Agent": "Mount Pleasant zoning map (+https://www.fabiobrocca.tech/boza/)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        feed = r.read().decode("utf-8", "replace")
    added = 0
    for e in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)", e).group(1)
        title = html.unescape(re.search(r"<title>([^<]+)", e).group(1))
        day = date_of(title)
        if not day:
            continue
        for b in bodies(title):
            if b not in data.setdefault(day, {}):  # keep the first match if a meeting was uploaded twice
                data[day][b] = vid
                added += 1
    with open(OUT, "w") as f:
        json.dump(dict(sorted(data.items())), f, indent=1)
    print(f"videos: {sum(len(v) for v in data.values())} meeting recordings on {len(data)} dates ({added} new)")


if __name__ == "__main__":
    main()
