from flask import Flask, Response, render_template, request, redirect, send_file, jsonify, url_for
import pandas as pd
import plotly.graph_objs as go
import hmac, math, os, io, re, shutil, zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, text, Column, Integer, String, Float, DateTime, UniqueConstraint
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError

from inbound_exports import build_excel, build_pdf
import commodity_exports

# ------------------ APP SETUP ------------------

app = Flask(__name__)

# ------------------ DEPLOYMENT CONFIG ------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Everything the app writes lives in DATA_DIR. In the cloud, point it at a
# persistent volume; container filesystems are wiped on every redeploy.
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", BASE_DIR))
os.makedirs(DATA_DIR, exist_ok=True)

def data_path(filename):
    """Path to a file in DATA_DIR, seeded from the bundled copy if it isn't there yet."""
    path = os.path.join(DATA_DIR, filename)
    bundled = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path) and os.path.exists(bundled):
        shutil.copy2(bundled, path)
    return path

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

# Lets the Chrome extension import rake data without the site password.
# Imports are refused until this is set.
API_TOKEN = os.environ.get("API_TOKEN")

# The Dockerfile sets REQUIRE_AUTH=1 so a deployment can't go public without a password.
if os.environ.get("REQUIRE_AUTH") == "1" and not APP_PASSWORD:
    raise RuntimeError("APP_PASSWORD must be set when REQUIRE_AUTH=1")

@app.before_request
def require_login():
    # The import endpoints check API_TOKEN themselves.
    if not APP_PASSWORD or request.endpoint in (
        "healthz", "import_rakes", "import_inbound", "import_distances", "import_station_names",
    ):
        return None

    auth = request.authorization
    if auth:
        username_ok = hmac.compare_digest((auth.username or "").encode(), APP_USERNAME.encode())
        password_ok = hmac.compare_digest((auth.password or "").encode(), APP_PASSWORD.encode())
        if username_ok and password_ok:
            return None

    return Response(
        "Login required", 401,
        {"WWW-Authenticate": 'Basic realm="Rake Dashboard", charset="UTF-8"'},
    )

# ------------------ DATABASE ------------------

Base = declarative_base()

class Rake(Base):
    __tablename__ = "rakes"

    id = Column(Integer, primary_key=True)
    sr_no = Column(String)

    received_time = Column(DateTime, index=True)
    dispatched_time = Column(DateTime)

    transit_time = Column(String)
    transit_time_hrs = Column(Float)

    sttn_from = Column(String, index=True)
    sttn_to = Column(String, index=True)

    cmdt = Column(String, index=True)
    commodity = Column(String)
    rake_type = Column(String, index=True)

    totl_unts = Column(Integer)

    __table_args__ = (
        UniqueConstraint("received_time", "sttn_from", "sttn_to","cmdt","rake_type","dispatched_time", name="uq_rake_time_to_from_cmdt_type"),
    )

class InboundRake(Base):
    """One row of a FOIS Loaded In-Bound report. Each import adds a new list; times stay as FOIS shows them."""
    __tablename__ = "inbound_rakes"

    id = Column(Integer, primary_key=True)
    imported_at = Column(DateTime, index=True, nullable=False)

    crnt_zone = Column(String)
    crnt_dvsn = Column(String)
    crnt_locn = Column(String)
    stts_code = Column(String)
    stts_time = Column(String)
    sttn_from = Column(String)
    sttn_to = Column(String, index=True)
    line_no = Column(String)
    cc = Column(String)
    load_name = Column(String)
    rake_id = Column(String)
    load_type = Column(String)
    totl_unts = Column(String)
    eight_w = Column(String)
    loaded_empty = Column(String)
    cmdt = Column(String)
    cnsr = Column(String)
    cnsg = Column(String)
    ldng_time = Column(String)
    dept_time = Column(String)
    transit_time = Column(String)
    loco_no = Column(String)
    loco_type = Column(String)
    expd_arvl_time = Column(String)

class RailDistance(Base):
    """Goods distance from a station to a plant yard, looked up once on the Railways' RBS site by
    the Chrome extension. km is empty when RBS doesn't know the station."""
    __tablename__ = "rail_distances"

    from_code = Column(String, primary_key=True)
    to_code = Column(String, primary_key=True)
    km = Column(Float)
    fetched_at = Column(DateTime, nullable=False)

# FOIS heading (lower case, without spaces, dots or underscores) -> InboundRake column
INBOUND_HEADINGS = {
    "crntzone": "crnt_zone", "crntdvsn": "crnt_dvsn", "crntlocn": "crnt_locn",
    "sttscode": "stts_code", "sttstime": "stts_time", "sttnfrom": "sttn_from",
    "sttnto": "sttn_to", "lineno": "line_no", "cc": "cc", "loadname": "load_name",
    "rakeid": "rake_id", "loadtype": "load_type", "totlunts": "totl_unts",
    "8w": "eight_w", "l/e": "loaded_empty", "cmdt": "cmdt", "cnsr": "cnsr",
    "cnsg": "cnsg", "ldngtime": "ldng_time", "depttime": "dept_time",
    "transittime": "transit_time", "locono": "loco_no", "locotype": "loco_type",
    "expdarvltime": "expd_arvl_time",
}

IST = timezone(timedelta(hours=5, minutes=30))

engine = create_engine(URL.create("sqlite", database=data_path("rake_data.db")))
class StationLookup(Base):
    """A station code whose name the Chrome extension looked up on FOIS Station Help, so it's only
    asked once. name is empty when FOIS doesn't know the code. Found names also go into the station
    mappings, which is what the pages show."""
    __tablename__ = "station_lookups"

    code = Column(String, primary_key=True)
    name = Column(String)
    fetched_at = Column(DateTime, nullable=False)

Base.metadata.create_all(engine)
SessionDB = sessionmaker(bind=engine)

# ------------------ CONFIGURATION LOADING ------------------

def load_mappings(filepath):
    """
    Load mappings from a configuration file.
    Format: KEY = VALUE
    Lines starting with # are comments and will be ignored.
    """
    mappings = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Parse KEY = VALUE format
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if key and value:
                        mappings[key] = value
    except FileNotFoundError:
        print(f"Warning: Configuration file {filepath} not found. Using empty mappings.")
    except Exception as e:
        print(f"Error loading {filepath}: {str(e)}")
    
    return mappings

def save_mappings(filepath, mappings):
    """
    Save mappings to a configuration file.
    """
    try:
        with open(filepath, 'w') as f:
            # Write header
            f.write("# Configuration File\n")
            f.write("# Format: CODE = Full Name\n")
            f.write("# Lines starting with # are comments\n")
            f.write("# You can add, remove, or modify mappings as needed\n\n")
            
            # Write mappings
            for key, value in sorted(mappings.items()):
                f.write(f"{key} = {value}\n")
        return True
    except Exception as e:
        print(f"Error saving {filepath}: {str(e)}")
        return False

# Load configuration files
STATION_MAPPINGS_FILE = data_path("station_mappings.txt")
COMMODITY_MAPPINGS_FILE = data_path("commodity_mappings.txt")

station_mappings = load_mappings(STATION_MAPPINGS_FILE)
commodity_mappings = load_mappings(COMMODITY_MAPPINGS_FILE)

def get_station_display_name(station_code):
    if not station_code:
        return station_code
    return station_mappings.get(station_code, station_code)

# ------------------ PLANTS ------------------

PLANTS = ["BSP", "DSP", "RSP", "BSL", "ISP"]

# Destination yard -> plant
DESTINATION_PLANTS = {
    "BSCS": "BSL",
    "BSPC": "BSP",
    "DSEY": "DSP",
    "IISD": "ISP",
    "BCME": "ISP",
    "HSPG": "RSP",
    "NHSB": "RSP",
}

# In-Bound report only. The Rakes Received dashboard counts just DESTINATION_PLANTS.
PELLET_AGENTS = ["PMRN", "MOMG", "GFMK", "SSPL", "NKKH"]
INBOUND_COLUMNS = [*PLANTS, *PELLET_AGENTS]
INBOUND_DESTINATIONS = {**DESTINATION_PLANTS, **{agent: agent for agent in PELLET_AGENTS}}

def plant_sort_key(code):
    """Sort key putting plants in PLANTS order (BSP, DSP, RSP, BSL, ISP), then the pellet agents in
    their order, then anything else by name. Takes a plant name or one of its yard codes."""
    code = (code or "").strip().upper()
    plant = INBOUND_DESTINATIONS.get(code, code)
    return (INBOUND_COLUMNS.index(plant) if plant in INBOUND_COLUMNS else len(INBOUND_COLUMNS), code)

# ------------------ RAIL DISTANCE ------------------

STABLED_STATUS = "ST"  # STTS CODE of a stabled rake
SLAB_KM = 50  # Width of each distance slab
UNKNOWN_SLAB = "Unknown"
MAX_RAIL_KM = 10000

def station_code(value):
    """A clean station code, or None if the value isn't one. RBS codes are up to 4 characters."""
    code = (value or "").strip().upper() if isinstance(value, str) else ""
    return code if re.fullmatch(r"[A-Z0-9]{1,4}", code) else None

def missing_distance_pairs(rakes, session):
    """(station, yard) pairs for rakes going to the plants or agents that have never been looked up."""
    known = set(session.query(RailDistance.from_code, RailDistance.to_code).all())
    pairs = set()
    for rake in rakes:
        pair = (station_code(rake.crnt_locn), station_code(rake.sttn_to))
        if all(pair) and pair[1] in INBOUND_DESTINATIONS and pair[0] != pair[1] and pair not in known:
            pairs.add(pair)
    return sorted(pairs)

def missing_station_codes(rakes, session):
    """Codes with no name in the station mappings that have never been looked up on FOIS: the source and
    destination of rakes to the plants or agents, and the source of any rake for consignee SAIL."""
    looked_up = {code for (code,) in session.query(StationLookup.code).all()}
    codes = set()
    for rake in rakes:
        if station_code(rake.sttn_to) in INBOUND_DESTINATIONS:
            codes.update(filter(None, (station_code(rake.sttn_from), station_code(rake.sttn_to))))
        elif is_sail(rake.cnsg) and station_code(rake.sttn_from):
            codes.add(station_code(rake.sttn_from))
    return sorted(code for code in codes if code not in station_mappings and code not in looked_up)

MAX_STATION_NAME = 80

def distance_left_km(rake, distances):
    """Km left for a rake using {(station, yard): km}, or None if it isn't known."""
    start, end = station_code(rake.crnt_locn), station_code(rake.sttn_to)
    if not start or not end:
        return None
    return 0 if start == end else distances.get((start, end))

def slab_start(km):
    """Where a distance's slab starts, so 50 km is in the slab starting at 50.
    Unknown distances sort after every slab."""
    return math.inf if km is None else int(km) // SLAB_KM * SLAB_KM

