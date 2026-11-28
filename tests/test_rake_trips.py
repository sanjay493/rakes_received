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
