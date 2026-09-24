"""Data quality: conditions that distort a provision."""
import pandas as pd
import streamlit as st

import api
from ui import caption, fmt_table, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Data quality",
           "Reported, never corrected. Severity is a guide to what distorts a "
           "provision most, not to how easy it is to fix.")

with guard():
    q = pd.DataFrame(api.quality(run_id))

if len(q) == 0:
    st.success("No data-quality findings.")
    st.stop()

counts = q.groupby("severity")["contracts"].sum()
metric_row([
    ("Findings", money(len(q))),
    ("Errors", money(counts.get("error", 0))),
    ("Warnings", money(counts.get("warn", 0))),
    ("Contracts affected", money(int(q["contracts"].sum()))),
])

with guard():
    detail = api.quality_detail(run_id)

for sev, label in (("error", "Errors"), ("warn", "Warnings"), ("info", "Notes")):
    part = q[q["severity"] == sev]
    if len(part) == 0:
        continue
    st.subheader(label)
    for _, r in part.iterrows():
        with st.expander(f"{r['check']} — {int(r['contracts']):,} contracts "
                         f"({r['pct']:.2f}% of the book)"):
            st.write(r["note"])
            c1, c2 = st.columns(2)
            c1.metric("Exposure", money(r["exposure"]))
            c2.metric("ECL", money(r["ecl"]))

            rows = pd.DataFrame(detail.get(r["check"], []))
            if len(rows):
                caption("Largest exposure first. A count is an argument; a "
                        "list of contract ids is something somebody can act "
                        "on.")
                st.dataframe(
                    fmt_table(rows, money_cols=("exposure", "ecl")),
                    use_container_width=True, hide_index=True)
                st.download_button(
                    "Download these contracts", rows.to_csv(index=False),
                    file_name=f"{run_id}_{r['check'].lower().replace(' ', '_')}.csv",
                    mime="text/csv", key=f"dl_{r['check']}")
