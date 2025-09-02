# app.py
import streamlit as st
import pandas as pd
import plotly.express as px
import matplotlib.pyplot as plt
from pywaffle import Waffle
from pathlib import Path
import json

# -------------------------
# Config / Files
# -------------------------
SUMMARY_CSV = "bills_summary.csv"
RAW_DIR = Path("bills_raw")    # optional: used to derive true start dates if present

# -------------------------
# Load data
# -------------------------
df = pd.read_csv(SUMMARY_CSV)

# Ensure expected columns exist
required_cols = {"state", "bill_number", "title", "dem_sponsors", "rep_sponsors",
                 "session_start", "session_end", "last_action_date", "completed", "last_action"}
missing = required_cols - set(df.columns)
if missing:
    st.error(f"Missing required columns in {SUMMARY_CSV}: {missing}")
    st.stop()

# -------------------------
# Derive start / end dates
# -------------------------
start_map = {}
end_map = {}

if RAW_DIR.exists() and any(RAW_DIR.glob("*.json")):
    for f in RAW_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                j = json.load(fh)
        except Exception:
            continue
        key = f"{j.get('state')}_{j.get('bill_number')}"
        dates = []
        for arr_key in ("history", "progress", "texts"):
            for it in j.get(arr_key, []):
                d = it.get("date")
                if d:
                    dates.append(d)
        if dates:
            start_map[key] = min(dates)
            end_map[key] = max(dates)

def _to_start(row):
    key = f"{row['state']}_{row['bill_number']}"
    if key in start_map:
        parsed_date = pd.to_datetime(start_map[key], errors="coerce")
        if pd.notna(parsed_date):
            return parsed_date
    try:
        y = int(row["session_start"])
        return pd.to_datetime(f"{y}-01-01")
    except Exception:
        return pd.to_datetime("2020-01-01")  # Default fallback instead of NaT

def _to_end(row):
    # Try last_action_date first
    if pd.notna(row.get("last_action_date")) and str(row["last_action_date"]).strip():
        parsed_date = pd.to_datetime(row["last_action_date"], errors="coerce")
        if pd.notna(parsed_date):
            return parsed_date
    
    # Try raw data end date
    key = f"{row['state']}_{row['bill_number']}"
    if key in end_map:
        parsed_date = pd.to_datetime(end_map[key], errors="coerce")
        if pd.notna(parsed_date):
            return parsed_date
    
    # Fall back to session end
    try:
        y = int(row["session_end"])
        return pd.to_datetime(f"{y}-12-31")
    except Exception:
        return pd.to_datetime("2025-12-31")  # Default fallback instead of NaT

df["start_date"] = df.apply(_to_start, axis=1)
df["end_date"] = df.apply(_to_end, axis=1)

# Convert other date columns
df["last_action_date"] = pd.to_datetime(df["last_action_date"], errors="coerce")
df["session_start"] = pd.to_numeric(df["session_start"], errors="coerce").astype("Int64")

df["completion_label"] = df["completed"].map({1: "Completed", 0: "Not Completed"})

# -------------------------
# Sidebar: description + author + filters
# -------------------------
st.sidebar.markdown(
    """
**Right to Repair — Bill Tracker**

Interactive dashboard to explore Right-to-Repair related bills across states.  
Filter by session year, state, and completion to inspect timelines, sponsor balance, and details.

_A small project by Payam Saeedi_
"""
)

st.sidebar.markdown("---")

# Year filter: all years, default = 2025 if present
available_years = sorted(df["session_start"].dropna().unique())
year_selection = st.sidebar.multiselect(
    "Session Start Year",
    options=available_years,
    default=[2025] if 2025 in available_years else available_years
)

# State filter
state_options = sorted(df["state"].dropna().unique())
state_selection = st.sidebar.multiselect("State", options=state_options, default=state_options)

# Completion filter
comp_label_map = {"Completed": 1, "Not Completed": 0}
comp_selection = st.sidebar.multiselect(
    "Completion Status",
    options=list(comp_label_map.keys()),
    default=list(comp_label_map.keys())
)
comp_values = [comp_label_map[x] for x in comp_selection]

