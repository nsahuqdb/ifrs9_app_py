"""What the Stage 2 days-past-due threshold is actually worth.

A policy debate about 30 versus 60 days is usually conducted without anybody
having priced it. This prices it: the book is repriced at each candidate
threshold through the same engine, with everything else held.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, line, metric_row, money,
                page_setup, pct, signed)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Staging threshold", "Repriced at each candidate policy")

choices = st.multiselect(
    "Thresholds to price (days)", [0, 15, 30, 45, 60, 75, 90],
    default=[0, 30, 60, 90],
    help="The policy this run actually used is always included.")
caption("Each threshold is a full repricing, so several take a few seconds.")

if st.button("Reprice", type="primary", disabled=not choices):
    with guard():
        r = api.threshold_sweep(run_id, ",".join(str(c) for c in choices))

    rows = pd.DataFrame(r["rows"])
    used = r["run_threshold"]
    base = rows.loc[rows["threshold"] == used, "ecl"]
    base = float(base.iloc[0]) if len(base) else float("nan")

    metric_row([
        ("Policy in force", f"{used:g} days"),
        ("Provision at that policy", money(base)),
        ("Widest alternative", signed(rows["ecl"].max() - base)),
        ("As a share", pct(100 * (rows["ecl"].max() - base) / max(base, 1))),
    ])

    line(rows, "threshold", "ecl", title="Provision by threshold (days)")
    caption("Rarely a straight line, and usually much flatter than people "
            "expect: most of the book is staged by watchlist, restructuring "
            "and contagion rather than by days past due, so moving the "
            "threshold moves comparatively little. That is the finding, and "
            "it is the difference between a policy debate and an argument "
            "about an untested number.")

    col = f"vs_{used:g}"
    show = rows.copy()
    if col in show.columns:
        show[col] = show[col].map(signed)
    st.dataframe(
        fmt_table(show, money_cols=("ecl", "moved", "customers_moved"),
                  pct_cols=(f"{col}_pct",)),
        use_container_width=True, hide_index=True)

    bar(rows.assign(label=[f"{t:g} days" for t in rows["threshold"]]),
        "label", "customers_moved", title="Customers restaged")
