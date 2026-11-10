"""Write one static page per neighborhood, so shared links preview with the right title.

    python3 tools/hood_pages.py <site_dir>

Creates <site_dir>/n/index.html (all neighborhoods) and <site_dir>/n/<slug>/index.html
for each neighborhood with a page, from hood.html. Link previews on Nextdoor and
Facebook don't run JavaScript, so the title and description must be in the HTML.
Run at deploy time; the pages are not committed.
"""
import html
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE = "https://www.fabiobrocca.tech/boza/"
E = html.escape


def page(tpl, base, slug, title, desc, url):
    head = (f'<base href="{base}">\n<title>{E(title)}</title>\n'
            f'<meta name="description" content="{E(desc)}">\n'
            f'<meta property="og:title" content="{E(title)}">\n'
            f'<meta property="og:description" content="{E(desc)}">\n'
            f'<meta property="og:url" content="{E(url)}">\n<meta property="og:type" content="website">\n'
            f'<link rel="canonical" href="{E(url)}">')
    out = re.sub(r"<!--HEAD-->.*?<!--/HEAD-->", head, tpl, flags=re.S)
    return out.replace("<!--HOOD-->", f"<script>window.HOOD = {json.dumps(slug)};</script>")


def main(site):
    tpl = open(os.path.join(ROOT, "hood.html")).read()
    nb = json.load(open(os.path.join(ROOT, "data", "neighborhoods.json")))
    props = {p["id"]: p for p in json.load(open(os.path.join(ROOT, "data", "properties.json")))["properties"]}
    os.makedirs(os.path.join(site, "n"), exist_ok=True)
    pages = [h for h in nb["hoods"] if h.get("page")]
    with open(os.path.join(site, "n", "index.html"), "w") as f:
        f.write(page(tpl, "../", None, "Mount Pleasant zoning by neighborhood",
                     f"Zoning cases in {len(pages)} Mount Pleasant, SC neighborhoods: what's been filed, what's coming up and what was decided since 2017.",
                     SITE + "n/"))
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
            f.write(page(tpl, "../../", h["slug"], f"Zoning in {h['name']}, Mount Pleasant", desc, f"{SITE}n/{h['slug']}/"))
    print(f"wrote {len(pages) + 1} neighborhood pages to {site}/n/")


if __name__ == "__main__":
    main(sys.argv[1])
