"""Subscribable feeds for upcoming zoning meetings, from data/upcoming.json.

    python3 tools/feeds.py <site_dir>

Writes <site_dir>/feeds/meetings.ics (calendar: add once, every posted zoning
meeting appears) and <site_dir>/feeds/agenda.xml (RSS: one entry per agenda item).
Run at deploy time after tools/upcoming.py; events keep stable UIDs so calendar
apps update rather than duplicate them.
"""
import datetime
import html
import json
import os
import re
import sys
from email.utils import format_datetime
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE = "https://www.fabiobrocca.tech/boza/"
LOCATION = "Town Hall, 100 Ann Edwards Lane, Mount Pleasant, SC 29464"
TZ = ZoneInfo("America/New_York")


def start_of(m):
    t = re.match(r"(\d{1,2}):(\d{2})\s*([ap])", (m.get("time") or "").lower())
    if not t:
        return None
    h = int(t.group(1)) % 12 + (12 if t.group(3) == "p" else 0)
    return datetime.datetime.fromisoformat(m["date"]).replace(hour=h, minute=int(t.group(2)), tzinfo=TZ)


def ics_text(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def fold(line):  # RFC 5545: lines over 75 octets are folded
    out, b = [], line.encode()
    while len(b) > 75:
        cut = 75
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode())
        b = b" " + b[cut:]
    out.append(b.decode())
    return "\r\n".join(out)


def main(site):
    up = json.load(open(os.path.join(ROOT, "data", "upcoming.json")))
    os.makedirs(os.path.join(site, "feeds"), exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mount Pleasant Zoning Map//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Mount Pleasant zoning meetings", "X-WR-TIMEZONE:America/New_York",
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
             # US Eastern time rules, so clients that need a VTIMEZONE (Outlook) read the times correctly
             "BEGIN:VTIMEZONE", "TZID:America/New_York",
             "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0500", "TZOFFSETTO:-0400", "TZNAME:EDT", "DTSTART:20070311T020000",
             "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
             "BEGIN:STANDARD", "TZOFFSETFROM:-0400", "TZOFFSETTO:-0500", "TZNAME:EST", "DTSTART:20071104T020000",
             "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD", "END:VTIMEZONE"]
    rss = []
    for m in up.get("meetings", []):
        items = "\n".join(f"- {it['title']}" + (f": {it['request']}" if it.get("request") else "") for it in m["items"])
        how = f"\nWritten comments by {m['deadline']}" + (f" to {m['email']}" if m.get("email") else "") + "." if m.get("deadline") else ""
        desc = f"{items}\n{how}\nAgenda: {m['agenda']}\nMap: {SITE}"
        s = start_of(m)
        when = (f"DTSTART;TZID=America/New_York:{s.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=America/New_York:{(s + datetime.timedelta(hours=2)).strftime('%Y%m%dT%H%M%S')}") if s else \
               (f"DTSTART;VALUE=DATE:{m['date'].replace('-', '')}",
                f"DTEND;VALUE=DATE:{(datetime.date.fromisoformat(m['date']) + datetime.timedelta(days=1)).strftime('%Y%m%d')}")
        lines += ["BEGIN:VEVENT", f"UID:{m['body']}-{m['date']}@mp-zoning-map", f"DTSTAMP:{stamp}", *when,
                  f"SUMMARY:{ics_text(m['label'] + ' (' + str(len(m['items'])) + ' zoning item' + ('s' if len(m['items']) != 1 else '') + ')')}",
                  f"LOCATION:{ics_text(LOCATION)}", f"DESCRIPTION:{ics_text(desc)}", f"URL:{m['agenda']}", "END:VEVENT"]
        for i, it in enumerate(m["items"]):
            rss.append((s or datetime.datetime.fromisoformat(m["date"]).replace(tzinfo=TZ), m, it, i))
    lines.append("END:VCALENDAR")
    with open(os.path.join(site, "feeds", "meetings.ics"), "w", newline="") as f:
        f.write("\r\n".join(fold(l) for l in lines) + "\r\n")

    E = html.escape
    entries = "".join(
        f"<item><title>{E(m['label'] + ', ' + datetime.date.fromisoformat(m['date']).strftime('%b %-d') + ': ' + it['title'][:120])}</title>"
        f"<link>{E(m['agenda'])}</link><guid isPermaLink=\"false\">{E(m['body'] + '-' + m['date'] + '-' + str(i))}</guid>"
        f"<pubDate>{format_datetime(now)}</pubDate>"
        f"<description>{E((it.get('kind') or '') + ('. ' + it['request'] if it.get('request') else '') + (' Written comments by ' + m['deadline'] + '.' if m.get('deadline') else ''))}</description></item>"
        for _, m, it, i in rss)
    with open(os.path.join(site, "feeds", "agenda.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
                "<title>Mount Pleasant zoning: on upcoming agendas</title>"
                f"<link>{SITE}</link><description>Zoning items on agendas the Town has posted for upcoming meetings.</description>"
                f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>{entries}</channel></rss>\n")
    print(f"feeds: {len(up.get('meetings', []))} meetings, {len(rss)} agenda items")


if __name__ == "__main__":
    main(sys.argv[1])
