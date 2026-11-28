# BOBSNM1 Rake Trips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a page of the Chrome extension, fetch BOBSNM1 rake trips (FOIS "Get RR" and Rakes Received) for a period and store them in a new `rake_trips` table.

**Architecture:** The extension page `trips.html` injects fetch functions into an open logged-in FOIS tab, then POSTs the rows to the local Flask app. All row parsing and trip keys live in a new pure module `rake_trips.py`; `app.py` holds only the model and two endpoints.

**Tech Stack:** Python, Flask, SQLAlchemy, SQLite, pytest; Chrome Manifest V3, plain JavaScript (no dependencies).

**Spec:** `docs/superpowers/specs/2026-11-28-rake-trips-design.md`

## Global Constraints

- Extension version `1.8.0`. Dashboard address `http://127.0.0.1:5000`, `Authorization: Bearer <API token>`, `credentials: "omit"`.
- FOIS requests run inside an open tab matching `https://fois.indianrail.gov.in/ecbs/*`, one at a time, 1.5 s apart. Never navigate or reload that tab. Never handle FOIS passwords or cookies.
- Stop after 3 failures in a row. A response that is neither a report nor "NO RECORDS FOUND" is an error, never "no trips".
- `POST /api/rakes`, the `rakes` and `inbound_rakes` tables and existing pages are not changed.
- New endpoints check the API token and are exempt from the site password.
- No new Python or JavaScript dependencies. No JavaScript test files; JavaScript is checked with `node` commands and by hand.
- Commit steps run only if the user has allowed commits. Add only the files a step names (`station_mappings.txt` has an unrelated uncommitted change).
- Commands run from `D:\rakes_received`. Tests: `.\venv\Scripts\python.exe -m pytest tests` (79 passed before this work).

## Review Focus

1. A Rake ID typed with lower case or extra spaces (`dmf   080423120400`) must be the same rake: Task 1 and Task 3.
2. A rake whose request failed must be reported as failed, never listed as "no trips": Task 3.
3. A From date after the To date, or a blank date, must send nothing and say why: Task 3 and Task 4.
4. A wrong API token must stop the run at once, before any FOIS request: Task 4.
5. A logged-out FOIS session must show an error, not zero trips: Task 3 (functions), Task 4 (hand check).

---

### Task 1: Parse trip rows

**Files:**
- Create: `rake_trips.py`
- Test: `tests/test_rake_trips.py`

**Interfaces:**
- Produces:
  - `clean_rake_id(value) -> str | None`: upper case, runs of whitespace collapsed, `None` if blank or not a string.
  - `read_rr_rows(rake_id: str, rows: list) -> tuple[list[dict], int]`: (records, unreadable count).
  - `read_received_rows(columns: list, rows: list) -> tuple[list[dict], int]`: same shape; raises `ValueError` naming the heading if RAKE ID, STTN FROM, STTN TO, RECEIVED TIME or DISPATCHED TIME is missing.
  - A record is a dict of `rake_trips` columns (names in the spec's "Dashboard" list except `imported_at`; ones that don't apply may be omitted), including `trip_key` and `source`. Dates are `datetime.date`, times `datetime.datetime`; `chargeable_wt`, `distance_km`, `rate`, `rebate_pct`, `rebate_amt` are `float | None`; blank text is `None`.

**Rules:**
- RR cell order: from, to, invoice_no, invoice_date, rr_no, rr_date, cnsr, cnsg, cmdt, chargeable_wt, distance_km, freight_class, rate, rebate_pct, rebate_amt, used_by, rebate_head. Dates `dd-mm-yyyy`.
- RR `loaded_empty`: `"E"` when `rebate_head` is `ZERO FREIGHT RR` and `cmdt` is blank, else `"L"`.
- RR `trip_key`: `"rr|" + "|".join([rake_id, sttn_from, invoice_no, invoice_date ISO, rr_no, rr_date ISO])`, blanks as `""`. `trip_date` = invoice date.
- Received headings match lower case with whitespace, dots and underscores removed (`l/e` keeps its slash), so FOIS header text and `extract.js` names both work. `RAKE NAME` → `rake_name`, `TOTL UNTS` → `units`. Times `dd-mm-yyyy HH:MM`.
- Received `trip_key`: `"received|" + "|".join([rake_id, sttn_from, sttn_to, time.isoformat()])`, time = dispatched, else received. `trip_date` = that time's date.
- Unreadable (counted and skipped): an RR row that isn't a list of 17 or lacks from, to or a valid invoice date; a received row of the wrong length or lacking rake ID, from, to, or both times.

