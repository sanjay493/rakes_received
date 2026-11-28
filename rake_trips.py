"""Reading FOIS "Get RR" and Rakes Received rows into rake_trips records (dicts of its columns).

A trip's trip_key identifies it, so sending the same row again updates it instead of adding another.
"""
import re
from datetime import datetime

DATE_FORMAT = "%d-%m-%Y"
TIME_FORMAT = "%d-%m-%Y %H:%M"

# The 17 cells of a "Get RR" row, in order.
RR_CELLS = (
    "sttn_from", "sttn_to", "invoice_no", "invoice_date", "rr_no", "rr_date", "cnsr", "cnsg", "cmdt",
    "chargeable_wt", "distance_km", "freight_class", "rate", "rebate_pct", "rebate_amt", "used_by",
    "rebate_head",
)
RR_NUMBERS = ("chargeable_wt", "distance_km", "rate", "rebate_pct", "rebate_amt")
EMPTY_RR_HEAD = "ZERO FREIGHT RR"  # With no commodity, the empty return of the rake

# Rakes Received heading (lower case, without spaces, dots or underscores) -> column
RECEIVED_HEADINGS = {
    "rakeid": "rake_id", "rakename": "rake_name", "raketype": "rake_type", "totlunts": "units",
    "sttnfrom": "sttn_from", "sttnto": "sttn_to", "l/e": "loaded_empty", "cmdt": "cmdt",
    "cnsg": "cnsg", "cnsr": "cnsr", "receivedtime": "received_time", "dispatchedtime": "dispatched_time",
}
REQUIRED_RECEIVED = {
    "rake_id": "RAKE ID", "sttn_from": "STTN FROM", "sttn_to": "STTN TO",
    "received_time": "RECEIVED TIME", "dispatched_time": "DISPATCHED TIME",
}


def clean_rake_id(value):
    """A Rake ID in upper case with single spaces, or None if there isn't one."""
    if not isinstance(value, str):
        return None
    return " ".join(value.split()).upper() or None


def _text(value):
    """A cell's text with single spaces, or None when blank."""
    if value is None:
        return None
    return " ".join(str(value).split()) or None


def _number(value):
    try:
        return float(value.replace(",", "")) if value else None
    except ValueError:
        return None


def _moment(value, pattern):
    try:
        return datetime.strptime(value, pattern) if value else None
    except ValueError:
        return None


def _date(value):
    moment = _moment(value, DATE_FORMAT)
    return moment.date() if moment else None


def _key(*parts):
    return "|".join("" if part is None else str(part) for part in parts)


def read_rr_rows(rake_id, rows):
    """Records for one rake's "Get RR" rows. Returns (records, number of unreadable rows)."""
    rake_id = clean_rake_id(rake_id)
    records, unreadable = [], 0
    for row in rows:
        if not isinstance(row, list) or len(row) != len(RR_CELLS):
            unreadable += 1
            continue
        trip = dict(zip(RR_CELLS, map(_text, row)))
        trip["invoice_date"] = _date(trip["invoice_date"])
        if not (rake_id and trip["sttn_from"] and trip["sttn_to"] and trip["invoice_date"]):
            unreadable += 1
            continue
        trip["rr_date"] = _date(trip["rr_date"])
        for name in RR_NUMBERS:
            trip[name] = _number(trip[name])
        empty = (trip["rebate_head"] or "").upper() == EMPTY_RR_HEAD and not trip["cmdt"]
        trip.update(
            source="rr",
            rake_id=rake_id,
            loaded_empty="E" if empty else "L",
            trip_date=trip["invoice_date"],
            trip_key=_key("rr", rake_id, trip["sttn_from"], trip["invoice_no"],
                          trip["invoice_date"].isoformat(), trip["rr_no"],
                          trip["rr_date"] and trip["rr_date"].isoformat()),
        )
        records.append(trip)
    return records, unreadable


def _heading(name):
    return re.sub(r"[\s._]", "", str(name).lower())


def read_received_rows(columns, rows):
    """Records for Rakes Received rows. Returns (records, number of unreadable rows).
    Raises ValueError if the table lacks a heading it needs."""
    fields = [RECEIVED_HEADINGS.get(_heading(column)) for column in columns]
    missing = [heading for field, heading in REQUIRED_RECEIVED.items() if field not in fields]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")

    records, unreadable = [], 0
    for row in rows:
        if not isinstance(row, list) or len(row) != len(fields):
            unreadable += 1
            continue
        trip = {field: _text(value) for field, value in zip(fields, row) if field}
        trip["rake_id"] = clean_rake_id(trip["rake_id"])
        for name in ("received_time", "dispatched_time"):
            trip[name] = _moment(trip[name], TIME_FORMAT)
        moment = trip["dispatched_time"] or trip["received_time"]
        if not (trip["rake_id"] and trip["sttn_from"] and trip["sttn_to"] and moment):
            unreadable += 1
            continue
        trip.update(
            source="received",
            trip_date=moment.date(),
            trip_key=_key("received", trip["rake_id"], trip["sttn_from"], trip["sttn_to"], moment.isoformat()),
        )
        records.append(trip)
    return records, unreadable
