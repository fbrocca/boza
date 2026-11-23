"""Static pages for search engines and AI assistants, written at deploy time.

    python3 tools/static_pages.py <site_dir> <root_dir>

The map is a JavaScript app; crawlers (and most AI assistants) read plain HTML. This writes
the same record as plain pages, one per property, meeting and board, each with its sources:

  <site_dir>/p/<slug>/      one page per property: every case, outcome, hearing, document
  <site_dir>/p/             index of all properties by street
  <site_dir>/m/<date-board>/ one page per hearing: what was heard and decided
  <site_dir>/m/             index of meetings by year
  <site_dir>/g/<board>/     what each board decides, outcomes and the questions it asks
  <site_dir>/g/             index of guides
  <root_dir>/sitemap.xml, robots.txt, llms.txt

Slugs are stable: address plus the parcel number, so a page keeps its URL when cases are
added (app.js builds the same slug for its "Permanent page" link). No names of residents or
applicants appear; outcomes are counts, never predictions.
"""
import collections
import datetime
import html
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
SITE = "https://zoningrecord.com/mount-pleasant/"
ORIGIN = "https://zoningrecord.com/"
def E(s):
    return html.escape("" if s is None else str(s))


def cid(c):
    """Case number, or a stand-in when the minutes give none."""
    return c.get("case") or f"{c['kind']} ({day(c['first'], '%b %Y')})"
TODAY = datetime.date.today().isoformat()

BOARD_SLUG = {
    "Board of Zoning Appeals": "board-of-zoning-appeals", "Planning Commission": "planning-commission",
    "Planning Committee": "planning-committee", "Town Council": "town-council",
    "Historic District Preservation Commission": "historic-district-commission", "Design Review Board": "design-review-board",
}
RELIEF = {
    "front_setback": "Front setback", "side_setback": "Side setback", "rear_setback": "Rear setback", "multiple_setbacks": "Several setbacks",
    "height": "Height", "lot_coverage_or_bar": "Lot coverage / building area", "tree_removal_or_protection": "Tree removal / protection",
    "buffer": "Buffer", "parking": "Parking", "lot_size_density_subdivision": "Lot size / density", "accessory_structure": "Accessory structure",
    "signage": "Signage", "use": "Use", "porch_or_design_standard": "Porch / design standard", "dock_or_marsh": "Dock / marsh",
}
GUIDES = [
    {"slug": "board-of-zoning-appeals", "title": "Board of Zoning Appeals",
     "h1": "Variances, special exceptions and appeals in Mount Pleasant",
     "bodies": {"Board of Zoning Appeals"}, "faq": "boza:all",
     "what": "The Board of Zoning Appeals hears requests to depart from the zoning code on a specific lot "
             "(variances, such as building closer to a property line than the setback allows), special exceptions "
             "the code lets the board grant case by case, and appeals of decisions made by Town staff. "
             "Its decision is final at the Town level."},
    {"slug": "rezoning-and-annexation", "title": "Rezonings and annexations",
     "h1": "Rezonings, annexations and planned developments in Mount Pleasant",
     "bodies": {"Planning Commission", "Planning Committee", "Town Council"}, "faq": "planning:rezoning",
     "what": "Requests to change a property's zoning district, bring land into the Town, or amend a planned development "
             "start at the Planning Commission, which holds a hearing and makes a recommendation. Town Council decides, "
             "usually after review by its Planning Committee and over two readings of an ordinance. "
             "The Planning Commission also reviews sketch plans for new subdivisions."},
    {"slug": "historic-district-commission", "title": "Historic District Preservation Commission",
     "h1": "Historic district reviews and demolitions in Mount Pleasant",
     "bodies": {"Historic District Preservation Commission"}, "faq": "hdpc:all",
     "what": "The Historic District Preservation Commission reviews exterior changes, new buildings and demolitions in the "
             "Town's historic district and on designated historic properties. Projects often come back more than once: "
             "a preliminary or conceptual review with comments, then a final review with a vote."},
    {"slug": "design-review-board", "title": "Design Review Board",
     "h1": "Design review of commercial and larger projects in Mount Pleasant",
     "bodies": {"Design Review Board"}, "faq": "drb:all",
     "what": "The Design Review Board reviews the design of commercial, multifamily and other larger projects in the Town's "
             "design review areas: building form, materials, landscaping and site layout. Like the historic commission, "
             "it often sees a project at a preliminary stage before giving final approval."},
]


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def prop_slug(p):
    """Same rule as propSlug() in app.js."""
    if p["id"].startswith("tms-"):
        return f"{slugify(p['address'])}-{re.sub(r'[^0-9]', '', p['id'])}"
    return slugify(p["id"][5:] if p["id"].startswith("addr-") else p["id"])


