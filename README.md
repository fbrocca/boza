# BOZA: Mount Pleasant Zoning Map

Every property-specific zoning action in the Town of Mount Pleasant, SC since
2017, on a map:

- **Board of Zoning Appeals**: variances, special exceptions, appeals.
- **Rezoning & planning**: rezonings, annexations, PD amendments, sketch plans
  and plats. Each case is followed from the Planning Commission, through the
  Planning Committee of Council, to the Town Council readings, and gets a
  final status (Adopted by Council, Denied by Council, Passed first reading, or
  recommendation only).
- **Design review**: Historic District Preservation Commission (Old Village
  certificates of appropriateness, demolitions, historic designations, staff
  approvals) and Design Review Board (commercial and multi-family
  architecture). These boards decide on their own; items rarely carry case
  numbers, so each lot's items are grouped into one project timeline.

Draw a boundary on the map (Draw button, then drag a freehand shape) to see only
the cases inside it; the boundary is kept in the URL (`?area=`), so the link
can be shared. Click a property to see every case on it, with a timeline of each step, the
minutes text, a link to the exact page of the minutes PDF, and links to the
case documents the Town published with the agenda (application, staff report,
correspondence, presentation).

**Site:** https://fbrocca.github.io/boza/

## Plan a request (`plan.html`)

Enter an address (or TMS) and what you want to do. The page looks up the lot live
(Charleston County address and parcel services, Town of Mount Pleasant zoning
services), then shows: current zoning, overlays, height limit and Comprehensive
Plan designation; the lot's case history and cases within 500 ft; which
application is likely needed (variance vs rezoning vs subdivision, plus Historic
District / Design Review Board review where an overlay or district applies); how
comparable requests fared, with sample sizes; and how to strengthen an
application, each point backed by counts from `data/case-facts.json` and links to
real cases and their application documents. Nothing is scored or predicted, and
nothing entered is stored.

## What's here

| Path | What |
|---|---|
| `index.html`, `app.js`, `style.css` | The map page. Static, no build step. Leaflet is vendored in `vendor/`. |
| `minutes/` | All BOZA minutes PDFs (`YYYY-MM-DD.pdf`), with `index.csv` and a README listing. |
| `sources/pc`, `sources/pcom`, `sources/council`, `sources/hdpc`, `sources/drb` | Text of every Planning Commission, Planning Committee, Town Council, Historic District Preservation Commission and Design Review Board minutes (`YYYY-MM-DD-<id>.txt`). Only the text is kept because these PDFs total ~2 GB; the map links to the Town's copy. |
| `data/cases.json` | Every BOZA hearing extracted from the minutes. |
| `data/planning.json` | Every Planning Commission case with its linked Committee and Council events. |
| `data/design.json` | Every HDPC / DRB project, grouped by parcel, with its review timeline. |
| `data/properties.json` | All cases grouped by parcel, with location and lot outline. What the map loads. |
| `data/minutes-text.json` | Minutes text per event, fetched when someone opens it. |
| `data/agenda-docs.json` | Links to case documents found in each BOZA and Planning Commission agenda, assigned to cases. Links only; the documents stay on the Town's site. |
| `data/parcels.json`, `data/geocode-cache.json` | Cached county parcel and address lookups. |
| `data/zoning.json` | Zoning district, overlay districts, height limit and Comprehensive Plan future land use per parcel, from the Town's map server (`tools/zoning.py`). |
| `data/case-facts.sqlite` | The same facts as one SQLite table, for ad-hoc queries. |
| `data/case-facts.json` | Structured facts for 684 BOZA and rezoning cases, read from the minutes with an AI-assisted coding sheet and checked against them: type of relief, size of request, arguments made, opposition, vote, stated reasons, outcome, and a one-line summary. Where a fact sheet states the outcome, it replaces the automatic guess on the map. New cases need coding (see below). |
| `data/geocode-overrides.json` | Hand-placed pins for locations that can't be found automatically. |
| `tools/` | The pipeline (below). |

## Pipeline

