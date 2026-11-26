# Raw Material Status page: design

Date: 2026-11-25. Status: awaiting approval.

## Intent

The In-Bound page shows loaded rakes by plant and loading date, but FOIS gives only a broad commodity
code. Plants need to see each Iron Ore, Coal and Imported Coal rake with its sub-commodity, for example
"Iron Ore, RSP, Barsua, Full Lump, at Dumetra, 8 km". Users type the sub-commodity once, and it stays with
that rake until the rake reaches its plant.

## Goals

- A separate page showing these rakes plant by plant, then by commodity.
- Manual entry of one or more sub-commodities per rake, each with its wagon count.
- The entry stays on the rake through later In-Bound sends.
- Loading date shown for every rake.

## Non-goals

- Excel or PDF download.
- Bulk entry or spreadsheet upload.
- Pellet conversion agents, empty rakes, other commodities.
- Showing sub-commodities on other pages, or on received rakes.
- Recording who made an entry.

## Anti-goals

- An entry moving to a different trip of the same rake. Shuttle rakes repeat the same source and plant
  within days, so a wrong carry-over is worse than asking for the entry again.
- An entry disappearing because a later send revised the rake's data.

## Approaches

1. **Add or Edit on each rake (chosen).** Entry and status on one page, handles mixed loads well. One save
   per rake.
2. Bulk-entry grid. Faster for many rakes, but a second screen and awkward for mixed loads.
3. Excel download and upload. Slowest for a few rakes, and errors show only at upload.

The user chose 1, and "each sub-commodity with its wagon count" for mixed loads.

## Page

New page at `/raw_materials`, "Raw Material Status", linked in the menu. It shows the latest In-Bound list's
rakes that are going to the five plant yards (`DESTINATION_PLANTS`), are not empty, and whose commodity name
is one of:

| Section | Commodity names (from the commodity mappings) |
|---|---|
| Iron Ore | IRON ORE |
| Coal | COAL, NON PROGRAMMED COAL |
| Imported Coal | IMPORTED COAL |

The date and time of the list is shown, as on the In-Bound page.

**Summary** at the top: for each plant and section, every sub-commodity with its rakes, wagons and tonnage,
plus "Not entered". Rakes are counted by wagon share (changed at the user's request after the first build):
a sub-commodity's rakes are the sum of its wagons divided by each rake's wagons, for example
24/58 + 58/58 + 38/38 + 37/58 = 3.05, shown to two decimals. Tonnage is wagons × 70 T. A section's total
counts each rake once. The table runs by commodity (Coal, Imported Coal, Iron Ore), then plant, with PCC,
MCC and Midling first in each plant, other names by name, and "Not entered" last.

**Rake list**: plants in the order BSP, DSP, RSP, BSL, ISP; within a plant Iron Ore, Coal, Imported Coal;
within a section, nearest first, unknown distance last.

| Column | Value |
|---|---|
| Loaded | `LDNG TIME`, date and time |
| Source | `Name (CODE)`; ISP imported coal adds the siding, `→ BCME` or `→ IISD` |
| Sub-commodity | `Full Lump`, or `0.6 PCC 30 + Grade B 28`, or "Not entered" |
| Wagons | First number of `TOTL UNTS` (`58+1` is 58) |
| Now at | `Name (CODE)` of `CRNT LOCN` |
| Km left | RBS distance from there to the plant yard, as on the In-Bound page |
| Status | `STTS CODE`; stabled rakes highlighted |
| Rake ID | For identification |

Filters: plant, and "show only not entered". The layout works on a phone, like the other pages.

## Entry

- **Add** or **Edit** on a rake opens a small form under it.
- Each line is a sub-commodity and a wagon count. A new entry starts as one line with all the rake's wagons.
  **+ Add another** adds a line for a mixed load.
- The sub-commodity box suggests names already used in that section, and accepts a new one. Names are
  trimmed and spacing collapsed; a name differing only in letter case reuses the existing spelling.
- Saving requires a name on every line, whole wagon counts above zero, no name twice, and counts adding up
  to the rake's wagons. Errors appear on the form and keep what was typed.
- **Remove entry** returns the rake to "Not entered".
- After saving, the page returns to the same rake with the same filters.

## Keeping the entry with the rake

A trip is identified by Rake ID, source (`STTN FROM`) and `LDNG TIME`.

FOIS can revise `LDNG TIME` while a rake is still at loading: in the saved lists it changed for rakes that
had no departure time (`DEPT TIME`). So when a new list arrives, an entry moves to the rake's new loading
time only if all of these hold:

- same Rake ID, source and destination;
- in the list before, the rake had the entry's loading time and **no departure time**.

Otherwise a new loading time means a new trip, which starts as "Not entered". Once a rake has departed, its
entry matches only that loading time.

A rake leaves the page when it's no longer in the latest list, which is treated as received. The entry stays
in the database, so a rake that was missing from a partial send gets it back.

If FOIS later changes a rake's wagon count, the entry stays and the rake is marked "check wagons".

## Data

A new table, one row per sub-commodity line: Rake ID, source, destination, loading time, line number,
sub-commodity, wagons, time entered. It lives in `rake_data.db`, so the Google Drive backup includes it.

## Station names

The In-Bound send's Station Help lookup also covers the current location of these rakes when it has no
name. Until then the code shows alone. A location first seen in a send is named after the extension's lookup
tab finishes.

## Left to the builder

Table and column names, markup and styling (following the In-Bound page), and where the code lives.

## Tests

Which rakes appear and in what order; summary counts with a mixed rake; each validation rule; edit and
remove; an entry surviving a loading-time revision before departure; an entry not passing to a new trip; the
extra station lookup.
