from flask import Flask, render_template, request, redirect, send_file
import pandas as pd
import plotly.express as px
import os, io

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
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
            index_elements=["received_time", "sttn_from", "sttn_to","cmdt", "rake_type", "dispatched_time"
]
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

def run_analysis(df, analysis_type):
    if df.empty:
        return df

    df["received_time"] = pd.to_datetime(df["received_time"])

    if analysis_type == "daily":
        df["date"] = df["received_time"].dt.date
        return df.groupby(["sttn_from", "date"], as_index=False)["transit_time_hrs"].mean()

    if analysis_type == "weekly":
        return (
            df.set_index("received_time")
              .groupby("sttn_from")
              .resample("W")["transit_time_hrs"]
              .mean()
              .reset_index()
        )

    if analysis_type == "fortnightly":
        return (
            df.set_index("received_time")
              .groupby("sttn_from")
              .resample("15D")["transit_time_hrs"]
              .mean()
              .reset_index()
        )

    if analysis_type == "monthly":
        return (
            df.set_index("received_time")
              .groupby("sttn_from")
              .resample("M")["transit_time_hrs"]
              .mean()
              .reset_index()
        )

    if analysis_type == "commodity":
        return df.groupby("cmdt", as_index=False)["transit_time_hrs"].mean()

    if analysis_type == "source":
        return df.groupby("sttn_from", as_index=False)["transit_time_hrs"].mean()

    if analysis_type == "rake_type":
        return df.groupby("rake_type", as_index=False)["transit_time_hrs"].mean()

    if analysis_type == "bottleneck":
        return (
            df.groupby(["sttn_from", "sttn_to"], as_index=False)["transit_time_hrs"]
              .mean()
              .sort_values("transit_time_hrs", ascending=False)
              .head(10)
        )

    return df

# ------------------ ROUTES ------------------
@app.route("/", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files["file"]
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

    # Get all unique values for filters
    sttn_froms = sorted({x[0] for x in session_db.query(Rake.sttn_from).distinct()})
    sttn_tos = sorted({x[0] for x in session_db.query(Rake.sttn_to).distinct()})
    commodities = sorted({x[0] for x in session_db.query(Rake.cmdt).distinct()})
    rake_types = sorted({x[0] for x in session_db.query(Rake.rake_type).distinct()})

    # Default to first unit if available
    selected_unit = request.args.get("unit") or request.form.get("unit") or (sttn_tos[0] if sttn_tos else None)
    analysis_type = request.form.get("analysis_type", "last30days")
    
    # Filters
    sttn_from = request.form.get("sttn_from", "")
    commodity = request.form.get("commodity", "")
    rake_type = request.form.get("rake_type", "")

    graph_html = None
    
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
            
            # Generate analysis based on type
            if analysis_type == "last30days":
                df["date"] = df["received_time"].dt.date
                result = df.groupby("date", as_index=False)["transit_time_hrs"].mean()
                result = result.sort_values("date")
                
                fig = px.line(result, x="date", y="transit_time_hrs", markers=True,
                            title=f"Last 30 Days Transit Time - {selected_unit}")
                fig.update_xaxes(title_text="Date")
                
            elif analysis_type == "weekly":
                result = (
                    df.set_index("received_time")
                      .resample("W")["transit_time_hrs"]
                      .mean()
                      .reset_index()
                )
                result.columns = ["week", "transit_time_hrs"]
                result = result.dropna()
                
                fig = px.line(result, x="week", y="transit_time_hrs", markers=True,
                            title=f"Weekly Average Transit Time - {selected_unit}")
                fig.update_xaxes(title_text="Week")
                
            elif analysis_type == "fortnightly":
                result = (
                    df.set_index("received_time")
                      .resample("2W")["transit_time_hrs"]
                      .mean()
                      .reset_index()
                )
                result.columns = ["fortnight", "transit_time_hrs"]
                result = result.dropna()
                
                fig = px.bar(result, x="fortnight", y="transit_time_hrs",
                           title=f"Fortnightly Average Transit Time - {selected_unit}")
                fig.update_xaxes(title_text="Fortnight")
                
            elif analysis_type == "monthly":
                result = (
                    df.set_index("received_time")
                      .resample("M")["transit_time_hrs"]
                      .mean()
                      .reset_index()
                )
                result.columns = ["month", "transit_time_hrs"]
                result = result.dropna()
                
                fig = px.bar(result, x="month", y="transit_time_hrs",
                           title=f"Monthly Average Transit Time - {selected_unit}")
                fig.update_xaxes(title_text="Month")
            
            fig.update_yaxes(title_text="Transit Time (Hours)")
            fig.update_layout(
                height=500,
                hovermode='x unified',
                showlegend=False
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
        graph_html=graph_html
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
            result = df.groupby("date", as_index=False)["transit_time_hrs"].mean()
        elif analysis_type == "weekly":
            result = (
                df.set_index("received_time")
                  .resample("W")["transit_time_hrs"]
                  .mean()
                  .reset_index()
            )
        elif analysis_type == "fortnightly":
            result = (
                df.set_index("received_time")
                  .resample("2W")["transit_time_hrs"]
                  .mean()
                  .reset_index()
            )
        elif analysis_type == "monthly":
            result = (
                df.set_index("received_time")
                  .resample("M")["transit_time_hrs"]
                  .mean()
                  .reset_index()
            )
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
