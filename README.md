# The Zoning Record · Mount Pleasant

Every property-specific zoning action in the Town of Mount Pleasant, SC since
2017, on a map, with a page per property, hearing and board:

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

**Site:** https://zoningrecord.com/mount-pleasant/ (map at `/map/`).

## The Zoning Record (landing page)

`index.html` (with `landing.css`, `landing.js`) is the front door: search (which
opens the map at the result), a live docket of items on posted agendas, a survey
drawing of the lots around the Old Village and Coleman Boulevard that went before a
Town board (green: on an upcoming agenda), live counts and the method. The map
lives at `map/` (its page carries `<base href="../">`, so its paths are unchanged);
links shared before the landing page existed (`#property`, `?area=`, `?q=`) are
forwarded there. `tools/landing_data.py` writes `data/summary.json` and `plat.svg`
at deploy.

## Pages for search engines and AI assistants (`tools/static_pages.py`)

The site lives at https://zoningrecord.com/mount-pleasant/. The map is a JavaScript app, which most
crawlers and AI assistants don't run, so the deploy also writes the record as plain HTML:

- `p/<address>-<parcel digits>/`: one page per property with every case, outcome, hearing and source link.
  The slug never changes as cases are added; the map's "Permanent page" button links to it.
- `m/<date>-<board>/`: one page per hearing, with what was heard and decided.
- `g/<board>/`: what each board decides, outcomes on record, and the questions it asks.
- `p/`, `m/`, `g/`: indexes. At the domain root: `sitemap.xml`, `robots.txt` (search and AI crawlers
  allowed) and `llms.txt`.

Pages carry canonical URLs and schema.org data (Place, Event, Article, BreadcrumbList). Nothing is
committed; everything is rebuilt on every deploy, so new cases appear as soon as the data updates.
The root `index.html` forwards to `/mount-pleasant/`; the root `404.html` rewrites links shared
before the move (including `fabiobrocca.tech/boza/...`), keeping `#property` and `?q=`.

## Document archive (`tools/archive_docs.py`)

The Town removes documents from its website over time: of the 2017-2018 case documents, 73 were gone
by November 2026 and only one had ever been saved by the Wayback Machine. Every document, minutes
file and agenda the record cites is now copied to a private S3 bucket
(`zoningrecord-archive-272106374268`, us-east-1) the first time the pipeline sees it:

- `docs/<sha256[:2]>/<sha256>.<ext>`: the file, stored by content hash; `text/.../<sha256>.txt`: its text.
- `data/archive-manifest.json` (public, no content): source URL to hash, size, type and fetch date, or the
  HTTP status when the Town no longer has it.
- Runs in the daily job with a 40-minute budget, so the backlog (about 4,400 links, roughly 27 GB)
  fills over a few nights. Versioned bucket, cheaper storage tier after 30 days.
- No stored keys: the job assumes the IAM role `zoningrecord-archiver` through GitHub's OIDC; only this
  repository's `main` branch can, and the role can read and write the bucket but not delete.