# -------------------------
# Apply filters
# -------------------------
filtered = df[
    df["session_start"].isin(year_selection) &
    df["state"].isin(state_selection) &
    df["completed"].isin(comp_values)
].copy()

# -------------------------
# Main page: title, KPIs
# -------------------------
st.title("Right to Repair Bills — Dashboard")

col1, col2, col3 = st.columns(3)
col1.metric("Total Bills", len(filtered))
col2.metric("Completed", int(filtered["completed"].sum()))
col3.metric("Not Completed", int(len(filtered) - filtered["completed"].sum()))

st.markdown("---")

# -------------------------
# Waffle chart: Dem (blue) vs GOP (red)
# -------------------------
st.subheader("Sponsor Breakdown — Democrats (Blue) vs Republicans (Red)")
dem_total = int(filtered["dem_sponsors"].sum())
rep_total = int(filtered["rep_sponsors"].sum())

if dem_total + rep_total > 0:
    party_data = {"Democrats": dem_total, "Republicans": rep_total}
    fig = plt.figure(
        FigureClass=Waffle,
        plots={
            111: {
                "values": party_data,
                "rows": 10,
                "legend": {"loc": "upper left", "bbox_to_anchor": (1.0, 1.0)},
                "labels": [f"{k} ({v})" for k, v in party_data.items()],
            }
        },
        figsize=(8, 3),
        colors=["#1f77b4", "#d62728"],  # blue for Dems, red for GOP
    )
    st.pyplot(fig)
else:
    st.info("No sponsor counts available for the current filters.")

st.markdown("---")

# -------------------------
# Timeline (Gantt-like): start -> end lines
# -------------------------
st.subheader("Bill Timelines (start → last action)")

if filtered.empty:
    st.warning("No bills match the current filters.")
else:
    tl = filtered.copy()
    tl["bill_label"] = tl["state"] + " — " + tl["bill_number"].astype(str)
    
    # Debug: Show exact data going to Plotly
    with st.sidebar:
        st.markdown("### Debug Info")
        st.write(f"Filtered bills: {len(filtered)}")
        st.write(f"Timeline bills: {len(tl)}")
        
        # Show H5169 specifically
        h5169 = tl[tl["bill_number"] == "H5169"]
        if not h5169.empty:
            st.write("H5169 data:")
            row = h5169.iloc[0]
            st.write(f"State: {row['state']}")
            st.write(f"Bill: {row['bill_number']}")
            st.write(f"Label: {row['bill_label']}")
            st.write(f"Start: {row['start_date']} (type: {type(row['start_date'])})")
            st.write(f"End: {row['end_date']} (type: {type(row['end_date'])})")
            st.write(f"Completion: {row['completion_label']}")
        
        # Show data types
        st.write("Data types:")
        st.write(f"start_date: {tl['start_date'].dtype}")
        st.write(f"end_date: {tl['end_date'].dtype}")
    
    # Show raw data for inspection
    st.subheader("Raw Timeline Data (first 10 rows)")
    st.dataframe(tl[["bill_label", "start_date", "end_date", "completion_label"]].head(10))
    
    color_map = {"Completed": "#2ca02c", "Not Completed": "#d62728"}
    fig_tl = px.timeline(
        tl,
        x_start="start_date",
        x_end="end_date",
        y="bill_label",
        color="completion_label",
        color_discrete_map=color_map,
    )
    fig_tl.update_yaxes(autorange="reversed")
    fig_tl.update_layout(legend_title_text="Completion")

    # Disable all hover tooltips
    fig_tl.update_traces(hoverinfo="skip", hovertemplate=None)

    st.plotly_chart(fig_tl, use_container_width=True)

st.markdown("---")

# -------------------------
# Interactive explorer table
# -------------------------
st.subheader("Bill Explorer")

# Bill Explorer tied to current filters
explorer_df = filtered[[
    "state", "bill_number", "title", "dem_sponsors", "rep_sponsors",
    "start_date", "end_date", "last_action_date", "completion_label", "last_action"
]].sort_values(["state", "start_date"])

st.dataframe(explorer_df, use_container_width=True)

csv = filtered.to_csv(index=False)
st.download_button("Download filtered CSV", csv, "filtered_bills.csv", "text/csv")
