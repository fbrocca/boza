"""Most recent recorded sale and county appraisal per parcel, from Charleston County.

    python3 tools/sales.py <data/sales.json> <data/parcels.json>

Source: Charleston County ProVal parcel map service (assessor's CAMA table joined to
parcels). It holds only the latest recorded transfer per parcel, so this is "last
sold", not a sale history. Refreshed in full on every run (about 15 requests).

Kept: sale price, document and recorded dates, deed book-page, land / building /
total appraisal, property class. Not kept: owner names and mailing addresses, which
are in the same table.
A recorded price under $1,000 is a nominal transfer (trust, family, correction deed),
flagged "nominal" so it is never shown as a market price.
"""
import datetime
import json
import sys
import time
import urllib.parse
import urllib.request

URL = "https://gisccapps.charlestoncounty.org/arcgis/rest/services/ProVal/ParcelMap/MapServer/0/query"
FIELDS = ["PID", "SALE_PRICE", "RECORDED_DATE", "DOC_DATE", "DEED_BOOK_PAGE", "LAND_APPR", "IMP_APPR", "APPRAISAL", "CLASS_CODE"]
QUAL = {f: ("SDE.P_POLY_PARCEL." if f == "PID" else "SDE.CAMA.") + f for f in FIELDS}
NOMINAL = 1000


def get(params, tries=4):
    q = urllib.parse.urlencode({**params, "f": "json"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(URL + "?" + q, timeout=90) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d.get("features", [])
        except Exception as e:
            if i == tries - 1:
                print("sales lookup failed:", e, file=sys.stderr)
                return None
            time.sleep(3 * (i + 1))


def day(ms):
    if not isinstance(ms, (int, float)):
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date().isoformat()


def main(out_path, parcels_path):
    tms = sorted(t for t, v in json.load(open(parcels_path)).items() if v)
    out, failed = {}, 0
    for i in range(0, len(tms), 80):
        pids = [t.replace("-", "") for t in tms[i:i + 80]]
        feats = get({"where": QUAL["PID"] + " IN (" + ",".join(f"'{p}'" for p in pids) + ")",
                     "outFields": ",".join(QUAL.values()), "returnGeometry": "false"})
        if feats is None:
            failed += len(pids)
            continue
        for f in feats:
            a = {k.split(".")[-1]: v for k, v in f["attributes"].items()}
            pid = a["PID"]
            t = f"{pid[:3]}-{pid[3:5]}-{pid[5:7]}-{pid[7:]}"
            price = a.get("SALE_PRICE")
            rec = {
                "price": round(price) if isinstance(price, (int, float)) else None,
                "date": day(a.get("DOC_DATE")) or day(a.get("RECORDED_DATE")),
                "recorded": day(a.get("RECORDED_DATE")),
                "deed": (a.get("DEED_BOOK_PAGE") or "").strip() or None,
                "land": a.get("LAND_APPR"), "building": a.get("IMP_APPR"), "appraisal": a.get("APPRAISAL"),
                "class": (a.get("CLASS_CODE") or "").strip() or None,
            }
            rec["nominal"] = rec["price"] is not None and rec["price"] < NOMINAL
            out[t] = {k: v for k, v in rec.items() if v not in (None, "")}
    if failed and not out:
        sys.exit("sales: county service unavailable; keeping the previous file")
    json.dump(dict(sorted(out.items())), open(out_path, "w"), indent=1)
    market = sum(1 for v in out.values() if v.get("price") and not v.get("nominal"))
    print(f"sales: {len(out)}/{len(tms)} parcels; {market} with a market price; {failed} not looked up")


if __name__ == "__main__":
    main(*sys.argv[1:])
