"""Monthly check of the Town links the record cites (case documents and minutes).

    python3 tools/check_links.py [--max N] [--minutes M]

The Town removes documents from its Document Center over time (73 from 2017-2018 were gone by
November 2026, and only one had ever been captured by the Wayback Machine). This script:

  1. checks each document and minutes link, oldest-checked first, politely (one at a time);
  2. records links that now return 404 or 410 in data/dead-docs.json, with a Wayback Machine copy
     when one exists, so build_data.py links to the archived copy or drops the link;
  3. asks the Wayback Machine to save live documents that have no copy yet, a few per run
     (best effort: the save service is rate-limited and sometimes refuses).

State is kept in data/link-status.json: {url: {"s": status, "d": date checked, "w": wayback url}}.
Stops after --minutes (default 25) so the monthly job stays short; the next run picks up where this
one stopped.
"""
import argparse
import datetime
import json
import os
import time

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
UA = {"User-Agent": "The Zoning Record link check (+https://zoningrecord.com/)"}
SAVE_PER_RUN = 25


def load(name, default):
    try:
        return json.load(open(os.path.join(DATA, name)))
    except (OSError, ValueError):
        return default


def save(name, obj):
    with open(os.path.join(DATA, name), "w") as f:
        json.dump(obj, f, indent=0, sort_keys=True)


def cited_links():
    props = load("properties.json", {"properties": []})["properties"]
    urls = set()
    for p in props:
        for c in p["cases"]:
            for e in c["events"]:
                if e.get("town"):
                    urls.add(e["town"])
                for d in e.get("docs") or []:
                    urls.add(d["u"])
    return urls


def status_of(s, url):
    for attempt in range(3):
        try:
            r = s.get(url, timeout=60, stream=True, allow_redirects=True)
            r.close()
            return r.status_code
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    return "error"


def wayback_copy(s, url):
    try:
        snap = s.get("https://archive.org/wayback/available", params={"url": url}, timeout=30).json()
        snap = (snap.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and str(snap.get("status", "200")).startswith("2"):
            return snap["url"].replace("http://", "https://", 1)
    except (requests.RequestException, ValueError):
        pass
    return None


def wayback_save(s, url):
    try:
        r = s.get("https://web.archive.org/save/" + url, timeout=120)
        return r.status_code < 400
    except requests.RequestException:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=100000)
    ap.add_argument("--minutes", type=float, default=25)
    args = ap.parse_args()
    deadline = time.time() + args.minutes * 60
    today = datetime.date.today().isoformat()
    state = load("link-status.json", {})
    dead = load("dead-docs.json", {"urls": [], "archive": {}})
    dead.setdefault("archive", {})
    dead_set = set(dead["urls"])
    s = requests.Session()
    s.headers.update(UA)
    todo = sorted(cited_links() | dead_set, key=lambda u: (state.get(u, {}).get("d", ""), u))
    checked = newly_dead = saved = 0
    for url in todo[:args.max]:
        if time.time() > deadline:
            break
        st = status_of(s, url)
        rec = state.setdefault(url, {})
        rec.update({"s": st, "d": today})
        checked += 1
        if st in (404, 410):
            if url not in dead_set:
                dead["urls"].append(url)
                dead_set.add(url)
                newly_dead += 1
            w = rec.get("w") or wayback_copy(s, url)
            if w:
                rec["w"] = w
                dead["archive"][url] = w
        elif st == 200 and url in dead_set:  # came back
            dead["urls"].remove(url)
            dead_set.discard(url)
            dead["archive"].pop(url, None)
        elif st == 200 and not rec.get("w") and saved < SAVE_PER_RUN and "DocumentCenter" in url:
            if wayback_save(s, url):
                saved += 1
                time.sleep(10)
                rec["w"] = wayback_copy(s, url) or "requested"
        time.sleep(0.6)
    dead["urls"].sort()
    dead["note"] = ("Town links that returned 404 or 410 when last checked (tools/check_links.py). build_data.py links "
                    "to the Wayback Machine copy in 'archive' when there is one, and otherwise leaves the link out.")
    save("dead-docs.json", dead)
    save("link-status.json", state)
    print(f"links: checked {checked} of {len(todo)}, {newly_dead} newly dead, {len(dead_set)} dead in total "
          f"({len(dead['archive'])} with an archived copy), {saved} sent to the Wayback Machine")


if __name__ == "__main__":
    main()