- The bucket stays private (applications carry applicants' names and phone numbers). Copies are not
  republished; `tools/check_links.py` links removed documents to a Wayback Machine copy when one exists.

## Alerts (`alerts/lambda_function.py`, `tools/send_alerts.py`)

Email alerts when the Town posts zoning items for a neighborhood a subscriber chose (or all of Mount Pleasant).

- **Signup:** the "Get alerts" dialog posts to an AWS Lambda function URL (`alerts/lambda_function.py`, deployed by
  hand; code in this repo). Subscribers are stored in DynamoDB `zoningrecord-alerts` (us-east-1), never in this repo.
  Double opt-in: nothing is sent until the address is confirmed. One confirmation per address per 10 minutes; a
  hidden honeypot field drops bots. Unsubscribing deletes the record.
- **Sending:** `tools/send_alerts.py` runs in the daily job after the agendas update. One email per subscriber with
  only items they haven't been sent, via Amazon SES from `alerts@zoningrecord.com`, with a one-click unsubscribe
  link and List-Unsubscribe headers. It also retries confirmations that couldn't be sent at signup.
- **Credentials:** the job's IAM role (GitHub OIDC) may scan and update the table and send from that address only.

## Coming up

`tools/upcoming.py` reads the agendas the Town has posted for meetings that
haven't happened yet (about a week ahead) for Zoning Appeals, Planning
Commission, Planning Committee, Town Council, Historic District and Design
Review, and writes `data/upcoming.json`: meeting date and time, comment
deadline and address where the agenda gives them, and each zoning item (case
number, address / TMS, request). Committee and Council agendas keep only
zoning-related items. Items are pinned from our own properties (same case or
TMS) or the county parcel layer. The map shows a "Coming up" tab (opened by
default when agendas are posted), blue date pins, and an "On the agenda" note on
the property page.

## Neighborhoods (`n/`)

`tools/neighborhoods.py` assigns every mapped property to a neighborhood using the
Town's GIS: the Old Village Historic District, the five Neighborhood Preservation
Overlay neighborhoods, the 959 subdivisions with recorded plats, then the
mixed-use and Ten Mile overlays (first match wins; the rest are "Other areas").
It writes `data/neighborhoods.json` (names, counts, assignment) and
`data/neighborhood-shapes.json` (simplified boundaries). Neighborhoods with 3+
cases get a page: what's coming up there (with calendar and how to comment),
approval rates against the town-wide figure with sample sizes, cases per year by
outcome, cases by type, a map, and recent decisions. `tools/hood_pages.py` writes
one static page per neighborhood at deploy (`n/<slug>/`), so shared links preview
with the neighborhood's name.

## Meeting videos, feeds, map layers, development pipeline

- **Videos** (`tools/videos.py`, daily): the Town's YouTube channel feed and Open
  Publica's meeting list (openpublica.com: free API, no key, independent machine
  transcripts of the Town's videos from Aug 2025) are matched by date and body to
  Town Council, Planning Committee and Planning Commission meetings
  (`data/videos.json`). Where a transcript exists, each case heard that day is
  located by house number + street, case number or project name, and the densest
  five minutes of mentions gives a "Watch from h:mm:ss" link
  (`data/video-moments.json`; approximate; 26 of 80 hearings at the 17 transcribed
  meetings so far). Zoning Appeals, Historic District and Design Review meetings
  are not recorded on the channel; the minutes PDFs carry no recording links.
- **Feeds** (`tools/feeds.py`, at deploy): `feeds/meetings.ics` (subscribable
  calendar of posted zoning meetings) and `feeds/agenda.xml` (RSS, one entry per
  agenda item), from `data/upcoming.json`.
- **Map layers**: zoning districts, FEMA 2021 flood zones and future land use,
  drawn by the Town's map server for the current view, with its legend. Zoning
  draws at 1:12,000 and closer (map zoom 16+).
- **Development pipeline**: counts of approved rezonings, annexations, PD
  amendments and subdivisions by year (neighborhood index) and per neighborhood.
  Lots or units are shown per case where the request or minutes state them
  (`c.units`, about 40 of 175 approvals); no totals, because counts are partial and
  parcel acreage overstates phased projects.
- **Frequently raised questions** (`tools/faq_build.py`): 4,483 question and
  concern sentences were taken from the minutes (all six boards, 2017–2026) and
  coded by AI readers against a fixed sheet: who raised it (board member,
  resident, applicant, staff), topic, and a short restated question without names,
  addresses or case numbers (`data/questions-coded.json`, not published). The
  Plan page shows what board members asked most often at hearings of the same
  type; neighborhood pages show what residents raised. Counts are hearings.
  Minutes record questions selectively, so counts understate frequency. New
  minutes are not coded automatically.
- **Staff recommendations** are not extracted: sampled staff reports state facts
  and code comments but no approve / deny recommendation.

## Sales (`tools/sales.py`)

The most recent recorded transfer and the county appraisal for each parcel, from
Charleston County's ProVal parcel map service (assessor's table joined to
parcels): price, sale and recorded dates, deed book-page, land / building /
total appraisal, property class. Owner names and mailing addresses in the same
table are not kept. Transfers under $1,000 (trusts, family, correction deeds)
are flagged nominal and never shown as a price. Refreshed in full by
`tools/build.sh --geocode`. Property pages show "Last sold"; the Plan page
queries the same service live for sales within ¼ mile in the last 3 years, same
property class. Only the latest transfer per parcel is in this service, so each
monthly run adds what it sees to a per-parcel `history`: a sales history builds
up from November 2026. Property pages note when a market sale followed an
approval on the lot within 3 years. The county Auditor's record-card site has
transfers for 1991 to October 2011 only (not used: no zoning cases that early);
the county public-access portal, which covers later years, disallows automated
access by Claude in its robots.txt and is not used.

## Report an error, calendar, how to comment (`shared.js`)