```bash
python3 tools/fetch_minutes.py   # download new minutes from the Town's Agenda Center
python3 tools/agenda_docs.py     # read new agendas for links to case documents
tools/build.sh --geocode         # extract cases, look up parcels/addresses, rebuild data/
```

1. `fetch_minutes.py` scrapes the Town's CivicPlus Agenda Center and pulls
   any new minutes: BOZA PDFs into `minutes/`, and the text of Planning
   Commission, Planning Committee and Town Council minutes into `sources/`.
2. `pdftotext -layout` turns each PDF into text. All have a text layer.
3. `extract_cases.py` splits the minutes into cases (`Case V-06-25, 683 Linns
   Point, TMS# 559-02-00-233, Request for ...`). It infers each decision from
   the last motion that didn't fail.
4. `extract_planning.py` pulls every Planning Commission item tied to a
   parcel, then links Planning Committee items and Town Council ordinance
   readings to it: by case number, else TMS, else street address, else street
   name plus zoning districts, within a date window. Readings of one ordinance
   are tied by ordinance number.
5. `parcels.py` fetches each lot outline by TMS from Charleston County GIS,
   plus the county's street address for it.
6. `geocode.py` matches addresses against county address points, with the
   US Census geocoder as fallback.
7. `build_data.py` groups hearings by parcel and picks a location: a manual
   pin, then the county parcel if it's within 300 m of the address point,
   then the address point (a mismatch usually means a TMS typo in the
   minutes), then the Census estimate.

Needs `pdftotext` (poppler-utils) and Python 3. No third-party packages.

### Case documents

`agenda_docs.py` reads each agenda's hyperlinks (`pdftohtml -xml`) and assigns
each document to a case: by the case number in the document's file name, else
in the link text, else the case number inside the same agenda item. A staff
report named only by board and date covers the whole meeting and is shown on
every case that night. Links in items with no case number (street names, text
amendments) and general links (bylaws, code, GIS) are dropped. The map links to
the Town's copy; nothing is downloaded, stored or extracted from the documents,
including applicant contact details.

### Case facts

`data/case-facts.json` was produced by reading every 2017–2026 BOZA case and every
rezoning / annexation / PD amendment against a fixed coding sheet, with verbatim
evidence quotes checked against the minutes. Cases added by the monthly update are
not coded yet: they show the automatic outcome until coded.

## Automation

`.github/workflows/site.yml` publishes the site to GitHub Pages on every push
to `main`. On the 5th of each month it also downloads new minutes, rebuilds
the data, commits the changes, and redeploys. Run it by hand from the Actions
tab ("Update and publish" → Run workflow).

## Accuracy

The minutes are the official record. Every event links to its source page.

- Decisions are inferred from motion wording, not entered by hand. A spot
  check of 8 random hearings matched the minutes after one fix. About 9% show
  "See minutes" (items heard together with another case, deadlocks).
- 599 of 630 properties are mapped, mostly on the county parcel. The rest
  have no street number and a retired or missing TMS, so they're listed as
  "not on map". Add them to `data/geocode-overrides.json` to pin them.
- Coverage: 457 BOZA cases (548 hearings) and 312 Planning Commission cases.
  173 of the 223 rezonings, annexations and PD amendments are linked to at
  least one Town Council reading. The rest were withdrawn, are pending, or
  couldn't be matched automatically (shown as "Recommended approval/denial").
- Rezoning outcomes come from Council motion wording ("Motion to deny...
  carried", "SIGNED, SEALED and DELIVERED", "[Deferred]"). Committee and
  Council matches are automatic; a few cases may be missing a step or carry a
  related companion item (e.g. a Comprehensive Plan amendment for the same
  parcel). "Recommended approval/denial" means no Council decision was found.
- Rezonings are not heard by the Board of Zoning Appeals. A property can have
  cases on both sides.

Sources: Town of Mount Pleasant Agenda Center (public records), Charleston
County GIS, US Census Geocoder, OpenStreetMap, Esri World Imagery.