def meet_slug(date, body):
    return f"{date}-{BOARD_SLUG.get(body, slugify(body))}"


def day(d, fmt="%B %-d, %Y"):
    try:
        return datetime.date.fromisoformat(d).strftime(fmt)
    except (TypeError, ValueError):
        return d or ""


def hms(t):
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def load(name, default):
    try:
        return json.load(open(os.path.join(DATA, name)))
    except (OSError, ValueError):
        return default


def shell(base, title, desc, url, body, ld=None, crumbs=None):
    lds = [ld] if ld else []
    if crumbs:
        lds.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + u} for i, (n, u) in enumerate(crumbs)]})
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, separators=(",", ":"))}</script>\n' for x in lds)
    crumb_html = ""
    if crumbs:
        crumb_html = '<nav class="crumbs" aria-label="Breadcrumb">' + " / ".join(
            f'<a href="{E(u)}">{E(n)}</a>' for n, u in crumbs[:-1]) + "</nav>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="{base}">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(url)}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{E(url)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="The Zoning Record">
<link rel="icon" href="icons/favicon.svg" type="image/svg+xml">
<link rel="icon" href="icons/favicon.ico" sizes="16x16 32x32 48x48">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="manifest" href="site.webmanifest">
<meta name="theme-color" content="#f5f2ea">
<meta property="og:image" content="https://zoningrecord.com/mount-pleasant/icons/og.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="landing.css">
<link rel="stylesheet" href="pages.css">
{ld_html}</head>
<body>
<header class="mast"><div class="wrap">
  <a class="logo" href="./"><svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="4"><path d="M8 8H56V56H8Z"/><path d="M8 30H56M30 8V56"/></g><path class="lot" d="M32 32H54V54H32Z" fill="#2e5b3f"/></svg><span>The Zoning Record</span><i>Mount Pleasant</i></a>
  <nav aria-label="Main"><a href="map/">Map</a><a href="n/">Neighborhoods</a><a href="p/">Properties</a><a href="m/">Meetings</a><a href="g/">Guides</a><a href="plan.html">Plan a request</a></nav>
</div></header>
<main class="wrap doc">
{crumb_html}
{body}
</main>
<footer class="foot"><div class="wrap">
  <span>The Zoning Record · Mount Pleasant. Independent; not affiliated with the Town. Not legal advice. The Town's minutes are authoritative.</span>
  <span><a href="p/">Properties</a> · <a href="m/">Meetings</a> · <a href="g/">Guides</a> · <a href="feeds/meetings.ics">Calendar</a> · <a href="https://github.com/fbrocca/boza">Method and data</a></span>
