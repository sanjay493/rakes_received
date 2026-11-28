# BOBSNM1 loading counts and rake list on /bobsnm1

Date: 28-11-2026. Status: awaiting approval.

## Intent

Show on `/bobsnm1` all `BOBSNM1` rakes and how many were loaded, date wise and consigner (`CNSR`) wise.

## Goals

- A table of BOBSNM1 loadings: loading date by consigner, for any period.
- A list of every BOBSNM1 Rake ID loaded in that period.
- Show where the counts are likely to be short.

## Not in this version

- Filling missed loadings from the received rakes or from `rake_trips`.
- Excel or PDF download.
- Changes to the existing sections of the page, including the SAIL/TISCO consignee comparison.

## What was found (database, 28-11-2026)

- `inbound_rakes` has, for BOBSNM1: rake ID, loading time (`LDNG TIME`), source, destination, consigner.
  Lists start on 12-11. All saved lists are all-India. 35 Rake IDs; consigners SAIL and TISC.
- Counting once per rake, loading time and source gives 228 loadings (loading dates 10-11 to 28-11).
  Three pairs are the same rake less than 12 hours apart: two with the same loading time and two
  different sources, one with the same source and a revised time. Counting those once gives 225.
- No lists were received from 21-11 to 24-11. The longest stretch without a list touching each day was
  8 to 130 hours.
- Compared with the received rakes of the SAIL plants (matched on source, plant and date, so an
  estimate), about 79-88% of loadings were in the lists for 13-19 November, and 50-56% for 13-24.

## Approaches

| | How | Trade-off |
|---|---|---|
| **A (chosen)** | In-Bound lists only | Every count traces to a Rake ID and consigner; missed rakes stay missing |
| B | Also add unmatched received rakes | Fewer gaps for SAIL, but consigner assumed and matching can double count |

The user chose A.

## Design

Two new sections near the top of `/bobsnm1`, sharing one **Loaded from / to** filter.

### Counting

- A loading comes from every saved list, whatever its date; only rows with a readable `LDNG TIME`
  and not marked empty (`L/E` of `E`) count.
- Rows of one rake (Rake ID, or load name when blank) whose loading times are less than 12 hours apart
  are one loading. The latest list's date, source, destination and consigner are used.
- The date is the date of that loading time.

### Loading count

- One row per date in the period, latest first, including dates with none.
- Columns: one per consigner found in the period (most loadings first, blank as a dash), Total, Lists
  received that day, Longest gap in hours. A total row.
- Longest gap: the longest stretch without an all-India list that touches the day, up to the latest list.
  Over 8 hours is highlighted, with a note that loadings may be missing. Dates before the first list are
  marked as having no list.

### Rake list

- One row per rake with a loading in the period, most loadings first: Rake ID, loadings per consigner,
  total, last loading time, its source, destination and consigner.
- The page's Find box works on it.

## Calls made by the builder (correct any)

- Opened without dates, the period is the last 30 days, as the received rakes section does; a "Show all"
  link covers everything saved.
- The 12-hour merge and the 8-hour gap threshold are constants in `app.py`. A BOBSNM1 round trip is
  assumed to be longer than 12 hours; 8 hours is about the shortest transit to RSP.
- The older comparison table counts differently (by consignee, `BOBSN*` wagons, loading time and source),
  so its numbers can differ slightly.

## Keeping the counts complete

Turn on the extension's "Send the Loaded In-Bound list automatically every 5 hours" with the all-India
report open. This is an existing feature; no change.

## Testing

Pytest, test first: counting and merging rules, consigner columns, empty dates, the date filter, gap
hours, rake list totals, and that the page still renders with no lists. Then a check of the page against
the live database, read only.
