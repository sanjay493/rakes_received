# Pending Indents Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the FOIS "ODR Wise Rake Outstanding Details" list and show SAIL's pending indents, against other parties at the same sources, on a new `/indents` page with Excel and PDF downloads.

**Architecture:** All reading, rules and report-building live in a new pure module `indents.py` that knows nothing about Flask or the database, so it is tested directly. `app.py` gets a thin layer: one table, one import endpoint, one page, and the queries that feed the pure functions. Downloads live in `indent_exports.py`, reusing helpers from `inbound_exports.py`.

**Tech Stack:** Python 3.11, Flask 3, SQLAlchemy 2 (SQLite), pandas, openpyxl, reportlab, Jinja templates, Chrome extension (Manifest V3, plain JS), pytest (new, dev only).

**Spec:** `docs/superpowers/specs/2026-11-15-pending-indents-design.md`

## Global Constraints

- SAIL party code is `SAIL` (use `is_sail` / `SAIL_CONSIGNEE` in `app.py`; in `indents.py` compare upper-cased, stripped text to `"SAIL"`).
- Plants (steel sources): the keys of `DESTINATION_PLANTS` — BSCS, BSPC, DSEY, IISD, BCME, HSPG, NHSB. Steel commodity group: `IS`.
- Age buckets, exact labels: `0–2`, `3–7`, `8–15`, `>15` (en dash). Age = list date − DEMAND DATE, in days.
- Loaded-rakes window: `SHARED_SOURCE_DAYS` (7) days ending on the ODR list's date.
- Highlight rule: oldest SAIL pending indent over 7 days old and at least one rake loaded there for others in the window.
- DEMAND DATE is `dd-mm-yy`; SUPPLIED TIME is `dd-mm-yyyy`, often blank.
- Other parties' indents never add into SAIL's numbers. An ODR import never touches `rakes`, `inbound_rakes`, `rail_distances` or `station_lookups`.
- The real ODR CSV is company data: do not copy it into the repo. Tests build their rows inline.
- Run everything with `.\venv\Scripts\python.exe`. Do not commit unless the user asks; where a task says "Commit", stage and commit only if the user has allowed commits for this work, otherwise leave the changes in the working tree.
- Page wording follows the existing pages: plain English, "rakes", "indents", station names from `station_label`, commodity names from `commodity_name`.

## Review Focus

1. **ODR list holding only SAIL's indents** (the sample file): "Others pending" shows a dash, nothing fails. → Task 3.
2. **DEMAND DATE that cannot be read:** the indent is kept and counted as pending, its age is blank, it is in no bucket, and it is never the "oldest". → Task 2.
3. **No all-India In-Bound list stored, or none in the 7-day window:** the two "loaded" columns show a dash and no row is highlighted. → Tasks 3 and 4.
4. **The same ODR list sent twice, or sent again later:** the page shows only the latest list; counts do not double. → Task 4.
5. **Units that are blank or not a number, and a second-part row arriving first (no row above it):** units count as 0; the orphan row becomes its own indent instead of raising. → Task 1.

---

## File Structure

| File | Responsibility |
|---|---|
| `indents.py` (new) | Read ODR rows, apply the indent rules, build the three report tables. Pure functions. |
| `indent_exports.py` (new) | `build_excel(data)`, `build_pdf(data)` for the page. |
| `app.py` (modify) | `OdrIndent` table, `POST /api/odr`, `/indents` (GET page, POST CSV), downloads, the queries. |
| `templates/indents.html` (new) | The page. |
| `templates/base.html` (modify, line ~241) | Menu link. |
| `chrome_extension/extract.js`, `popup.js`, `popup.html`, `manifest.json` (modify) | Recognise and send the ODR table. |
| `tests/test_indents.py` (new) | Tests for `indents.py`. |
| `tests/test_indents_app.py` (new) | Tests for the endpoint and page. |
| `requirements-dev.txt` (new) | `-r requirements.txt` and `pytest`. |
| `README.md` (modify) | One short section: the ODR list and how to run tests. |

---

### Task 1: Read ODR rows

**Files:**
- Create: `indents.py`, `tests/test_indents.py`, `requirements-dev.txt`

