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


def test_both_endpoints_say_when_the_server_has_no_token(client, monkeypatch):
    monkeypatch.setattr(rakes_app, "API_TOKEN", None)
    for response in (client.get("/api/rake_ids", headers=AUTH), send_rr(client, [LOADED])):
        assert response.status_code == 503 and "no API_TOKEN set" in response.get_json()["error"]


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
