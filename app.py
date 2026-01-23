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
    rake_type = Column(String, index=True)

    totl_unts = Column(Integer)

    __table_args__ = (
        UniqueConstraint("received_time", "sttn_from", "sttn_to","cmdt","rake_type","dispatched_time", name="uq_rake_time_to_from_cmdt_type"),
    )

engine = create_engine("sqlite:///rake_data.db")
Base.metadata.create_all(engine)
SessionDB = sessionmaker(bind=engine)

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

    # Commodity normalization
    df["cmdt"] = df["cmdt"].replace({"IOST": "IORE", "IORE": "IORE"})

    # ------------------ PATCHED sttn_to LOGIC ------------------

    # Keep only valid destinations
    valid_destinations = ["BSCS","BSPC","DSEY","IISD","BCME","HSPG","NHSB"]
    df = df[df["sttn_to"].isin(valid_destinations)]

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

    return df

# ------------------ INSERT WITH DEDUP ------------------

def insert_cleaned_data(df):
    if df.empty:
        return 0, 0

    session = SessionDB()
    inserted = 0
    total = len(df)

    try:
        # Prepare data
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
                "rake_type": row["rake_type"],
                "totl_unts": row["totl_unts"],
            }
            for _, row in df.iterrows()
        ]

        stmt = insert(Rake).values(records)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["received_time", "sttn_from", "sttn_to","cmdt", "rake_type", "dispatched_time"]
        )

        result = session.execute(stmt)
        inserted = result.rowcount
        session.commit()

    except Exception as e:
        session.rollback()
        print("Bulk upsert failed:", str(e))
        # fallback
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

def query_to_df(rows):
    return pd.DataFrame([{
        "received_time": r.received_time,
        "transit_time_hrs": r.transit_time_hrs,
        "sttn_from": r.sttn_from,
        "sttn_to": r.sttn_to,
        "cmdt": r.cmdt,
        "rake_type": r.rake_type
    } for r in rows])

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
        filtered_commodities = query.filter(Rake.cmdt == commodity)
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
        sources_query = sources_query.filter(Rake.cmdt == commodity)
    if rake_type and rake_type != "All Rake Types":
        sources_query = sources_query.filter(Rake.rake_type == rake_type)
    sources = sorted({x[0] for x in sources_query.with_entities(Rake.sttn_from).distinct()})
    
    # For commodities: filter by source and rake_type
    commodities_query = query
    if source and source != "All Sources":
        commodities_query = commodities_query.filter(Rake.sttn_from == source)
    if rake_type and rake_type != "All Rake Types":
        commodities_query = commodities_query.filter(Rake.rake_type == rake_type)
    commodities = sorted({x[0] for x in commodities_query.with_entities(Rake.cmdt).distinct()})
    
    # For rake_types: filter by source and commodity
    rake_types_query = query
    if source and source != "All Sources":
        rake_types_query = rake_types_query.filter(Rake.sttn_from == source)
    if commodity and commodity != "All Commodities":
        rake_types_query = rake_types_query.filter(Rake.cmdt == commodity)
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
        commodities = sorted({x[0] for x in base_query.with_entities(Rake.cmdt).distinct()})
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
            query = query.filter(Rake.cmdt == commodity)
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
                
                fig.update_layout(
                    title=f"Last 30 Days Analysis - {selected_unit}",
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
                      .resample("W")
                      .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                      .reset_index()
                )
                result.columns = ["week", "avg_transit_time", "rake_count"]
                result['avg_transit_time'] = result['avg_transit_time'].round(2)  # Round to 2 decimals
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
                    x=result['week'],
                    y=result['rake_count'],
                    name='Rake Count',
                    marker_color='rgba(255, 152, 0, 0.7)',  # Orange
                    yaxis='y2',
                    text=result['rake_count'],
                    textposition='outside',
                    textfont=dict(size=10, color='rgb(245, 124, 0)')
                ))
                
                fig.add_trace(go.Scatter(
                    x=result['week'],
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
                
                fig.update_layout(
                    title=f"Weekly Average Analysis - {selected_unit}",
                    xaxis=dict(title="Week"),
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
                      .resample("2W")
                      .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                      .reset_index()
                )
                result.columns = ["fortnight", "avg_transit_time", "rake_count"]
                result['avg_transit_time'] = result['avg_transit_time'].round(2)  # Round to 2 decimals
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
                    x=result['fortnight'],
                    y=result['rake_count'],
                    name='Rake Count',
                    marker_color='rgba(255, 87, 34, 0.7)',  # Deep Orange
                    yaxis='y2',
                    text=result['rake_count'],
                    textposition='outside',
                    textfont=dict(size=10, color='rgb(230, 74, 25)')
                ))
                
                fig.add_trace(go.Scatter(
                    x=result['fortnight'],
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
                
                fig.update_layout(
                    title=f"Fortnightly Average Analysis - {selected_unit}",
                    xaxis=dict(title="Fortnight"),
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
                      .resample("ME")  # Changed from "M" to "ME" (Month End)
                      .agg({'transit_time_hrs': 'mean', 'sttn_from': 'count'})
                      .reset_index()
                )
                result.columns = ["month", "avg_transit_time", "rake_count"]
                result['avg_transit_time'] = result['avg_transit_time'].round(2)  # Round to 2 decimals
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
                
                fig.update_layout(
                    title=f"Monthly Average Analysis - {selected_unit}",
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
        outlier_count=len(outliers_df)
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
        query = query.filter(Rake.cmdt == commodity)
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

# ------------------ RUN ------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