**Interfaces:**
- Produces:
  - `ODR_HEADINGS: dict[str, str]` — FOIS heading with spaces, dots and underscores removed and lower-cased → field name:
    `srno→sr_no, dvsn→dvsn, sttnfrom→sttn_from, demandno→demand_no, demanddate→demand_date_text, demandtime→demand_time, expdldngdate→expd_ldng_date, cnsr→cnsr, cnsg→cnsg, gruprakecmdt→grup_cmdt, rakecmdt→rake_cmdt, tt→tt, pc→pc, pbf→pbf, via→via, sttnto→sttn_to, indentedtype→indented_type, indentedunits→indented_units, indented8w→indented_8w, ostgunits→ostg_units, ostg8w→ostg_8w, suppliedunits→supplied_units, suppliedtime→supplied_time, demandid→demand_id`
  - `read_odr_rows(columns: list, rows: list[list]) -> list[dict]` — one dict per usable row with every field above as stripped text (`""` for blank or `None`), plus `indent_no: int` (1, 2, 3… — goes up at each row with a filled `sr_no`), `part_no: int` (1 for that row, 2, 3… for the blank-`sr_no` rows under it) and `demand_date: date | None`. `indented_units`, `ostg_units`, `supplied_units` are `int` (0 when blank or not a number). Raises `ValueError("STTNFROM and DEMAND ID are required")` when either heading is missing. Rows whose length differs from `columns`, or that are entirely blank, are skipped.
  - Fill-down: for a blank-`sr_no` row these fields, when blank, are copied from the row above: `dvsn, sttn_from, demand_no, demand_date_text, demand_time, expd_ldng_date, cnsr, cnsg, grup_cmdt, tt, pc, pbf, via, demand_id`.

- [ ] **Step 1: Add pytest.** Create `requirements-dev.txt` with `-r requirements.txt` and `pytest`; run `.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt`. Expected: pytest installs.

- [ ] **Step 2: Write the failing tests** in `tests/test_indents.py`. Put the shared rows at the top of the file; later tasks use them.

```python
from datetime import date
import pytest
import indents

COLUMNS = ["SR.NO.", "DVSN", "STTNFROM", "DEMAND NO.", "DEMAND DATE", "DEMAND TIME", "EXPD LDNG DATE",
           "CNSR", "CNSG", "GRUP RAKE CMDT", "RAKE CMDT", "TT", "PC", "PBF", "VIA", "STTNTO",
           "INDENTED TYPE", "INDENTED UNITS", "INDENTED 8W", "OSTG UNITS", "OSTG 8W",
           "SUPPLIED UNITS", "SUPPLIED TIME", "DEMAND ID"]

def row(sr, source, demand_date, cnsr, cnsg, group, cmdt, to, wagon, indented, ostg,
        supplied_time="", demand_id="X1"):
    filled = sr != ""
    return [sr, "CKP" if filled else "", source if filled else "", "1" if filled else "",
            demand_date if filled else "", "10:00" if filled else "", "", cnsr if filled else "",
            cnsg if filled else "", group if filled else "", cmdt, "GG" if filled else "",
            "C" if filled else "", "N" if filled else "", "", to, wagon, str(indented), str(indented),
            str(ostg), str(ostg), "0", supplied_time, demand_id]

ROWS = [
    row("1", "BSCS", "12-11-26", "SAIL", "SAIL", "IS", "IS", "CDG", "BOST", 18, 18, demand_id="BSCS7"),
    row("",  "",     "",         "",     "",     "",   "IS", "DDL", "BRN",  25, 25, demand_id="BSCS7"),
    row("2", "CBSP", "30-10-26", "ABCD", "SAIL", "IMCL", "IMCL", "BSPC", "BOXN", 58, 58, demand_id="CBSP1"),
    row("3", "CBSP", "14-11-26", "ABCD", "SAIL", "IMCL", "IMCL", "BSPC", "BOXN", 58, 58, demand_id="CBSP2"),
    row("4", "CBSP", "13-11-26", "ABCD", "TISC", "IMCL", "IMCL", "TATA", "BOXN", 58, 58, demand_id="CBSP3"),
    row("5", "BYFS", "13-11-26", "SAIL", "SAIL", "ORES", "IOST", "MOMG", "BOXNHL", 59, 1, demand_id="BYFS1"),
    row("6", "VSPV", "11-11-26", "ABCD", "SAIL", "IMCL", "IMCL", "BSPC", "BOXN", 58, 58,
        supplied_time="15-11-2026", demand_id="VSPV1"),
]

def test_reads_rows_and_fills_second_part():
    rows = indents.read_odr_rows(COLUMNS, ROWS)
    assert len(rows) == 7
    assert [r["indent_no"] for r in rows] == [1, 1, 2, 3, 4, 5, 6]
    assert [r["part_no"] for r in rows[:3]] == [1, 2, 1]
    second = rows[1]
    assert (second["sttn_from"], second["cnsg"], second["grup_cmdt"]) == ("BSCS", "SAIL", "IS")
    assert (second["sttn_to"], second["indented_type"], second["indented_units"]) == ("DDL", "BRN", 25)
    assert second["demand_date"] == date(2026, 11, 12)

def test_missing_heading_raises():
    with pytest.raises(ValueError, match="STTNFROM and DEMAND ID are required"):
        indents.read_odr_rows(["SR.NO.", "DVSN"], [["1", "CKP"]])

def test_bad_units_blank_cells_and_orphan_second_part():
    orphan = row("", "", "", "", "", "", "IS", "DDL", "BRN", 25, 25)
    bad = row("1", "FOS", "xx", "SAIL", "SAIL", "ORES", "IOST", "IISD", "BOXNHL", "", "n/a")
    bad[5] = None                      # the extension sends null for a blank cell
    rows = indents.read_odr_rows(COLUMNS, [orphan, bad, ["short"], [None] * len(COLUMNS)])
    assert len(rows) == 2
    assert rows[0]["indent_no"] == 1 and rows[1]["indent_no"] == 2
    assert rows[1]["indented_units"] == 0 and rows[1]["ostg_units"] == 0
    assert rows[1]["demand_date"] is None and rows[1]["demand_time"] == ""
```