def slab_label(start):
    return UNKNOWN_SLAB if start == math.inf else f"{start}-{start + SLAB_KM} km"

def commodity_name(code):
    """The readable name from the commodity mappings, or the code if there isn't one."""
    code = (code or "").strip().upper()
    return commodity_mappings.get(code, code) or "—"

def is_stabled(rake):
    return (rake.stts_code or "").strip().upper() == STABLED_STATUS

def counts_line(counts):
    """Per-plant counts plus overall totals, from {"rakes": {plant: n}, "stabled": {plant: n}}."""
    return {
        "plants": counts["rakes"],
        "stabled": counts["stabled"],
        "total": sum(counts["rakes"].values()),
        "total_stabled": sum(counts["stabled"].values()),
    }

def loading_date(value):
    """(sort key, column label) for an LDNG TIME. Dates read day first; other text keeps its own column."""
    text = (value or "").strip()
    if not text:
        return (2, ""), "No date"
    match = re.match(r"(\d{1,2})[-/.](\d{1,2}|[A-Za-z]{3})[-/.](\d{2,4})\b", text)
    if match:
        day, month, year = match.groups()
        month_format = "%b" if month.isalpha() else "%m"
        year_format = "%Y" if len(year) == 4 else "%y"
        try:
            date = datetime.strptime(f"{day}-{month}-{year}", f"%d-{month_format}-{year_format}").date()
            return (0, date.isoformat()), date.strftime("%d-%m")
        except ValueError:
            pass
    first_word = text.split()[0]
    return (1, first_word), first_word

def station_label(code):
    """ "NAME (CODE)" for a station code, just the code when it has no name, or a dash when blank."""
    if not code:
        return "\u2014"
    name = get_station_display_name(code)
    return f"{name} ({code})" if name and name != code else code

def mark_runs(rows, field, key):
    """On the first row of each run of rows with the same key(row), set field to the run's length;
    0 on the rest. The page merges those cells."""
    first = None
    for row in rows:
        row[field] = 0
        if first is None or key(row) != key(first):
            first = row
        first[field] += 1

def route_date_report(rakes):
    """Count rakes by commodity, source, destination and loading date. Dates are columns, oldest first.
    Commodities run alphabetically, then sources in code order with a blank source last, then destinations in plant order.
    commodity_rows and source_rows on a run's first row say how many rows to merge."""
    counts = {}
    labels = {}
    for rake in rakes:
        source = (rake.sttn_from or "").strip().upper()
        destination = rake.sttn_to.strip().upper()
        key, label = loading_date(rake.ldng_time)
        labels[key] = label
        counts.setdefault((commodity_name(rake.cmdt), source, destination), Counter())[key] += 1

    keys = sorted(labels)
    rows = []
    ordered = sorted(counts.items(), key=lambda item: (item[0][0], not item[0][1], item[0][1], plant_sort_key(item[0][2])))
    for (commodity, source, destination), dates in ordered:
        rows.append({
            "commodity": commodity,
            "source_code": source,
            "source": station_label(source),
            "destination": station_label(destination),
            "counts": [dates[key] for key in keys],
            "total": sum(dates.values()),
        })
    mark_runs(rows, "commodity_rows", lambda row: row["commodity"])
    mark_runs(rows, "source_rows", lambda row: (row["commodity"], row["source_code"]))

    # The same rows nested by commodity and source, with totals, for the phone list.
    groups = []
    for row in rows:
        if row["commodity_rows"]:
            groups.append({"commodity": row["commodity"], "total": 0, "sources": []})
        if row["source_rows"]:
            groups[-1]["sources"].append({"source": row["source"], "total": 0, "rows": []})
        groups[-1]["total"] += row["total"]
        groups[-1]["sources"][-1]["total"] += row["total"]
        groups[-1]["sources"][-1]["rows"].append(row)

    return {
        "dates": [labels[key] for key in keys],
        "rows": rows,
        "groups": groups,
        "totals": [sum(row["counts"][index] for row in rows) for index in range(len(keys))],
        "total": len(rakes),
    }

def add_counts(lines):
    """Add up counts_line() results, plant by plant."""
    return counts_line({
        "rakes": {plant: sum(line["plants"][plant] for line in lines) for plant in PLANTS},
        "stabled": {plant: sum(line["stabled"][plant] for line in lines) for plant in PLANTS},
    })

def empty_counts():
    return {"rakes": dict.fromkeys(PLANTS, 0), "stabled": dict.fromkeys(PLANTS, 0)}

def commodity_plant_report(rakes):
    """Count rakes and stabled rakes by commodity, distance slab, source station and plant, largest
    commodity first. Within a slab, the source with the most rakes comes first. Rakes to the pellet
    agents are left out of this table; the page's other lists still show them."""
    counts = {}
    for rake in rakes:
        plant = INBOUND_DESTINATIONS[rake.sttn_to.strip().upper()]
        if plant not in PLANTS:
            continue
        slabs = counts.setdefault(commodity_name(rake.cmdt), {})
        sources = slabs.setdefault(slab_start(rake.distance_km), {})
        source = sources.setdefault((rake.sttn_from or "").strip().upper(), empty_counts())
        source["rakes"][plant] += 1
        source["stabled"][plant] += is_stabled(rake)

    report = []
    for commodity, slabs in counts.items():
        # Only slabs and sources with rakes are in the dict, so empty ones never appear.
        lines = []
        for start in sorted(slabs):
            sources = [
                {"code": code or "—", "name": get_station_display_name(code) if code else "—", **counts_line(c)}
                for code, c in slabs[start].items()
            ]
            sources.sort(key=lambda line: (-line["total"], line["code"]))
            lines.append({"label": slab_label(start), "sources": sources, **add_counts(sources)})

        # The same rakes again, source by source over all distances, for the bottom of the commodity.
        by_source = {}
        for line in lines:
            for source in line["sources"]:
                by_source.setdefault(source["code"], []).append(source)
        by_source = [
            {"code": code, "name": group[0]["name"], **add_counts(group)} for code, group in by_source.items()
        ]
        by_source.sort(key=lambda line: (-line["total"], line["code"]))

        slab_rows = sum(len(line["sources"]) for line in lines)
        report.append({"commodity": commodity, "slabs": lines, "by_source": by_source, "totals": add_counts(lines),
                       "row_count": slab_rows + len(by_source) + 1})
    report.sort(key=lambda row: (-row["totals"]["total"], row["commodity"]))

    return {
        "rows": report,
        "totals": add_counts([row["totals"] for row in report]),
    }

# ------------------ CLEANING ------------------

def clean_data(df):
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace(".", "")
    )

    required_cols = [
        "sr_no", "received_time", "dispatched_time",
        "transit_time", "sttn_from", "sttn_to",
        "cmdt", "totl_unts", "rake_type"
    ]

    df = df[required_cols].copy()

    df["received_time"] = pd.to_datetime(
        df["received_time"], format="%d-%m-%Y %H:%M", errors="coerce"
    )

    df["dispatched_time"] = pd.to_datetime(
        df["dispatched_time"], format="%d-%m-%Y %H:%M", errors="coerce"
    )

    # Transit time → hours
    parts = df["transit_time"].astype(str).str.split(":", expand=True)
    df["Hrs"] = pd.to_numeric(parts[0], errors="coerce")
    df["Mins"] = pd.to_numeric(parts[1], errors="coerce")

    df["transit_time_hrs"] = (df["Hrs"] + df["Mins"] / 60).round(2)
    df.drop(["Hrs", "Mins"], axis=1, inplace=True)

    # Units cleanup
    df["totl_unts"] = df["totl_unts"].astype(str).str.split(r"\+").str[0]
    df["totl_unts"] = pd.to_numeric(df["totl_unts"], errors="coerce")
   

    # Commodity normalization from configuration file
    if commodity_mappings:
        df["commodity"] = df["cmdt"].replace(commodity_mappings)

    # ------------------ PATCHED sttn_to LOGIC ------------------

    # Keep only valid destinations
    df = df[df["sttn_to"].isin(DESTINATION_PLANTS)]

    clean_sttn_from = ["BNDM","DSPY"]
    df = df[~df["sttn_from"].isin(clean_sttn_from)]

    # Standardize destination codes
    df["sttn_to"] = df["sttn_to"].replace(DESTINATION_PLANTS)

    # Drop invalid rows
    df = df.dropna(subset=["received_time", "transit_time_hrs"])
    df.to_csv(os.path.join(DATA_DIR, "cleaned_data_debug.csv"), index=False)  # Debugging line

    return df

# ------------------ INSERT WITH DEDUP ------------------
def insert_cleaned_data(df):
    if df.empty:
        return 0, 0

    session = SessionDB()
    inserted = 0
    total = len(df)

    try:
        records = [
            {
                "sr_no": row["sr_no"],
                "received_time": row["received_time"],
                "dispatched_time": row["dispatched_time"],
                "transit_time": row["transit_time"],
                "transit_time_hrs": row["transit_time_hrs"],
                "sttn_from": row["sttn_from"],
                "sttn_to": row["sttn_to"],
                "cmdt": row["cmdt"],
                "commodity": row["commodity"],
                "rake_type": row["rake_type"],
                "totl_unts": row["totl_unts"],
            }
            for _, row in df.iterrows()
        ]

        # Batch insert to avoid SQLite param limit
        chunksize = 50  # Adjust if needed (50 * 10 cols = 500 params < 999 limit)
        for i in range(0, len(records), chunksize):
            chunk = records[i:i + chunksize]
            stmt = insert(Rake).values(chunk)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["received_time", "sttn_from", "sttn_to", "cmdt", "rake_type", "dispatched_time"]
            )
            result = session.execute(stmt)
            inserted += result.rowcount  # Accumulate inserted count

        session.commit()

    except Exception as e:
        session.rollback()
        print("Bulk upsert failed:", str(e))
        # fallback (but with batching, this should rarely trigger)
        inserted, skipped = fallback_insert(session, records)
        total = inserted + skipped

    finally:
        session.close()

    skipped = total - inserted
    print(f"Upload summary -> Inserted: {inserted}  Skipped/duplicates: {skipped}")
    return inserted, skipped

def fallback_insert(session, records):
    inserted = 0
    skipped = 0
    for rec in records:
        try:
            r = Rake(**rec)
            session.add(r)
            session.flush()
            inserted += 1
        except IntegrityError:
            session.rollback()
            skipped += 1
        except Exception as e:
            print("Row error:", str(e))
            skipped += 1
    session.commit()
    return inserted, skipped

# ------------------ ANALYTICS ------------------