</div></footer>
<script>window.goatcounter = {{ path: function () {{ return location.pathname; }} }};</script>
<script data-goatcounter="https://fbrocca.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
</body>
</html>
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def plural(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


class Links:
    def __init__(self):
        self.videos = load("videos.json", {})
        self.moments = load("video-moments.json", {})

    def event(self, e):
        out = []
        m = self.moments.get(e["id"])
        vid = (self.videos.get(e["date"]) or {}).get(e["body"])
        if m:
            out.append(f'<a href="https://www.youtube.com/watch?v={E(m[0])}&amp;t={int(m[1])}s" rel="noopener">Video, from about {hms(int(m[1]))}</a>')
        elif vid:
            out.append(f'<a href="https://www.youtube.com/watch?v={E(vid)}" rel="noopener">Meeting video</a>')
        if e.get("town"):
            out.append(f'<a href="{E(e["town"])}#page={e.get("page", 1)}" rel="noopener">Minutes, p.{e.get("page", 1)}</a>')
        for d in e.get("docs") or []:
            out.append(f'<a href="{E(d["u"])}" rel="noopener">{E(d["t"])}</a>')
        return " · ".join(out)


def property_pages(site, props, hoods, assign, links, meet_of):
    urls = []
    for p in props:
        slug = prop_slug(p)
        url = f"{SITE}p/{slug}/"
        cases = sorted(p["cases"], key=lambda c: c["date"], reverse=True)
        years = sorted({c["first"][:4] for c in cases} | {c["date"][:4] for c in cases})
        hood = hoods.get(assign.get(p["id"]))
        lead_bits = [f'{E(cid(c))} ({E(c["kind"].lower())}, {E(c['status'][:1].lower() + c['status'][1:])}, {day(c["date"], "%b %Y")})' for c in cases[:4]]
        more = f" and {len(cases) - 4} more" if len(cases) > 4 else ""
        lead = (f'{E(p["address"])} has {plural(len(cases), "zoning case")} on record'
                f'{" since " + years[0] if years else ""}: {", ".join(lead_bits)}{more}.')
        facts = []
        if p.get("tms"):
            facts.append(f'TMS {E(p["tms"])}')
        if p.get("acres"):
            facts.append(f'{p["acres"]:.2f} acres')
        z = (p.get("zoning") or {}).get("zoning")
        if z:
            facts.append("Zoned " + E(", ".join(z)))
        if hood and hood.get("page"):
            facts.append(f'<a href="n/{E(hood["slug"])}/">{E(hood["name"])}</a>')
        sale = p.get("sale") or {}
        sale_html = ""
        if sale.get("price") and not sale.get("nominal"):
            sale_html = f'<p class="note">Last recorded sale: ${sale["price"]:,.0f}, {day(sale.get("date"), "%B %Y")} (Charleston County records).</p>'
        blocks = []
        for c in cases:
            f = c.get("facts") or {}
            tags = [E(c["kind"])]
            if f.get("relief") in RELIEF:
                tags.append(E(RELIEF[f["relief"]]))
            if f.get("vote") and f["vote"] not in ("n/a", "unknown"):
                tags.append("Vote " + E(f["vote"]))
            summ = f'<p class="ai"><span>AI summary</span>{E(f["key_factor"])}</p>' if f.get("key_factor") else ""
            evs = []
            for e in sorted(c["events"], key=lambda e: e["date"]):
                ms = meet_slug(e["date"], e["body"])
                meet_of[ms].append((p, c, e))
                lk = links.event(e)
                evs.append(f'<li><span class="when"><a href="m/{ms}/">{day(e["date"], "%b %-d, %Y")}</a></span>'
                           f'<span><b>{E(e["body"])}</b>: {E(e["decision"])}{f"<br><small>{lk}</small>" if lk else ""}</span></li>')
            blocks.append(f"""<section class="case" id="{E(slugify(cid(c)))}">
  <h2>{E(cid(c))} <span class="status">{E(c['status'])}</span></h2>
  <p class="tags">{' · '.join(tags)}</p>
  <p>{E(c['request'])}</p>
  {f'<p class="note">Outcome from the minutes of {day(c["status_evidence"]["date"])}: “{E(c["status_evidence"]["quote"])}”</p>' if c.get("status_evidence") else ""}
  {summ}
  <ol class="hearings">{''.join(evs)}</ol>
</section>""")
        body = f"""<article>
<p class="kicker">Zoning history</p>
<h1>{E(p['address'])}</h1>
<p class="lede">{lead}</p>
<p class="facts">{' · '.join(facts)}</p>
{sale_html}
<p class="actions"><a class="btn" href="map/#{E(p['id'])}">Open on the map</a> <a href="plan.html?address={E(p['address'])}">Plan a request here</a></p>
{''.join(blocks)}
<p class="note">Outcomes and summaries are read from the Town's minutes; AI summaries are labeled and checked against the minutes they cite. The minutes remain authoritative. <a href="map/#{E(p['id'])}">See something wrong? Report it from the map.</a></p>
</article>"""
        desc = f"Zoning history of {p['address']}, Mount Pleasant, SC: {plural(len(cases), 'case')}, " + \
               ", ".join(f"{cid(c)} {c['kind'].lower()} {c['status'].lower()}" for c in cases[:3]) + "."
        ld = {"@context": "https://schema.org", "@type": "Place", "name": p["address"], "url": url,
              "address": {"@type": "PostalAddress", "streetAddress": p["address"], "addressLocality": "Mount Pleasant",
                          "addressRegion": "SC", "addressCountry": "US"}}
        if p.get("lat"):
            ld["geo"] = {"@type": "GeoCoordinates", "latitude": p["lat"], "longitude": p["lng"]}
        write(os.path.join(site, "p", slug, "index.html"),
              shell("../../", f"{p['address']} · Zoning history · Mount Pleasant, SC", desc[:300], url, body, ld,
                    [("Mount Pleasant", "./"), ("Properties", "p/"), (p["address"], f"p/{slug}/")]))
        urls.append((url, p.get("date") or TODAY))
    # index by street
    by_street = collections.defaultdict(list)
    for p in props:
        street = re.sub(r"^[0-9][0-9A-Za-z\-/ &]*?\s+(?=[A-Za-z])", "", p["address"]).strip() or p["address"]
        by_street[street.title()].append(p)
    groups, letters = [], []
    for street in sorted(by_street, key=lambda s: s.lower()):
        items = sorted(by_street[street], key=lambda p: (len(p["address"]), p["address"]))
        first = street[:1].upper() if street[:1].isalpha() else "#"
        anchor = ""
        if first not in letters:
            letters.append(first)
            anchor = f' id="l-{"0" if first == "#" else first}"'
        groups.append(f'<li{anchor}><b>{E(street)}</b> ' + " · ".join(
            f'<a href="p/{prop_slug(p)}/">{E(p["address"])}</a>' for p in items) + "</li>")
    body = f"""<p class="kicker">Index</p><h1>Every property with a zoning case</h1>
<p class="lede">{len(props):,} Mount Pleasant properties that went before a Town board since 2017, by street. Each page lists every case, its outcome and the minutes behind it.</p>
<p class="jump">{' '.join(f'<a href="p/#l-{"0" if l == "#" else l}">{l}</a>' for l in letters)}</p>
<ul class="index streets">{''.join(groups)}</ul>"""
    write(os.path.join(site, "p", "index.html"),
          shell("../", "All properties · The Zoning Record · Mount Pleasant", f"{len(props):,} Mount Pleasant, SC properties with zoning, historic or design review cases since 2017.",
                SITE + "p/", body, crumbs=[("Mount Pleasant", "./"), ("Properties", "p/")]))
    urls.append((SITE + "p/", TODAY))
    return urls


def meeting_pages(site, meet_of, links):
    urls, by_year = [], collections.defaultdict(list)
    for ms, rows in meet_of.items():
        date, body_name = rows[0][2]["date"], rows[0][2]["body"]
        title = f"{body_name}, {day(date)}"
        decided = collections.Counter(e["decision"] for _, _, e in rows)
        sample = rows[0][2]
        meeting_links = []
        vid = (links.videos.get(date) or {}).get(body_name)
        if vid:
            meeting_links.append(f'<a href="https://www.youtube.com/watch?v={E(vid)}" rel="noopener">Meeting video</a>')
        if sample.get("town"):
            meeting_links.append(f'<a href="{E(sample["town"])}" rel="noopener">Minutes (Town)</a>')
        items = []
        for p, c, e in sorted(rows, key=lambda r: cid(r[1])):
            items.append(f'<li><a href="p/{prop_slug(p)}/#{E(slugify(cid(c)))}"><b>{E(p["address"])}</b></a> '
                         f'<span class="mono">{E(cid(c))}</span> · {E(c["kind"])}<br>'
                         f'<span class="dec">{E(e["decision"])}</span> · {E(c["request"][:220])}{"…" if len(c["request"]) > 220 else ""}</li>')
        summary = ", ".join(f"{n} {d.lower()}" for d, n in decided.most_common())
        body = f"""<article><p class="kicker">Hearing</p><h1>{E(title)}</h1>
<p class="lede">{plural(len(rows), "zoning item")} heard: {E(summary)}.</p>
<p class="facts">{' · '.join(meeting_links)}</p>
<ol class="items">{''.join(items)}</ol></article>"""
        url = f"{SITE}m/{ms}/"
        ld = {"@context": "https://schema.org", "@type": "Event", "name": title, "startDate": date, "url": url,
              "eventStatus": "https://schema.org/EventScheduled", "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
              "location": {"@type": "Place", "name": "Mount Pleasant Town Hall",
                           "address": {"@type": "PostalAddress", "streetAddress": "100 Ann Edwards Lane", "addressLocality": "Mount Pleasant", "addressRegion": "SC", "postalCode": "29464", "addressCountry": "US"}},
              "organizer": {"@type": "GovernmentOrganization", "name": f"Town of Mount Pleasant {body_name}"}}
        write(os.path.join(site, "m", ms, "index.html"),
              shell("../../", f"{title} · Zoning decisions · The Zoning Record", f"What the Mount Pleasant {body_name} heard and decided on {day(date)}: {summary}.",
                    url, body, ld, [("Mount Pleasant", "./"), ("Meetings", "m/"), (title, f"m/{ms}/")]))
        urls.append((url, date))
        by_year[date[:4]].append((date, body_name, ms, len(rows)))
    parts = []
    for y in sorted(by_year, reverse=True):
        lis = "".join(f'<li><span class="when">{day(d, "%b %-d")}</span><a href="m/{ms}/">{E(b)}</a> <small>{plural(n, "item")}</small></li>'
                      for d, b, ms, n in sorted(by_year[y], reverse=True))
        parts.append(f'<h2>{y}</h2><ul class="index meets">{lis}</ul>')
    body = f"""<p class="kicker">Index</p><h1>Every zoning hearing since 2017</h1>
<p class="lede">{len(meet_of):,} meetings of the Board of Zoning Appeals, Planning Commission, Town Council, Historic District Preservation Commission and Design Review Board, with what each heard and decided.</p>
{''.join(parts)}"""
    write(os.path.join(site, "m", "index.html"),
          shell("../", "All meetings · The Zoning Record · Mount Pleasant", "Every Mount Pleasant, SC zoning, historic and design review hearing since 2017, with decisions.",
                SITE + "m/", body, crumbs=[("Mount Pleasant", "./"), ("Meetings", "m/")]))
    urls.append((SITE + "m/", TODAY))
    return urls


def guide_pages(site, props, faq, meet_of):
    urls, cards = [], []
    for g in GUIDES:
        rows = [(p, c, e) for p in props for c in p["cases"] for e in c["events"] if e["body"] in g["bodies"]]
        cases = {(p["id"], cid(c)): (p, c) for p, c, _ in rows}
        status = collections.Counter(c["status"] for _, c in cases.values())
        kinds = collections.Counter(c["kind"] for _, c in cases.values())
        meetings = {meet_slug(e["date"], e["body"]) for _, _, e in rows}
        first = min((e["date"] for _, _, e in rows), default="")
        stat_rows = "".join(f"<tr><th>{E(s)}</th><td>{n:,}</td></tr>" for s, n in status.most_common())
        kind_rows = "".join(f"<tr><th>{E(k)}</th><td>{n:,}</td></tr>" for k, n in kinds.most_common())
        relief = ""
        if g["slug"] == "board-of-zoning-appeals":
            rc = collections.defaultdict(collections.Counter)
            for _, c in cases.values():
                r = (c.get("facts") or {}).get("relief")
                if c["kind"] == "Variance" and r in RELIEF:
                    rc[RELIEF[r]][c["status"]] += 1
            rr = "".join(f"<tr><th>{E(k)}</th><td>{sum(v.values())}</td><td>{v['Approved'] + v['Approved with conditions']}</td><td>{v['Denied']}</td></tr>"
                         for k, v in sorted(rc.items(), key=lambda kv: -sum(kv[1].values())))
            relief = f"""<h2>Variances by what they ask for</h2>
<p>Variance cases where the minutes make the type of relief clear. Counts, not odds: every lot is different.</p>
<table class="t"><thead><tr><th>Relief</th><td>Cases</td><td>Approved</td><td>Denied</td></tr></thead><tbody>{rr}</tbody></table>"""
        fq = (faq.get("groups") or {}).get(g["faq"])
        faq_html = ""
        if fq:
            lis = []
            for t in fq["topics"][:8]:
                ex = "".join(f'<li>{E(x["q"])} <a href="p/{prop_slug(pid_map[x["pid"]])}/">{E(x.get("case") or "case")}</a></li>'
                             for x in t["examples"] if x.get("pid") in pid_map)
                lis.append(f'<li><b>{E(t["label"])}</b> <small>raised in {t["hearings"]:,} of {fq["hearings"]:,} hearings</small><ul>{ex}</ul></li>')
            faq_html = f"""<h2>What the board asks</h2>
<p>Topics board members raised, counted by hearing, from the minutes. Minutes record questions selectively, so these undercount. <a href="plan.html">Plan a request</a> shows the questions for your type of request.</p>
<ol class="faq">{''.join(lis)}</ol>"""
        recent = sorted(rows, key=lambda r: r[2]["date"], reverse=True)
        seen, rec = set(), []
        for p, c, e in recent:
            if (p["id"], cid(c)) in seen or e["decision"] in ("Deferred", "See minutes"):
                continue
            seen.add((p["id"], cid(c)))
            rec.append(f'<li><span class="when">{day(e["date"], "%b %-d, %Y")}</span><span><a href="p/{prop_slug(p)}/#{E(slugify(cid(c)))}">{E(p["address"])}</a> · {E(c["kind"])} · <b>{E(e["decision"])}</b></span></li>')
            if len(rec) == 12:
                break
        lead = (f"Since {first[:4]}, the record holds {plural(len(cases), 'case')} heard at {plural(len(meetings), 'meeting')} "
                f"of the {E(' and '.join(sorted(g['bodies'])) if len(g['bodies']) < 3 else 'Planning Commission, Planning Committee and Town Council')}.")
        body = f"""<article><p class="kicker">Guide · {E(g['title'])}</p><h1>{E(g['h1'])}</h1>
<p class="lede">{E(g['what'])}</p>
<p>{lead} Updated {day(TODAY)}.</p>
<h2>Outcomes on record</h2>
<div class="two"><table class="t"><thead><tr><th>Outcome</th><td>Cases</td></tr></thead><tbody>{stat_rows}</tbody></table>
<table class="t"><thead><tr><th>Type of request</th><td>Cases</td></tr></thead><tbody>{kind_rows}</tbody></table></div>
{relief}
{faq_html}
<h2>Latest decisions</h2><ol class="hearings">{''.join(rec)}</ol>
<p class="note">Counts come from the Town's minutes since 2017. A case is counted once, with its latest status. Not legal advice; confirm requirements with the Town's Planning Department.</p></article>"""
        url = f"{SITE}g/{g['slug']}/"
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": g["h1"], "url": url, "dateModified": TODAY,
              "about": {"@type": "GovernmentOrganization", "name": f"Town of Mount Pleasant {g['title']}"},
              "publisher": {"@type": "Organization", "name": "The Zoning Record", "url": ORIGIN}}
        write(os.path.join(site, "g", g["slug"], "index.html"),
              shell("../../", f"{g['h1']} · The Zoning Record", f"{g['what'][:200]} Outcomes and questions from {len(cases):,} cases since {first[:4]}.",
                    url, body, ld, [("Mount Pleasant", "./"), ("Guides", "g/"), (g["title"], f"g/{g['slug']}/")]))
        urls.append((url, TODAY))
        cards.append(f'<li><a href="g/{g["slug"]}/"><b>{E(g["title"])}</b></a><br>{E(g["what"][:160].rsplit(" ", 1)[0])}… <small>{plural(len(cases), "case")}</small></li>')
    body = f"""<p class="kicker">Guides</p><h1>How zoning decisions get made in Mount Pleasant</h1>
<p class="lede">What each Town board decides, how its cases have turned out since 2017, and the questions it asks, from the minutes.</p>
<ul class="index guides">{''.join(cards)}</ul>"""
    write(os.path.join(site, "g", "index.html"),
          shell("../", "Guides · The Zoning Record · Mount Pleasant", "How the Board of Zoning Appeals, Planning Commission, Town Council, Historic District Commission and Design Review Board decide zoning cases in Mount Pleasant, SC.",
                SITE + "g/", body, crumbs=[("Mount Pleasant", "./"), ("Guides", "g/")]))
    urls.append((SITE + "g/", TODAY))
    return urls