- [ ] **Step 3: Run** `.\venv\Scripts\python.exe -m pytest tests/test_indents.py -v`. Expected: FAIL, `No module named 'indents'`.

- [ ] **Step 4: Implement** `ODR_HEADINGS` and `read_odr_rows` in `indents.py`. Heading key: `re.sub(r"[\s._]", "", str(heading).lower())`, the same as `/api/inbound` uses. Unknown headings are ignored.

- [ ] **Step 5: Run** the same command. Expected: 3 passed.

- [ ] **Step 6: Commit** `indents.py tests/test_indents.py requirements-dev.txt` — "Pending indents: read the ODR list".

---

### Task 2: Indent rules

**Files:**
- Modify: `indents.py`, `tests/test_indents.py`

**Interfaces:**
- Consumes: `read_odr_rows` (Task 1).
- Produces:
  - `BUCKETS = ["0–2", "3–7", "8–15", ">15"]`
  - `build_indents(rows: list[dict], list_date: date, plants: set[str]) -> list[dict]` — one dict per `indent_no`, in list order:

    | key | value |
    |---|---|
    | `source` | `sttn_from` of part 1, upper-cased |
    | `cnsr`, `cnsg`, `group`, `pc`, `dvsn`, `demand_id`, `demand_date` | from part 1 |
    | `cmdt` | `rake_cmdt` of part 1 |
    | `destinations`, `wagon_types` | lists over the parts, in order, no repeats |
    | `indented`, `outstanding` | sums over the parts |
    | `status` | `"supplied"` if any part has a `supplied_time`; else `"pending"` if `indented > 0` and `outstanding * 2 >= indented`; else `"part"` if `outstanding > 0`; else `"done"` |
    | `age` | `(list_date - demand_date).days`, floor 0; `None` if no date |
    | `bucket` | the `BUCKETS` label for `age`; `None` if `age` is `None` |
    | `steel_out` | `source in plants and group == "IS"` |
    | `sail` | `cnsg == "SAIL"`, or `steel_out and cnsr == "SAIL"` |

- [ ] **Step 1: Write the failing tests** (append):

