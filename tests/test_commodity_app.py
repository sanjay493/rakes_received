"""Source station names on the Commodity Analysis page, against a database in a temporary folder."""
import io
import os
from datetime import datetime, timedelta

import pytest
from openpyxl import load_workbook

import app as rakes_app

AUTH = {"Authorization": "Bearer test-token"}
MAPPINGS = {"BOCM": "BELPAHAR OPEN CAST MINES", "BOMB": "BELPAHAR OPEN CAST MINES", "BSPC": "BHILAI SIDING"}


@pytest.fixture
def client(monkeypatch):
    assert os.path.dirname(rakes_app.engine.url.database) == os.environ["DATA_DIR"]
    session = rakes_app.SessionDB()
    for model in (rakes_app.InboundRake, rakes_app.Rake, rakes_app.StationLookup):
        session.query(model).delete()
    session.commit()
    session.close()
    monkeypatch.setattr(rakes_app, "station_mappings", dict(MAPPINGS))
    return rakes_app.app.test_client()


def add(*rows):
    session = rakes_app.SessionDB()
    session.add_all(rows)
    session.commit()
    session.close()


def received(source):
    return rakes_app.Rake(
        received_time=datetime.now() - timedelta(days=1), sttn_from=source, sttn_to="BSP",
        commodity="COAL", transit_time_hrs=20.0,
    )


def on_the_way(source):
    return rakes_app.InboundRake(
        imported_at=datetime(2026, 11, 24, 6, 0), rake_id=f"R-{source}", sttn_from=source,
        sttn_to="BSPC", cmdt="COAL", loaded_empty="L",
    )


def rows():
    data = rakes_app.commodity_analysis_data("COAL", "")
    return {item["source"]: item for items in data["grouped_data"].values() for item in items}


def test_sources_show_name_and_code_or_just_the_code(client):
    add(received("BOCM"), received("KCCJ"))
    assert set(rows()) == {"BELPAHAR OPEN CAST MINES (BOCM)", "KCCJ"}


def test_codes_sharing_a_name_get_their_own_rows(client):
    add(received("BOCM"), received("BOMB"), received("BOMB"))
    counts = {source: item["count_4d"] for source, item in rows().items()}
    assert counts == {"BELPAHAR OPEN CAST MINES (BOCM)": 1, "BELPAHAR OPEN CAST MINES (BOMB)": 2}


def test_rakes_in_transit_join_the_row_of_their_source_code(client):
    add(received("BOCM"), on_the_way("BOCM"), on_the_way("RNG"))
    found = {source: (item["count_4d"], item["in_transit"]) for source, item in rows().items()}
    assert found == {"BELPAHAR OPEN CAST MINES (BOCM)": (1, 1), "RNG": (0, 1)}


def test_outliers_link_uses_the_code_and_finds_its_rakes(client):
    add(received("BOCM"))
    page = client.get("/commodity_analysis?commodity=COAL").get_data(as_text=True)
    assert 'href="/source_outliers/BOCM?' in page
    outliers = client.get("/source_outliers/BOCM?commodity=COAL&destination=BSP").get_data(as_text=True)
    assert "BELPAHAR OPEN CAST MINES (BOCM)" in outliers


def test_excel_download_keeps_a_ticked_source(client):
    add(received("BOCM"), received("KCCJ"))
    download = client.post("/commodity_analysis/report.xlsx", data={
        "commodity": "COAL", "pick": "COAL||BELPAHAR OPEN CAST MINES (BOCM)",
    })
    assert download.status_code == 200
    sheet = load_workbook(io.BytesIO(download.data)).active
    values = {cell.value for row in sheet.iter_rows() for cell in row}
    assert "BELPAHAR OPEN CAST MINES (BOCM)" in values and "KCCJ" not in values


def test_inbound_send_asks_for_names_of_received_rake_sources(client):
    add(received("KCCJ"), received("BOCM"), received("RNG"),
        rakes_app.StationLookup(code="RNG", name=None, fetched_at=datetime(2026, 11, 1)))
    sent = client.post("/api/inbound", headers=AUTH, json={
        "columns": ["RAKE ID", "STTN FROM", "STTN TO"], "rows": [["R1", "BOCM", "BSPC"]],
    })
    # KCCJ has no name yet; BOCM and BSPC have one, and FOIS was already asked about RNG.
    assert sent.get_json()["missing_stations"] == ["KCCJ"]