- [ ] **Step 1: Write the failing tests**

```python
"""Reading Get RR and Rakes Received rows into rake_trips records."""
from datetime import date, datetime

import pytest

import rake_trips

RAKE = "DMF 080423120400"
LOADED = ["HLSR", "NHSB", "104", "27-11-2026", "261008200", "27-11-2026", "SAIL", "SAIL", "1421318",
          "3525", "63", "165", "203.5", "10", "71733.75", "GPWIS/AUTHORIZED CUSTOMER", "GIVEN ON RR"]
EMPTY = ["NHSB", "PBSB", "52", "27-11-2026", "211000705", "27-11-2026", "SAIL", "SAIL", "", "", "73",
         "", "", "", "", "", "ZERO FREIGHT RR"]
COLUMNS = ["SR. NO.", "RECEIVED TIME", "DISPATCHED TIME", "TRANSIT TIME", "STTN FROM", "FROM SAIL UNIT",
           "STTN TO", "TO SAIL UNIT", "RAKE NAME", "RAKE ID", "RAKE TYPE", "L/E", "CMDT", "CNSG", "CNSR",
           "TOTL UNTS", "TOTL 8W"]
RECEIVED = ["1", "28-11-2026 04:15", "27-11-2026 13:55", "14:20", "FOS", "KIRIBURU", "NHSB", "",
            "BNBSM1-C-NK832", "BNDM221026225706", "BOBSNM1", "L", "IOST", "SAIL", "SAIL", "51+0", ""]


def received(**changes):
    """RECEIVED with cells replaced, e.g. received(RAKE_ID="")."""
    row = list(RECEIVED)
    for heading, value in changes.items():
        row[COLUMNS.index(heading.replace("_", " "))] = value
    return row


@pytest.mark.parametrize("typed", [RAKE, "  dmf   080423120400 ", "Dmf\t080423120400"])
def test_rake_ids_ignore_case_and_extra_spaces(typed):
    assert rake_trips.clean_rake_id(typed) == RAKE


@pytest.mark.parametrize("value", ["", "   ", None, 5])
def test_blank_rake_id_is_none(value):
    assert rake_trips.clean_rake_id(value) is None


def test_loaded_rr_row():
    (trip,), unreadable = rake_trips.read_rr_rows(" dmf  080423120400", [LOADED])
    assert unreadable == 0
    assert trip["source"] == "rr" and trip["rake_id"] == RAKE and trip["loaded_empty"] == "L"
    assert (trip["sttn_from"], trip["sttn_to"]) == ("HLSR", "NHSB")
    assert trip["trip_date"] == trip["invoice_date"] == trip["rr_date"] == date(2026, 11, 27)
    assert (trip["invoice_no"], trip["rr_no"], trip["cmdt"]) == ("104", "261008200", "1421318")
    assert (trip["chargeable_wt"], trip["distance_km"], trip["rate"]) == (3525.0, 63.0, 203.5)
    assert (trip["rebate_pct"], trip["rebate_amt"], trip["freight_class"]) == (10.0, 71733.75, "165")
    assert trip["trip_key"] == "rr|DMF 080423120400|HLSR|104|2026-11-27|261008200|2026-11-27"


def test_zero_freight_without_commodity_is_empty():
    (trip,), _ = rake_trips.read_rr_rows(RAKE, [EMPTY])
    assert trip["loaded_empty"] == "E" and trip["cmdt"] is None and trip["chargeable_wt"] is None
    assert trip["rebate_head"] == "ZERO FREIGHT RR"


def test_other_rebate_heads_are_loaded():
    row = LOADED[:16] + ["GPWIS SCHEME NOT APPLICABLE - WAGON LOAD"]
    assert rake_trips.read_rr_rows(RAKE, [row])[0][0]["loaded_empty"] == "L"


def test_unreadable_rr_rows_are_counted():
    bad = [LOADED[:16], [""] + LOADED[1:], LOADED[:3] + ["soon"] + LOADED[4:], "text"]
    trips, unreadable = rake_trips.read_rr_rows(RAKE, bad + [LOADED])
    assert (len(trips), unreadable) == (1, 4)


def test_received_row():
    (trip,), unreadable = rake_trips.read_received_rows(COLUMNS, [RECEIVED])
    assert unreadable == 0
    assert trip["source"] == "received" and trip["rake_id"] == "BNDM221026225706"
    assert trip["received_time"] == datetime(2026, 11, 28, 4, 15)
    assert trip["dispatched_time"] == datetime(2026, 11, 27, 13, 55)
    assert trip["trip_date"] == date(2026, 11, 27)
    assert (trip["rake_name"], trip["rake_type"], trip["units"]) == ("BNBSM1-C-NK832", "BOBSNM1", "51+0")
    assert (trip["loaded_empty"], trip["cnsg"], trip["cmdt"]) == ("L", "SAIL", "IOST")
    assert trip["trip_key"] == "received|BNDM221026225706|FOS|NHSB|2026-11-27T13:55:00"


def test_extension_column_names_are_read_too():
    names = ["sr_no", "received_time", "dispatched_time", "transit_time", "sttn_from", "fromsailunit",
             "sttn_to", "tosailunit", "rakename", "rakeid", "rake_type", "l/e", "cmdt", "cnsg", "cnsr",
             "totl_unts", "totl8w"]
    assert rake_trips.read_received_rows(names, [RECEIVED]) == rake_trips.read_received_rows(COLUMNS, [RECEIVED])


def test_blank_dispatch_time_uses_received_time():
    (trip,), _ = rake_trips.read_received_rows(COLUMNS, [received(DISPATCHED_TIME="")])
    assert trip["dispatched_time"] is None and trip["trip_date"] == date(2026, 11, 28)
    assert trip["trip_key"].endswith("|2026-11-28T04:15:00")


def test_unreadable_received_rows_are_counted():
    bad = [received(RAKE_ID=""), received(STTN_TO=""),
           received(RECEIVED_TIME="", DISPATCHED_TIME=""), RECEIVED[:5]]
    trips, unreadable = rake_trips.read_received_rows(COLUMNS, bad + [RECEIVED])
    assert (len(trips), unreadable) == (1, 4)


def test_received_table_without_rake_id_is_refused():
    columns = [c for c in COLUMNS if c != "RAKE ID"]
    with pytest.raises(ValueError, match="RAKE ID"):
        rake_trips.read_received_rows(columns, [])
```

- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests/test_rake_trips.py -q`. Expected: FAIL, `No module named 'rake_trips'`.
- [ ] **Step 3: Write `rake_trips.py`** to the interfaces and rules above (standard library only, like `indents.py`, no database code).
- [ ] **Step 4: Run the same command.** Expected: all pass.
- [ ] **Step 5: Commit** `rake_trips.py tests/test_rake_trips.py` — "Read Get RR and Rakes Received rows as rake trips".

---

### Task 2: Store trips and serve Rake IDs

**Files:**
- Modify: `app.py` (imports near line 16; `require_login` exempt tuple near line 81; new model after `StationLookup`, before `Base.metadata.create_all`; endpoints after `import_station_names`)
- Test: `tests/test_rake_trips_app.py`

**Interfaces:**
- Consumes: Task 1's three functions.
- Produces:
  - Model `RakeTrip`, table `rake_trips`, `trip_key` unique and not null, `rake_id` indexed, `imported_at` (IST, naive, as other imports).
  - `save_rake_trips(records: list[dict]) -> tuple[int, int]` returning (new, updated). Records sharing a `trip_key` count once, last wins. Look up existing keys in chunks of 500.
  - `GET /api/rake_ids` (function `rake_ids`) → `{"rake_ids": [sorted, cleaned, unique]}`: `inbound_rakes` rows with `load_type` BOBSNM1 and `cnsg` SAIL (trimmed, any case), plus `rake_trips` rows with `cnsg` SAIL and `rake_type` BOBSNM1 or null.
  - `POST /api/rake_trips` (function `import_rake_trips`) body `{"source": "rr", "rake_id": str, "rows": list}` or `{"source": "received", "columns": list, "rows": list}` → 200 `{"received": len(rows), "new": n, "updated": n, "unreadable": n}`. 401 for a bad token. 400 `{"error": ...}` for: not an object, unknown source, `rows` not a non-empty list, `rr` without a usable rake ID, `received` whose `columns` is not a list or raises `ValueError`.

- [ ] **Step 1: Write the failing tests**

```python
"""Storing rake trips and listing Rake IDs, against a database in a temporary folder."""
import os
from datetime import datetime