```python
PLANTS = {"BSCS", "BSPC", "DSEY", "IISD", "BCME", "HSPG", "NHSB"}
LIST_DATE = date(2026, 11, 15)

def built():
    return indents.build_indents(indents.read_odr_rows(COLUMNS, ROWS), LIST_DATE, PLANTS)

def test_two_part_indent_is_one_rake():
    first = built()[0]
    assert (first["indented"], first["outstanding"], first["status"]) == (43, 43, "pending")
    assert first["destinations"] == ["CDG", "DDL"] and first["wagon_types"] == ["BOST", "BRN"]
    assert first["steel_out"] and first["sail"]

def test_status_age_and_party():
    by_id = {i["demand_id"]: i for i in built()}
    assert (by_id["CBSP1"]["age"], by_id["CBSP1"]["bucket"]) == (16, ">15")
    assert (by_id["CBSP2"]["age"], by_id["CBSP2"]["bucket"]) == (1, "0–2")
    assert by_id["CBSP3"]["sail"] is False and by_id["CBSP3"]["status"] == "pending"
    assert by_id["BYFS1"]["status"] == "part"          # 1 of 59 outstanding
    assert by_id["VSPV1"]["status"] == "supplied"      # supplied time present, all still outstanding
    assert by_id["CBSP1"]["steel_out"] is False

def test_bucket_edges_and_unreadable_date():
    def one(demand_date):
        rows = indents.read_odr_rows(COLUMNS, [row("1", "FOS", demand_date, "SAIL", "SAIL", "ORES", "IOST", "IISD", "BOXNHL", 59, 59)])
        return indents.build_indents(rows, LIST_DATE, PLANTS)[0]
    assert [one(d)["bucket"] for d in ("13-11-26", "12-11-26", "08-11-26", "07-11-26", "31-10-26", "30-10-26")] == \
           ["0–2", "3–7", "3–7", "8–15", "8–15", ">15"]
    unreadable = one("xx")
    assert unreadable["status"] == "pending" and unreadable["age"] is None and unreadable["bucket"] is None
    assert one("20-11-26")["age"] == 0                 # a date after the list
```

- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests/test_indents.py -v`. Expected: the 3 new tests FAIL (`build_indents` missing).
- [ ] **Step 3: Implement** `BUCKETS` and `build_indents`.
- [ ] **Step 4: Run** again. Expected: 6 passed.
- [ ] **Step 5: Commit** — "Pending indents: pending, supplied and part-supplied rules".

---

### Task 3: The three report tables

**Files:**
- Modify: `indents.py`, `tests/test_indents.py`

**Interfaces:**
- Consumes: `build_indents` output (Task 2).
- Produces (all take `commodity_name: Callable[[str], str]` and `station_label: Callable[[str], str]` so the module stays free of the app):
  - `source_report(indents, loaded, commodity_name, station_label) -> list[dict]`
    - `loaded`: `{(source code, commodity name): {"sail": int, "others": int}}`, or `None` when there is no loading history.
    - Rows: one per (source, commodity name) that has a SAIL indent which is not steel going out. Keys: `source` (label), `source_code`, `commodity`, `wagon_types` (sorted list), `pending`, `buckets` (`{label: count}` for every `BUCKETS` label), `oldest` (max age of pending indents, `None` if none has an age), `supplied`, `part`, `others` (`[(party, pending count)]`, most first then by code — other parties' pending indents at the same source and commodity, steel excluded), `loaded_sail`, `loaded_others` (`None` when `loaded` is `None`; 0 when the key is absent), `flag` (`oldest is not None and oldest > 7 and bool(loaded_others)`).
    - Order: commodity with most pending first, then source with most pending, then source label.
  - `plant_pipeline(indents, in_transit, received, commodity_name, plant_of) -> list[dict]`
    - `in_transit`: `{(commodity name, plant): int}`; `received`: `{(commodity name, plant): {"per_day": float, "yesterday": int}}`; `plant_of`: `dict` yard or agent code → plant name.
    - Counts SAIL indents with status `pending`, not steel going out, whose **first** destination is in `plant_of`. Rows over the union of keys of the three inputs: `plant`, `commodity`, `pending`, `in_transit`, `per_day` (`None` if absent), `yesterday` (`None` if absent). Order: plant in the order of `plant_of`'s values, then commodity.
  - `steel_report(indents, station_label) -> list[dict]` — SAIL indents with `steel_out`: one row per (source, wagon types joined with `" + "`): `plant` (label), `wagon`, `pending`, `buckets`, `oldest`, `supplied`. Order: plant label, wagon.
  - `summary(indents) -> dict` — `inward_pending`, `steel_pending`, `supplied`, `part`, `others_pending`, and `oldest`: the oldest SAIL pending indent as `{"source": code, "demand_date": date, "age": int}` or `None`.

- [ ] **Step 1: Write the failing tests** (append):

```python
NAMES = {"IMCL": "IMPORTED COAL", "IOST": "IRON ORE", "IS": "STEEL"}
name = lambda code: NAMES.get(code, code)
label = lambda code: f"{code} name"

def test_source_report_compares_sail_with_others():
    loaded = {("CBSP", "IMPORTED COAL"): {"sail": 2, "others": 5}}
    rows = indents.source_report(built(), loaded, name, label)
    cbsp = next(r for r in rows if r["source_code"] == "CBSP")
    assert (cbsp["commodity"], cbsp["pending"], cbsp["oldest"]) == ("IMPORTED COAL", 2, 16)
    assert cbsp["buckets"] == {"0–2": 1, "3–7": 0, "8–15": 0, ">15": 1}
    assert cbsp["others"] == [("TISC", 1)]
    assert (cbsp["loaded_sail"], cbsp["loaded_others"], cbsp["flag"]) == (2, 5, True)
    assert rows[0]["source_code"] == "CBSP"                       # most pending first
    vspv = next(r for r in rows if r["source_code"] == "VSPV")
    assert (vspv["pending"], vspv["supplied"], vspv["loaded_others"], vspv["flag"]) == (0, 1, 0, False)
    byfs = next(r for r in rows if r["source_code"] == "BYFS")
    assert (byfs["pending"], byfs["part"]) == (0, 1)
    assert all(r["source_code"] != "BSCS" for r in rows)          # steel is not in this table

def test_source_report_without_others_or_loading_history():
    sail_only = [i for i in built() if i["sail"]]
    rows = indents.source_report(sail_only, None, name, label)
    cbsp = next(r for r in rows if r["source_code"] == "CBSP")
    assert cbsp["others"] == [] and cbsp["loaded_sail"] is None and cbsp["loaded_others"] is None
    assert cbsp["flag"] is False

def test_plant_pipeline_and_steel_and_summary():
    plant_of = {"BSPC": "BSP", "MOMG": "MOMG"}
    rows = indents.plant_pipeline(
        built(), {("IMPORTED COAL", "BSP"): 7, ("IRON ORE", "BSP"): 3},
        {("IMPORTED COAL", "BSP"): {"per_day": 4.5, "yesterday": 6}}, name, plant_of)
    coal = next(r for r in rows if (r["plant"], r["commodity"]) == ("BSP", "IMPORTED COAL"))
    assert (coal["pending"], coal["in_transit"], coal["per_day"], coal["yesterday"]) == (2, 7, 4.5, 6)
    ore = next(r for r in rows if (r["plant"], r["commodity"]) == ("BSP", "IRON ORE"))
    assert (ore["pending"], ore["in_transit"], ore["per_day"]) == (0, 3, None)

    steel = indents.steel_report(built(), label)
    assert steel == [{"plant": "BSCS name", "wagon": "BOST + BRN", "pending": 1,
                      "buckets": {"0–2": 0, "3–7": 1, "8–15": 0, ">15": 0}, "oldest": 3, "supplied": 0}]

    total = indents.summary(built())
    assert (total["inward_pending"], total["steel_pending"], total["supplied"], total["part"],
            total["others_pending"]) == (2, 1, 1, 1, 1)
    assert total["oldest"] == {"source": "CBSP", "demand_date": date(2026, 10, 30), "age": 16}

def test_summary_ignores_undated_indent_for_oldest():
    rows = indents.read_odr_rows(COLUMNS, [row("1", "FOS", "xx", "SAIL", "SAIL", "ORES", "IOST", "IISD", "BOXNHL", 59, 59)])
    total = indents.summary(indents.build_indents(rows, LIST_DATE, PLANTS))
    assert total["inward_pending"] == 1 and total["oldest"] is None
```

- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests/test_indents.py -v`. Expected: the 4 new tests FAIL.
- [ ] **Step 3: Implement** the four functions.
- [ ] **Step 4: Run** again. Expected: 10 passed.
- [ ] **Step 5: Commit** — "Pending indents: source, plant and steel tables".

