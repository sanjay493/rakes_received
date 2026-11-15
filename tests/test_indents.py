from datetime import date

import pytest

import indents

COLUMNS = ["SR.NO.", "DVSN", "STTNFROM", "DEMAND NO.", "DEMAND DATE", "DEMAND TIME", "EXPD LDNG DATE",
           "CNSR", "CNSG", "GRUP RAKE CMDT", "RAKE CMDT", "TT", "PC", "PBF", "VIA", "STTNTO",
           "INDENTED TYPE", "INDENTED UNITS", "INDENTED 8W", "OSTG UNITS", "OSTG 8W",
           "SUPPLIED UNITS", "SUPPLIED TIME", "DEMAND ID"]


def row(sr, source, demand_date, cnsr, cnsg, group, cmdt, to, wagon, indented, ostg,
        supplied_time="", demand_id="X1"):
    """One ODR row. A blank sr makes a second-part row, with the indent's own fields left blank."""
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


# ---------- reading the list ----------

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


# ---------- the rules ----------

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
        rows = indents.read_odr_rows(
            COLUMNS, [row("1", "FOS", demand_date, "SAIL", "SAIL", "ORES", "IOST", "IISD", "BOXNHL", 59, 59)])
        return indents.build_indents(rows, LIST_DATE, PLANTS)[0]
    assert [one(d)["bucket"] for d in ("13-11-26", "12-11-26", "08-11-26", "07-11-26", "31-10-26", "30-10-26")] == \
           ["0–2", "3–7", "3–7", "8–15", "8–15", ">15"]
    unreadable = one("xx")
    assert unreadable["status"] == "pending" and unreadable["age"] is None and unreadable["bucket"] is None
    assert one("20-11-26")["age"] == 0                 # a date after the list


# ---------- the tables ----------

NAMES = {"IMCL": "IMPORTED COAL", "IOST": "IRON ORE", "IS": "STEEL"}


def name(code):
    return NAMES.get(code, code)


def label(code):
    return f"{code} name"


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
    rows = indents.read_odr_rows(
        COLUMNS, [row("1", "FOS", "xx", "SAIL", "SAIL", "ORES", "IOST", "IISD", "BOXNHL", 59, 59)])
    total = indents.summary(indents.build_indents(rows, LIST_DATE, PLANTS))
    assert total["inward_pending"] == 1 and total["oldest"] is None


def test_steel_rows_ignore_the_order_of_wagon_types():
    rows = indents.read_odr_rows(COLUMNS, [
        row("1", "BSCS", "12-11-26", "SAIL", "SAIL", "IS", "IS", "CDG", "BOST", 18, 18),
        row("", "", "", "", "", "", "IS", "DDL", "BRN", 25, 25),
        row("2", "BSCS", "13-11-26", "SAIL", "SAIL", "IS", "IS", "CDG", "BRN", 18, 18),
        row("", "", "", "", "", "", "IS", "DDL", "BOST", 25, 25),
    ])
    steel = indents.steel_report(indents.build_indents(rows, LIST_DATE, PLANTS), label)
    assert [(r["wagon"], r["pending"]) for r in steel] == [("BOST + BRN", 2)]


def test_plant_pipeline_leaves_out_rows_with_nothing_pending_or_on_the_way():
    rows = indents.plant_pipeline(
        [], {("IRON ORE", "BSP"): 3}, {("FURNACE OIL", "BSP"): {"per_day": 0.1, "yesterday": 0}},
        name, {"BSPC": "BSP"})
    assert [(r["plant"], r["commodity"]) for r in rows] == [("BSP", "IRON ORE")]


def test_steel_sent_by_sail_from_a_siding_outside_the_plant_list_is_steel_going_out():
    rows = indents.read_odr_rows(
        COLUMNS, [row("1", "SCOB", "12-11-26", "SAIL", "SAIL", "IS", "IS", "KKU", "BOST", 45, 45)])
    built_rows = indents.build_indents(rows, LIST_DATE, PLANTS)
    assert built_rows[0]["steel_out"] is True
    assert indents.source_report(built_rows, None, name, label) == []
    assert [r["plant"] for r in indents.steel_report(built_rows, label)] == ["SCOB name"]


# ---------- found in review ----------

def test_indent_with_blank_units_is_still_pending():
    def status(indented, ostg):
        rows = indents.read_odr_rows(
            COLUMNS, [row("1", "FOS", "12-11-26", "SAIL", "SAIL", "ORES", "IOST", "IISD", "BOXNHL", indented, ostg)])
        return indents.build_indents(rows, LIST_DATE, PLANTS)[0]["status"]
    assert status("", "") == "pending"        # units not shown: still an indent waiting for a rake
    assert status("", 58) == "pending"
    assert status(58, 0) == "done"


def test_sr_no_heading_is_required():
    columns = ["SL NO" if c == "SR.NO." else c for c in COLUMNS]
    with pytest.raises(ValueError, match="SR.NO., STTNFROM and DEMAND ID are required"):
        indents.read_odr_rows(columns, ROWS)


def test_units_that_are_not_a_finite_number_count_as_zero():
    rows = indents.read_odr_rows(
        COLUMNS, [row("1", "FOS", "12-11-26", "SAIL", "SAIL", "ORES", "IOST", "IISD", "BOXNHL", "inf", "nan")])
    assert (rows[0]["indented_units"], rows[0]["ostg_units"]) == (0, 0)
