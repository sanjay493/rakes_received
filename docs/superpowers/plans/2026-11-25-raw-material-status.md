# Raw Material Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/raw_materials` page showing loaded Iron Ore, Coal and Imported Coal rakes plant by plant, with manually entered sub-commodities that stay with each rake until it leaves the In-Bound list.

**Architecture:** Pure rules (sections, wagon counts, form checks, summary, trip matching) go in a new `raw_materials.py`, like `indents.py`. `app.py` gets one table, the page data, the route and a hook in the In-Bound import. One server-rendered template serves desktop and phone.

**Tech Stack:** Flask, SQLAlchemy (SQLite), Jinja, a few lines of plain JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-raw-material-status-design.md`

## Global Constraints

- Page `/raw_materials`, titled "Raw Material Status", linked in the menu.
- Rakes: latest In-Bound list, `STTN TO` in `DESTINATION_PLANTS`, `L/E` not `E`, commodity name in a section.
- Sections: "Iron Ore" = `IRON ORE`; "Coal" = `COAL`, `NON PROGRAMMED COAL`; "Imported Coal" = `IMPORTED COAL`.
- Order: plants BSP, DSP, RSP, BSL, ISP; sections as above; nearest first, unknown distance last.
- Stations show as `station_label(code)`: `Name (CODE)`.
- No Excel/PDF, bulk entry, upload, or record of who entered. No new dependencies.
- A form line left completely empty (no name, no wagons) is ignored.
- Do not commit unless the user asks. The working tree already has uncommitted changes; leave them.
- Run tests with `./venv/Scripts/python.exe -m pytest -q`. `tests/conftest.py` already points the app at a temporary database.

## Review Focus

1. The list changes between opening the page and saving: nothing is saved, and the page says so (Task 3).
2. An empty extra line, or wagons such as `29.5` or `abc`: ignored or a form error, never a crash (Task 1).
3. A rake with a blank Rake ID: listed, with no Add button, and a POST for it saves nothing (Task 3).
4. `TOTL UNTS` blank or unreadable: wagons show "—" and the total check is skipped (Tasks 1, 2).
5. No In-Bound list yet: the page loads and says so (Task 2).

---

### Task 1: Rules

**Files:** Create `raw_materials.py`, `tests/test_raw_materials.py`

**Interfaces (Produces):**
- `SECTIONS`: tuple of `(section, commodity_names)` in page order; `NOT_ENTERED = "Not entered"`; `MAX_NAME = 80`
- `section_of(commodity: str) -> str | None`
- `wagon_count(units: str | None) -> int | None`: the leading whole number
- `trip_key(rake) -> tuple[str, str, str]`: `(rake_id, sttn_from, ldng_time)`, stripped, source upper-cased
- `check_lines(names: list[str], counts: list[str], wagons: int | None, known: list[str]) -> tuple[list[tuple[str, int]], list[str]]`: `(lines, errors)`
- `summary(rakes, plants: list[str]) -> list[dict]`: reads `.plant`, `.section`, `.wagons`, `.parts` (`[(name, wagons)]`); returns `{"plant", "section", "rakes", "wagons", "lines": [{"name", "rakes", "wagons"}]}`
- `moved_entries(trips: set[tuple[str, str, str, str]], previous, latest) -> dict[tuple[str, str, str], str]`: `trips` are `(rake_id, source, destination, ldng_time)`; returns `{trip_key: new_ldng_time}`

- [ ] **Step 1: Write the failing tests**

```python
from types import SimpleNamespace as Rake
import pytest
import raw_materials as rules

def test_sections():
    assert rules.section_of("NON PROGRAMMED COAL") == "Coal"
    assert rules.section_of("IMPORTED COAL") == "Imported Coal"
    assert rules.section_of("PELLET") is None

def test_wagon_count():
    assert rules.wagon_count("58+1") == 58
    assert rules.wagon_count("") is None and rules.wagon_count(None) is None and rules.wagon_count("x") is None

