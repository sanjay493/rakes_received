"""Rules of the Raw Material Status page."""
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


def coal(wagons, *parts):
    return Rake(plant="BSP", section="Coal", wagons=wagons, parts=list(parts))


def test_summary_counts_each_part_as_its_share_of_the_rake():
    rakes = [coal(58, ("PCC", 24), ("B", 34)), coal(58, ("PCC", 58)), coal(38, ("PCC", 38)),
             coal(58, ("PCC", 37), ("B", 21)), coal(None)]
    [block] = rules.summary(rakes, ["BSP", "RSP"])
    assert (block["rakes"], block["wagons"], block["tonnes"]) == (5, 212, 212 * 70)
    pcc, b, not_entered = block["lines"]
    # 24/58 + 58/58 + 38/38 + 37/58
    assert (pcc["name"], round(pcc["rakes"], 2), pcc["wagons"], pcc["tonnes"]) == ("PCC", 3.05, 157, 10990)
    assert (b["name"], round(b["rakes"], 2), b["wagons"], b["tonnes"]) == ("B", 0.95, 55, 3850)
    assert not_entered == {"name": "Not entered", "rakes": 1, "wagons": 0, "tonnes": 0}


def test_summary_runs_coal_first_then_plants_with_pcc_mcc_midling_in_order():
    def one(plant, section, *names):
        return Rake(plant=plant, section=section, wagons=len(names) or 58, parts=[(name, 1) for name in names])

    blocks = rules.summary([
        one("BSP", "Iron Ore", "Fines"), one("BSP", "Imported Coal", "Soft"), one("DSP", "Coal", "PCC"),
        one("BSP", "Coal", "midling", "IPT-Coke", "MCC", "PCC"), one("BSP", "Coal"),
    ], ["BSP", "DSP"])
    assert [(block["section"], block["plant"]) for block in blocks] == [
        ("Coal", "BSP"), ("Coal", "DSP"), ("Imported Coal", "BSP"), ("Iron Ore", "BSP")]
    assert [line["name"] for line in blocks[0]["lines"]] == ["PCC", "MCC", "midling", "IPT-Coke", "Not entered"]
    # Rows the commodity's cell spans (each plant's lines and total), on its first plant only.
    assert [block["section_rows"] for block in blocks] == [8, 0, 2, 2]


def test_summary_shares_add_up_to_one_rake_when_wagons_have_changed():
    # FOIS now shows 57 wagons for a rake entered with 58.
    [block] = rules.summary([coal(57, ("A", 29), ("B", 29))], ["BSP"])
    assert [line["rakes"] for line in block["lines"]] == [0.5, 0.5]


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
