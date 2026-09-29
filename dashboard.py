import json
from pathlib import Path

import streamlit as st


RESULTS_FILE = Path(__file__).with_name("job_results.jsonl")

st.set_page_config(page_title="AI Job Hunter Dashboard", page_icon="💼", layout="wide")
st.title("AI Job Hunter Dashboard")
st.caption("Track how many jobs matched your resume and how many were actually attempted.")

if not RESULTS_FILE.exists():
    st.info("No job run data has been logged yet. Run the agent once with `--test` to generate results.")
    st.stop()

records = []
with open(RESULTS_FILE, "r", encoding="utf-8") as file_obj:
    for line in file_obj:
        line = line.strip()
        if line:
            records.append(json.loads(line))

if not records:
    st.info("The result log is empty right now.")
    st.stop()

matched_count = sum(1 for record in records if record.get("matched"))
applied_count = sum(1 for record in records if record.get("applied"))
recent_rows = records[-10:]

col1, col2, col3 = st.columns(3)
col1.metric("Jobs Matched", matched_count)
col2.metric("Jobs Applied", applied_count)
col3.metric("Total Jobs Reviewed", len(records))

st.subheader("Recent Job Results")

status_df = [
    {
        "Portal": record.get("portal", "-"),
        "Company": record.get("company", "-"),
        "Title": record.get("title", "-"),
        "Matched": "Yes" if record.get("matched") else "No",
        "Applied": "Yes" if record.get("applied") else "No",
        "Score": round(record.get("score", 0), 2),
        "Overlaps": ", ".join(record.get("overlaps", []))[:120],
    }
    for record in recent_rows
]

st.dataframe(status_df, use_container_width=True, hide_index=True)

portal_breakdown = {}
for record in records:
    portal = record.get("portal", "unknown")
    portal_breakdown.setdefault(portal, {"matched": 0, "applied": 0, "total": 0})
    portal_breakdown[portal]["total"] += 1
    if record.get("matched"):
        portal_breakdown[portal]["matched"] += 1
    if record.get("applied"):
        portal_breakdown[portal]["applied"] += 1

st.subheader("Portal-wise Summary")
summary_rows = [
    {
        "Portal": portal,
        "Total Jobs": stats["total"],
        "Matched": stats["matched"],
        "Applied": stats["applied"],
    }
    for portal, stats in portal_breakdown.items()
]
st.dataframe(summary_rows, use_container_width=True, hide_index=True)
