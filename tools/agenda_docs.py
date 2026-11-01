"""Find the case documents (applications, staff reports, correspondence) that
each agenda links to, and assign them to cases.

    python3 tools/agenda_docs.py

For every Board of Zoning Appeals and Planning Commission meeting we have
minutes for, downloads the agenda PDF, reads its hyperlinks with their
position and anchor text (`pdftohtml -xml`), and writes data/agenda-docs.json:

    {"boza/2026-09-28": [{"case": "V-18-26", "type": "Application",
                          "url": "https://www.tompsc.com/DocumentCenter/View/55557/...",
                          "label": "V-18-26 960 McCants Drive Combined Application"}, ...]}

A link is assigned to a case by, in order: the case number in the document's
file name, the case number in the link text, else the nearest case number
above it on the page. Links above the first case (one staff report for the
whole meeting) get case=null and apply to every case that night.

Only links are kept. Documents are not downloaded or stored, and nothing is
extracted from them. Meetings already in the file are skipped.
"""
import csv
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = "https://sc-mountpleasant2.civicplus.com/AgendaCenter/ViewFile/Agenda/"
OUT = os.path.join(ROOT, "data", "agenda-docs.json")
CASE = re.compile(r"\b([AVSR]|SP)\s?[-–]\s?(\d{1,3})\s?[-–]\s?(\d{2,4})\b")
SKIP = re.compile(r"bylaws|case-law|explanation-of|future-land-use|document-library|projects-applications-map|"
                  r"recusal|amlegal|arcgis|adobe\.com|agendacenter|mailto:|/index\.aspx|tompsc\.com/?$|"
                  r"tompsc\.com/\d+/|title-vi|youtube|granicus|swagit", re.I)


def norm(m):
    return f"{m.group(1)}-{int(m.group(2)):02d}-{m.group(3)[-2:]}"


def doc_type(text):
    t = text.lower()
    if re.search(r"staff[\s_-]*(?:report|comment)|\bsr\b", t):
        return "Staff report"
    if re.search(r"correspond|letter|comment|petition|opposition|support", t):
        return "Correspondence"
    if re.search(r"present|ppt|slides", t):
        return "Presentation"
    if re.search(r"applic|submittal|\bsub\b|combined|narrative|plat|plan|survey|exhibit|site|request|packet|"
                 r"binder|\b\d{10,13}\b", t):  # BOZA packets are named address + TMS + date
        return "Application"
    return "Document"


def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "boza-archive (+https://github.com/fbrocca/boza)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                print(f"  gave up {url}: {e}", file=sys.stderr)
                return b""
            time.sleep(3 * (i + 1))


