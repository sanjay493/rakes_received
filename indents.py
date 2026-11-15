"""Pending indents from the FOIS "ODR Wise Rake Outstanding Details" list: reading the rows, the
rules for a pending rake, and the tables on the Pending Indents page. Nothing here knows about
Flask or the database."""
import re
from datetime import datetime

# FOIS heading (lower case, without spaces, dots or underscores) -> field
ODR_HEADINGS = {
    "srno": "sr_no", "dvsn": "dvsn", "sttnfrom": "sttn_from", "demandno": "demand_no",
    "demanddate": "demand_date_text", "demandtime": "demand_time", "expdldngdate": "expd_ldng_date",
    "cnsr": "cnsr", "cnsg": "cnsg", "gruprakecmdt": "grup_cmdt", "rakecmdt": "rake_cmdt",
    "tt": "tt", "pc": "pc", "pbf": "pbf", "via": "via", "sttnto": "sttn_to",
    "indentedtype": "indented_type", "indentedunits": "indented_units", "indented8w": "indented_8w",
    "ostgunits": "ostg_units", "ostg8w": "ostg_8w", "suppliedunits": "supplied_units",
    "suppliedtime": "supplied_time", "demandid": "demand_id",
}
UNIT_FIELDS = ("indented_units", "ostg_units", "supplied_units")
# A second-part row (blank SR.NO.) leaves these blank; they come from the row above it.
FILL_DOWN = (
    "dvsn", "sttn_from", "demand_no", "demand_date_text", "demand_time", "expd_ldng_date",
    "cnsr", "cnsg", "grup_cmdt", "tt", "pc", "pbf", "via", "demand_id",
)


def heading_key(heading):
    return re.sub(r"[\s._]", "", str(heading).lower())


def whole_number(text):
    try:
        return int(float(text))
    except (ValueError, OverflowError):  # Blank, text, or "inf"
        return 0


