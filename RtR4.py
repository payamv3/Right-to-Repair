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
        return pd.to_datetime(start_map[key], errors="coerce")
    try:
        y = int(row["session_start"])
        return pd.to_datetime(f"{y}-01-01")
    except Exception:
        return pd.NaT

def _to_end(row):
    if pd.notna(row.get("last_action_date")):
        return pd.to_datetime(row["last_action_date"], errors="coerce")
    key = f"{row['state']}_{row['bill_number']}"
    if key in end_map:
        return pd.to_datetime(end_map[key], errors="coerce")
    try:
        y = int(row["session_end"])
        return pd.to_datetime(f"{y}-12-31")
    except Exception:
        return pd.NaT

df["start_date"] = df.apply(_to_start, axis=1)
df["end_date"] = df.apply(_to_end, axis=1)

mask_missing_start = df["start_date"].isna()
if mask_missing_start.any():
    df.loc[mask_missing_start, "start_date"] = pd.to_datetime(
        df.loc[mask_missing_start, "session_start"].astype(str) + "-01-01", errors="coerce"
    )

mask_missing_end = df["end_date"].isna()
if mask_missing_end.any():
    fallback = pd.to_datetime(df.loc[mask_missing_end, "last_action_date"], errors="coerce")
    df.loc[mask_missing_end, "end_date"] = fallback.fillna(
        pd.to_datetime(df.loc[mask_missing_end, "session_end"].astype(str) + "-12-31", errors="coerce")
    )

df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
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
    tl = filtered.dropna(subset=["start_date", "end_date"]).copy()
    if tl.empty:
        st.warning("No valid start/end dates to show on the timeline for the current selection.")
    else:
        color_map = {"Completed": "#2ca02c", "Not Completed": "#d62728"}
        fig_tl = px.timeline(
            tl,
            x_start="start_date",
            x_end="end_date",
            y="bill_number",
            color="completion_label",
            hover_data=["state", "title", "last_action", "dem_sponsors", "rep_sponsors"],
            color_discrete_map=color_map,
        )
        fig_tl.update_yaxes(autorange="reversed")
        fig_tl.update_layout(legend_title_text="Completion")
        st.plotly_chart(fig_tl, use_container_width=True)

st.markdown("---")

# -------------------------
# Interactive explorer table
# -------------------------
st.subheader("Bill Explorer")
st.dataframe(
    filtered[[
        "state", "bill_number", "title", "dem_sponsors", "rep_sponsors",
        "start_date", "end_date", "last_action_date", "completion_label", "last_action"
    ]].sort_values(["state", "start_date"]),
    use_container_width=True
)

csv = filtered.to_csv(index=False)
st.download_button("Download filtered CSV", csv, "filtered_bills.csv", "text/csv")

# -------------------------
# Notes
# -------------------------
st.markdown(
    """
**Notes**
- Requires: `streamlit`, `pandas`, `plotly`, `pywaffle`, `matplotlib`.
- Install with `pip install streamlit pandas plotly pywaffle matplotlib`.
- If your `bills_raw/` folder is present, the app will try to derive more accurate start/end dates from the raw JSONs.
"""
)
