"""Write one static page per neighborhood, so shared links preview with the right title.

    python3 tools/hood_pages.py <site_dir>

Creates <site_dir>/n/index.html (all neighborhoods) and <site_dir>/n/<slug>/index.html
for each neighborhood with a page, from hood.html. Link previews on Nextdoor and
Facebook don't run JavaScript, so the title and description must be in the HTML.
Run at deploy time; the pages are not committed.
"""
import collections
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from static_pages import prop_slug, day  # noqa: E402  same slugs as the property pages

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE = "https://zoningrecord.com/mount-pleasant/"
E = html.escape


def page(tpl, base, slug, title, desc, url, body=None):
    head = (f'<base href="{base}">\n<title>{E(title)}</title>\n'
            f'<meta name="description" content="{E(desc)}">\n'
            f'<meta property="og:title" content="{E(title)}">\n'
            f'<meta property="og:description" content="{E(desc)}">\n'
            f'<meta property="og:url" content="{E(url)}">\n<meta property="og:type" content="website">\n'
            f'<link rel="canonical" href="{E(url)}">')
    out = re.sub(r"<!--HEAD-->.*?<!--/HEAD-->", head, tpl, flags=re.S)
    if body:  # readable without JavaScript (crawlers, AI assistants); hood.js replaces it for visitors
        out = out.replace('<div class="loading">Loading…</div>', body, 1)
    return out.replace("<!--HOOD-->", f"<script>window.HOOD = {json.dumps(slug)};</script>")


def hood_body(h, props, faq):
    """Plain-HTML summary of a neighborhood: counts, what neighbors raise, latest decisions, every property."""
    plist = sorted(props, key=lambda p: p["address"])
    cases = [(p, c) for p in plist for c in p["cases"] if c["kind"] != "Staff approval"]
    kinds = collections.Counter(c["kind"] for _, c in cases)
    first = min((c["first"] for _, c in cases), default="")[:4]
    out = [f'<section class="h-head"><p class="eyebrow">Neighborhood</p><h1>{E(h["name"])}</h1>'
           f'<p class="h-sub">{len(cases)} zoning cases on {len(plist)} properties since {first or 2017}: '
           + ", ".join(f"{n} {k.lower()}" for k, n in kinds.most_common(4)) + ".</p></section>"]
    fq = (faq.get("hoods") or {}).get(h["slug"])
    if fq:
        out.append('<section class="h-section"><h2>What neighbors raise</h2><ul class="h-list">' + "".join(
            f'<li><span class="h-li-main">{E(t["label"])}</span><span class="h-li-sub">Raised at {t["hearings"]} hearings. '
            + " ".join(E(x["q"]) for x in t["examples"][:2]) + "</span></li>" for t in fq["topics"][:5]) + "</ul></section>")
    latest = sorted(cases, key=lambda pc: pc[1]["date"], reverse=True)[:10]
    out.append('<section class="h-section"><h2>Latest decisions</h2><ul class="h-list">' + "".join(
        f'<li><a class="h-li-main" href="p/{prop_slug(p)}/">{E(p["address"])}</a>'
        f'<span class="h-li-sub">{E(c["status"])} · {E(c["kind"])}{" · " + E(c["case"]) if c.get("case") else ""} · {day(c["date"], "%b %-d, %Y")}</span></li>'
        for p, c in latest) + "</ul></section>")
    out.append('<section class="h-section"><h2>Every property with a case here</h2><p>' + " · ".join(
        f'<a href="p/{prop_slug(p)}/">{E(p["address"])}</a>' for p in plist) + "</p></section>")
    return "".join(out)


def main(site):
    tpl = open(os.path.join(ROOT, "hood.html")).read()
    nb = json.load(open(os.path.join(ROOT, "data", "neighborhoods.json")))
    props = {p["id"]: p for p in json.load(open(os.path.join(ROOT, "data", "properties.json")))["properties"]}
    faq = json.load(open(os.path.join(ROOT, "data", "faq.json"))) if os.path.exists(os.path.join(ROOT, "data", "faq.json")) else {}
    os.makedirs(os.path.join(site, "n"), exist_ok=True)
    pages = [h for h in nb["hoods"] if h.get("page")]
    with open(os.path.join(site, "n", "index.html"), "w") as f:
        f.write(page(tpl, "../", None, "Mount Pleasant zoning by neighborhood",
                     f"Zoning cases in {len(pages)} Mount Pleasant, SC neighborhoods: what's been filed, what's coming up and what was decided since 2017.",
                     SITE + "n/", '<section class="h-head"><p class="eyebrow">Neighborhoods</p><h1>Zoning by neighborhood</h1></section>'
                     '<section class="h-section"><ul class="h-list">' + "".join(
                         f'<li><a class="h-li-main" href="n/{E(h["slug"])}/">{E(h["name"])}</a></li>' for h in sorted(pages, key=lambda h: h["name"]))
                     + "</ul></section>"))
    for h in pages:
        cases = [c for pid, s in nb["assign"].items() if s == h["slug"] for c in props[pid]["cases"] if c["kind"] != "Staff approval"]
        dec = [c for c in cases if c["status"] in ("Approved", "Approved with conditions", "Adopted by Council", "Denied", "Denied by Council")]
        ok = sum(c["status"] != "Denied" and c["status"] != "Denied by Council" for c in dec)
        desc = (f"{len(cases)} zoning cases in {h['name']}, Mount Pleasant, SC since 2017"
                + (f": {ok} of {len(dec)} decided requests approved." if dec else ".")
                + " What's been filed, what's coming up and what was decided.")
        d = os.path.join(site, "n", h["slug"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            hp = [props[pid] for pid, s in nb["assign"].items() if s == h["slug"] and pid in props]
            f.write(page(tpl, "../../", h["slug"], f"Zoning in {h['name']}, Mount Pleasant", desc, f"{SITE}n/{h['slug']}/",
                         hood_body(h, hp, faq)))
    print(f"wrote {len(pages) + 1} neighborhood pages to {site}/n/")


if __name__ == "__main__":
    main(sys.argv[1])