# def query_to_df(rows):
#     return pd.DataFrame([{
#         "received_time": r.received_time,
#         "transit_time_hrs": r.transit_time_hrs,
#         "sttn_from": r.sttn_from,
#         "sttn_to": r.sttn_to,
#         "commodity": r.commodity,
#         "rake_type": r.rake_type
#     } for r in rows])

def query_to_df(rows):
    # Explicit columns so an empty result (no rakes in the date range) still has them.
    columns = ["received_time", "transit_time_hrs", "sttn_from", "sttn_to", "commodity", "rake_type"]
    df = pd.DataFrame([{
        "received_time": r.received_time,
        "transit_time_hrs": r.transit_time_hrs,
        "sttn_from": r.sttn_from,
        "sttn_to": r.sttn_to,
        "commodity": r.commodity,
        "rake_type": r.rake_type
    } for r in rows], columns=columns)

    # map codes → readable names once
    df["sttn_from"] = df["sttn_from"].apply(get_station_display_name)
    # df["sttn_to"]   = df["sttn_to"].apply(get_station_display_name)
    # df["commodity"] = df["commodity"].apply(get_commodity_display_name)

    return df
# ------------------ CHROME EXTENSION IMPORT ------------------

def api_token_valid():
    auth = request.authorization
    token = auth.token if auth and auth.type == "bearer" else None
    return bool(API_TOKEN and token and hmac.compare_digest(token.encode(), API_TOKEN.encode()))

def read_import_request():
    """Check the API token and read {"columns": [...], "rows": [[...], ...]} from the request.
    Returns (data, None), or (None, error response)."""
    if not api_token_valid():
        return None, (jsonify(error="Invalid or missing API token"), 401)

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data.get("columns") or not data.get("rows"):
        return None, (jsonify(error="Expected JSON with columns and rows"), 400)
    return data, None

@app.route("/api/rakes", methods=["POST"])
def import_rakes():
    """Import a Rakes Received table."""
    data, error = read_import_request()
    if error:
        return error

    try:
        df_raw = pd.DataFrame(data["rows"], columns=data["columns"])
        df_clean = clean_data(df_raw)
    except (KeyError, TypeError, ValueError) as e:
        return jsonify(error=f"Could not read the table: {e}"), 400

    inserted, skipped = insert_cleaned_data(df_clean)
    return jsonify(received=len(df_raw), inserted=inserted, skipped=skipped)

@app.route("/api/inbound", methods=["POST"])
def import_inbound():
    """Save a Loaded In-Bound table as the latest list of rakes on the way."""
    data, error = read_import_request()
    if error:
        return error

    columns = data["columns"]
    rows = data["rows"]
    if not isinstance(columns, list) or not isinstance(rows, list):
        return jsonify(error="Expected JSON with columns and rows"), 400

    fields = [INBOUND_HEADINGS.get(re.sub(r"[\s._]", "", str(c).lower())) for c in columns]
    if "rake_id" not in fields or "sttn_to" not in fields:
        return jsonify(error="Could not read the table: RAKE ID and STTN TO are required"), 400

    imported_at = datetime.now(IST).replace(tzinfo=None)
    records = [
        InboundRake(imported_at=imported_at, **{f: v for f, v in zip(fields, row) if f})
        for row in rows
        if isinstance(row, list) and len(row) == len(columns)
    ]
    if not records:
        return jsonify(error="The table has no usable rows"), 400

    session = SessionDB()
    try:
        missing = missing_distance_pairs(records, session)
        missing_names = missing_station_codes(records, session)
        session.add_all(records)
        session.commit()
    finally:
        session.close()

    return jsonify(
        received=len(rows),
        inserted=len(records),
        missing_distances=[{"from": start, "to": end} for start, end in missing],
        missing_stations=missing_names,
    )

@app.route("/api/distances", methods=["POST"])
def import_distances():
    """Save distances the extension looked up: {"distances": [{"from", "to", "km"}, ...]}.
    An empty km means RBS doesn't know the station, so it won't be looked up again."""
    if not api_token_valid():
        return jsonify(error="Invalid or missing API token"), 401

    data = request.get_json(silent=True)
    distances = data.get("distances") if isinstance(data, dict) else None
    if not isinstance(distances, list):
        return jsonify(error="Expected JSON with distances"), 400

    fetched_at = datetime.now(IST).replace(tzinfo=None)
    saved = 0
    session = SessionDB()
    try:
        for item in distances:
            if not isinstance(item, dict):
                continue
            start, end, km = station_code(item.get("from")), station_code(item.get("to")), item.get("km")
            km_valid = km is None or (
                isinstance(km, (int, float)) and not isinstance(km, bool) and 0 <= km <= MAX_RAIL_KM
            )
            if start and end and km_valid:
                session.merge(RailDistance(from_code=start, to_code=end, km=km, fetched_at=fetched_at))
                saved += 1
        session.commit()
    finally:
        session.close()

    return jsonify(saved=saved)

@app.route("/api/station_names", methods=["POST"])
def import_station_names():
    """Save station names the extension read from FOIS Station Help: {"stations": [{"code", "name"}, ...]}.
    An empty name means FOIS doesn't know the code, so it won't be looked up again. A name already in
    the station mappings is kept, so names typed on the config page win."""
    if not api_token_valid():
        return jsonify(error="Invalid or missing API token"), 401

    data = request.get_json(silent=True)
    stations = data.get("stations") if isinstance(data, dict) else None
    if not isinstance(stations, list):
        return jsonify(error="Expected JSON with stations"), 400

    fetched_at = datetime.now(IST).replace(tzinfo=None)
    saved = 0
    added = {}
    session = SessionDB()
    try:
        for item in stations:
            if not isinstance(item, dict):
                continue
            code, name = station_code(item.get("code")), item.get("name")
            if isinstance(name, str):
                name = " ".join(name.split())[:MAX_STATION_NAME] or None
            elif name is not None:
                continue
            if code:
                session.merge(StationLookup(code=code, name=name, fetched_at=fetched_at))
                saved += 1
                if name and code not in station_mappings:
                    added[code] = name
        session.commit()
    finally:
        session.close()

    if added:
        station_mappings.update(added)
        save_mappings(STATION_MAPPINGS_FILE, station_mappings)
    return jsonify(saved=saved, added=len(added))

# ------------------ NEW: API ENDPOINTS FOR DYNAMIC FILTERS ------------------

@app.route("/api/get_filters", methods=["POST"])
def get_filters():
    """Get dynamically filtered options based on current selections"""
    data = request.json
    destination = data.get('destination')
    source = data.get('source')
    commodity = data.get('commodity')
    rake_type = data.get('rake_type')
    
    session_db = SessionDB()
    
    # Build base query for this destination
    query = session_db.query(Rake).filter(Rake.sttn_to == destination)
    
    # Apply filters progressively to get remaining options
    if source and source != "All Sources":
        filtered_sources = query.filter(Rake.sttn_from == source)
    else:
        filtered_sources = query
    
    if commodity and commodity != "All Commodities":
        filtered_commodities = query.filter(Rake.commodity == commodity)
    else:
        filtered_commodities = query
    
    if rake_type and rake_type != "All Rake Types":
        filtered_rake_types = query.filter(Rake.rake_type == rake_type)
    else:
        filtered_rake_types = query
    
    # Get available options based on other selections
    # For sources: filter by commodity and rake_type
    sources_query = query
    if commodity and commodity != "All Commodities":
        sources_query = sources_query.filter(Rake.commodity == commodity)
    if rake_type and rake_type != "All Rake Types":
        sources_query = sources_query.filter(Rake.rake_type == rake_type)
    sources = sorted({x[0] for x in sources_query.with_entities(Rake.sttn_from).distinct()})
    
    # For commodities: filter by source and rake_type
    commodities_query = query
    if source and source != "All Sources":
        commodities_query = commodities_query.filter(Rake.sttn_from == source)
    if rake_type and rake_type != "All Rake Types":
        commodities_query = commodities_query.filter(Rake.rake_type == rake_type)
    commodities = sorted({x[0] for x in commodities_query.with_entities(Rake.commodity).distinct()})
    
    # For rake_types: filter by source and commodity
    rake_types_query = query
    if source and source != "All Sources":
        rake_types_query = rake_types_query.filter(Rake.sttn_from == source)
    if commodity and commodity != "All Commodities":
        rake_types_query = rake_types_query.filter(Rake.commodity == commodity)
    rake_types = sorted({x[0] for x in rake_types_query.with_entities(Rake.rake_type).distinct()})
    
    session_db.close()
    
    return jsonify({
        'sources': sources,
        'commodities': commodities,
        'rake_types': rake_types
    })



# ------------------ ROUTES ------------------

@app.route("/healthz")
def healthz():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return jsonify(status="ok")

@app.route("/")
def index():
    return redirect("/dashboard")

# ------------------ ALL-INDIA EN-ROUTE ------------------

SAIL_CONSIGNEE = "SAIL"  # CNSG of rakes for SAIL, at the plants and at its stockyards
# In the In-Bound loading-date table, this commodity (its name in the commodity mappings) lists only
# consignee SAIL's rakes, to every destination in the list.
SAIL_ONLY_COMMODITY = "IRON ORE"
SHARED_SOURCE_DAYS = 7

def is_sail(cnsg):
    return (cnsg or "").strip().upper() == SAIL_CONSIGNEE

def party(code):
    """A consigner or consignee code, with a dash for a blank one."""
    return (code or "").strip().upper() or "\u2014"

def loading_datetime(value):
    """LDNG TIME as a datetime ("11-11-2026 03:05"), or None if it can't be read."""
    text = (value or "").strip()
    for size, pattern in ((16, "%d-%m-%Y %H:%M"), (10, "%d-%m-%Y")):
        try:
            return datetime.strptime(text[:size], pattern)
        except ValueError:
            pass
    return None

def not_plant_list():
    """SQL condition for a rake going somewhere other than the plants and agents. A list with any such
    rake is an all-India list, rather than one filtered to the SAIL plants."""
    return ~func.upper(func.trim(func.coalesce(InboundRake.sttn_to, ""))).in_(list(INBOUND_DESTINATIONS))

def party_report(rakes, key, other):
    """Rakes per key party (consigner or consignee), most first, each with the other parties as
    [(code, rakes)], most first."""
    counts = {}
    for rake in rakes:
        counts.setdefault(party(key(rake)), Counter())[party(other(rake))] += 1
    rows = [
        {"code": code, "total": sum(others.values()), "others": sorted(others.items(), key=lambda kv: (-kv[1], kv[0]))}
        for code, others in counts.items()
    ]
    rows.sort(key=lambda row: (-row["total"], row["code"]))
    return rows