def test_good_lines_are_tidied_and_reuse_known_spelling():
    assert rules.check_lines(["  full   lump ", ""], ["58", ""], 58, ["Full Lump"]) == ([("Full Lump", 58)], [])

@pytest.mark.parametrize("names, counts, error", [
    ([""], [""], "Enter at least one sub-commodity."),
    ([""], ["58"], "Enter a sub-commodity on every line."),
    (["A"], ["29.5"], "Wagons must be a whole number above 0."),
    (["A"], ["abc"], "Wagons must be a whole number above 0."),
    (["A"], ["0"], "Wagons must be a whole number above 0."),
    (["A"], [""], "Wagons must be a whole number above 0."),
    (["A", "a"], ["30", "28"], "a is entered twice."),
    (["A", "B"], ["30", "20"], "Wagons add up to 50, but the rake has 58."),
])
def test_bad_lines(names, counts, error):
    assert error in rules.check_lines(names, counts, 58, [])[1]

def test_total_is_not_checked_without_a_wagon_count():
    assert rules.check_lines(["A"], ["12"], None, []) == ([("A", 12)], [])

def test_summary_counts_a_mixed_rake_under_each_part():
    rakes = [Rake(plant="RSP", section="Coal", wagons=58, parts=[("B", 28), ("A", 30)]),
             Rake(plant="RSP", section="Coal", wagons=58, parts=[("A", 58)]),
             Rake(plant="RSP", section="Coal", wagons=None, parts=[])]
    [block] = rules.summary(rakes, ["BSP", "RSP"])
    assert (block["rakes"], block["wagons"]) == (3, 116)
    assert block["lines"] == [{"name": "A", "rakes": 2, "wagons": 88}, {"name": "B", "rakes": 1, "wagons": 28},
                              {"name": "Not entered", "rakes": 1, "wagons": 0}]

def row(ldng, dept="", dest="BSPC", rake_id="R1"):
    return Rake(rake_id=rake_id, sttn_from="RSDG", sttn_to=dest, ldng_time=ldng, dept_time=dept)

TRIP = {("R1", "RSDG", "BSPC", "T1")}

def test_entry_follows_a_revised_loading_time_before_departure():
    assert rules.moved_entries(TRIP, [row("T1")], [row("T2", "D")]) == {("R1", "RSDG", "T1"): "T2"}

@pytest.mark.parametrize("previous, latest", [
    ([row("T1", "D")], [row("T2")]),              # had departed: a new trip
    ([], [row("T2")]),                            # not in the list before
    ([row("T0")], [row("T2")]),                   # list before had another loading time
    ([row("T1")], [row("T2", dest="HSPG")]),      # destination differs
    ([row("T1")], [row("T1")]),                   # nothing changed
    ([row("T1")], [row("")]),                     # new loading time blank
    ([row("T1")], [row("T2"), row("T1")]),        # old trip still listed
])
def test_entry_stays_where_it_is(previous, latest):
    assert rules.moved_entries(TRIP, previous, latest) == {}
```

- [ ] **Step 2:** Run `./venv/Scripts/python.exe -m pytest tests/test_raw_materials.py -q`. Expected: fails, no module `raw_materials`.
- [ ] **Step 3:** Implement the interfaces. `check_lines` reports each distinct error once, and checks the total only when every line is otherwise valid. Names are whitespace-collapsed, capped at `MAX_NAME`, and compared case-insensitively. `summary`: blocks in `plants` order then `SECTIONS` order, only non-empty ones; lines sorted by name ignoring case, `NOT_ENTERED` last; block wagons is the sum of each rake's `wagons`, or of its parts when `wagons` is None.
- [ ] **Step 4:** Run the same command. Expected: PASS.

### Task 2: Table, page and station names

**Files:** Modify `app.py` (model after `OdrIndent`; `missing_station_codes`; endpoint after `inbound_pdf`), `templates/base.html` (menu link after In-Bound). Create `templates/raw_materials.html`, `tests/test_raw_materials_app.py`.

**Interfaces:**
- Consumes: Task 1; `commodity_name`, `station_label`, `distance_left_km`, `loading_date`, `plant_sort_key`, `is_stabled`, `DESTINATION_PLANTS`, `PLANTS`.
- Produces:
  - `RakeSubCommodity`, table `rake_sub_commodities`: `id`, `rake_id`, `sttn_from`, `sttn_to`, `ldng_time`, `line_no`, `section`, `sub_commodity`, `wagons`, `entered_at`
  - `raw_material_section(rake) -> str | None`: None unless a plant yard, not empty, and in a section
  - `raw_material_data(plant: str = "", missing_only: bool = False) -> dict` with `imported_at`, `rakes`, `summary`, `suggestions` (`{section: [names]}`, sorted), `plants`, `plant`, `missing_only`. Each rake gains `plant`, `section`, `wagons`, `parts`, `distance_km`, `source`, `location`, `loaded`, `stabled`, `check_wagons`, `can_enter` (Rake ID not blank), `anchor` (HTML id from `trip_key`)
  - `GET /raw_materials?plant=RSP&missing=1`, endpoint `raw_material_status`

- [ ] **Step 1: Write the failing tests**

```python
"""The Raw Material Status page, against a database in a temporary folder."""
import os
import pytest
import app as rakes_app

AUTH = {"Authorization": "Bearer test-token"}
HEADINGS = ["RAKE ID", "STTN FROM", "STTN TO", "CMDT", "L/E", "LDNG TIME", "DEPT TIME", "TOTL UNTS", "CRNT LOCN", "STTS CODE"]

@pytest.fixture
def client(monkeypatch):
    assert os.path.dirname(rakes_app.engine.url.database) == os.environ["DATA_DIR"]
    session = rakes_app.SessionDB()
    for model in (rakes_app.RakeSubCommodity, rakes_app.InboundRake, rakes_app.Rake,
                  rakes_app.RailDistance, rakes_app.StationLookup):
        session.query(model).delete()
    session.commit()
    session.close()
    monkeypatch.setattr(rakes_app, "commodity_mappings",
                        {"IOST": "IRON ORE", "STC": "COAL", "IMCL": "IMPORTED COAL", "PIOR": "PELLET"})
    monkeypatch.setattr(rakes_app, "station_mappings", {"BSUA": "BARSUA", "DMTO": "DUMETRA", "HSPG": "ROURKELA SIDING"})
    return rakes_app.app.test_client()

def rake(rake_id="R1", dest="HSPG", cmdt="IOST", empty="L", ldng="23-11-2026 10:00", dept="", units="58+1", at="DMTO"):
    return [rake_id, "BSUA", dest, cmdt, empty, ldng, dept, units, at, "DP"]

def send(client, *rows):
    reply = client.post("/api/inbound", json={"columns": HEADINGS, "rows": list(rows)}, headers=AUTH)
    assert reply.status_code == 200
    return reply.get_json()

def listed(**filters):
    return [r.rake_id for r in rakes_app.raw_material_data(**filters)["rakes"]]

def test_page_before_any_list(client):
    page = client.get("/raw_materials")
    assert page.status_code == 200 and b"No In-Bound list has been received yet" in page.data

def test_only_loaded_ore_and_coal_to_plants(client):
    send(client, rake("KEEP"), rake("EMPTY", empty="E"), rake("PELLET", cmdt="PIOR"), rake("AGENT", dest="PMRN"))
    assert listed() == ["KEEP"]

def test_order_and_filters(client):
    session = rakes_app.SessionDB()
    session.add(rakes_app.RailDistance(from_code="DMTO", to_code="HSPG", km=8, fetched_at=rakes_app.datetime(2026, 11, 1)))
    session.commit()
    session.close()
    send(client, rake("IMP", cmdt="IMCL"), rake("FAR", at="XXXX"), rake("NEAR"),
         rake("COAL", cmdt="STC"), rake("BHILAI", dest="BSPC"))
    assert listed() == ["BHILAI", "NEAR", "FAR", "COAL", "IMP"]
    assert listed(plant="BSP") == ["BHILAI"]

