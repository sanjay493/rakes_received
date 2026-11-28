# BOBSNM1 rake trips by Rake ID

Date: 28-11-2026. Status: revised, awaiting approval.

## Intent

Collect the trips (station to station movements) of SAIL's BOBSNM1 rakes, identified by Rake ID, for a
chosen period, and keep them in the dashboard database through the existing Chrome extension.

## Goals

- From a page of the extension, choose a period and Rake IDs, fetch their trips from FOIS ("Get RR" and
  the Rakes Received report) and send them to the dashboard.
- No report has to be opened by hand: a logged-in FOIS tab is enough.
- Sending the same data twice never duplicates a trip.

## Not in this version

- A dashboard page or download for viewing trips.
- Fetching on a schedule.
- The Dispatched Rakes report (its query has not been made to work).
- Building trips from the In-Bound lists already in `inbound_rakes`.
- Matching an RR trip with the received-report row for the same movement.
- Any change to `POST /api/rakes` or the existing dashboards.

## What was found (FOIS and the database, 28-11-2026)

### Get RR

- `POST /ecbs/RouterServlet` with `operation=query`, `suboperation=gwisgfr`, `txtTrxnFlag=A`,
  `txtCust=SAIL`, `txtRprtFlag=R`, `txtCntrId`, `txtAgreDtls`, `txtRakeId`, and empty
  `txtPerd`, `txtDateFrom`, `txtDateTo`.
- Agreement ID and Rake ID each filter the result, and either one is enough. With the agreement blank,
  `DMF 080423120400` returned the same 1,072 trips as with it. Another rake's agreement returned none.
  So the GPWIS list page is not needed.
- It returns the whole history, with no choice of dates (about 1.7 MB for 1,072 trips).
- The last table has 17 cells per trip: from, to, invoice no, invoice date, RR no, RR date, consignor,
  consignee, commodity, chargeable weight, distance, class, rate, rebate %, rebate amount, rake used by,
  rebate accountal head. No departure or arrival times.
- No trips reads "NO RECORDS FOUND FOR RR".
- Of the 29 BOBSNM1 Rake IDs with consignee SAIL in `inbound_rakes`, tried with a blank agreement, 4
  returned trips (the 4 in the GPWIS list): `DMF 080423120400`, `DMF 100323132718`, `MXA 130225133310`,
  `MXA 170625120929`.

### Rakes Received

- `GET /ecbs/JSP/RcvdRakes.jsp` gives the query form. Its `txtSttnTo` list has the login's stations and
  an `ALL` entry.
- `POST /ecbs/RouterServlet` with `operation=query`, `suboperation=rcvdrakes`, `zonesttnflag=S`,
  `txtSttnTo` (the entry's value), `txtLocn` (the same entry's inner HTML; without it no table comes
  back), `optSelect=P`, `txtDate`, `txtDateTo` (dd-mm-yyyy), `txtSttnFr=on`, empty `txtSttnFrom` and
  `txtCmdt`, `txtRakeType=BOBSNM1`, `optLE=A` (loaded and empty).
- The result is `table#example` with the columns the extension already reads, including RAKE ID.
- 01-11 to 28-11-2026, all stations: 166 trips of 9 rakes (159 loaded to NHSB, matching the report on
  screen, and 7 empty to BNDM).
- August, September and October 2026 returned 100, 79 and 150 trips. January 2026 returned a table headed
  "NO RECORDS FOUND", so FOIS does not seem to offer all past periods.

### Database

- `rakes` has no Rake ID column: the import drops it.
- Rake IDs can contain a space. They are compared with runs of spaces collapsed and posted to FOIS
  exactly as FOIS gives them.

## Approaches

| | How | Trade-off |
|---|---|---|
| **A (chosen)** | Run inside the logged-in FOIS tab | No password or session copying; needs FOIS open |
| B | Python on saved report files | Re-runnable, but every report is saved by hand |
| C | Python signing in to FOIS itself | Could be scheduled, but needs the login session copied out |

