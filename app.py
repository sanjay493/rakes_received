from flask import Flask, render_template, request, redirect, send_file, jsonify
import pandas as pd
import plotly.graph_objs as go
import os, io

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError

# ------------------ APP SETUP ------------------

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

engine = create_engine("sqlite:///rake_data.db")
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
STATION_MAPPINGS_FILE = "station_mappings.txt"
COMMODITY_MAPPINGS_FILE = "commodity_mappings.txt"

station_mappings = load_mappings(STATION_MAPPINGS_FILE)
commodity_mappings = load_mappings(COMMODITY_MAPPINGS_FILE)

def get_station_display_name(station_code):
    if not station_code:
        return station_code
    return station_mappings.get(station_code, station_code)

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
    valid_destinations = ["BSCS","BSPC","DSEY","IISD","BCME","HSPG","NHSB"]
    df = df[df["sttn_to"].isin(valid_destinations)]

    clean_sttn_from = ["BNDM","DSPY"]
    df = df[~df["sttn_from"].isin(clean_sttn_from)]

    # Standardize destination codes
    df["sttn_to"] = df["sttn_to"].replace({
        "BSCS": "BSL",
        "BSPC": "BSP",
        "DSEY": "DSP",
        "IISD": "ISP",
        "BCME": "ISP",
        "HSPG": "RSP",
        "NHSB": "RSP"
    })

    # Drop invalid rows
    df = df.dropna(subset=["received_time", "transit_time_hrs"])
    df.to_csv("cleaned_data_debug.csv", index=False)  # Debugging line

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
    print(f"Upload summary → Inserted: {inserted}  Skipped/duplicates: {skipped}")
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
    df = pd.DataFrame([{
        "received_time": r.received_time,
        "transit_time_hrs": r.transit_time_hrs,
        "sttn_from": r.sttn_from,
        "sttn_to": r.sttn_to,
        "commodity": r.commodity,
        "rake_type": r.rake_type
    } for r in rows])

    # map codes → readable names once
    df["sttn_from"] = df["sttn_from"].apply(get_station_display_name)
    # df["sttn_to"]   = df["sttn_to"].apply(get_station_display_name)
    # df["commodity"] = df["commodity"].apply(get_commodity_display_name)

    return df
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

@app.route("/")
def index():
    return redirect("/dashboard")

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.endswith('.csv'):
            return "Invalid file", 400

        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(filepath)

        try:
            df_raw = pd.read_csv(filepath)
            df_clean = clean_data(df_raw)
            inserted, skipped = insert_cleaned_data(df_clean)
            msg = f"Processed. Inserted: {inserted}, Skipped (duplicates/old): {skipped}"
        except Exception as e:
            msg = f"Error processing file: {str(e)}"
            print(msg)

        os.remove(filepath)  # cleanup

        return redirect("/dashboard?msg=" + msg)

    return render_template("upload.html")


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    from datetime import datetime, timedelta
    
    session_db = SessionDB()

    # Get all unique destinations
    sttn_tos = sorted({x[0] for x in session_db.query(Rake.sttn_to).distinct()})

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

@app.route("/commodity_analysis")
def commodity_analysis():
    """Commodity-wise analysis dashboard showing all plants grouped by source station"""
    from datetime import datetime, timedelta
    
    session_db = SessionDB()
    
    # Get filter parameters
    selected_commodity = request.args.get("commodity", "")
    selected_destination = request.args.get("destination", "")
    
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
        
        # Pad if less than 4
        while len(header_months) < 4:
            header_months.insert(0, "—")
        
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
        
        # Group by commodity, destination, and source
        grouped = df.groupby(['commodity', 'sttn_to', 'sttn_from'])
        
        for (commodity, destination, source), group_df in grouped:
            # Use the same date ranges as calculated for headers
            # Last 4 months - month by month breakdown
            df_4m = group_df[group_df['received_time'] >= last_4_months]
            months_data = []
            if len(df_4m) > 0:
                monthly_breakdown = (
                    df_4m.set_index('received_time')
                    .resample('MS')
                    .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                    .reset_index()
                )
                # Get last 4 months
                monthly_breakdown = monthly_breakdown.tail(4)
                for _, row in monthly_breakdown.iterrows():
                    if row['sttn_from'] > 0:  # Only add if data exists
                        months_data.append({
                            'label': row['received_time'].strftime('%b %y'),
                            'avg': round(row['transit_time_hrs'], 2) if pd.notna(row['transit_time_hrs']) else None,
                            'count': int(row['sttn_from'])
                        })
            
            # Last 4 weeks - week by week breakdown using simple 7-day intervals
            df_8w = group_df[group_df['received_time'] >= last_8_weeks]
            weeks_data = []
            if len(df_8w) > 0:
                # Create 4 weeks manually: week 1, week 2, week 3, week 4
                for i in range(3, -1, -1):  # 3, 2, 1, 0
                    week_end = yesterday - timedelta(days=i*7)
                    week_start = week_end - timedelta(days=6)
                    
                    # Filter data for this specific week
                    week_df = group_df[
                        (group_df['received_time'] >= week_start) & 
                        (group_df['received_time'] <= week_end + timedelta(hours=23, minutes=59, seconds=59))
                    ]
                    
                    if len(week_df) > 0:
                        avg_transit = week_df['transit_time_hrs'].mean()
                        count = len(week_df)
                        
                        weeks_data.append({
                            'label': week_start.strftime('%d-%m'),
                            'avg': round(avg_transit, 2) if pd.notna(avg_transit) else None,
                            'count': int(count)
                        })
            
            # Last 4 days - day by day breakdown using simple day intervals
            df_4d = group_df[group_df['received_time'] >= last_4_days]
            days_data = []
            if len(df_4d) > 0:
                # Create 4 days manually: yesterday-3, yesterday-2, yesterday-1, yesterday
                for i in range(3, -1, -1):  # 3, 2, 1, 0
                    day = yesterday - timedelta(days=i)
                    day_start = day
                    day_end = day + timedelta(hours=23, minutes=59, seconds=59)
                    
                    # Filter data for this specific day
                    day_df = group_df[
                        (group_df['received_time'] >= day_start) & 
                        (group_df['received_time'] <= day_end)
                    ]
                    
                    if len(day_df) > 0:
                        avg_transit = day_df['transit_time_hrs'].mean()
                        count = len(day_df)
                        
                        days_data.append({
                            'label': day.strftime('%d-%b'),
                            'avg': round(avg_transit, 2) if pd.notna(avg_transit) else None,
                            'count': int(count)
                        })
            
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
    
    return render_template(
        "commodity_analysis.html",
        grouped_data=grouped_data,
        commodities=sorted(commodities),
        destinations=sorted(destinations),
        selected_commodity=selected_commodity,
        selected_destination=selected_destination,
        header_months=header_months,
        header_weeks=header_weeks,
        header_days=header_days
    )

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
    app.run(host="0.0.0.0", port=5000, debug=True)