def links_in(pdf_bytes):
    """[(page, top, left, href, anchor_text)] plus all text runs, in reading order."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.pdf")
        open(p, "wb").write(pdf_bytes)
        r = subprocess.run(["pdftohtml", "-xml", "-i", "-q", "-stdout", p], capture_output=True)
        xml = r.stdout.decode("utf-8", "replace")
    xml = re.sub(r"<!DOCTYPE[^>]*>", "", xml)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], []
    runs, links = [], []
    for page in root.iter("page"):
        pn = int(page.get("number"))
        for t in page.iter("text"):
            txt = html.unescape("".join(t.itertext())).strip()
            top, left = int(t.get("top")), int(t.get("left"))
            runs.append((pn, top, left, txt))
            for a in t.iter("a"):
                links.append((pn, top, left, a.get("href", ""), txt))
    runs.sort()
    links.sort()
    return runs, links


SKIP_TEXT = re.compile(r"explanation of|case law|comprehensive plan|future land use|use table|zoning code|"
                       r"bylaws|code of ordinances|recusal|title vi|minutes|agenda", re.I)
def meeting_wide(slug, txt):
    """A staff report for the whole meeting: named only by board and date ('BOZA Staff Report 9282026')."""
    name = slug if re.search(r"[A-Za-z]{3}", slug) else txt
    if doc_type(name) != "Staff report":
        return False
    rest = re.sub(r"(?i)\b(boza|pc|planning|commission|board|of|zoning|appeals|staff|reports?|sr|pdf)\b|\d+|\W", "", name)
    return rest == ""


ITEM_START = re.compile(r"^\s*(?:[A-Ha-h]|\d{1,2})[.)](?:\s+\S|\s*$)")


def assign(runs, links, by_item=False):
    """by_item: boards without case numbers (HDPC, DRB). Documents inside an item keep the
    item's text, and build_data.py matches them to a property by TMS or street address."""
    # Agenda items in reading order; each item's case = first case number inside it.
    starts = [(pn, top) for pn, top, _, txt in runs if ITEM_START.match(txt)]
    def item_of(pos):
        above = [s_ for s_ in starts if s_ <= pos]
        return above[-1] if above else None
    def case_in_item(item):
        if item is None:
            return None
        nxt = [s_ for s_ in starts if s_ > item]
        end = nxt[0] if nxt else (10 ** 6, 0)
        for pn, top, _, txt in runs:
            if item <= (pn, top) < end:
                m = CASE.search(txt)
                if m:
                    return norm(m)
        return None
    def text_of(item):
        nxt = [s_ for s_ in starts if s_ > item]
        end = nxt[0] if nxt else (10 ** 6, 0)
        return " ".join(txt for pn, top, _, txt in runs if item <= (pn, top) < end)[:400]
    best = {}  # href -> (strength, order, doc)
    for order, (pn, top, left, href, txt) in enumerate(links):
        href = href.strip()
        if not href.startswith("http") or SKIP.search(href) or "DocumentCenter" not in href:
            continue
        if SKIP_TEXT.search(txt) and not CASE.search(txt):
            continue
        slug = re.sub(r"[-_]+", " ", href.rsplit("/", 1)[-1].split("?")[0])
        if SKIP_TEXT.search(slug) and not CASE.search(slug.replace(" ", "-")):
            continue
        ms, mt = CASE.search(slug.replace(" ", "-")), CASE.search(txt)
        item = item_of((pn, top + 4))
        strength = 3 if ms else 2 if mt else 1 if item is not None else 0
        if ms or mt:
            case = norm(ms or mt)
        elif item is not None:
            case = case_in_item(item)
            if case is None and by_item and not meeting_wide(slug, txt):
                dtype = doc_type(f"{slug} {txt}")
                label = slug if re.search(r"[A-Za-z]{3}", slug) else txt
                doc = {"case": None, "item": text_of(item), "type": dtype, "url": href, "label": label.strip()[:90]}
                if href not in best:
                    best[href] = (1, order, doc)
                continue
            if case is None and not meeting_wide(slug, txt):
                continue  # an item without a case number (street names, text amendments)
        else:
            case = None  # above the first item: meeting-wide
        dtype = doc_type(f"{slug} {txt}")
        if case is None and not meeting_wide(slug, txt):
            continue  # general correspondence/updates are not about one case
        if dtype == "Document" and (ms or CASE.fullmatch(txt.strip(" ."))):
            dtype = "Application"  # the case packet: named after, or linked from, the case number
        label = slug if re.search(r"[A-Za-z]{3}", slug) else txt
        if not re.search(r"[A-Za-z]{3}", slug) and not CASE.search(txt) and len(txt) < 25:
            label = "Case document"  # a hyperlinked fragment of the item description
        doc = {"case": case, "type": dtype, "url": href, "label": label.strip()[:90]}
        if href not in best or strength > best[href][0]:
            best[href] = (strength, best.get(href, (0, order))[1] if href in best else order, doc)
    return [d for _, _, d in sorted(best.values(), key=lambda x: x[1])]


def meetings():
    with open(os.path.join(ROOT, "minutes", "index.csv")) as f:
        for row in csv.DictReader(f):
            m = re.search(r"_(\d{8})-(\d+)", row["source_agenda"] or "")
            if m:
                yield "boza", row["date"], m.group(0)
    for body in ("pc", "hdpc", "drb"):
        folder = os.path.join(ROOT, "sources", body)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(\d+)\.txt$", name)
            if m:
                y, mo, d, aid = m.groups()
                yield body, f"{y}-{mo}-{d}", f"_{mo}{d}{y}-{aid}"


def main():
    data = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [(b, d, a) for b, d, a in meetings() if f"{b}/{d}" not in data]
    print(f"{len(todo)} agendas to read ({len(data)} cached)")
    for k, (body, date, aid) in enumerate(todo, 1):
        pdf = get(BASE + aid)
        if not pdf.startswith(b"%PDF"):
            continue  # not cached: retried next run
        runs, links = links_in(pdf)
        data[f"{body}/{date}"] = assign(runs, links, by_item=body in ("hdpc", "drb"))
        if k % 25 == 0:
            print(f"  {k}/{len(todo)}")
            json.dump(dict(sorted(data.items())), open(OUT, "w"), indent=1)
    json.dump(dict(sorted(data.items())), open(OUT, "w"), indent=1)
    n = sum(len(v) for v in data.values())
    print(f"{len(data)} agendas, {n} case documents, {sum(1 for v in data.values() if v)} with any")


if __name__ == "__main__":
    main()
