"""The SAIL consignee filter on the In-Bound page, against a database in a temporary folder."""
import io
import os
from datetime import datetime

import pytest
from openpyxl import load_workbook

import app as rakes_app

IMPORTED = datetime(2026, 11, 26, 6, 0)


@pytest.fixture
def client():
    assert os.path.dirname(rakes_app.engine.url.database) == os.environ["DATA_DIR"]
    session = rakes_app.SessionDB()
    session.query(rakes_app.InboundRake).delete()
    session.add_all([
        rake("R-SAIL-BSP", "BSPC", "SAIL"),
        rake("R-SAIL-BSL", "BSCS", " sail "),
        rake("R-TISC-BSP", "BSPC", "TISC"),
        rake("R-BLANK-DSP", "DSEY", None),
    ])
    session.commit()
    session.close()
    return rakes_app.app.test_client()


def rake(rake_id, sttn_to, cnsg):
    return rakes_app.InboundRake(
        imported_at=IMPORTED, rake_id=rake_id, sttn_from="KCCJ", sttn_to=sttn_to, cnsg=cnsg,
        cmdt="COAL", loaded_empty="L", ldng_time="25-11-2026 03:05",
    )


def ids(data):
    return {r.rake_id for r in data["rakes"]}


def test_only_sail_is_listed_by_default(client):
    assert ids(rakes_app.inbound_data("")) == {"R-SAIL-BSP", "R-SAIL-BSL"}
    page = client.get("/inbound").get_data(as_text=True)
    assert "R-SAIL-BSP" in page and "R-TISC-BSP" not in page


def test_all_lists_every_consignee(client):
    data = rakes_app.inbound_data("", "ALL")
    assert ids(data) == {"R-SAIL-BSP", "R-SAIL-BSL", "R-TISC-BSP", "R-BLANK-DSP"}
    assert (data["total"], data["all_consignees_count"], data["sail_count"]) == (4, 4, 2)


def test_sail_filter_lists_only_consignee_sail(client):
    data = rakes_app.inbound_data("", "SAIL")
    assert ids(data) == {"R-SAIL-BSP", "R-SAIL-BSL"}
    assert dict(data["counts"]) == {"BSPC": 1, "BSCS": 1}
    assert data["total"] == 2
    assert data["report"]["totals"]["total"] == 2
    assert data["routes"]["total"] == 2


def test_sail_filter_combines_with_the_destination_filter(client):
    data = rakes_app.inbound_data("BSPC", "SAIL")
    assert ids(data) == {"R-SAIL-BSP"}
    assert (data["all_consignees_count"], data["sail_count"]) == (2, 1)


def test_page_links_keep_both_filters(client):
    page = client.get("/inbound?sttn_to=BSPC&cnsg=ALL").get_data(as_text=True)
    assert "R-SAIL-BSP" in page and "R-TISC-BSP" in page
    assert 'href="/inbound?sttn_to=BSPC"' in page  # SAIL only, same destination
    assert 'href="/inbound?cnsg=ALL"' in page  # All destinations, still all consignees
    assert 'href="/inbound/report.xlsx?sttn_to=BSPC&amp;cnsg=ALL"' in page
    assert 'href="/inbound/report.pdf?sttn_to=BSPC&amp;cnsg=ALL"' in page


def test_destination_without_sail_rakes_says_so_and_offers_all_consignees(client):
    page = client.get("/inbound?sttn_to=DSEY").get_data(as_text=True)
    assert "No SAIL rakes to DSEY in this list." in page
    assert 'href="/inbound?sttn_to=DSEY&amp;cnsg=ALL"' in page


def test_excel_download_is_sail_only_by_default(client):
    download = client.get("/inbound/report.xlsx")
    assert download.status_code == 200
    assert "_SAIL_" in download.headers["Content-Disposition"]
    workbook = load_workbook(io.BytesIO(download.data))
    assert workbook["Rakes in Transit"]["A1"].value == "SAIL Rakes in Transit"
    values = {cell.value for row in workbook["Rake Details"].iter_rows() for cell in row}
    assert "R-SAIL-BSP" in values and "R-TISC-BSP" not in values


def test_excel_download_of_all_consignees(client):
    download = client.get("/inbound/report.xlsx?cnsg=ALL")
    assert "_SAIL_" not in download.headers["Content-Disposition"]
    workbook = load_workbook(io.BytesIO(download.data))
    assert workbook["Rakes in Transit"]["A1"].value == "Rakes in Transit"
    values = {cell.value for row in workbook["Rake Details"].iter_rows() for cell in row}
    assert {"R-SAIL-BSP", "R-TISC-BSP"} <= values


def test_pdf_download(client):
    download = client.get("/inbound/report.pdf")
    assert download.status_code == 200
    assert download.data.startswith(b"%PDF")