import pytest

import app as rakes_app
from test_rake_trips import COLUMNS, EMPTY, LOADED, RAKE, RECEIVED, received

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client():
    assert os.path.dirname(rakes_app.engine.url.database) == os.environ["DATA_DIR"]
    session = rakes_app.SessionDB()
    for model in (rakes_app.RakeTrip, rakes_app.InboundRake, rakes_app.Rake):
        session.query(model).delete()
    session.commit()
    session.close()
    return rakes_app.app.test_client()


def send_rr(client, rows, rake_id=RAKE):
    return client.post("/api/rake_trips", json={"source": "rr", "rake_id": rake_id, "rows": rows}, headers=AUTH)


def send_received(client, rows):
    return client.post("/api/rake_trips", json={"source": "received", "columns": COLUMNS, "rows": rows},
                       headers=AUTH)


def count(model):
    session = rakes_app.SessionDB()
    try:
        return session.query(model).count()
    finally:
        session.close()


def test_both_endpoints_need_the_token(client):
    assert client.get("/api/rake_ids").status_code == 401
    body = {"source": "rr", "rake_id": RAKE, "rows": [LOADED]}
    assert client.post("/api/rake_trips", json=body).status_code == 401
    assert count(rakes_app.RakeTrip) == 0


def test_endpoints_skip_the_site_password(client, monkeypatch):
    monkeypatch.setattr(rakes_app, "APP_PASSWORD", "secret")
    assert client.get("/api/rake_ids", headers=AUTH).status_code == 200
    assert send_rr(client, [LOADED]).status_code == 200


def test_sending_twice_adds_nothing(client):
    assert send_rr(client, [LOADED, EMPTY]).get_json() == {"received": 2, "new": 2, "updated": 0, "unreadable": 0}
    assert send_rr(client, [LOADED, EMPTY]).get_json() == {"received": 2, "new": 0, "updated": 2, "unreadable": 0}
    assert count(rakes_app.RakeTrip) == 2


def test_a_trip_sent_again_is_updated(client):
    send_rr(client, [LOADED])
    send_rr(client, [LOADED[:16] + ["REVISED HEAD"]], rake_id="dmf  080423120400")
    session = rakes_app.SessionDB()
    trip = session.query(rakes_app.RakeTrip).one()
    session.close()
    assert trip.rebate_head == "REVISED HEAD" and trip.rake_id == RAKE


def test_repeated_row_in_one_send_counts_once(client):
    assert send_rr(client, [LOADED, LOADED]).get_json()["new"] == 1


def test_received_rows_are_saved_apart_from_rr(client):
    assert send_received(client, [RECEIVED, received(RAKE_ID="")]).get_json() == {
        "received": 2, "new": 1, "updated": 0, "unreadable": 1}
    send_rr(client, [LOADED])
    session = rakes_app.SessionDB()
    assert sorted(t.source for t in session.query(rakes_app.RakeTrip)) == ["received", "rr"]
    session.close()


def test_more_trips_than_one_lookup_chunk(client):
    rows = [LOADED[:2] + [str(n)] + LOADED[3:] for n in range(1200)]
    assert send_rr(client, rows).get_json()["new"] == 1200
    assert send_rr(client, rows).get_json()["updated"] == 1200


@pytest.mark.parametrize("body", [
    [], {"source": "other", "rows": [LOADED]}, {"source": "rr", "rake_id": RAKE, "rows": []},
    {"source": "rr", "rake_id": "  ", "rows": [LOADED]},
    {"source": "received", "columns": ["SR. NO."], "rows": [["1"]]},
    {"source": "received", "rows": [RECEIVED]},
])
def test_bad_requests_are_refused(client, body):
    response = client.post("/api/rake_trips", json=body, headers=AUTH)
    assert response.status_code == 400 and response.get_json()["error"]


