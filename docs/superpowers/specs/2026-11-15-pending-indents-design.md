# Pending Indents page (ODR) — design

Date: 2026-11-15

## Why

SAIL's plants run short of rakes. The app today sees only rakes that were supplied (loaded, in
transit, received). It cannot see demand that the Railways has not met. The FOIS page "ODR Wise Rake
Outstanding Details" lists pending indents, for SAIL and for other parties at the same sources.
Bringing it in shows where SAIL is waiting, for how long, and whether other parties are being
loaded at the same source in the meantime.

This is piece 1 of 3. Piece 2 (Out-Bound list from the plants) and piece 3 (SAIL vs Others page)
get their own designs later.

## Goals

- Store each ODR list sent from FOIS, for SAIL and other parties.
- One page, `/indents`, that answers:
  1. How many SAIL rakes are pending at each source, for which commodity, and how old?
  2. At the same source, how many indents of other parties are pending, and how many rakes were
     loaded there for SAIL and for others in the last 7 days?
  3. For each plant and commodity: pending indents, rakes in transit, rakes received per day.
  4. For steel going out: pending indents at each plant by wagon type.
- Excel and PDF download of the page, like the other pages.

## Not in this piece

- Days from indent to supply (needs some weeks of stored lists first).
- Automatic resend of the ODR list every 5 hours.
- Out-Bound list, loading-to-departure waits, the SAIL vs Others page.

## Must not happen

- An indent that is nearly supplied must not be shown as a pending rake.
- Other parties' indents must never be added into SAIL's numbers.
- A new ODR import must not change or delete the existing rake data.

## The ODR table as FOIS gives it

Headings: SR.NO., DVSN, STTNFROM, DEMAND NO., DEMAND DATE, DEMAND TIME, EXPD LDNG DATE, CNSR, CNSG,
GRUP RAKE CMDT, RAKE CMDT, TT, PC, PBF, VIA, STTNTO, INDENTED TYPE, INDENTED UNITS, INDENTED 8W,
OSTG UNITS, OSTG 8W, SUPPLIED UNITS, SUPPLIED TIME, DEMAND ID.

- A row with a SR.NO. starts an indent. A row with a blank SR.NO. is a second part of the indent
  above it (a second destination or wagon type); it carries its own RAKE CMDT, STTNTO, type and
  units, and the same DEMAND ID. Its blank fields are filled from the row above.
- DEMAND DATE is dd-mm-yy. SUPPLIED TIME is dd-mm-yyyy and is often blank.
- The sample file (15-11-2026) has 291 rows, 255 indents, all SAIL.

## Approaches considered

1. **A new Pending Indents page with its own table (chosen).** Keeps indents, which include steel
   going out and other parties, in one place, and the existing pages stay as they are.
2. Indent columns added to the Commodity Analysis page. Rejected: that page is already wide, it is
   organised by plant receipts, and steel indents and other parties' indents have no row there.
3. A one-off analysis of the CSV. Rejected: the value is in the daily picture and, later, in the
   history.

## Design

### Storage

New table `odr_indents`, one row per ODR row, every import kept as its own list with `imported_at`
(same pattern as `inbound_rakes`). Columns: the FOIS fields above, kept as FOIS shows them, plus
`demand_date` parsed to a date, and `part_no` (1 for the first row of an indent, 2 for the next).
The pages read only the latest list.

### Getting the data in

- `POST /api/odr`, same token and `{"columns", "rows"}` shape as `/api/inbound`. Requires STTNFROM
  and DEMAND ID. Blank fields of second-part rows are filled on the server.
- The Chrome extension recognises the ODR table on the open FOIS page and sends it with the same
  Send button. Extension version goes up.
- The `/indents` page also takes the downloaded CSV file, as a fallback and for the first load.

### Rules

- **SAIL indent:** CNSG is SAIL (same rule as `is_sail`), or CNSR is SAIL for steel leaving a plant.
- **Steel going out:** STTNFROM is one of the plants (BSPC, DSEY, HSPG, NHSB, BSCS, IISD, BCME) and
  the commodity group is IS. Everything else with consignee SAIL is raw material coming in.
- **Supplied, under loading:** an indent with a SUPPLIED TIME on any of its parts has its rake
  placed; FOIS still shows its wagons outstanding until loading is done. It is counted as
  "supplied", not as pending.
- **Pending rake:** any other indent counts as one pending rake when its outstanding units, over
  all its parts, are at least half of its indented units. Below that it is "part supplied" and
  shown in its own small count, not as pending.
- An indent is the run of rows from one filled SR.NO. to the next; rows are not grouped by
  DEMAND ID alone.
- **Age:** days from DEMAND DATE to the date of the list. Buckets: 0–2, 3–7, 8–15, over 15.
- Station and commodity names come from the existing mappings.

### The page `/indents`

Top line: date and time of the list; SAIL pending rakes coming in; SAIL pending rakes of steel
going out; oldest pending indent (source, date, days).

1. **Pending at each source** — one row per source and commodity:
   source | commodity | wagon types | SAIL pending | 0–2 | 3–7 | 8–15 | >15 | oldest (days) |
   others pending (party: count) | loaded here in last 7 days: SAIL | others.
   Loaded counts come from the stored all-India In-Bound lists, counted once per rake and loading
   time, the way the shared-source table does it. Rows where SAIL waits over 7 days while others
   were loaded are highlighted.
2. **Pipeline to each plant** — one row per plant (and pellet agent) and commodity:
   pending indents | in transit | received per day (30-day average) | received yesterday.
3. **Steel indents at each plant** — plant | wagon type | pending | age buckets | oldest.
4. **All pending indents** — the full list, sortable, with a party filter (SAIL / others / all).

A link to the page goes in the menu in `base.html`.

### Downloads

`/indents/report.xlsx` and `/indents/report.pdf`, with tables 1 to 3, built the way
`inbound_exports.py` builds its reports.

## Left to the builder

- How the extension tells the ODR table from the other FOIS tables (by its headings).
- Exact colours and column widths, following the existing pages.
- Tests: reading the sample CSV (291 rows → 255 indents), filling second-part rows, the
  pending-rake rule, age buckets, and SAIL vs others separation.
