"""The ODR import and the Pending Indents page, against a copy of the database in a temporary folder."""
import io
import os

import pytest
from openpyxl import load_workbook

import app as rakes_app
from test_indents import COLUMNS, ROWS

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client():
    assert os.path.dirname(rakes_app.engine.url.database) == os.environ["DATA_DIR"]
    session = rakes_app.SessionDB()
    for model in (rakes_app.OdrIndent, rakes_app.InboundRake, rakes_app.Rake):
        session.query(model).delete()
    session.commit()
    session.close()
    return rakes_app.app.test_client()


def send(client):
    return client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}, headers=AUTH)


def test_page_before_any_list(client):
    page = client.get("/indents")
    assert page.status_code == 200 and b"No ODR list has been received yet" in page.data


def test_import_needs_token_and_headings(client):
    assert client.post("/api/odr", json={"columns": COLUMNS, "rows": ROWS}).status_code == 401
    bad = client.post("/api/odr", json={"columns": ["SR.NO."], "rows": [["1"]]}, headers=AUTH)
    assert bad.status_code == 400 and "STTNFROM and DEMAND ID are required" in bad.get_json()["error"]


def test_import_twice_shows_latest_list_only(client):
    assert send(client).get_json() == {"received": 7, "inserted": 7, "indents": 6}
    send(client)
    data = rakes_app.indents_data()
    assert data["summary"]["inward_pending"] == 2 and data["summary"]["steel_pending"] == 1
    assert all(i["sail"] for i in data["all"])
    assert len(rakes_app.indents_data("all")["all"]) == 6
    assert len(rakes_app.indents_data("others")["all"]) == 1


def test_page_without_inbound_history_shows_dashes(client):
    send(client)
    data = rakes_app.indents_data()
    assert all(r["loaded_others"] is None and not r["flag"] for r in data["sources"])
    assert client.get("/indents").status_code == 200


def test_import_leaves_other_tables_alone(client):
    session = rakes_app.SessionDB()
    session.add(rakes_app.InboundRake(
        imported_at=rakes_app.datetime(2026, 11, 15, 6, 0), rake_id="R1", sttn_to="BSPC"))
    session.commit()
    session.close()
    send(client)
    session = rakes_app.SessionDB()
    assert session.query(rakes_app.InboundRake).count() == 1
    session.close()


def test_downloads(client):
    assert client.get("/indents/report.xlsx").status_code == 404
    send(client)
    excel = client.get("/indents/report.xlsx")
    assert excel.status_code == 200
    book = load_workbook(io.BytesIO(excel.data))
    assert book.sheetnames == ["Sources", "Plants", "Steel"]
    cells = [c.value for r in book["Sources"].iter_rows() for c in r if c.value is not None]
    assert any("CBSP" in str(v) for v in cells) and "SAIL pending" in cells
    pdf = client.get("/indents/report.pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert "pending_indents_" in excel.headers["Content-Disposition"]