Property and neighborhood pages have a "Report an error" form. There is no
backend: reports are recorded as private GoatCounter events (`report/<property>`,
with the visitor's text in the title), visible only on the GoatCounter dashboard.
Reports from browsers that block GoatCounter are not sent, and the visitor is told
so. Coming-up meetings offer Google Calendar and .ics links and the ways to
comment that the agenda states (written deadline and address, public comment).

## Plan a request (`plan.html`)

Enter an address (or TMS) and what you want to do. The page looks up the lot live
(Charleston County address and parcel services, Town of Mount Pleasant zoning
services), then shows: current zoning, overlays, height limit and Comprehensive
Plan designation; the lot's case history and cases within 500 ft; which
application is likely needed (variance vs rezoning vs subdivision, plus Historic
District / Design Review Board review where an overlay or district applies); how
comparable requests fared, with sample sizes; and how to strengthen an
application, each point backed by counts from the case facts in `data/properties.json` and links to
real cases and their application documents. Nothing is scored or predicted, and
nothing entered is stored.

The "What the current code requires" panel reads `data/code-standards.json`,
transcribed by hand from Zoning Code Chapter 156 as rewritten in 2025 (adopted
1-14-25, effective 5-1-25, amendments through 4-17-26): district lot, setback,
coverage, height and density standards; accessory building limits (§ 156.424);
NP-OD and OV-HD overlay rules (§ 156.203, § 156.218); and the 20% setback
reduction for nonconforming lots (§ 156.1525). It compares the user's request to
the requirement and flags when most comparables were decided under the old code.
PD and some special districts are not tabulated. Update the JSON when the code
is amended.

## What's here

| Path | What |
|---|---|
| `index.html`, `landing.css`, `landing.js` | The landing page. |
| `map/index.html`, `app.js`, `style.css`, `shared.js` | The map page (`<base href="../">`). Static, no build step. Leaflet is vendored in `vendor/`. |
| `plan.html`/`plan.js`/`plan.css`, `hood.html`/`hood.js`/`hood.css`, `pages.css` | Plan a request; neighborhood pages (template for `tools/hood_pages.py`); static property, meeting and guide pages. |
| `root/` | Domain-root redirect and 404 pages. |
| `alerts/` | The alerts signup function deployed to AWS Lambda. |
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
| `data/case-facts.sqlite` | The same facts as one SQLite table, for ad-hoc queries. Not regenerated: refresh by hand if `case-facts.json` changes. |
| `data/upcoming.json`, `data/videos.json`, `data/video-moments.json` | Posted agendas for upcoming meetings; meeting recordings and the moment each case comes up. |
| `data/sales.json`, `data/code-standards.json`, `data/faq.json`, `data/questions-coded.json`, `data/neighborhoods.json`, `data/neighborhood-shapes.json` | Recorded sales; current code standards; questions boards and residents raise (coded, and summarised); neighborhood assignment and outlines. |
| `data/status-corrections.json`, `data/dead-docs.json`, `data/archive-manifest.json` | Outcomes read by hand where the parser found none (with quotes); Town links that now 404; the S3 document archive index. |
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

Needs `pdftotext` (poppler-utils) and Python 3. The extraction and build use the standard library only; `check_links.py`, `archive_docs.py` and `send_alerts.py` need `requests` and `boto3`.

### Case documents

`agenda_docs.py` reads each agenda's hyperlinks (`pdftohtml -xml`) and assigns
each document to a case: by the case number in the document's file name, else
in the link text, else the case number inside the same agenda item. A staff
report named only by board and date covers the whole meeting and is shown on
every case that night. Links in items with no case number (street names, text
amendments) and general links (bylaws, code, GIS) are dropped. The map links to
the Town's copy. A private copy of every document is kept in S3 (see Document archive); nothing from the documents, including applicant contact details, is published.

### Case facts

`data/case-facts.json` was produced by reading every 2017–2026 BOZA case and every
rezoning / annexation / PD amendment against a fixed coding sheet, with verbatim
evidence quotes checked against the minutes. Cases added by the monthly update are
not coded yet: they show the automatic outcome until coded.

## Automation

`.github/workflows/site.yml` publishes the site to GitHub Pages on every push
to `main`. Every day it refreshes posted agendas and meeting videos, sends alerts,
archives new Town documents to S3, commits data changes and redeploys. On the 5th
of each month it also downloads new minutes, checks every cited link, rebuilds the
data and regenerates the pages. Running it by hand from the Actions tab ("Update and
publish" → Run workflow) does the full rebuild unless "rebuild" is unticked.

## Accuracy

The minutes are the official record. Every event links to its source page.

- Decisions are inferred from motion wording, not entered by hand. A spot
  check of 8 random hearings matched the minutes after one fix. Cases the parser
  couldn't settle were read against the minutes (`data/status-corrections.json`);
  5 of 1649 still show "See minutes".
- 1139 of 1183 properties are mapped, mostly on the county parcel. The rest
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