def test_other_tables_are_untouched(client):
    send_received(client, [RECEIVED])
    send_rr(client, [LOADED])
    assert count(rakes_app.Rake) == 0 and count(rakes_app.InboundRake) == 0


def test_rake_ids_are_sail_bobsnm1_from_both_tables(client):
    session = rakes_app.SessionDB()
    for rake_id, load_type, cnsg in [("MXA 1", "BOBSNM1", "SAIL"), (" mxa  1", " bobsnm1 ", " sail "),
                                     ("TISCO1", "BOBSNM1", "TISC"), ("OTHER1", "BOXN", "SAIL"),
                                     (None, "BOBSNM1", "SAIL")]:
        session.add(rakes_app.InboundRake(imported_at=datetime(2026, 11, 28, 6), rake_id=rake_id,
                                          load_type=load_type, cnsg=cnsg, sttn_to="NHSB"))
    session.commit()
    session.close()
    send_received(client, [RECEIVED])
    send_rr(client, [LOADED])
    assert client.get("/api/rake_ids", headers=AUTH).get_json() == {
        "rake_ids": ["BNDM221026225706", RAKE, "MXA 1"]}
```

- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests/test_rake_trips_app.py -q`. Expected: FAIL, no attribute `RakeTrip`.
- [ ] **Step 3: Add the model, `save_rake_trips` and the two endpoints to `app.py`**, using `api_token_valid()` and adding `"rake_ids", "import_rake_trips"` to the `require_login` exempt tuple. Close sessions in `finally`.
- [ ] **Step 4: Run** `.\venv\Scripts\python.exe -m pytest tests -q`. Expected: all pass, the earlier 79 included.
- [ ] **Step 5: Commit** `app.py tests/test_rake_trips_app.py` — "Store rake trips and list SAIL BOBSNM1 Rake IDs".

---

### Task 3: FOIS requests and page logic

**Files:**
- Create: `chrome_extension/trips_logic.js` (pure functions, also loadable by `node`)
- Create: `chrome_extension/foisfetch.js` (functions injected into the FOIS tab)

**Interfaces:**
- Produces, in `trips_logic.js` (ends with `if (typeof module !== "undefined") module.exports = {...}`); `from`/`to` are `yyyy-mm-dd` strings from date inputs:
  - `cleanRakeId(text) -> string` (upper case, collapsed, trimmed; `""` if blank)
  - `monthRanges(from, to) -> [{from, to}]` one per calendar month, values `dd-mm-yyyy`; `[]` if either is blank or `from > to`
  - `rrRowsInPeriod(rows, from, to) -> rows` keeping those whose cell 3 (invoice date) is within, both ends included
  - `receivedRowsFor(columns, rows, ids) -> rows`; `ids` is a `Set` of cleaned IDs, or `null` for all; the column is `RAKE ID`
  - `rakeIdsIn(columns, rows) -> string[]` unique cleaned IDs, first-seen order
  - `rakesWithoutTrips(chosen, withTrips, failed) -> string[]`: members of `chosen` in neither `Set`
- Produces, in `foisfetch.js`. Each is passed to `chrome.scripting.executeScript` as `func`, so it uses nothing outside its own body, and returns `{ok: false, error}` instead of throwing:
  - `async function foisReceived(from, to) -> {ok: true, columns: string[], rows: string[][]}`
  - `async function foisRR(rakeId) -> {ok: true, rows: string[][]}` (17 cells each, whole history)

**Request values** (relative URLs, `credentials: "same-origin"`, body `URLSearchParams`, POST to `/ecbs/RouterServlet`; cell text has whitespace collapsed and trimmed):

- `foisReceived`: first GET `/ecbs/JSP/RcvdRakes.jsp`; in `select[name=txtSttnTo]` take the option whose trimmed text is `ALL`. Then post `operation=query`, `suboperation=rcvdrakes`, `zonesttnflag=S`, `txtSttnTo=<option.value>`, `txtLocn=<option.innerHTML>`, `optSelect=P`, `txtDate=<from>`, `txtDateTo=<to>`, `txtSttnFr=on`, `txtSttnFrom=`, `txtCmdt=`, `txtRakeType=BOBSNM1`, `optLE=A`.
  - `table#example` present → columns from its first row, rows = later rows with the same cell count.
  - Else a table whose first row reads `NO RECORDS FOUND` → `ok: true`, no rows, empty columns.
  - Else, or no `ALL` option, or HTTP not ok → error "FOIS did not return the Rakes Received report. Check that FOIS is logged in."