---

### Task 4: Table, import and the page

**Files:**
- Modify: `app.py` (model after `InboundRake` ~line 130; `require_login` exemption list ~line 54; import endpoint after `import_inbound` ~line 702; `shared_source_report` ~line 897; page routes after the In-Bound routes ~line 1335), `templates/base.html:241`
- Create: `templates/indents.html`, `tests/test_indents_app.py`

**Interfaces:**
- Consumes: everything in `indents.py`.
- Produces:
  - `class OdrIndent(Base)`, table `odr_indents`: `id`, `imported_at` (DateTime, indexed, not null), `indent_no` (Integer), `part_no` (Integer), `demand_date` (Date), `indented_units`, `ostg_units`, `supplied_units` (Integer), and every other `ODR_HEADINGS` field as `String`.
  - `save_odr(columns, rows) -> int` — reads with `read_odr_rows`, stores the rows as one new list stamped `datetime.now(IST).replace(tzinfo=None)`, returns the row count. Lets `ValueError` through.
  - `POST /api/odr` (endpoint name `import_odr`, added to the `require_login` exemption tuple): token check through `read_import_request`; `400` with `{"error": "Could not read the table: …"}` on `ValueError`; else `{"received": n, "inserted": n, "indents": count of distinct indent_no}`.
  - `loadings_in_window(session, start: date, end: date) -> (dict, first_list)` — the loop now inside `shared_source_report` that builds `loadings` (`{(rake id or load name, loaded datetime, source): (cnsg, commodity name)}`) and finds `first_list`, moved out unchanged; `shared_source_report` calls it. Its output must not change.
  - `loaded_by_source(session, end: date) -> dict | None` — `{(source code, commodity name): {"sail": n, "others": n}}` over `SHARED_SOURCE_DAYS` days ending `end`, from `loadings_in_window`; `None` when no In-Bound list falls in the window.
  - `transit_by_destination(session) -> dict` — `{(commodity name, plant): loaded rakes}` from the latest In-Bound list, destinations in `INBOUND_DESTINATIONS`, rows with L/E `E` left out (same rule as `rakes_in_transit`).
  - `received_by_plant(session, end: date) -> dict` — `{(commodity, sttn_to): {"per_day": rakes in the 30 days before end / 30, rounded to 1 decimal, "yesterday": rakes received on end − 1 day}}` from `Rake`.
  - `indents_data(party: str = "sail") -> dict` — `{"imported_at": None}` when no list is stored; else `imported_at`, `summary`, `sources`, `plants`, `steel`, `buckets` (`BUCKETS`), `party`, and `all` (every indent with status `pending`, `supplied` or `part`, filtered by `party` in `sail` / `others` / `all`, oldest first, each with `source_label` and `commodity` added). Reads only the rows with the latest `imported_at`; `list_date` is `imported_at.date()`.
  - Routes: `GET /indents?party=` renders `indents.html`; `POST /indents` takes a CSV file field `file` (`pd.read_csv(..., dtype=str, keep_default_na=False)`), calls `save_odr`, redirects to `/indents?msg=…`.

- [ ] **Step 1: Write the failing tests** in `tests/test_indents_app.py`. The app opens its database at import, so point `DATA_DIR` at an empty temporary folder **before** importing it, and set `API_TOKEN`. `data_path` copies the bundled `rake_data.db` into that folder, so each test first deletes all rows of `OdrIndent`, `InboundRake` and `Rake` in the temporary copy (never the real file).

