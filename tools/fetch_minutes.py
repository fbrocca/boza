"""Download minutes from the Town of Mount Pleasant Agenda Center.

    python3 tools/fetch_minutes.py

Board of Zoning Appeals (category 8): PDFs are kept in minutes/ as
YYYY-MM-DD.pdf, with minutes/index.csv and minutes/README.md rewritten.

Planning Commission (1), Planning Committee (17), Town Council (4): only the
text is kept, as sources/<body>/YYYY-MM-DD-<agendaID>.txt, because their PDFs
total well over GitHub Pages' 1 GB limit. The map links to the Town's copy.

Files already present are never re-downloaded. The Town's server drops
connections often, so every request is retried.
"""
import csv
import datetime
import html
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

BASE = "https://sc-mountpleasant2.civicplus.com"
CAT = 8
FIRST_YEAR = 2017
TEXT_BODIES = {"pc": 1, "pcom": 17, "council": 4}
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UA = {"User-Agent": "boza-archive (+https://github.com/fbrocca/boza)"}


def get(url, data=None, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # connection resets are routine on this server
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} {url}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))


def year_rows(year, cat=CAT):
    body = urllib.parse.urlencode({"year": year, "catID": cat}).encode()
    page = get(f"{BASE}/AgendaCenter/UpdateCategoryList", data=body).decode("utf-8", "replace")
    for r in re.split(r'<tr id="row', page)[1:]:
        m = re.search(r'aria-label="Agenda for ([^"]+)"', r)
        if not m:
            continue
        title = re.search(r'href="/AgendaCenter/ViewFile/Agenda/[^"]+"[^>]*>\s*(.*?)\s*</a>', r, re.S)
        mins = re.search(r'href="(/AgendaCenter/ViewFile/Minutes/[^"]+)"', r)
        ag = re.search(r'href="(/AgendaCenter/ViewFile/Agenda/_[^"?]+)"', r)
        yield {
            "date": datetime.datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d"),
            "title": html.unescape(re.sub(r"\s+", " ", title.group(1))) if title else "",
            "minutes": BASE + mins.group(1) if mins else "",
            "agenda": BASE + ag.group(1) if ag else "",
            "id": mins.group(1).rsplit("-", 1)[1] if mins else "",
        }


def fetch_text_bodies():
    """Keep only pdftotext output for the large-PDF bodies."""
    for body, cat in TEXT_BODIES.items():
        out = os.path.join(ROOT, "sources", body)
        os.makedirs(out, exist_ok=True)
        have = set(os.listdir(out))
        new = 0
        for y in range(FIRST_YEAR, datetime.date.today().year + 1):
            for r in year_rows(y, cat):
                name = f"{r['date']}-{r['id']}.txt"
                if not r["minutes"] or name in have:
                    continue
                pdf = get(r["minutes"])
                if not pdf.startswith(b"%PDF"):
                    continue
                with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
                    t.write(pdf)
                    t.flush()
                    subprocess.run(["pdftotext", "-layout", t.name, os.path.join(out, name)], check=True)
                have.add(name)
                new += 1
        print(f"{body}: {len(have)} minutes, {new} new")


def main(out):
    os.makedirs(out, exist_ok=True)
    rows = []
    for y in range(FIRST_YEAR, datetime.date.today().year + 1):
        rows.extend(year_rows(y))
    rows.sort(key=lambda r: r["date"], reverse=True)
    new = 0
    for r in rows:
        if not r["minutes"]:
            continue
        path = os.path.join(out, r["date"] + ".pdf")
        if os.path.exists(path):
            continue
        pdf = get(r["minutes"])
        if not pdf.startswith(b"%PDF"):
            print(f"  skip {r['date']}: not a PDF", file=sys.stderr)
            continue
        open(path, "wb").write(pdf)
        new += 1
        print(f"  new: {r['date']}")

    with open(os.path.join(out, "index.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "title", "status", "local_minutes", "source_minutes", "source_agenda"])
        for r in rows:
            held = bool(r["minutes"])
            w.writerow([r["date"], r["title"], "held" if held else "canceled",
                        f"minutes/{r['date']}.pdf" if held else "", r["minutes"], r["agenda"]])

    held = [r for r in rows if r["minutes"]]
    lines = ["# Board of Zoning Appeals minutes", "",
             f"{len(held)} sets of minutes from the Town of Mount Pleasant, SC "
             f"[Agenda Center]({BASE}/AgendaCenter), {held[-1]['date'][:4]} to {held[0]['date'][:4]}. "
             f"Updated {datetime.date.today().isoformat()}.", "",
             "Files are named by meeting date. Machine-readable index: [`index.csv`](index.csv). "
             "Canceled meetings have no minutes.", ""]
    year = None
    for r in rows:
        if r["date"][:4] != year:
            year = r["date"][:4]
            lines += ["", f"## {year}", "", "| Meeting | Minutes | Source |", "|---|---|---|"]
        if r["minutes"]:
            lines.append(f"| {r['date']} | [PDF]({r['date']}.pdf) | [Town minutes]({r['minutes']}) / [agenda]({r['agenda']}) |")
        else:
            lines.append(f"| {r['date']} | Canceled | [agenda]({r['agenda']}) |")
    open(os.path.join(out, "README.md"), "w").write("\n".join(lines) + "\n")
    print(f"{len(rows)} meetings listed, {len(held)} with minutes, {new} new PDFs")


if __name__ == "__main__":
    main(os.path.join(ROOT, "minutes"))
    fetch_text_bodies()