- `foisRR`: post `operation=query`, `suboperation=gwisgfr`, `txtTrxnFlag=A`, `txtCntrId=`, `txtRakeId=<rakeId>`, `txtPerd=`, `txtCust=SAIL`, `txtAgreDtls=`, `txtRprtFlag=R`, `txtDateFrom=`, `txtDateTo=`.
  - HTTP not ok, or page text lacks `RR DETAILS` → error "FOIS did not return the RR report. Check that FOIS is logged in."
  - Text has `NO RECORDS FOUND FOR RR` → no rows.
  - Else rows = rows of the last table with 17 cells and cell 3 matching `^\d\d-\d\d-\d{4}$`; none → error "The RR report layout was not recognised."

- [ ] **Step 1: Write `trips_logic.js`.**
- [ ] **Step 2: Check it.** Run in PowerShell:

```powershell
@'
const a = require("assert"), t = require("./chrome_extension/trips_logic.js");
a.strictEqual(t.cleanRakeId("  dmf   080423120400 "), "DMF 080423120400");
a.deepStrictEqual(t.monthRanges("2026-09-15", "2026-11-05"), [
  {from: "15-09-2026", to: "30-09-2026"}, {from: "01-10-2026", to: "31-10-2026"}, {from: "01-11-2026", to: "05-11-2026"}]);
a.strictEqual(t.monthRanges("2026-12-31", "2027-01-01").length, 2);
a.deepStrictEqual(t.monthRanges("2028-02-10", "2028-02-29"), [{from: "10-02-2028", to: "29-02-2028"}]);
a.deepStrictEqual(t.monthRanges("2026-11-05", "2026-11-01"), []);
a.deepStrictEqual(t.monthRanges("", "2026-11-01"), []);
const rr = (d) => ["A", "B", "1", d];
a.deepStrictEqual(t.rrRowsInPeriod([rr("31-10-2026"), rr("01-11-2026"), rr("27-11-2026"), rr("28-11-2026")],
  "2026-11-01", "2026-11-27"), [rr("01-11-2026"), rr("27-11-2026")]);
const cols = ["SR. NO.", "RAKE ID"], rows = [["1", "MXA  1"], ["2", "ADTP2"], ["3", "MXA 1"]];
a.deepStrictEqual(t.rakeIdsIn(cols, rows), ["MXA 1", "ADTP2"]);
a.strictEqual(t.receivedRowsFor(cols, rows, new Set(["MXA 1"])).length, 2);
a.strictEqual(t.receivedRowsFor(cols, rows, null).length, 3);
a.deepStrictEqual(t.rakesWithoutTrips(["A", "B", "C"], new Set(["A"]), new Set(["B"])), ["C"]);
console.log("ok");
'@ | node -
```

Expected: `ok`.

- [ ] **Step 3: Write `foisfetch.js`.**
- [ ] **Step 4: Check syntax and the logged-out case.** Run:

```powershell
@'
const a = require("assert"), vm = require("vm"), fs = require("fs");
const page = { body: { textContent: "Please login" }, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null };
const ctx = { URLSearchParams, fetch: async () => ({ ok: true, text: async () => "" }),
  DOMParser: class { parseFromString() { return page; } } };
vm.createContext(ctx); vm.runInContext(fs.readFileSync("chrome_extension/foisfetch.js", "utf8"), ctx);
(async () => {
  for (const r of [await ctx.foisRR("X"), await ctx.foisReceived("01-11-2026", "02-11-2026")]) {
    a.strictEqual(r.ok, false); a.match(r.error, /logged in/);
  }
  ctx.fetch = async () => { throw new Error("offline"); };
  a.strictEqual((await ctx.foisRR("X")).ok, false);
  console.log("ok");
})();
'@ | node -
```

Expected: `ok`.

- [ ] **Step 5: Commit** both files — "Extension: fetch Rakes Received and Get RR from the open FOIS tab".

---

### Task 4: The Rake trips page