def shared_source_report(session, latest_at):
    """For each source station that loaded a rake for SAIL in the last SHARED_SOURCE_DAYS days, the rakes it
    loaded for SAIL and for other consignees, in all and on each loading date (the date in LDNG TIME).
    There is a row per commodity and source, covering every commodity such a source loaded. Every list sent in that time counts, so rakes already
    delivered still count; a rake in several lists is counted once, by Rake ID and loading time."""
    end = latest_at.date()
    start = end - timedelta(days=SHARED_SOURCE_DAYS - 1)
    rows = (
        session.query(InboundRake.rake_id, InboundRake.load_name, InboundRake.sttn_from,
                      InboundRake.cnsg, InboundRake.cmdt, InboundRake.ldng_time, InboundRake.imported_at)
        .filter(InboundRake.imported_at >= datetime.combine(start, datetime.min.time()))
        .all()
    )
    loadings = {}
    first_list = None
    for rake_id, load_name, sttn_from, cnsg, cmdt, ldng_time, imported_at in rows:
        first_list = min(first_list or imported_at, imported_at)
        loaded = loading_datetime(ldng_time)
        source = station_code(sttn_from)
        if not loaded or not source or not start <= loaded.date() <= end:
            continue
        key = ((rake_id or "").strip() or (load_name or "").strip(), loaded, source)
        loadings[key] = (cnsg, commodity_name(cmdt))

    dates = [start + timedelta(days=n) for n in range(SHARED_SOURCE_DAYS)]
    sail_sources = {source for (_, _, source), (cnsg, _) in loadings.items() if is_sail(cnsg)}
    lines = {}
    for (_, loaded, source), (cnsg, commodity) in loadings.items():
        if source not in sail_sources:
            continue  # Only sources that load for SAIL
        line = lines.setdefault(
            (commodity, source), {"sail": 0, "others": Counter(), "daily": {day: [0, 0] for day in dates}}
        )
        # daily: loading date -> [rakes for SAIL, rakes for others]
        if is_sail(cnsg):
            line["sail"] += 1
            line["daily"][loaded.date()][0] += 1
        else:
            line["others"][party(cnsg)] += 1
            line["daily"][loaded.date()][1] += 1

    report = []
    for (commodity, source), line in lines.items():
        others = sum(line["others"].values())
        report.append({
            "commodity": commodity,
            "source": station_label(source),
            "sail": line["sail"],
            "others": others,
            "total": line["sail"] + others,
            "sail_share": round(100 * line["sail"] / (line["sail"] + others)),
            "other_parties": sorted(line["others"].items(), key=lambda kv: (-kv[1], kv[0])),
            "daily": [line["daily"][day] for day in dates],
        })
    # Commodities with the most rakes first; within one, sources with the most rakes first.
    commodity_totals = Counter()
    for row in report:
        commodity_totals[row["commodity"]] += row["total"]
    report.sort(key=lambda row: (-commodity_totals[row["commodity"]], row["commodity"], -row["total"], row["source"]))
    groups = []
    for row in report:
        if not groups or groups[-1]["commodity"] != row["commodity"]:
            groups.append({"commodity": row["commodity"], "rows": []})
        groups[-1]["rows"].append(row)
    for group in groups:
        # Sub totals for the date-wise table.
        group["sail"] = sum(row["sail"] for row in group["rows"])
        group["others"] = sum(row["others"] for row in group["rows"])
        group["total"] = group["sail"] + group["others"]
        group["daily"] = [
            [sum(row["daily"][n][side] for row in group["rows"]) for side in (0, 1)]
            for n in range(len(dates))
        ]
    return {
        "rows": report,
        "groups": groups,
        "source_count": len(sail_sources),
        "dates": dates,
        # Per loading date, [SAIL, others] over all the sources in the table.
        "daily": [
            [sum(row["daily"][n][side] for row in report) for side in (0, 1)]
            for n in range(len(dates))
        ],
        "start": start,
        "end": end,
        "sail": sum(row["sail"] for row in report),
        "others": sum(row["others"] for row in report),
        "total": sum(row["total"] for row in report),
        # History is complete only once lists go back to the start of the window.
        "history_from": first_list.date() if first_list and first_list.date() > start else None,
    }

def enroute_data():
    """The latest all-India list, by consigner and by consignee, and the shared-source table."""
    session = SessionDB()
    try:
        latest_at = session.query(func.max(InboundRake.imported_at)).filter(not_plant_list()).scalar()
        if not latest_at:
            return {"imported_at": None}
        rakes = (
            session.query(InboundRake.cnsr, InboundRake.cnsg)
            .filter(InboundRake.imported_at == latest_at)
            .all()
        )
        shared = shared_source_report(session, latest_at)
    finally:
        session.close()

    return {
        "imported_at": latest_at,
        "total": len(rakes),
        "sail_total": sum(is_sail(cnsg) for _, cnsg in rakes),
        "by_consigner": party_report(rakes, key=lambda r: r[0], other=lambda r: r[1]),
        "by_consignee": party_report(rakes, key=lambda r: r[1], other=lambda r: r[0]),
        "shared": shared,
        "sail": SAIL_CONSIGNEE,
        "days": SHARED_SOURCE_DAYS,
    }

@app.route("/enroute")
def enroute():
    """All-India en-route rakes from the latest all-India Loaded In-Bound list."""
    return render_template("enroute.html", **enroute_data())

def counted(values):
    """[(value, count)], most first."""
    return sorted(Counter(values).items(), key=lambda kv: (-kv[1], kv[0]))

@app.route("/enroute/rakes")
def enroute_rakes():
    """The rakes of one consigner (cnsr), one consignee (cnsg), or one pair, in the latest all-India list."""
    cnsr = request.args.get("cnsr", "").strip().upper()
    cnsg = request.args.get("cnsg", "").strip().upper()
    if not cnsr and not cnsg:
        return redirect(url_for("enroute"))

    session = SessionDB()
    try:
        latest_at = session.query(func.max(InboundRake.imported_at)).filter(not_plant_list()).scalar()
        rakes = (
            session.query(InboundRake).filter(InboundRake.imported_at == latest_at).all() if latest_at else []
        )
    finally:
        session.close()

    rakes = [
        rake for rake in rakes
        if (not cnsr or party(rake.cnsr) == cnsr) and (not cnsg or party(rake.cnsg) == cnsg)
    ]
    for rake in rakes:
        rake.loaded = loading_datetime(rake.ldng_time)
        rake.source = station_label(station_code(rake.sttn_from))
        rake.destination = station_label(station_code(rake.sttn_to))
        rake.commodity_name = commodity_name(rake.cmdt)
        rake.stabled = is_stabled(rake)
    # Oldest loading first; rakes without a loading time last.
    rakes.sort(key=lambda rake: (rake.loaded is None, rake.loaded or datetime.min, rake.id))

    if cnsr and cnsg:
        title = f"Rakes from consigner {cnsr} to consignee {cnsg}"
    elif cnsr:
        title = f"Rakes loaded by consigner {cnsr}"
    else:
        title = f"Rakes for consignee {cnsg}"
    return render_template(
        "enroute_rakes.html",
        title=title,
        cnsr=cnsr,
        cnsg=cnsg,
        imported_at=latest_at,
        rakes=rakes,
        stabled_count=sum(rake.stabled for rake in rakes),
        # The other side is worth a breakdown only when one side is chosen.
        by_party=counted(party(r.cnsg) for r in rakes) if not cnsg else counted(party(r.cnsr) for r in rakes) if not cnsr else [],
        party_heading="consignee" if not cnsg else "consigner",
        by_commodity=counted(r.commodity_name for r in rakes),
        by_source=counted(r.source for r in rakes),
        sail=SAIL_CONSIGNEE,
    )

WAGON_PAGE_TYPE = "BOBSNM1"  # Wagon type listed on the /bobsnm1 page

