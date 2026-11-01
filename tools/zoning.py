"""Zoning facts per parcel from the Town of Mount Pleasant's map server.

    python3 tools/zoning.py <data/zoning.json> <data/parcels.json>

For each parcel (TMS) in parcels.json:
  zoning   district (MPSC_Zoning_New layer 2, by PARCEL_ID), and whether split-zoned
  overlays overlay districts at the lot's pin (layer 0), e.g. NP-OD, VSP-OD
  height   height limit and its note (MPSC_Height_New layer 0)
  flu      Comprehensive Plan future land use (MPSC_Land_Use_New layer 3)
Results are cached; delete an entry to refresh it.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://maps.tompsc.com/arcgis/rest/services/Parcel_Search_New"


def get(url, params, tries=4):
    q = urllib.parse.urlencode({**params, "f": "json"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(url + "?" + q, timeout=60) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d.get("features", [])
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(2 * (i + 1))


def at_point(layer, lat, lng, fields):
    return get(f"{BASE}/{layer}/query", {
        "geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": fields, "returnGeometry": "false"})


def point_facts(item):
    tms, loc = item
    ov = at_point("MPSC_Zoning_New/MapServer/0", loc["lat"], loc["lng"], "NAME,LABEL,LINK")
    ht = at_point("MPSC_Height_New/MapServer/0", loc["lat"], loc["lng"], "Height,Notes")
    fl = at_point("MPSC_Land_Use_New/MapServer/3", loc["lat"], loc["lng"], "New_FLU")
    if ov is None or ht is None or fl is None:
        return tms, None  # retry next run
    return tms, {
        "overlays": [{k: v for k, v in {"name": f["attributes"].get("NAME"), "label": f["attributes"].get("LABEL"),
                                        "link": f["attributes"].get("LINK")}.items() if v} for f in ov],
        "height": ht[0]["attributes"].get("Height") if ht else None,
        "height_note": ht[0]["attributes"].get("Notes") if ht else None,
        "flu": fl[0]["attributes"].get("New_FLU") if fl else None,
    }


def main(out_path, parcels_path):
    parcels = {t: v for t, v in json.load(open(parcels_path)).items() if v}
    cache = json.load(open(out_path)) if os.path.exists(out_path) else {}
    todo = [t for t in parcels if t not in cache]
    print(f"{len(todo)} parcels to look up ({len(cache)} cached)")
    zoning = {}
    for i in range(0, len(todo), 80):
        pids = [t.replace("-", "") for t in todo[i:i + 80]]
        feats = get(f"{BASE}/MPSC_Zoning_New/MapServer/2/query", {
            "where": "PARCEL_ID IN (" + ",".join(f"'{p}'" for p in pids) + ")",
            "outFields": "PARCEL_ID,ZONINGVALU,SPLITZONED,LINK", "returnGeometry": "false"}) or []
        for f in feats:
            a = f["attributes"]
            zoning.setdefault(a["PARCEL_ID"], []).append(a)
    with ThreadPoolExecutor(6) as pool:
        for tms, facts in pool.map(point_facts, [(t, parcels[t]) for t in todo]):
            if facts is None:
                continue
            z = zoning.get(tms.replace("-", ""), [])
            facts["zoning"] = sorted({a["ZONINGVALU"] for a in z if a.get("ZONINGVALU")}) or None
            facts["split"] = any((a.get("SPLITZONED") or "").lower() == "yes" for a in z) or len(facts["zoning"] or []) > 1
            facts["zoning_link"] = next((a["LINK"] for a in z if a.get("LINK")), None)
            cache[tms] = facts
    json.dump(dict(sorted(cache.items())), open(out_path, "w"), indent=1, ensure_ascii=False)
    print(f"zoning: {sum(1 for v in cache.values() if v.get('zoning'))}/{len(cache)} parcels with a district")


if __name__ == "__main__":
    main(*sys.argv[1:])