def demand_date(text):
    """DEMAND DATE ("12-11-26", or with a four-digit year) as a date, or None if it can't be read."""
    for pattern in ("%d-%m-%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def read_odr_rows(columns, rows):
    """The ODR table as one dict per usable row: every ODR_HEADINGS field as text, the units as whole
    numbers, demand_date as a date, and indent_no / part_no. An indent is the run of rows from one
    filled SR.NO. to the next; the rows under it with a blank SR.NO. are its further parts."""
    fields = [ODR_HEADINGS.get(heading_key(column)) for column in columns]
    # Without SR.NO. the rows can't be split into indents: every row would join the first one.
    if "sr_no" not in fields or "sttn_from" not in fields or "demand_id" not in fields:
        raise ValueError("SR.NO., STTNFROM and DEMAND ID are required")

    result = []
    indent_no = 0
    previous = None
    for cells in rows:
        if not isinstance(cells, (list, tuple)) or len(cells) != len(columns):
            continue
        record = {field: "" for field in ODR_HEADINGS.values()}
        for field, cell in zip(fields, cells):
            if field:
                record[field] = "" if cell is None else str(cell).strip()
        if not any(record.values()):
            continue

        if record["sr_no"] or previous is None:
            indent_no += 1
            record["part_no"] = 1
        else:
            record["part_no"] = previous["part_no"] + 1
            for field in FILL_DOWN:
                record[field] = record[field] or previous[field]
        record["indent_no"] = indent_no
        for field in UNIT_FIELDS:
            record[field] = whole_number(record[field])
        record["demand_date"] = demand_date(record["demand_date_text"])
        result.append(record)
        previous = record
    return result


# ------------------ THE RULES ------------------

SAIL = "SAIL"
STEEL_GROUP = "IS"  # GRUP RAKE CMDT of iron and steel
BUCKETS = ["0–2", "3–7", "8–15", ">15"]  # Days an indent has been pending
BUCKET_ENDS = (2, 7, 15)


def bucket_of(age):
    if age is None:
        return None
    for label, end in zip(BUCKETS, BUCKET_ENDS):
        if age <= end:
            return label
    return BUCKETS[-1]


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def indent_status(parts, indented, outstanding):
    """supplied: the rake is placed (a SUPPLIED TIME is shown) though FOIS still shows its wagons
    outstanding until loading is done. pending: at least half the wagons are still outstanding.
    part: fewer than half are. done: none are."""
    if any(part["supplied_time"] for part in parts):
        return "supplied"
    if outstanding * 2 >= indented and (outstanding > 0 or indented == 0):
        return "pending"
    return "part" if outstanding > 0 else "done"


def build_indents(rows, list_date, plants):
    """One dict per indent, in the list's order, from read_odr_rows' rows. list_date is the date of
    the list, for the age; plants are the station codes whose iron and steel loading is steel going out."""
    groups = {}
    for record in rows:
        groups.setdefault(record["indent_no"], []).append(record)

    result = []
    for parts in groups.values():
        first = parts[0]
        source = first["sttn_from"].upper()
        cnsr = first["cnsr"].upper()
        cnsg = first["cnsg"].upper()
        group = first["grup_cmdt"].upper()
        indented = sum(part["indented_units"] for part in parts)
        outstanding = sum(part["ostg_units"] for part in parts)
        age = max((list_date - first["demand_date"]).days, 0) if first["demand_date"] else None
        # Steel loaded at a plant, or sent by SAIL from any other siding of its plants (such as SCOB).
        steel_out = group == STEEL_GROUP and (source in plants or cnsr == SAIL)
        result.append({
            "source": source,
            "cnsr": cnsr,
            "cnsg": cnsg,
            "group": group,
            "pc": first["pc"],
            "dvsn": first["dvsn"],
            "demand_id": first["demand_id"],
            "demand_date": first["demand_date"],
            "cmdt": first["rake_cmdt"].upper(),
            "destinations": unique(part["sttn_to"].upper() for part in parts),
            "wagon_types": unique(part["indented_type"].upper() for part in parts),
            "indented": indented,
            "outstanding": outstanding,
            "status": indent_status(parts, indented, outstanding),
            "age": age,
            "bucket": bucket_of(age),
            "steel_out": steel_out,
            "sail": cnsg == SAIL or (steel_out and cnsr == SAIL),
        })
    return result


# ------------------ THE TABLES ------------------

def empty_buckets():
    return {label: 0 for label in BUCKETS}


def oldest_age(indents):
    ages = [indent["age"] for indent in indents if indent["age"] is not None]
    return max(ages) if ages else None


def count_status(indents, status):
    return sum(indent["status"] == status for indent in indents)


def bucket_counts(indents):
    counts = empty_buckets()
    for indent in indents:
        if indent["bucket"]:
            counts[indent["bucket"]] += 1
    return counts


def source_report(indents, loaded, commodity_name, station_label):
    """A row per source and commodity with a SAIL indent for raw material: SAIL's pending rakes by
    age, the other parties' pending indents there, and the rakes loaded there for SAIL and for others.
    loaded is {(source code, commodity name): {"sail": rakes, "others": rakes}}, or None when there
    is no loading history, which leaves both loaded figures as None."""
    sail = {}
    others = {}
    for indent in indents:
        if indent["steel_out"] or indent["status"] == "done":
            continue
        key = (indent["source"], commodity_name(indent["cmdt"]))
        if indent["sail"]:
            sail.setdefault(key, []).append(indent)
        elif indent["status"] == "pending":
            party = indent["cnsg"] or "—"
            others.setdefault(key, {})
            others[key][party] = others[key].get(party, 0) + 1

    rows = []
    for (source, commodity), group in sail.items():
        pending = [indent for indent in group if indent["status"] == "pending"]
        oldest = oldest_age(pending)
        counts = None if loaded is None else loaded.get((source, commodity), {"sail": 0, "others": 0})
        loaded_others = counts["others"] if counts else None
        rows.append({
            "source": station_label(source),
            "source_code": source,
            "commodity": commodity,
            "wagon_types": sorted({wagon for indent in group for wagon in indent["wagon_types"]}),
            "pending": len(pending),
            "buckets": bucket_counts(pending),
            "oldest": oldest,
            "supplied": count_status(group, "supplied"),
            "part": count_status(group, "part"),
            "others": sorted(others.get((source, commodity), {}).items(), key=lambda kv: (-kv[1], kv[0])),
            "loaded_sail": counts["sail"] if counts else None,
            "loaded_others": loaded_others,
            # SAIL has waited over a week here while rakes were loaded for others.
            "flag": oldest is not None and oldest > 7 and bool(loaded_others),
        })

    commodity_pending = {}
    for line in rows:
        commodity_pending[line["commodity"]] = commodity_pending.get(line["commodity"], 0) + line["pending"]
    rows.sort(key=lambda line: (
        -commodity_pending[line["commodity"]], line["commodity"], -line["pending"], line["source"],
    ))
    return rows


def plant_pipeline(indents, in_transit, received, commodity_name, plant_of):
    """A row per plant and commodity: SAIL's pending indents for it, rakes on the way, and rakes
    received. in_transit is {(commodity name, plant): rakes}; received is {(commodity name, plant):
    {"per_day", "yesterday"}}; plant_of maps a yard or agent code to its plant. A two-point indent
    counts for its first destination."""
    pending = {}
    for indent in indents:
        destination = indent["destinations"][0] if indent["destinations"] else ""
        if indent["sail"] and not indent["steel_out"] and indent["status"] == "pending" and destination in plant_of:
            key = (commodity_name(indent["cmdt"]), plant_of[destination])
            pending[key] = pending.get(key, 0) + 1

    order = {plant: position for position, plant in enumerate(dict.fromkeys(plant_of.values()))}
    keys = sorted(
        # Commodities only received, with nothing pending or on the way, would crowd the table.
        {key for key in set(pending) | set(in_transit) if pending.get(key) or in_transit.get(key)},
        key=lambda key: (order.get(key[1], len(order)), key[1], key[0]),
    )
    return [
        {
            "plant": plant,
            "commodity": commodity,
            "pending": pending.get((commodity, plant), 0),
            "in_transit": in_transit.get((commodity, plant), 0),
            "per_day": received.get((commodity, plant), {}).get("per_day"),
            "yesterday": received.get((commodity, plant), {}).get("yesterday"),
        }
        for commodity, plant in keys
    ]


def steel_report(indents, station_label):
    """A row per plant and wagon type: SAIL's pending indents for steel going out."""
    groups = {}
    for indent in indents:
        if indent["sail"] and indent["steel_out"] and indent["status"] in ("pending", "supplied"):
            groups.setdefault((indent["source"], " + ".join(sorted(indent["wagon_types"]))), []).append(indent)

    rows = []
    for (source, wagon), group in groups.items():
        pending = [indent for indent in group if indent["status"] == "pending"]
        rows.append({
            "plant": station_label(source),
            "wagon": wagon,
            "pending": len(pending),
            "buckets": bucket_counts(pending),
            "oldest": oldest_age(pending),
            "supplied": count_status(group, "supplied"),
        })
    rows.sort(key=lambda line: (line["plant"], line["wagon"]))
    return rows


def summary(indents):
    """The page's top line: SAIL's pending rakes coming in and of steel going out, its supplied and
    part-supplied indents, the other parties' pending indents, and SAIL's oldest pending indent."""
    sail = [indent for indent in indents if indent["sail"]]
    pending = [indent for indent in sail if indent["status"] == "pending"]
    dated = [indent for indent in pending if indent["age"] is not None]
    oldest = max(dated, key=lambda indent: indent["age"]) if dated else None
    return {
        "inward_pending": sum(not indent["steel_out"] for indent in pending),
        "steel_pending": sum(indent["steel_out"] for indent in pending),
        "supplied": count_status(sail, "supplied"),
        "part": count_status(sail, "part"),
        "others_pending": sum(not indent["sail"] and indent["status"] == "pending" for indent in indents),
        "oldest": oldest and {
            "source": oldest["source"], "demand_date": oldest["demand_date"], "age": oldest["age"],
        },
    }