def test_row_shows_the_listed_values(client):
    send(client, rake(), rake("R2", units=""))
    first, second = rakes_app.raw_material_data()["rakes"]
    assert (first.loaded, first.source, first.location, first.wagons) == ("23-11", "BARSUA (BSUA)", "DUMETRA (DMTO)", 58)
    assert second.wagons is None
    assert "Not entered" in client.get("/raw_materials").get_data(as_text=True)

def test_inbound_send_asks_for_unnamed_current_locations(client):
    result = send(client, rake(at="XXXX"), rake("P", cmdt="PIOR", at="YYYY"))
    assert result["missing_stations"] == ["XXXX"]
```

- [ ] **Step 2:** Run `./venv/Scripts/python.exe -m pytest tests/test_raw_materials_app.py -q`. Expected: fails, no `RakeSubCommodity`.
- [ ] **Step 3:** Add the model, `raw_material_section`, `raw_material_data` and the route. The summary follows the plant filter and ignores `missing_only`. Parts attach by `trip_key`, ordered by `line_no`. `check_wagons` is true when there are parts, `wagons` is known and the parts' total differs.
- [ ] **Step 4:** In `missing_station_codes`, also collect `crnt_locn` of rakes with a `raw_material_section`; add that to its docstring and to the README's Station Help paragraph.
- [ ] **Step 5:** Write the template: heading with the list's date and time (or "No In-Bound list has been received yet."), plant buttons (`.unit-buttons`) and a "Show only not entered" toggle, the summary table, then one rake table with a heading row per plant and section. Columns: Loaded, Source, Sub-commodity, Wagons, Now at, Km left, Status, Rake ID. Parts show as the name alone for one part matching the rake's wagons, else `Name N` joined by ` + `; "check wagons" in red when flagged; stabled rows shaded `#fef3f2`. Under 700px the same rows stack as labelled cards (CSS only, one set of markup). Add the menu link "Raw Material Status".
- [ ] **Step 6:** Run `./venv/Scripts/python.exe -m pytest -q`. Expected: all PASS.

### Task 3: Add, edit and remove

**Files:** Modify `app.py`, `templates/raw_materials.html`, `tests/test_raw_materials_app.py`

**Interfaces:**
- Consumes: `check_lines`, `trip_key`, `raw_material_data`, `RakeSubCommodity`.
- Produces: `POST /raw_materials` (same endpoint). Fields: `rake_id`, `sttn_from`, `ldng_time`, repeated `sub_commodity` and `wagons`, `action` (`save` | `remove`), `plant`, `missing`. Success: 303 to `url_for("raw_material_status", plant=..., missing=..., _anchor=rake.anchor)`. Invalid: 400, the page with that rake's form open, errors shown and typed values kept. Rake not in the latest list, or blank Rake ID: 409, nothing saved, "This rake is no longer in the latest list. Check it below and enter it again."

- [ ] **Step 1: Write the failing tests**

