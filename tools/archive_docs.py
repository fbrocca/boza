"""Archive every Town document the record cites to private S3 storage.

    python3 tools/archive_docs.py --bucket zoningrecord-archive-272106374268 [--minutes 40] [--dry-run DIR]

The Town removes documents from its website over time (73 of 2017-2018 were gone by November 2026,
72 of them lost for good). This keeps our own copy of each one the first time the pipeline sees it:

  docs/<sha256[:2]>/<sha256>.<ext>   the file, stored by content hash (identical files stored once)
  text/<sha256[:2]>/<sha256>.txt     its text (pdftotext -layout), for search and future extraction

S3 metadata on each file records the source URL and when it was fetched. data/archive-manifest.json
(public, no content) maps each source URL to its hash, size, type and fetch date, or the HTTP status
when the Town no longer has it. The bucket is private: applications carry applicants' names and phone
numbers, so copies are not republished.

Sources: case documents (data/agenda-docs.json and data/properties.json), the minutes and agenda
links in the record, and agendas for upcoming meetings (data/upcoming.json). Runs daily in GitHub
Actions with a time budget, oldest-unarchived first, so a backlog spreads over several nights.
Credentials come from the job (an IAM role assumed through GitHub's OIDC); none are stored.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.parse

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
MANIFEST = os.path.join(DATA, "archive-manifest.json")
UA = {"User-Agent": "The Zoning Record archive (+https://zoningrecord.com/)"}
MAX_BYTES = 300 * 1024 * 1024
EXT = {"application/pdf": "pdf", "text/html": "html", "application/msword": "doc", "image/jpeg": "jpg", "image/png": "png",
       "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx"}


def load(name, default):
    try:
        return json.load(open(os.path.join(DATA, name)))
    except (OSError, ValueError):
        return default


def sources():
    urls = set()
    for docs in load("agenda-docs.json", {}).values():
        urls.update(d["url"] for d in docs if d.get("url", "").startswith("http"))
    for p in load("properties.json", {"properties": []})["properties"]:
        for c in p["cases"]:
            for e in c["events"]:
                if e.get("town"):
                    urls.add(e["town"])
                urls.update(d["u"] for d in e.get("docs") or [] if "web.archive.org" not in d["u"])
    for m in load("upcoming.json", {"meetings": []}).get("meetings", []):
        if m.get("agenda", "").startswith("http"):
            urls.add(m["agenda"])
    return urls


class Store:
    """S3, or a local directory with --dry-run."""

    def __init__(self, bucket, local):
        self.local = local
        if not local:
            import boto3
            self.s3, self.bucket = boto3.client("s3"), bucket

    def has(self, key):
        if self.local:
            return os.path.exists(os.path.join(self.local, key))
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.s3.exceptions.ClientError:
            return False

    def put(self, key, path, ctype, meta):
        if self.local:
            os.makedirs(os.path.dirname(os.path.join(self.local, key)), exist_ok=True)
            os.replace(path, os.path.join(self.local, key)) if os.path.exists(path) else None
            return
        with open(path, "rb") as f:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=f, ContentType=ctype, Metadata=meta)


def fetch(s, url, dest):
    """Download to dest; return (status, content type, size, sha256)."""
    for attempt in range(3):
        try:
            with s.get(url, timeout=90, stream=True, allow_redirects=True) as r:
                if r.status_code != 200:
                    return r.status_code, None, 0, None
                h, n = hashlib.sha256(), 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        n += len(chunk)
                        if n > MAX_BYTES:
                            return "too large", None, n, None
                        h.update(chunk)
                        f.write(chunk)
                return 200, r.headers.get("content-type", "").split(";")[0].strip().lower(), n, h.hexdigest()
        except requests.RequestException:
            time.sleep(10 * (attempt + 1))
    return "error", None, 0, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=os.environ.get("ARCHIVE_BUCKET"))
    ap.add_argument("--minutes", type=float, default=40)
    ap.add_argument("--max", type=int, default=100000)
    ap.add_argument("--dry-run", metavar="DIR", help="write to a local directory instead of S3")
    args = ap.parse_args()
    if not args.bucket and not args.dry_run:
        raise SystemExit("--bucket or ARCHIVE_BUCKET is required")
    deadline = time.time() + args.minutes * 60
    store = Store(args.bucket, args.dry_run)
    manifest = load("archive-manifest.json", {})
    today = datetime.date.today().isoformat()
    s = requests.Session()
    s.headers.update(UA)
    # never archived first; then ones that failed before (retried at most weekly)
    todo = [u for u in sorted(sources()) if u not in manifest]
    todo += sorted((u for u, r in manifest.items() if r.get("status") not in (200, 404, 410)
                    and r.get("tried", "") < (datetime.date.today() - datetime.timedelta(days=7)).isoformat()))
    done = stored = gone = 0
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for url in todo[:args.max]:
            if time.time() > deadline:
                break
            path = os.path.join(tmp, "doc")
            st, ctype, size, sha = fetch(s, url, path)
            done += 1
            if st != 200:
                manifest[url] = {**manifest.get(url, {}), "status": st, "tried": today}
                gone += st in (404, 410)
                continue
            ext = EXT.get(ctype, "bin")
            key = f"docs/{sha[:2]}/{sha}.{ext}"
            if not store.has(key):
                meta = {"source-url": urllib.parse.quote(url, safe=":/?=&%"), "fetched": today}
                if ext == "pdf":
                    txt = subprocess.run(["pdftotext", "-layout", path, path + ".txt"], capture_output=True)
                    if txt.returncode == 0 and os.path.exists(path + ".txt"):
                        store.put(f"text/{sha[:2]}/{sha}.txt", path + ".txt", "text/plain; charset=utf-8", meta)
                store.put(key, path, ctype or "application/octet-stream", meta)
                stored += 1
                total += size
            manifest[url] = {"status": 200, "sha256": sha, "bytes": size, "type": ctype, "key": key, "fetched": today}
            for f in (path, path + ".txt"):
                if os.path.exists(f):
                    os.remove(f)
            time.sleep(0.5)
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=0, sort_keys=True)
    have = sum(1 for r in manifest.values() if r.get("status") == 200)
    print(f"archive: {done} fetched this run ({stored} new files, {total / 1e9:.2f} GB, {gone} already gone at the Town); "
          f"{have} of {len(sources())} cited links archived in total; {len(todo) - done} left in the queue")


if __name__ == "__main__":
    main()