**Files:**
- Create: `chrome_extension/trips.html`, `chrome_extension/trips.js`
- Modify: `chrome_extension/popup.html` (button after `#send`), `chrome_extension/popup.js` (its listener, in `init`), `chrome_extension/manifest.json`, `README.md` ("Chrome extension" section and the closing site-address sentence)

**Interfaces:**
- Consumes: Task 2's endpoints; Task 3's functions (`trips.html` loads `trips_logic.js`, `foisfetch.js`, `trips.js` in that order); the saved `apiToken` in `chrome.storage.local`.

**Page** (styled like `popup.html`):
- API token, From, To (`input type="date"`), radios **All BOBSNM1 rakes** (default) and **Ticked Rake IDs**, a checkbox list filled from `GET /api/rake_ids` (reloaded when the token changes), an **Add Rake ID** box (cleaned, appended ticked, no duplicates), **Fetch and send**, a status line, a results list.
- Popup button **Rake trips**, always enabled: `chrome.tabs.create({ url: "trips.html" })`.
- `manifest.json`: version `1.8.0`; description also mentions fetching BOBSNM1 rake trips. No new permissions.

**Run, in `trips.js`** (`DELAY_MS = 1500`, `MAX_ERRORS = 3`):
1. Refuse with a message, sending nothing, when: token blank; `monthRanges` empty ("Choose a From date on or before the To date."); ticked mode with nothing ticked.
2. `GET /api/rake_ids` first, and save the token. 401 → "The server rejected the API token." and stop. Unreachable → "Could not reach the dashboard (is it running?)" and stop.
3. Find the tab with `chrome.tabs.query({ url: "https://fois.indianrail.gov.in/ecbs/*" })`; none → "Open FOIS e-Customer in a tab and log in first." Inject with `chrome.scripting.executeScript({ target: { tabId }, func, args })` (top frame). A thrown injection error counts as that item's failure.
4. Disable **Fetch and send** until the run ends, however it ends.
5. For each month: `foisReceived`; in ticked mode filter with `receivedRowsFor`; POST non-empty rows; add `rakeIdsIn` of the sent rows to the with-trips set. In All mode add those IDs to the rake list.
6. Chosen rakes = ticked IDs, or in All mode the whole list (dashboard, added, found in step 5). For each: `foisRR`; `rrRowsInPeriod`; POST non-empty rows. Success with rows → with-trips set. Failure → failed set.
7. Each month and rake gets a result line: "N new, M updated" (plus "K unreadable" in red when K > 0), "no trips", or the error. A 401 from any POST stops at once; 3 failures in a row stop with "Stopped after 3 failures in a row."
8. End summary, in this order: failed months and rakes; rakes not reached because the run stopped; "No trips from either source: …" from `rakesWithoutTrips` over the rakes reached. If any month failed, that heading reads "No trips found (some Rakes Received months failed): …".

- [ ] **Step 1: Write `trips.html` and `trips.js`; make the popup, manifest and README changes.**
- [ ] **Step 2: Check syntax.** Run `node --check chrome_extension/trips.js; node --check chrome_extension/popup.js; node -e "console.log(require('./chrome_extension/manifest.json').version)"`. Expected: no errors, `1.8.0`.
- [ ] **Step 3: Run** `.\venv\Scripts\python.exe -m pytest tests -q`. Expected: all pass.
- [ ] **Step 4: Hand check with the user** (restart the dashboard; reload the extension at `chrome://extensions`; FOIS logged in):
  - Wrong token → "The server rejected the API token.", no FOIS requests.
  - From after To → refused.
  - Tick `DMF 080423120400`, 01-11-2026 to 27-11-2026 → the Get RR line shows 37 trips (the count on 28-11-2026; compare with FOIS "Get RR" if it differs), and the received count matches that rake's rows in the FOIS report for the period.
  - Run again → 0 new, the same number updated.
  - **All** for November → the received total matches the FOIS report (all stations, BOBSNM1, loaded and empty); the summary lists rakes without trips.
  - No FOIS tab → asks to open one. Logged out of FOIS → errors, stops after 3, never "no trips".
  - The FOIS page on screen did not change.
- [ ] **Step 5: Commit** the Task 4 files — "Extension 1.8.0: Rake trips page".