```python
def save(client, names, counts, rake_id="R1", ldng="23-11-2026 10:00", action="save", **extra):
    return client.post("/raw_materials", data={"rake_id": rake_id, "sttn_from": "BSUA", "ldng_time": ldng,
                       "sub_commodity": names, "wagons": counts, "action": action, **extra})

def parts():
    return {r.rake_id: r.parts for r in rakes_app.raw_material_data()["rakes"]}

def test_save_edit_and_remove_a_mixed_rake(client):
    send(client, rake())
    reply = save(client, ["Full Lump", "Fines"], ["30", "28"], plant="RSP", missing="1")
    assert reply.status_code == 303 and "plant=RSP" in reply.location and "#" in reply.location
    assert parts() == {"R1": [("Full Lump", 30), ("Fines", 28)]}
    assert listed(missing_only=True) == []
    save(client, ["full lump"], ["58"])
    assert parts() == {"R1": [("Full Lump", 58)]}
    assert rakes_app.raw_material_data()["suggestions"]["Iron Ore"] == ["Full Lump"]
    save(client, [], [], action="remove")
    assert parts() == {"R1": []}

def test_invalid_entry_keeps_what_was_typed(client):
    send(client, rake())
    reply = save(client, ["Typed Grade"], ["10"])
    page = reply.get_data(as_text=True)
    assert reply.status_code == 400 and "Wagons add up to 10, but the rake has 58." in page
    assert 'value="Typed Grade"' in page and parts() == {"R1": []}

@pytest.mark.parametrize("rake_id, ldng", [("R1", "01-01-2026 00:00"), ("", "23-11-2026 10:00")])
def test_rake_not_in_the_latest_list_saves_nothing(client, rake_id, ldng):
    send(client, rake(), rake(""))
    reply = save(client, ["A"], ["58"], rake_id=rake_id, ldng=ldng)
    assert reply.status_code == 409 and b"no longer in the latest list" in reply.data
    session = rakes_app.SessionDB()
    assert session.query(rakes_app.RakeSubCommodity).count() == 0
    session.close()

def test_changed_wagon_count_is_flagged(client):
    send(client, rake())
    save(client, ["A"], ["58"])
    send(client, rake(units="57+1"))
    assert rakes_app.raw_material_data()["rakes"][0].check_wagons
    assert "check wagons" in client.get("/raw_materials").get_data(as_text=True)
```

- [ ] **Step 2:** Run the app tests. Expected: new ones fail with 405.
- [ ] **Step 3:** Handle POST. Look the rake up in the latest list by `trip_key`; replace all its rows in one transaction; `remove` deletes them. Known spellings come from saved rows of the rake's section, excluding this trip's own rows.
- [ ] **Step 4:** In the template, give each `can_enter` rake a `<details>` row labelled Add or Edit: lines of a text input (`list` = the section's `<datalist>`) and a number input, a new entry pre-filled with the rake's wagons; "+ Add another" clones an empty line from a `<template>`; Save, and "Remove entry" when it has parts.
- [ ] **Step 5:** Run `./venv/Scripts/python.exe -m pytest -q`. Expected: all PASS.

### Task 4: Keep entries through later sends

**Files:** Modify `app.py` (`import_inbound`), `tests/test_raw_materials_app.py`, `README.md`

**Interfaces:**
- Consumes: `moved_entries`.
- Produces: `carry_sub_commodities(records: list[InboundRake], session) -> None`, called before `session.add_all(records)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_entry_survives_a_revision_before_departure(client):
    send(client, rake(ldng="23-11-2026 23:55"))
    save(client, ["A"], ["58"], ldng="23-11-2026 23:55")
    send(client, rake(ldng="24-11-2026 04:10", dept="24-11-2026 05:00"))
    assert parts() == {"R1": [("A", 58)]}

def test_entry_does_not_pass_to_a_new_trip(client):
    send(client, rake(dept="23-11-2026 11:00"))
    save(client, ["A"], ["58"])
    send(client, rake(ldng="26-11-2026 09:00"))
    assert parts() == {"R1": []}

def test_entry_returns_after_a_partial_send(client):
    send(client, rake())
    save(client, ["A"], ["58"])
    send(client, rake("OTHER"))
    assert listed() == ["OTHER"]
    send(client, rake())
    assert parts() == {"R1": [("A", 58)]}
```

- [ ] **Step 2:** Run the app tests. Expected: the revision test fails (`[]`).
- [ ] **Step 3:** Implement: take the latest saved list as `previous`, call `moved_entries` for the saved entries' trips, and update `ldng_time` on their rows, skipping any target trip that already has an entry. The import's own commit covers the change.
- [ ] **Step 4:** Add a README paragraph beside the In-Bound page's, covering which rakes show, how to enter a mixed rake, and when an entry stays or is asked again.
- [ ] **Step 5:** Run `./venv/Scripts/python.exe -m pytest -q`. Expected: all PASS.
- [ ] **Step 6:** Check the page in a browser against a copy of the real data (set `DATA_DIR` to a temporary folder holding a copy of `rake_data.db`, run on another port): add, edit and remove a mixed rake at desktop and phone widths.