The user chose A, delivered in the existing extension and sending to the database "as done in
`rakes_received`": a POST with the API token to `http://127.0.0.1:5000`. The user then agreed that the
extension fetches the Rakes Received report itself.

## Design

### Extension (version 1.8.0)

- The popup gets a **Rake trips** button that opens `trips.html` in its own tab. A popup closes when you
  click elsewhere, which would stop a fetch part way.
- The page has: API token (the saved one), From and To dates (both required), and which rakes: **All
  BOBSNM1 rakes** (the default) or ticked Rake IDs. The IDs listed are the dashboard's SAIL BOBSNM1 Rake
  IDs, plus a box to add others.
- **Fetch and send** runs the requests inside an open `fois.indianrail.gov.in/ecbs` tab, one at a time
  with a 1.5 s pause. The FOIS page on screen doesn't change. With no such tab, the page says so.
  1. Rakes Received for all stations, one query per calendar month of the period. With ticked IDs, only
     their rows are kept. Each month's rows are sent as they arrive.
  2. Get RR with a blank agreement for each chosen rake. "All" means the dashboard's list, added IDs and
     any new ID seen in step 1. Trips with an invoice date in the period (both days included) are sent.
- The page shows each month's and each rake's result: trips new and updated, none, or the error. At the
  end it lists the chosen rakes that got no trips from either source.
- It stops after 3 failures in a row. A response that is neither a report nor "NO RECORDS FOUND" (logged
  out, layout changed) is an error, never "no trips".

### Dashboard

New table `rake_trips`: `trip_key` (unique), `rake_id`, `source` (`rr` or `received`), `rake_name`,
`rake_type`, `units`, `sttn_from`, `sttn_to`, `loaded_empty`, `trip_date`, `dispatched_time`,
`received_time`, `invoice_no`, `invoice_date`, `rr_no`, `rr_date`, `cnsr`, `cnsg`, `cmdt`,
`chargeable_wt`, `distance_km`, `freight_class`, `rate`, `rebate_pct`, `rebate_amt`, `used_by`,
`rebate_head`, `imported_at`.

- RR trip key: rake ID, from, invoice no, invoice date, RR no, RR date. `trip_date` is the invoice date.
- Received trip key: rake ID, from, to, dispatched time (received time if that is blank). `trip_date` is
  the dispatched date, or the received date if blank.
- A trip sent again updates its row.

Endpoints, both checking the API token and exempt from the site password like the other imports:

- `GET /api/rake_ids`: SAIL BOBSNM1 Rake IDs from `inbound_rakes` and `rake_trips`.
- `POST /api/rake_trips`: `{"source": "rr", "rake_id": ..., "rows": [[17 cells], ...]}` or
  `{"source": "received", "columns": [...], "rows": [...]}`. Rows that can't be read are counted and
  reported.

## Calls made by the builder (correct any)

- An RR row with accountal head `ZERO FREIGHT RR` and no commodity is stored as empty (E), others as
  loaded (L). This is inferred from the rows seen; the raw head is stored too.
- Trips from the two sources are kept as separate rows, told apart by `source`, so counting trips means
  choosing one source or allowing for overlap.
- The period means received date for Rakes Received rows and invoice date for RR rows.
- Received rows are not also written to `rakes`.

## Limits

- Rakes Received covers only arrivals at the login's stations. Empty departures and trips to other plants
  appear only for rakes with RR data.
- Of the 29 known rakes, 11 had trips from at least one source in the checks above (4 from Get RR, 9 from
  November's Rakes Received, 2 in both). The other 18 are expected to get none.

## Testing

- Pytest, test first, for both endpoints: token, both sources, duplicates, updates, space-containing IDs,
  unreadable rows, and that `rakes` and `inbound_rakes` are untouched.
- The extension has no JavaScript tests: check by hand against live FOIS that November's received count
  and one rake's RR count for a period match what FOIS shows.
- `db_sync.py` copies the whole database, so the new table is backed up without changes.
