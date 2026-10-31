# BOZA: Mount Pleasant Zoning Appeals Map

Every property heard by the Town of Mount Pleasant, SC Board of Zoning Appeals
since 2017, on a map. Click a property to see each hearing: case number,
request, decision, the minutes text, and a link to the exact page of the
minutes PDF.

**Site:** https://fbrocca.github.io/boza/

## What's here

| Path | What |
|---|---|
| `index.html`, `app.js`, `style.css` | The map page. Static, no build step. Leaflet is vendored in `vendor/`. |
| `minutes/` | All BOZA minutes PDFs (`YYYY-MM-DD.pdf`), with `index.csv` and a README listing. |
| `data/cases.json` | Every hearing extracted from the minutes. This is the dataset. |
| `data/properties.json` | Hearings grouped by parcel, with location and lot outline. What the map loads. |
| `data/minutes-text.json` | Minutes text per hearing, fetched when someone opens it. |
| `data/parcels.json`, `data/geocode-cache.json` | Cached county parcel and address lookups. |
| `data/geocode-overrides.json` | Hand-placed pins for locations that can't be found automatically. |
| `tools/` | The pipeline (below). |

## Pipeline

```bash
python3 tools/fetch_minutes.py   # download new minutes from the Town's Agenda Center
tools/build.sh --geocode         # extract cases, look up parcels/addresses, rebuild data/
```

1. `fetch_minutes.py` scrapes the Town's CivicPlus Agenda Center (Board of
   Zoning Appeals) and downloads any minutes not already in `minutes/`.
2. `pdftotext -layout` turns each PDF into text. All have a text layer.
3. `extract_cases.py` splits the minutes into cases (`Case V-06-25, 683 Linns
   Point, TMS# 559-02-00-233, Request for ...`). It infers each decision from
   the last motion that didn't fail.
4. `parcels.py` fetches each lot outline by TMS from Charleston County GIS.
5. `geocode.py` matches addresses against county address points, with the
   US Census geocoder as fallback.
6. `build_data.py` groups hearings by parcel and picks a location: a manual
   pin, then the county parcel if it's within 300 m of the address point,
   then the address point (a mismatch usually means a TMS typo in the
   minutes), then the Census estimate.

Needs `pdftotext` (poppler-utils) and Python 3. No third-party packages.

## Automation

`.github/workflows/site.yml` publishes the site to GitHub Pages on every push
to `main`. On the 5th of each month it also downloads new minutes, rebuilds
the data, commits the changes, and redeploys. Run it by hand from the Actions
tab ("Update and publish" → Run workflow).

## Accuracy

- Decisions are inferred from motion wording, not entered by hand. A spot
  check of 8 random hearings matched the minutes after one fix. About 9% show
  "See minutes" (items heard together with another case, deadlocks).
- 391 of 398 properties are mapped (373 on the county parcel). The rest have
  no street number and a retired TMS, so they're listed as "not on map". Add
  them to `data/geocode-overrides.json` to pin them.
- The minutes are the official record. Every hearing links to its source page.

Sources: Town of Mount Pleasant Agenda Center (public records), Charleston
County GIS, US Census Geocoder, OpenStreetMap, Esri World Imagery.