```python
import os, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["API_TOKEN"] = "test-token"
os.environ.pop("APP_PASSWORD", None)
import pytest
import app as rakes_app
from test_indents import COLUMNS, ROWS

AUTH = {"Authorization": "Bearer test-token"}

@pytest.fixture
def client():
    assert os.path.dirname(rakes_app.engine.url.database) == os.environ["DATA_DIR"]
    session = rakes_app.SessionDB()
    for model in (rakes_app.OdrIndent, rakes_app.InboundRake, rakes_app.Rake):
        session.query(model).delete()
    session.commit(); session.close()
    return rakes_app.app.test_client()

def test_page_before_any_list(client):
    page = client.get("/indents")
    assert page.status_code == 200 and b"No ODR list has been received yet" in page.data

def test_import_needs_token_and_headings(client):
    assert client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}).status_code == 401
    bad = client.post("/api/odr", json={"columns": ["SR.NO."], "rows": [["1"]]}, headers=AUTH)
    assert bad.status_code == 400 and "STTNFROM and DEMAND ID are required" in bad.get_json()["error"]

def test_import_twice_shows_latest_list_only(client):
    first = client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}, headers=AUTH)
    assert first.get_json() == {"received": 7, "inserted": 7, "indents": 6}
    client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}, headers=AUTH)
    data = rakes_app.indents_data()
    assert data["summary"]["inward_pending"] == 2 and data["summary"]["steel_pending"] == 1
    assert all(i["sail"] for i in data["all"])
    assert len(rakes_app.indents_data("all")["all"]) == 6
    assert len(rakes_app.indents_data("others")["all"]) == 1

def test_page_without_inbound_history_shows_dashes(client):
    client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}, headers=AUTH)
    data = rakes_app.indents_data()
    assert all(r["loaded_others"] is None and not r["flag"] for r in data["sources"])
    assert client.get("/indents").status_code == 200

def test_import_leaves_other_tables_alone(client):
    session = rakes_app.SessionDB()
    session.add(rakes_app.InboundRake(imported_at=rakes_app.datetime(2026, 11, 15, 6, 0), rake_id="R1", sttn_to="BSPC"))
    session.commit(); session.close()
    client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}, headers=AUTH)
    session = rakes_app.SessionDB()
    assert session.query(rakes_app.InboundRake).count() == 1
    session.close()
```

- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests -v`. Expected: Task 1–3 tests pass; the 5 new tests FAIL (`/indents` 404, no `OdrIndent`).

- [ ] **Step 3: Implement** the model, `save_odr`, `/api/odr`, the `loadings_in_window` extraction, the three query helpers and `indents_data` in `app.py`.

- [ ] **Step 4: Create `templates/indents.html`** extending `base.html`, in the style of `enroute.html` and `inbound.html`:
  - When `imported_at` is `None`: the line "No ODR list has been received yet." and the CSV upload form.
  - Top line: "ODR list of {date time}", then four figures: SAIL rakes pending inward, SAIL steel rakes pending outward, supplied and under loading, oldest pending indent (source, date, days).
  - Table 1 "Pending at each source": Source | Commodity | Wagon | SAIL pending | 0–2 | 3–7 | 8–15 | >15 | Oldest (days) | Supplied | Part supplied | Others pending | Loaded in last 7 days: SAIL | Others. `None` shows as "—"; a `flag` row gets a highlighted background; a note under the table explains the highlight in one sentence.
  - Table 2 "Pipeline to each plant": Plant | Commodity | Pending indents | In transit | Received per day (30 days) | Received yesterday.
  - Table 3 "Steel indents at each plant": Plant | Wagon | Pending | the four buckets | Oldest (days) | Supplied.
  - Table 4 "All pending indents": links for SAIL / Others / All (`?party=`), columns Source | Party (CNSG) | Commodity | To | Wagon | Indented | Outstanding | Demand date | Age | Status.
  - Download links to `/indents/report.xlsx` and `/indents/report.pdf` (routes arrive in Task 5), and the CSV upload form at the foot.
  - Add `<a href="/indents">Pending Indents</a>` after the In-Bound link in `templates/base.html`.

- [ ] **Step 5: Run** `.\venv\Scripts\python.exe -m pytest tests -v`. Expected: 15 passed.

- [ ] **Step 6: Check with the real file.** Start the app (`$env:API_TOKEN="x"; .\venv\Scripts\python.exe app.py`), open `http://127.0.0.1:5000/indents`, upload `C:\Users\sanja\Downloads\ODR Wise Rake Outstanding Details.csv`. Expected: the top line counts add up to 255 indents across pending, supplied and part supplied (plus any with nothing outstanding); CBSP, DPCB, ISCG and HLSR are among the sources; the All-India page (`/enroute`) shows the same shared-source table as before the change.

- [ ] **Step 7: Commit** — "Pending Indents page: ODR list stored and shown by source, plant and steel wagon type".

---

### Task 5: Excel and PDF downloads