pid_map = {}


def main(site, root):
    props = load("properties.json", {"properties": []})["properties"]
    pid_map.update({p["id"]: p for p in props})
    nb = load("neighborhoods.json", {"hoods": [], "assign": {}})
    hoods = {h["slug"]: h for h in nb["hoods"]}
    faq = load("faq.json", {})
    links, meet_of = Links(), collections.defaultdict(list)
    urls = [(SITE, TODAY), (SITE + "map/", TODAY), (SITE + "plan.html", TODAY), (SITE + "n/", TODAY)]
    urls += [(f"{SITE}n/{h['slug']}/", TODAY) for h in nb["hoods"] if h.get("page")]
    urls += property_pages(site, props, hoods, nb.get("assign", {}), links, meet_of)
    urls += meeting_pages(site, meet_of, links)
    urls += guide_pages(site, props, faq, meet_of)

    with open(os.path.join(root, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.write("".join(f"<url><loc>{E(u)}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls))
        f.write("</urlset>\n")
    bots = ["Googlebot", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot",
            "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot", "Applebot-Extended", "DuckDuckBot"]
    with open(os.path.join(root, "robots.txt"), "w") as f:
        f.write("# The Zoning Record: public records, open to search engines and AI assistants.\n")
        f.write("".join(f"User-agent: {b}\nAllow: /\n\n" for b in bots))
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}sitemap.xml\n")
    n_cases = sum(len(p["cases"]) for p in props)
    llms = f"""# The Zoning Record

> Every zoning decision in Mount Pleasant, South Carolina, in one place: {n_cases:,} variance, rezoning, annexation, historic and design review cases on {len(props):,} properties since 2017, read from the Town's own minutes and agendas, each linked to its source. Independent; not affiliated with the Town of Mount Pleasant. Not legal advice; the Town's minutes are authoritative.

Each property page lists every case on that lot with its case number, type, request, outcome, the hearings it went through, and links to the minutes page, agenda documents (applications, staff reports) and meeting video where available. Summaries marked "AI summary" were written with AI assistance and checked against the cited minutes. Outcome counts describe past cases and do not predict decisions. Resident names are not published.

## Guides
""" + "".join(f"- [{g['title']}]({SITE}g/{g['slug']}/): {g['what'].split('. ')[0]}.\n" for g in GUIDES) + f"""
## Indexes
- [All properties]({SITE}p/): every property with a zoning case, by street; one page per property
- [All meetings]({SITE}m/): every hearing since 2017 with what was heard and decided
- [Neighborhoods]({SITE}n/): cases, outcomes and resident concerns by neighborhood
- [Interactive map]({SITE}map/): search by address or case number, see upcoming agendas
- [Plan a request]({SITE}plan.html): rules for a lot, the application needed, and how similar requests fared

## Feeds
- [Upcoming meetings calendar]({SITE}feeds/meetings.ics): zoning items on posted agendas
- [Upcoming agenda RSS]({SITE}feeds/agenda.xml)

## Optional
- [Method and source code](https://github.com/fbrocca/boza)
- [Town of Mount Pleasant Agenda Center](https://sc-mountpleasant2.civicplus.com/AgendaCenter): the primary source
"""
    for d in (root, site):
        with open(os.path.join(d, "llms.txt"), "w") as f:
            f.write(llms)
    print(f"static: {len(props)} property pages, {len(meet_of)} meeting pages, {len(GUIDES)} guides, {len(urls)} URLs in sitemap")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
