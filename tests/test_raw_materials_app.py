"""The Raw Material Status page, against a database in a temporary folder."""
import os

import pytest

import app as rakes_app

AUTH = {"Authorization": "Bearer test-token"}
HEADINGS = ["RAKE ID", "STTN FROM", "STTN TO", "CMDT", "L/E", "LDNG TIME", "DEPT TIME", "TOTL UNTS", "CRNT LOCN", "STTS CODE",
            "CNSG"]


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


def rake(rake_id="R1", dest="HSPG", cmdt="IOST", empty="L", ldng="23-11-2026 10:00", dept="", units="58+1", at="DMTO",
         cnsg="SAIL"):
    return [rake_id, "BSUA", dest, cmdt, empty, ldng, dept, units, at, "DP", cnsg]


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


def test_only_consignee_sail_is_listed(client):
    send(client, rake("KEEP", cnsg=" sail "), rake("NSPL", cnsg="NSPL", at="XXXX"), rake("BLANK", cnsg=""))
    assert listed() == ["KEEP"]
    assert "NSPL" not in client.get("/raw_materials").get_data(as_text=True)
    # A rake that isn't listed takes no entry.
    assert save(client, ["A"], ["58"], rake_id="NSPL").status_code == 409


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
    assert (first.loaded, first.source, first.location, first.wagons) == (
        "23-11-2026 10:00", "BARSUA (BSUA)", "DUMETRA (DMTO)", 58)
    assert second.wagons is None
    assert ">23-11-2026 10:00</td>" in client.get("/raw_materials").get_data(as_text=True)
    assert "Not entered" in client.get("/raw_materials").get_data(as_text=True)


def test_inbound_send_asks_for_unnamed_current_locations(client):
    result = send(client, rake(at="XXXX"), rake("P", cmdt="PIOR", at="YYYY"))
    assert result["missing_stations"] == ["XXXX"]


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


def test_inbound_send_accepts_values_that_are_not_text(client):
    send(client, rake())
    save(client, ["A"], ["58"])  # With an entry saved, the next send also compares the two lists.
    numbers = [7, 8, 123, 5, 0, 20261123, 1, 58, 9, 2, 3]
    assert send(client, numbers, rake(cmdt=5), rake(rake_id=7, dest="HSPG", ldng=20261123))["inserted"] == 3


def test_summary_table_shows_rake_shares_wagons_and_tonnage(client):
    send(client, rake())
    save(client, ["A", "B"], ["24", "34"])
    page = " ".join(client.get("/raw_materials").get_data(as_text=True).split())
    assert "Tonnage (T)" in page and "<th>Commodity</th><th>Plant</th>" in page
    assert '<th rowspan="3">Iron Ore</th> <th rowspan="3"><a href="#rakes-RSP-iron-ore"' in page
    assert '<td>A</td> <td class="num">0.41</td> <td class="num">24</td> <td class="num">1680</td>' in page
    assert '<td class="num">1.00</td> <td class="num">58</td> <td class="num">4060</td>' in page


def test_summary_plant_names_link_to_their_rakes(client):
    send(client, rake("ORE"), rake("IMP", cmdt="IMCL"))
    page = client.get("/raw_materials").get_data(as_text=True)
    for anchor in ("rakes-RSP-iron-ore", "rakes-RSP-imported-coal"):
        assert f'href="#{anchor}"' in page and f'id="{anchor}"' in page
    # With only those not entered listed, a fully entered group isn't below: its link shows all rakes.
    save(client, ["A"], ["58"], rake_id="ORE")
    page = client.get("/raw_materials?plant=RSP&missing=1").get_data(as_text=True)
    assert 'href="/raw_materials?plant=RSP#rakes-RSP-iron-ore"' in page and 'id="rakes-RSP-iron-ore"' not in page
    assert 'href="#rakes-RSP-imported-coal"' in page


def test_isp_imported_coal_shows_its_siding_after_the_source(client):
    send(client, rake("BURN", dest="BCME", cmdt="IMCL"), rake("IISCO", dest="IISD", cmdt="IMCL"),
         rake("ORE", dest="IISD"), rake("RSP", dest="HSPG", cmdt="IMCL"))
    sidings = {r.rake_id: r.siding for r in rakes_app.raw_material_data()["rakes"]}
    assert sidings == {"BURN": "BCME", "IISCO": "IISD", "ORE": None, "RSP": None}
    page = " ".join(client.get("/raw_materials").get_data(as_text=True).split())
    assert "BARSUA (BSUA) &rarr; BCME</td>" in page and "BARSUA (BSUA) &rarr; IISD</td>" in page
    assert page.count("&rarr;") == 2


def test_saved_rake_stays_in_view_under_the_not_entered_filter(client):
    send(client, rake(), rake("R2"))
    reply = save(client, ["A"], ["58"], missing="1")
    page = client.get(reply.location).get_data(as_text=True)
    assert 'id="rake-R1-BSUA-23-11-2026-10-00"' in page and 'id="rake-R2-BSUA-23-11-2026-10-00"' in page