**Files:**
- Create: `indent_exports.py`
- Modify: `app.py` (routes after `/indents`), `tests/test_indents_app.py`

**Interfaces:**
- Consumes: `indents_data()` (Task 4); from `inbound_exports`: `NAVY`, `pdf_styles`, `put_text`, `style_row`, `text_cell` (as `commodity_exports.py` does).
- Produces: `indent_exports.build_excel(data) -> bytes` (sheets "Sources", "Plants", "Steel", each with a title line giving the list's date and time, the same columns as the page tables 1–3, flagged rows filled), `indent_exports.build_pdf(data) -> bytes` (A4 landscape, the same three tables). Routes `GET /indents/report.xlsx` and `/indents/report.pdf`: `404` with "No ODR list has been received yet." when there is none; file name `pending_indents_YYYYMMDD_HHMM` + extension.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_indents_app.py`):

```python
import io
from openpyxl import load_workbook

def test_downloads(client):
    assert client.get("/indents/report.xlsx").status_code == 404
    client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}, headers=AUTH)
    excel = client.get("/indents/report.xlsx")
    assert excel.status_code == 200
    book = load_workbook(io.BytesIO(excel.data))
    assert book.sheetnames == ["Sources", "Plants", "Steel"]
    cells = [c.value for r in book["Sources"].iter_rows() for c in r if c.value is not None]
    assert any("CBSP" in str(v) for v in cells) and "SAIL pending" in cells
    pdf = client.get("/indents/report.pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert "pending_indents_" in excel.headers["Content-Disposition"]
```

- [ ] **Step 2: Run** `.\venv\Scripts\python.exe -m pytest tests/test_indents_app.py::test_downloads -v`. Expected: FAIL (routes missing).
- [ ] **Step 3: Implement** `indent_exports.py` and the two routes, following `inbound_download` in `app.py`.
- [ ] **Step 4: Run** `.\venv\Scripts\python.exe -m pytest tests -v`. Expected: 16 passed.
- [ ] **Step 5: Commit** — "Pending Indents: Excel and PDF report".

---

### Task 6: Chrome extension sends the ODR list

**Files:**
- Modify: `chrome_extension/extract.js`, `chrome_extension/popup.js`, `chrome_extension/popup.html`, `chrome_extension/manifest.json`, `README.md`

**Interfaces:**
- Consumes: `POST /api/odr` (Task 4), which returns `{"received", "inserted", "indents"}`.
- Produces: extension version `1.7.0`.

- [ ] **Step 1: `extract.js`** — add to `REPORTS`: `odr: ["sttn_from", "demand_no", "demand_date", "cnsg", "indented_units", "ostg_units", "demand_id"]`. Second-part rows have a blank SR.NO.; they already pass the existing filters (same cell count, some cell filled), so no other change is needed. Confirm by reading the filters; do not add an SR.NO. requirement.
- [ ] **Step 2: `popup.js`** — add `odr: { label: "ODR Rake Outstanding", url: "http://127.0.0.1:5000/api/odr" }` to `REPORTS`; in `send()`, add a branch for `table.report === "odr"` showing `Sent ${result.indents} indents. This is now the latest ODR list.`; add "ODR Wise Rake Outstanding Details" to the "No rake table found" hint. The automatic 5-hourly resend stays In-Bound only.
- [ ] **Step 3: `manifest.json`** — version `1.7.0`; description names the ODR list too. Update any report names listed in `popup.html`.
- [ ] **Step 4: `README.md`** — a short "Pending indents" section: open the ODR page on FOIS, click Send, see `/indents`; or upload the CSV on that page. Add a "Tests" line: `.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt` then `.\venv\Scripts\python.exe -m pytest tests`.
- [ ] **Step 5: Verify by hand.** Reload the extension in `chrome://extensions`, open the ODR page on FOIS with results shown, click the extension. Expected: popup says "ODR Rake Outstanding" with the row count; after Send, "Sent N indents…"; `/indents` shows the new list's time. Also open the Loaded In-Bound page and confirm it is still recognised as In-Bound. This step needs the user's FOIS login; if it cannot be done in the session, say so in the hand-over and leave it for the user.
- [ ] **Step 6: Commit** — "Extension 1.7.0 sends the ODR Rake Outstanding list".