def page_date(name):
    """A date from the query string ("2026-11-13"), or None when it is blank or unreadable."""
    try:
        return datetime.strptime(request.args.get(name, "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None

@app.route("/bobsnm1")
def bobsnm1():
    """Every BOBSNM1 rake: those in the Loaded In-Bound lists (each rake once, as it was last seen)
    and those in the received rakes, which follow the page's date filter."""
    date_from, date_to = page_date("from"), page_date("to")
    session = SessionDB()
    try:
        latest_at = session.query(func.max(InboundRake.imported_at)).scalar()
        snapshots = (
            session.query(InboundRake)
            .filter(func.upper(func.trim(func.coalesce(InboundRake.load_type, ""))) == WAGON_PAGE_TYPE)
            .order_by(InboundRake.imported_at, InboundRake.id)
            .all()
        )
        query = session.query(Rake).filter(
            func.upper(func.trim(func.coalesce(Rake.rake_type, ""))) == WAGON_PAGE_TYPE
        )
        received_total = query.count()
        if date_from:
            query = query.filter(Rake.received_time >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            query = query.filter(Rake.received_time < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
        received = query.order_by(Rake.received_time.desc(), Rake.id.desc()).all()
    finally:
        session.close()

    # A rake is in every list sent while it travels: keep its last snapshot. Lists are read oldest
    # first, so a later one replaces an earlier one.
    seen = {}
    for rake in snapshots:
        rake.loaded = loading_datetime(rake.ldng_time)
        key = ((rake.rake_id or "").strip() or (rake.load_name or "").strip(), rake.ldng_time, station_code(rake.sttn_from))
        seen[key] = rake
    inbound_rakes = list(seen.values())
    for rake in inbound_rakes:
        rake.source = station_label(station_code(rake.sttn_from))
        rake.destination = station_label(station_code(rake.sttn_to))
        rake.commodity_name = commodity_name(rake.cmdt)
        rake.stabled = is_stabled(rake)
        rake.en_route = rake.imported_at == latest_at
    # Rakes still en route first, then the most recently seen; within those, the latest loading first.
    inbound_rakes.sort(key=lambda rake: (
        not rake.en_route, -rake.imported_at.timestamp(), -(rake.loaded or datetime.min).timestamp() if rake.loaded else 0, rake.id
    ))

    for rake in received:
        rake.source = station_label(station_code(rake.sttn_from))
        rake.commodity_name = rake.commodity or commodity_name(rake.cmdt)
    hours = [rake.transit_time_hrs for rake in received if rake.transit_time_hrs is not None]
    return render_template(
        "bobsnm1.html",
        wagon_type=WAGON_PAGE_TYPE,
        latest_at=latest_at,
        inbound_rakes=inbound_rakes,
        en_route_count=sum(rake.en_route for rake in inbound_rakes),
        stabled_count=sum(rake.stabled and rake.en_route for rake in inbound_rakes),
        first_list=min((rake.imported_at for rake in snapshots), default=None),
        inbound_by_destination=counted(rake.destination for rake in inbound_rakes if rake.en_route),
        inbound_by_commodity=counted(rake.commodity_name for rake in inbound_rakes if rake.en_route),
        received=received,
        received_total=received_total,
        average_hours=round(sum(hours) / len(hours), 1) if hours else None,
        received_by_plant=sorted(Counter(rake.sttn_to or "—" for rake in received).items(), key=lambda kv: plant_sort_key(kv[0])),
        received_by_commodity=counted(rake.commodity_name for rake in received),
        received_by_source=counted(rake.source for rake in received),
        date_from=date_from,
        date_to=date_to,
    )

def inbound_data(destination):
    """Everything the In-Bound page and its downloads show: the latest list's rakes going to the
    plants and pellet agents. Rakes to other destinations stay saved but aren't shown."""
    session = SessionDB()
    try:
        imported_at = session.query(func.max(InboundRake.imported_at)).scalar()
        latest = session.query(InboundRake).filter(
            InboundRake.imported_at == imported_at,
            func.upper(func.trim(InboundRake.sttn_to)).in_(list(INBOUND_DESTINATIONS)),
        )
        counts = sorted(
            latest.with_entities(InboundRake.sttn_to, func.count()).group_by(InboundRake.sttn_to).all(),
            key=lambda item: plant_sort_key(item[0]),
        )
        if destination:
            latest = latest.filter(InboundRake.sttn_to == destination)
        rakes = latest.order_by(InboundRake.id).all()
        # For the loading-date table: SAIL's rakes of SAIL_ONLY_COMMODITY going anywhere else. Only an
        # all-India list has any, and a destination filter leaves them out.
        elsewhere = [] if destination else [
            rake for rake in session.query(InboundRake).filter(
                InboundRake.imported_at == imported_at,
                not_plant_list(),
                func.upper(func.trim(func.coalesce(InboundRake.cnsg, ""))) == SAIL_CONSIGNEE,
            ).order_by(InboundRake.id).all()
            if (rake.sttn_to or "").strip() and commodity_name(rake.cmdt) == SAIL_ONLY_COMMODITY
        ]
        distances = {(d.from_code, d.to_code): d.km for d in session.query(RailDistance).all()}
    finally:
        session.close()

    for rake in rakes:
        rake.distance_km = distance_left_km(rake, distances)
        rake.commodity_name = commodity_name(rake.cmdt)
        rake.stabled = is_stabled(rake)

    return {
        "rakes": rakes,
        "report": commodity_plant_report(rakes),
        # Iron ore shows only consignee SAIL, to every destination; other commodities are unchanged.
        "routes": route_date_report([
            rake for rake in rakes
            if rake.commodity_name != SAIL_ONLY_COMMODITY or is_sail(rake.cnsg)
        ] + elsewhere),
        "sail_only_commodity": SAIL_ONLY_COMMODITY,
        "plants": PLANTS,  # Columns of the Rakes in Transit table
        "distance_pairs": len(distances),
        "distance_pairs_with_km": sum(km is not None for km in distances.values()),
        "rakes_with_distance": sum(rake.distance_km is not None for rake in rakes),
        "stabled_count": sum(rake.stabled for rake in rakes),
        "counts": counts,
        "total": sum(count for _, count in counts),
        "destination": destination,
        "imported_at": imported_at,
    }

@app.route("/inbound")
def inbound():
    """Show the most recently imported Loaded In-Bound list."""
    return render_template("inbound.html", **inbound_data(request.args.get("sttn_to", "")))

def inbound_download(build, extension, mimetype):
    """Send the latest In-Bound report as a file, following the page's destination filter."""
    data = inbound_data(request.args.get("sttn_to", ""))
    if not data["imported_at"]:
        return "No In-Bound list has been received yet.", 404

    parts = ["inbound_report", station_code(data["destination"]), data["imported_at"].strftime("%Y%m%d_%H%M")]
    return send_file(
        io.BytesIO(build(data)),
        mimetype=mimetype,
        as_attachment=True,
        download_name="_".join(filter(None, parts)) + extension,
    )

@app.route("/inbound/report.xlsx")
def inbound_excel():
    return inbound_download(
        build_excel, ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/inbound/report.pdf")
def inbound_pdf():
    return inbound_download(build_pdf, ".pdf", "application/pdf")

@app.route("/inbound/extension.zip")
def inbound_extension():
    """Send the Chrome extension, with manifest.json at the top level so Load unpacked accepts it."""
    folder = os.path.join(BASE_DIR, "chrome_extension")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(os.listdir(folder)):
            archive.write(os.path.join(folder, name), name)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="rakes_received_extension.zip",
    )

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.endswith('.csv'):
            return "Invalid file", 400

        try:
            df_raw = pd.read_csv(file.stream)
            df_clean = clean_data(df_raw)
            inserted, skipped = insert_cleaned_data(df_clean)
            msg = f"Processed. Inserted: {inserted}, Skipped (duplicates/old): {skipped}"
        except Exception as e:
            msg = f"Error processing file: {str(e)}"
            print(msg)

        return redirect("/dashboard?msg=" + msg)

    return render_template("upload.html")


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    from datetime import datetime, timedelta
    
    session_db = SessionDB()

    # Get all unique destinations
    sttn_tos = sorted({x[0] for x in session_db.query(Rake.sttn_to).distinct() if x[0]}, key=plant_sort_key)

    # Default to first unit if available
    selected_unit = request.args.get("unit") or request.form.get("unit") or (sttn_tos[0] if sttn_tos else None)
    analysis_type = request.form.get("analysis_type", "last30days")
    
    # Get filters for the selected destination
    if selected_unit:
        # Get all available options for this destination
        base_query = session_db.query(Rake).filter(Rake.sttn_to == selected_unit)
        sttn_froms = sorted({x[0] for x in base_query.with_entities(Rake.sttn_from).distinct()})
        commodities = sorted({x[0] for x in base_query.with_entities(Rake.commodity).distinct()})
        rake_types = sorted({x[0] for x in base_query.with_entities(Rake.rake_type).distinct()})
    else:
        sttn_froms = []
        commodities = []
        rake_types = []
    
    # Filters from form
    sttn_from = request.form.get("sttn_from", "")
    commodity = request.form.get("commodity", "")
    rake_type = request.form.get("rake_type", "")

    graph_html = None
    outliers_df = pd.DataFrame()  # Initialize empty DataFrame for outliers
    
    # Labels for display
    source_label = sttn_from if sttn_from else "All Sources"
    commodity_label = commodity if commodity else "All Commodities"
    rake_type_label = rake_type if rake_type else "All Rake Types"
    
    if selected_unit:
        # Build query
        query = session_db.query(Rake).filter(Rake.sttn_to == selected_unit)
        
        if sttn_from:
            query = query.filter(Rake.sttn_from == sttn_from)
        if commodity:
            query = query.filter(Rake.commodity == commodity)
        if rake_type:
            query = query.filter(Rake.rake_type == rake_type)
        
        # Date filtering based on analysis type
        if analysis_type == "last30days":
            cutoff_date = datetime.now() - timedelta(days=30)
            query = query.filter(Rake.received_time >= cutoff_date)
        elif analysis_type == "weekly":
            cutoff_date = datetime.now() - timedelta(days=90)  # Last ~13 weeks
            query = query.filter(Rake.received_time >= cutoff_date)
        elif analysis_type == "fortnightly":
            cutoff_date = datetime.now() - timedelta(days=120)  # Last ~8 fortnights
            query = query.filter(Rake.received_time >= cutoff_date)
        elif analysis_type == "monthly":
            cutoff_date = datetime.now() - timedelta(days=365)  # Last 12 months
            query = query.filter(Rake.received_time >= cutoff_date)
        
        rows = query.all()
        df = query_to_df(rows)
        
        if not df.empty:
            df["received_time"] = pd.to_datetime(df["received_time"])
            
            # REQUIREMENT 1: Generate dual-axis chart with bar (rake count) and line (avg transit time)
            if analysis_type == "last30days":
                df["date"] = df["received_time"].dt.date
                result = df.groupby("date", as_index=False).agg({
                    'transit_time_hrs': 'mean',
                    'sttn_from': 'count'  # Count of rakes
                })
                result.columns = ['date', 'avg_transit_time', 'rake_count']
                result['avg_transit_time'] = result['avg_transit_time'].round(2)  # Round to 2 decimals
                result = result.sort_values("date")
                
                # Detect outliers using IQR method
                Q1 = df['transit_time_hrs'].quantile(0.25)
                Q3 = df['transit_time_hrs'].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                
                outliers_df = df[(df['transit_time_hrs'] < lower_bound) | (df['transit_time_hrs'] > upper_bound)].copy()
                outliers_df['received_time'] = outliers_df['received_time'].dt.strftime('%d-%m-%Y %H:%M')
                outliers_df = outliers_df.sort_values('transit_time_hrs', ascending=False)
                
                # Create dual-axis chart
                fig = go.Figure()
                
                # Add bar chart for rake count
                fig.add_trace(go.Bar(
                    x=result['date'],
                    y=result['rake_count'],
                    name='Rake Count',
                    marker_color='rgba(100, 181, 246, 0.7)',  # Light blue
                    yaxis='y2',
                    text=result['rake_count'],
                    textposition='outside',
                    textfont=dict(size=10, color='rgb(33, 150, 243)')
                ))
                
                # Add line chart for average transit time
                fig.add_trace(go.Scatter(
                    x=result['date'],
                    y=result['avg_transit_time'],
                    name='Avg Transit Time',
                    mode='lines+markers+text',
                    line=dict(color='rgb(76, 175, 80)', width=3),  # Green
                    marker=dict(size=10, color='rgb(76, 175, 80)', line=dict(width=2, color='white')),
                    text=result['avg_transit_time'],
                    textposition='top center',
                    textfont=dict(size=10, color='rgb(56, 142, 60)'),
                    yaxis='y'
                ))
                title_text = (
                   f"<span style='font-size:19px; font-weight:bold; color:#01579b; '>"
                   f"Last 30 Days Analysis of Received Rakes</span><br>"
                   f"<span style='font-size:18px; font-weight:bold; color:#ef6c00;'>"
                   f"Received Rakes – {selected_unit}</span>"
                   "<br>"
                   f"<span style='font-size:12px; color:#616161;'>"
                   f"Source: {source_label}  •  Commodity: {commodity_label}  •  Rake Type: {rake_type_label}"
                   "</span>")
                fig.update_layout(
                    title=title_text,
                    xaxis=dict(title="Date"),
                    yaxis=dict(
                        title=dict(text="Transit Time (Hours)", font=dict(color="rgb(76, 175, 80)")),
                        tickfont=dict(color="rgb(76, 175, 80)")
                    ),
                    yaxis2=dict(
                        title=dict(text="Rake Count", font=dict(color="rgb(33, 150, 243)")),
                        tickfont=dict(color="rgb(33, 150, 243)"),
                        overlaying='y',
                        side='right'
                    ),
                    hovermode='x unified',
                    height=550,
                    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
                )
                
            elif analysis_type == "weekly":
                result = (
                    df.set_index("received_time")
                      .resample("W-MON", label='left', closed='left')
                      .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                      .reset_index()
                )
                result.columns = ["week", "avg_transit_time", "rake_count"]
                result['avg_transit_time'] = result['avg_transit_time'].round(2)  # Round to 2 decimals
                result = result.dropna()
                # Create clear range labels (e.g., "03 Nov – 09 Nov")
                result['week_label'] = result['week'].apply(
                lambda x: f"{x.strftime('%d %b')} – {(x + pd.Timedelta(days=6)).strftime('%d %b')}"
                )
                # If you want year only on first/last: customize further if needed
               
               
                # Detect outliers using IQR method
                Q1 = df['transit_time_hrs'].quantile(0.25)
                Q3 = df['transit_time_hrs'].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                
                outliers_df = df[(df['transit_time_hrs'] < lower_bound) | (df['transit_time_hrs'] > upper_bound)].copy()
                outliers_df['received_time'] = outliers_df['received_time'].dt.strftime('%d-%m-%Y %H:%M')
                outliers_df = outliers_df.sort_values('transit_time_hrs', ascending=False)
                
                fig = go.Figure()
                
                fig.add_trace(go.Bar(
                    x=result['week_label'],
                    y=result['rake_count'],
                    name='Rake Count',
                    marker_color='rgba(255, 152, 0, 0.7)',  # Orange
                    yaxis='y2',
                    text=result['rake_count'],
                    textposition='outside',
                    textfont=dict(size=10, color='rgb(245, 124, 0)')
                ))
                
                fig.add_trace(go.Scatter(
                    x=result['week_label'],
                    y=result['avg_transit_time'],
                    name='Avg Transit Time',
                    mode='lines+markers+text',
                    line=dict(color='rgb(156, 39, 176)', width=3),  # Purple
                    marker=dict(size=10, color='rgb(156, 39, 176)', line=dict(width=2, color='white')),
                    text=result['avg_transit_time'],
                    textposition='top center',
                    textfont=dict(size=10, color='rgb(123, 31, 162)'),
                    yaxis='y'
                ))
                title_text = (
                   f"<span style='font-size:19px; font-weight:bold; color:#01579b; '>"
                   f"Weekly Average Analysis of Received Rakes </span><br>"
                   f"<span style='font-size:18px; font-weight:bold; color:#ef6c00;'>"
                   f"Received Rakes – {selected_unit}</span>"
                     "<br>"
                  
                   f"<span style='font-size:12px; color:#616161;'>"
                   f"Source: {source_label}  •  Commodity: {commodity_label}  •  Rake Type: {rake_type_label}"
                   "</span>")
                fig.update_layout(
                    title=title_text,
                    xaxis=dict(title="Week",tickangle=-45),
                    yaxis=dict(
                        title=dict(text="Transit Time (Hours)", font=dict(color="rgb(156, 39, 176)")),
                        tickfont=dict(color="rgb(156, 39, 176)")
                    ),
                    yaxis2=dict(
                        title=dict(text="Rake Count", font=dict(color="rgb(245, 124, 0)")),
                        tickfont=dict(color="rgb(245, 124, 0)"),
                        overlaying='y',
                        side='right'
                    ),
                    hovermode='x unified',
                    height=550,
                    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
                )
                
            elif analysis_type == "fortnightly":
                result = (
                    df.set_index("received_time")
                      .resample("2W-SUN", label='left', closed='left')
                      .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                      .reset_index()
                )
                result.columns = ["fortnight_start", "avg_transit_time", "rake_count"]
                result['avg_transit_time'] = result['avg_transit_time'].round(2)  # Round to 2 decimals
                result = result.dropna()
                # Create clear range labels: "21 Sep – 04 Oct"
                result['fortnight_label'] = result['fortnight_start'].apply(
                lambda x: f"{x.strftime('%d %b')} – {(x + pd.Timedelta(days=13)).strftime('%d %b')}"
                    )

                # Optional: Add year only when it changes (cleaner for multi-year data)
                # But for your 2025–2026 range, full year on first/last or all is fine
                # result['fortnight_label'] += result['fortnight_start'].dt.year.astype(str)


                
                # Detect outliers using IQR method
                Q1 = df['transit_time_hrs'].quantile(0.25)
                Q3 = df['transit_time_hrs'].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                
                outliers_df = df[(df['transit_time_hrs'] < lower_bound) | (df['transit_time_hrs'] > upper_bound)].copy()
                outliers_df['received_time'] = outliers_df['received_time'].dt.strftime('%d-%m-%Y %H:%M')
                outliers_df = outliers_df.sort_values('transit_time_hrs', ascending=False)
                
                fig = go.Figure()
                
                fig.add_trace(go.Bar(
                    x=result['fortnight_label'],
                    y=result['rake_count'],
                    name='Rake Count',
                    marker_color='rgba(255, 87, 34, 0.7)',  # Deep Orange
                    yaxis='y2',
                    text=result['rake_count'],
                    textposition='outside',
                    textfont=dict(size=10, color='rgb(230, 74, 25)')
                ))
                
                fig.add_trace(go.Scatter(
                    x=result['fortnight_label'],
                    y=result['avg_transit_time'],
                    name='Avg Transit Time',
                    mode='lines+markers+text',
                    line=dict(color='rgb(0, 150, 136)', width=3),  # Teal
                    marker=dict(size=10, color='rgb(0, 150, 136)', line=dict(width=2, color='white')),
                    text=result['avg_transit_time'],
                    textposition='top center',
                    textfont=dict(size=10, color='rgb(0, 121, 107)'),
                    yaxis='y'
                ))
                title_text = (
                   f"<span style='font-size:19px; font-weight:bold; color:#01579b; '>"
                   f"Fortnightly Average Analysis of Received Rakes</span><br>"
                   f"<span style='font-size:18px; font-weight:bold; color:#ef6c00;'>"
                   f"Received Rakes – {selected_unit}</span>"
                   "<br>"
                   f"<span style='font-size:12px; color:#616161;'>"
                   f"Source: {source_label}  •  Commodity: {commodity_label}  •  Rake Type: {rake_type_label}"
                   "</span>")
                fig.update_layout(
                    title=dict(
                    text=title_text,
                    font=dict(size=20),  # fallback size – actual sizes come from spans
                    x=0.5,
                    xanchor='center',
                    y=0.97,
                    pad=dict(t=20)),
                    # If your Plotly version doesn't support subtitle yet, use <br> + <span> as in Option 1
                    margin=dict(t=80),

                    xaxis=dict(title="Fortnight_Range",tickangle=-30,tickfont=dict(size=11)),
                    yaxis=dict(
                        title=dict(text="Transit Time (Hours)", font=dict(color="rgb(0, 150, 136)")),
                        tickfont=dict(color="rgb(0, 150, 136)")
                    ),
                    yaxis2=dict(
                        title=dict(text="Rake Count", font=dict(color="rgb(230, 74, 25)")),
                        tickfont=dict(color="rgb(230, 74, 25)"),
                        overlaying='y',
                        side='right'
                    ),
                    hovermode='x unified',
                    height=550,
                    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
                )
                
            elif analysis_type == "monthly": 
                result = (
                df.set_index("received_time")
                .resample("MS")   # ← Add this: label left/start
                .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                .reset_index()
                    )
                result.columns = ["month", "avg_transit_time", "rake_count"]
                result['month'] = result['month'].dt.strftime('%b %Y')  # Now shows Sep 2025 for Sep data
                result['avg_transit_time'] = result['avg_transit_time'].round(2)
                result = result.dropna()
                        
                # Detect outliers using IQR method
                Q1 = df['transit_time_hrs'].quantile(0.25)
                Q3 = df['transit_time_hrs'].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                
                outliers_df = df[(df['transit_time_hrs'] < lower_bound) | (df['transit_time_hrs'] > upper_bound)].copy()
                outliers_df['received_time'] = outliers_df['received_time'].dt.strftime('%d-%m-%Y %H:%M')
                outliers_df = outliers_df.sort_values('transit_time_hrs', ascending=False)
                
                fig = go.Figure()
                
                fig.add_trace(go.Bar(
                    x=result['month'],
                    y=result['rake_count'],
                    name='Rake Count',
                    marker_color='rgba(63, 81, 181, 0.7)',  # Indigo
                    yaxis='y2',
                    text=result['rake_count'],
                    textposition='outside',
                    textfont=dict(size=10, color='rgb(48, 63, 159)')
                ))
                
                fig.add_trace(go.Scatter(
                    x=result['month'],
                    y=result['avg_transit_time'],
                    name='Avg Transit Time',
                    mode='lines+markers+text',
                    line=dict(color='rgb(233, 30, 99)', width=3),  # Pink
                    marker=dict(size=10, color='rgb(233, 30, 99)', line=dict(width=2, color='white')),
                    text=result['avg_transit_time'],
                    textposition='top center',
                    textfont=dict(size=10, color='rgb(194, 24, 91)'),
                    yaxis='y'
                ))
                title_text = (
                   f"<span style='font-size:19px; font-weight:bold; color:#01579b; '>"
                   f"Monthly Average Analysis of Received Rakes</span><br>"
                   f"<span style='font-size:18px; font-weight:bold; color:#ef6c00;'>"
                   f"Received Rakes – {selected_unit}</span>"
                    "<br>"
                   f"<span style='font-size:12px; color:#616161;'>"
                   f"Source: {source_label}  •  Commodity: {commodity_label}  •  Rake Type: {rake_type_label}"
                   "</span>")
                fig.update_layout(
                    title=title_text,
                    xaxis=dict(title="Month"),
                    yaxis=dict(
                        title=dict(text="Transit Time (Hours)", font=dict(color="rgb(233, 30, 99)")),
                        tickfont=dict(color="rgb(233, 30, 99)")
                    ),
                    yaxis2=dict(
                        title=dict(text="Rake Count", font=dict(color="rgb(48, 63, 159)")),
                        tickfont=dict(color="rgb(48, 63, 159)"),
                        overlaying='y',
                        side='right'
                    ),
                    hovermode='x unified',
                    height=550,
                    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
                )
            
            graph_html = fig.to_html(full_html=False)

    session_db.close()

    return render_template(
        "dashboard.html",
        sttn_froms=sttn_froms,
        sttn_tos=sttn_tos,
        commodities=commodities,
        rake_types=rake_types,
        selected_unit=selected_unit,
        analysis_type=analysis_type,
        selected_sttn_from=sttn_from,
        selected_commodity=commodity,
        selected_rake_type=rake_type,
        source_label=source_label,
        commodity_label=commodity_label,
        rake_type_label=rake_type_label,
        graph_html=graph_html,
        outliers=outliers_df.to_dict('records') if not outliers_df.empty else [],
        outlier_count=len(outliers_df),
        total_records=len(df) if not df.empty else 0
    )

def commodity_analysis_data(selected_commodity="", selected_destination=""):
    """Everything the Commodity Analysis page and its downloads show: transit time by commodity,
    destination plant and source station, for the chosen commodity and destination (blank for all)."""
    from datetime import datetime, timedelta
    
    session_db = SessionDB()
    
    
    # Get all unique values for filters
    commodities = [r[0] for r in session_db.query(Rake.commodity).distinct().all() if r[0]]
    destinations = [r[0] for r in session_db.query(Rake.sttn_to).distinct().all() if r[0]]
    
    # Build base query
    query = session_db.query(Rake)
    
    # Apply filters if selected
    if selected_commodity:
        query = query.filter(Rake.commodity == selected_commodity)
    if selected_destination:
        query = query.filter(Rake.sttn_to == selected_destination)
    
    # Get all data
    all_rows = query.all()
    df = query_to_df(all_rows)
    
    # Prepare data structure for display
    analysis_data = []
    
    # Calculate header labels for the table based on filtered data
    header_months = []
    header_month_starts = []  # First day of each month column; None for a padded one
    header_weeks = []
    header_days = []
    
    if not df.empty:
        df["received_time"] = pd.to_datetime(df["received_time"])
        
        # Calculate date ranges based on yesterday, not actual data
        max_date = df['received_time'].max()
        min_date = df['received_time'].min()
        print("Last Record Date", max_date)
        # Use yesterday as anchor for all calculations
        yesterday = pd.Timestamp("today").normalize() - pd.Timedelta(days=1)
        last_4_months = yesterday - timedelta(days=120)
        last_8_weeks = yesterday - timedelta(days=28)
        last_4_days = yesterday - timedelta(days=4)
        print("Yesterday (anchor):", yesterday)
        print("Last_8_weeks:", last_8_weeks)
        # Generate header labels for months (last 4 months from actual data)
        temp_df = df[df['received_time'] >= last_4_months]
        if len(temp_df) > 0:
            month_headers = (
                temp_df.set_index('received_time')
                .resample('MS')
                .size()
                .reset_index()
            )
            # Only include months that actually have data
            month_headers = month_headers[month_headers[0] > 0]
            month_headers = month_headers.tail(4)
            for _, row in month_headers.iterrows():
                header_months.append(row['received_time'].strftime("%b'%y"))
                header_month_starts.append(row['received_time'])
        
        # Pad if less than 4
        while len(header_months) < 4:
            header_months.insert(0, "—")
            header_month_starts.insert(0, None)
        
        # Generate header labels for weeks (simple 7-day intervals from yesterday)
        # Create 4 weeks: (yesterday-27 to yesterday-21), (yesterday-20 to yesterday-14), 
        #                 (yesterday-13 to yesterday-7), (yesterday-6 to yesterday)
        header_weeks = []
        for i in range(3, -1, -1):  # 3, 2, 1, 0
            week_end = yesterday - timedelta(days=i*7)
            week_start = week_end - timedelta(days=6)
            
            print(f"Week {4-i}: Start: {week_start}, End: {week_end}")
            
            # If week spans two months
            if week_start.month == week_end.month:
                header_weeks.append(f"{week_start.strftime('%d')}-{week_end.strftime('%d %b')}")
            else:
                # Week spans two months
                header_weeks.append(f"{week_start.strftime('%d %b')}-{week_end.strftime('%d %b')}")
        
        # Generate header labels for days (last 4 days: yesterday-3, yesterday-2, yesterday-1, yesterday)
        header_days = []
        for i in range(3, -1, -1):  # 3, 2, 1, 0
            day = yesterday - timedelta(days=i)
            header_days.append(day.strftime('%d-%b'))
        
        def period_slot(period_df):
            """Average transit hours and rake count of one period; avg is None when it has no rakes."""
            avg = period_df['transit_time_hrs'].mean() if len(period_df) else None
            return {
                'avg': round(float(avg), 2) if avg is not None and pd.notna(avg) else None,
                'count': int(len(period_df)),
            }

        # Group by commodity, destination, and source
        grouped = df.groupby(['commodity', 'sttn_to', 'sttn_from'])
        
        for (commodity, destination, source), group_df in grouped:
            # One slot per column of the table, in the header's order, so a period without rakes
            # keeps its empty place instead of shifting the later ones left.
            df_4m = group_df[group_df['received_time'] >= last_4_months]
            months_data = []
            for month_start in header_month_starts:
                if month_start is None:
                    months_data.append({'avg': None, 'count': 0})
                else:
                    months_data.append(period_slot(df_4m[
                        (df_4m['received_time'] >= month_start) &
                        (df_4m['received_time'] < month_start + pd.offsets.MonthBegin(1))
                    ]))

            # Weeks are 7-day spans ending yesterday, 7, 14 and 21 days before.
            df_8w = group_df[group_df['received_time'] >= last_8_weeks]
            weeks_data = []
            for i in range(3, -1, -1):
                week_end = yesterday - timedelta(days=i*7)
                week_start = week_end - timedelta(days=6)
                weeks_data.append(period_slot(group_df[
                    (group_df['received_time'] >= week_start) &
                    (group_df['received_time'] <= week_end + timedelta(hours=23, minutes=59, seconds=59))
                ]))

            # Days are yesterday and the 3 days before.
            df_4d = group_df[group_df['received_time'] >= last_4_days]
            days_data = []
            for i in range(3, -1, -1):
                day = yesterday - timedelta(days=i)
                days_data.append(period_slot(group_df[
                    (group_df['received_time'] >= day) &
                    (group_df['received_time'] <= day + timedelta(hours=23, minutes=59, seconds=59))
                ]))

            # Calculate overall averages for compatibility
            avg_4m = df_4m['transit_time_hrs'].mean() if len(df_4m) > 0 else None
            count_4m = len(df_4m)
            avg_8w = df_8w['transit_time_hrs'].mean() if len(df_8w) > 0 else None
            count_8w = len(df_8w)
            avg_4d = df_4d['transit_time_hrs'].mean() if len(df_4d) > 0 else None
            count_4d = len(df_4d)
            
            # Calculate best monthly average (last 12 months from yesterday)
            last_12_months = yesterday - timedelta(days=365)
            df_12m = group_df[group_df['received_time'] >= last_12_months]
            
            if len(df_12m) > 0:
                monthly_avg = (
                    df_12m.set_index('received_time')
                    .resample('MS')
                    .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                    .reset_index()
                )
                monthly_avg = monthly_avg[monthly_avg['sttn_from'] >= 1]  # At least 1 rake
                best_monthly_avg = monthly_avg['transit_time_hrs'].min() if len(monthly_avg) > 0 else None
                best_monthly_count = int(monthly_avg.loc[monthly_avg['transit_time_hrs'] == best_monthly_avg, 'sttn_from'].iloc[0]) if best_monthly_avg else 0
            else:
                best_monthly_avg = None
                best_monthly_count = 0
            
            # Calculate best fortnightly average (last 6 months from yesterday)
            last_6_months = yesterday - timedelta(days=180)
            df_6m = group_df[group_df['received_time'] >= last_6_months]
            
            if len(df_6m) > 0:
                fortnightly_avg = (
                    df_6m.set_index('received_time')
                    .resample('2W')
                    .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                    .reset_index()
                )
                fortnightly_avg = fortnightly_avg[fortnightly_avg['sttn_from'] >= 1]
                best_fortnightly_avg = fortnightly_avg['transit_time_hrs'].min() if len(fortnightly_avg) > 0 else None
                best_fortnightly_count = int(fortnightly_avg.loc[fortnightly_avg['transit_time_hrs'] == best_fortnightly_avg, 'sttn_from'].iloc[0]) if best_fortnightly_avg else 0
            else:
                best_fortnightly_avg = None
                best_fortnightly_count = 0
            
            # Calculate best weekly average (last 3 months from yesterday) using simple 7-day intervals
            last_3_months = yesterday - timedelta(days=90)
            df_3m = group_df[group_df['received_time'] >= last_3_months]
            
            if len(df_3m) > 0:
                # Calculate weekly averages using simple 7-day periods
                weeks_in_3m = 12  # approximately 12 weeks in 3 months
                weekly_results = []
                
                for week_num in range(weeks_in_3m):
                    week_end = yesterday - timedelta(days=week_num*7)
                    week_start = week_end - timedelta(days=6)
                    
                    week_data = group_df[
                        (group_df['received_time'] >= week_start) & 
                        (group_df['received_time'] <= week_end + timedelta(hours=23, minutes=59, seconds=59))
                    ]
                    
                    if len(week_data) >= 1:
                        avg = week_data['transit_time_hrs'].mean()
                        weekly_results.append({
                            'avg': avg,
                            'count': len(week_data)
                        })
                
                if weekly_results:
                    best_week = min(weekly_results, key=lambda x: x['avg'])
                    best_weekly_avg = best_week['avg']
                    best_weekly_count = best_week['count']
                else:
                    best_weekly_avg = None
                    best_weekly_count = 0
            else:
                best_weekly_avg = None
                best_weekly_count = 0
            
            analysis_data.append({
                'commodity': commodity,
                'destination': destination,
                'source': source,
                'months_data': months_data,
                'weeks_data': weeks_data,
                'days_data': days_data,
                'avg_4m': round(avg_4m, 2) if avg_4m else None,
                'count_4m': count_4m,
                'avg_8w': round(avg_8w, 2) if avg_8w else None,
                'count_8w': count_8w,
                'avg_4d': round(avg_4d, 2) if avg_4d else None,
                'count_4d': count_4d,
                'best_monthly': round(best_monthly_avg, 2) if best_monthly_avg else None,
                'best_monthly_count': best_monthly_count,
                'best_fortnightly': round(best_fortnightly_avg, 2) if best_fortnightly_avg else None,
                'best_fortnightly_count': best_fortnightly_count,
                'best_weekly': round(best_weekly_avg, 2) if best_weekly_avg else None,
                'best_weekly_count': best_weekly_count
            })
    
    session_db.close()
    
    # Group data by commodity and destination for display
    grouped_data = {}
    for item in analysis_data:
        key = (item['commodity'], item['destination'])
        if key not in grouped_data:
            grouped_data[key] = []
        grouped_data[key].append(item)
    # Within each commodity, plants in the usual BSP, DSP, RSP, BSL, ISP order.
    grouped_data = dict(sorted(grouped_data.items(), key=lambda kv: (kv[0][0], plant_sort_key(kv[0][1]))))
    
    return {
        "grouped_data": grouped_data,
        "commodities": sorted(commodities),
        "destinations": sorted(destinations, key=plant_sort_key),
        "selected_commodity": selected_commodity,
        "selected_destination": selected_destination,
        "header_months": header_months,
        "header_weeks": header_weeks,
        "header_days": header_days,
    }

PICK_SEPARATOR = "||"  # Between the commodity and the source in a ticked box's value

def commodity_sources(grouped_data):
    """[(commodity, [source, ...])] for the report's tick list, both in name order."""
    sources = {}
    for (commodity, _), items in grouped_data.items():
        sources.setdefault(commodity, set()).update(item["source"] for item in items)
    return [(commodity, sorted(names)) for commodity, names in sorted(sources.items())]

@app.route("/commodity_analysis")
def commodity_analysis():
    """Commodity-wise analysis dashboard showing all plants grouped by source station"""
    data = commodity_analysis_data(request.args.get("commodity", ""), request.args.get("destination", ""))
    return render_template(
        "commodity_analysis.html",
        report_choices=commodity_sources(data["grouped_data"]),
        pick_separator=PICK_SEPARATOR,
        **data,
    )

def commodity_download(build, extension, mimetype):
    """Send the Commodity Analysis report as a file. It follows the page's commodity and destination
    filters, and keeps only the ticked commodity-source pairs ("pick" values) when any are sent."""
    data = commodity_analysis_data(request.values.get("commodity", ""), request.values.get("destination", ""))
    picks = {
        tuple(value.split(PICK_SEPARATOR, 1))
        for value in request.values.getlist("pick") if PICK_SEPARATOR in value
    }
    available = sum(len(items) for items in data["grouped_data"].values())
    if picks:
        kept = {
            key: [item for item in items if (item["commodity"], item["source"]) in picks]
            for key, items in data["grouped_data"].items()
        }
        data["grouped_data"] = {key: items for key, items in kept.items() if items}
    shown = sum(len(items) for items in data["grouped_data"].values())
    if not shown:
        return "Nothing to download: no rakes match the chosen commodities and sources.", 404

    data["customised"] = shown < available
    data["generated_at"] = datetime.now(IST).replace(tzinfo=None)
    parts = [
        "commodity_analysis", data["selected_destination"],
        "custom" if data["customised"] else "", data["generated_at"].strftime("%Y%m%d_%H%M"),
    ]
    return send_file(
        io.BytesIO(build(data)),
        mimetype=mimetype,
        as_attachment=True,
        download_name="_".join(filter(None, parts)) + extension,
    )

@app.route("/commodity_analysis/report.xlsx", methods=["GET", "POST"])
def commodity_analysis_excel():
    return commodity_download(
        commodity_exports.build_excel, ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/commodity_analysis/report.pdf", methods=["GET", "POST"])
def commodity_analysis_pdf():
    return commodity_download(commodity_exports.build_pdf, ".pdf", "application/pdf")

@app.route("/source_outliers/<source_station>")
def source_outliers(source_station):
    """Show outliers for a specific source station for the last 1 month"""
    from datetime import datetime, timedelta
    
    session_db = SessionDB()
    
    # Get commodity and destination filters from query params
    commodity = request.args.get("commodity", "")
    destination = request.args.get("destination", "")
    
    # Get last month data
    last_month = datetime.now() - timedelta(days=30)
    
    query = session_db.query(Rake).filter(
        Rake.sttn_from == source_station,
        Rake.received_time >= last_month
    )
    
    if commodity:
        query = query.filter(Rake.commodity == commodity)
    if destination:
        query = query.filter(Rake.sttn_to == destination)
    
    rows = query.all()
    df = query_to_df(rows)
    
    outliers_df = pd.DataFrame()
    total_records = 0
    
    if not df.empty:
        total_records = len(df)
        
        # Detect outliers using IQR method
        Q1 = df['transit_time_hrs'].quantile(0.25)
        Q3 = df['transit_time_hrs'].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        outliers_df = df[(df['transit_time_hrs'] < lower_bound) | (df['transit_time_hrs'] > upper_bound)].copy()
        outliers_df['received_time'] = pd.to_datetime(outliers_df['received_time']).dt.strftime('%d-%m-%Y %H:%M')
        outliers_df = outliers_df.sort_values('transit_time_hrs', ascending=False)
    
    session_db.close()
    
    return render_template(
        "source_outliers.html",
        source_station=source_station,
        outliers=outliers_df.to_dict('records') if not outliers_df.empty else [],
        outlier_count=len(outliers_df),
        total_records=total_records,
        commodity=commodity,
        destination=destination
    )

@app.route("/export", methods=["POST"])
def export_csv():
    from datetime import datetime, timedelta
    
    session_db = SessionDB()

    analysis_type = request.form.get("analysis_type", "last30days")
    selected_unit = request.form.get("unit")
    sttn_from = request.form.get("sttn_from", "")
    commodity = request.form.get("commodity", "")
    rake_type = request.form.get("rake_type", "")

    # Build query with same filters as dashboard
    query = session_db.query(Rake)
    
    if selected_unit:
        query = query.filter(Rake.sttn_to == selected_unit)
    if sttn_from:
        query = query.filter(Rake.sttn_from == sttn_from)
    if commodity:
        query = query.filter(Rake.commodity == commodity)
    if rake_type:
        query = query.filter(Rake.rake_type == rake_type)
    
    # Date filtering
    if analysis_type == "last30days":
        cutoff_date = datetime.now() - timedelta(days=30)
        query = query.filter(Rake.received_time >= cutoff_date)
    elif analysis_type == "weekly":
        cutoff_date = datetime.now() - timedelta(days=90)
        query = query.filter(Rake.received_time >= cutoff_date)
    elif analysis_type == "fortnightly":
        cutoff_date = datetime.now() - timedelta(days=120)
        query = query.filter(Rake.received_time >= cutoff_date)
    elif analysis_type == "monthly":
        cutoff_date = datetime.now() - timedelta(days=365)
        query = query.filter(Rake.received_time >= cutoff_date)

    rows = query.all()
    session_db.close()

    df = query_to_df(rows)
    
    if not df.empty:
        df["received_time"] = pd.to_datetime(df["received_time"])
        
        # Generate analysis based on type
        if analysis_type == "last30days":
            df["date"] = df["received_time"].dt.date
            result = df.groupby("date", as_index=False).agg({
                'transit_time_hrs': 'mean',
                'sttn_from': 'count'
            })
            result.columns = ['date', 'avg_transit_time_hrs', 'rake_count']
        elif analysis_type == "weekly":
            result = (
                df.set_index("received_time")
                  .resample("W")
                  .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                  .reset_index()
            )
            result.columns = ['week', 'avg_transit_time_hrs', 'rake_count']
        elif analysis_type == "fortnightly":
            result = (
                df.set_index("received_time")
                  .resample("2W")
                  .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                  .reset_index()
            )
            result.columns = ['fortnight', 'avg_transit_time_hrs', 'rake_count']
        elif analysis_type == "monthly":
            result = (
                df.set_index("received_time")
                  .resample("ME")  # Changed from "M" to "ME"
                  .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                  .reset_index()
            )
            result.columns = ['month', 'avg_transit_time_hrs', 'rake_count']
    else:
        result = df

    buffer = io.StringIO()
    result.to_csv(buffer, index=False)
    buffer.seek(0)

    return send_file(
        io.BytesIO(buffer.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{analysis_type}_analysis_{selected_unit or 'all'}.csv"
    )

# ------------------ CONFIGURATION MANAGEMENT ------------------

@app.route("/config")
def config_page():
    """Display configuration management page"""
    return render_template("config.html",
                         station_mappings=station_mappings,
                         commodity_mappings=commodity_mappings)

@app.route("/config/station", methods=["GET", "POST"])
def manage_station_config():
    """Manage station mappings"""
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            code = request.form.get("code", "").strip().upper()
            name = request.form.get("name", "").strip()
            if code and name:
                station_mappings[code] = name
                save_mappings(STATION_MAPPINGS_FILE, station_mappings)
                return jsonify({"success": True, "message": f"Added mapping: {code} → {name}"})
            return jsonify({"success": False, "message": "Code and name are required"})
        
        elif action == "delete":
            code = request.form.get("code", "").strip().upper()
            if code in station_mappings:
                del station_mappings[code]
                save_mappings(STATION_MAPPINGS_FILE, station_mappings)
                return jsonify({"success": True, "message": f"Deleted mapping for {code}"})
            return jsonify({"success": False, "message": f"Code {code} not found"})
        
        elif action == "edit":
            code = request.form.get("code", "").strip().upper()
            name = request.form.get("name", "").strip()
            if code and name:
                station_mappings[code] = name
                save_mappings(STATION_MAPPINGS_FILE, station_mappings)
                return jsonify({"success": True, "message": f"Updated mapping: {code} → {name}"})
            return jsonify({"success": False, "message": "Code and name are required"})
    
    return jsonify(station_mappings)

@app.route("/config/commodity", methods=["GET", "POST"])
def manage_commodity_config():
    """Manage commodity mappings"""
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            code = request.form.get("code", "").strip().upper()
            name = request.form.get("name", "").strip()
            if code and name:
                commodity_mappings[code] = name
                save_mappings(COMMODITY_MAPPINGS_FILE, commodity_mappings)
                return jsonify({"success": True, "message": f"Added mapping: {code} → {name}"})
            return jsonify({"success": False, "message": "Code and name are required"})
        
        elif action == "delete":
            code = request.form.get("code", "").strip().upper()
            if code in commodity_mappings:
                del commodity_mappings[code]
                save_mappings(COMMODITY_MAPPINGS_FILE, commodity_mappings)
                return jsonify({"success": True, "message": f"Deleted mapping for {code}"})
            return jsonify({"success": False, "message": f"Code {code} not found"})
        
        elif action == "edit":
            code = request.form.get("code", "").strip().upper()
            name = request.form.get("name", "").strip()
            if code and name:
                commodity_mappings[code] = name
                save_mappings(COMMODITY_MAPPINGS_FILE, commodity_mappings)
                return jsonify({"success": True, "message": f"Updated mapping: {code} → {name}"})
            return jsonify({"success": False, "message": "Code and name are required"})
    
    return jsonify(commodity_mappings)

@app.route("/config/reload", methods=["POST"])
def reload_config():
    """Reload configuration files"""
    global station_mappings, commodity_mappings
    station_mappings = load_mappings(STATION_MAPPINGS_FILE)
    commodity_mappings = load_mappings(COMMODITY_MAPPINGS_FILE)
    return jsonify({
        "success": True, 
        "message": "Configuration files reloaded successfully",
        "station_count": len(station_mappings),
        "commodity_count": len(commodity_mappings)
    })

# ------------------ RUN ------------------

if __name__ == "__main__":
    # Local development only; production runs under gunicorn (see Dockerfile).
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )