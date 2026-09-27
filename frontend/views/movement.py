"""Movement between two runs. The steps sum exactly to the closing balance."""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money,
                page_setup, pct, waterfall)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
compare_id = st.session_state.get("compare_id")
page_setup("Movement")

if not compare_id:
    st.info("Two runs are needed. Add another run to the runs folder.")
    st.stop()
caption(f"{compare_id} → {run_id}")

with guard():
    w = api.walk(compare_id, run_id)

steps = pd.DataFrame(w["steps"])
metric_row([
    ("Opening", money(w["opening"])),
    ("Closing", money(w["closing"])),
    ("Movement", money(w["closing"] - w["opening"])),
    ("% change", pct(100 * (w["closing"] - w["opening"]) / max(w["opening"], 1))),
    ("Stage migrated", money(w["counts"]["migrated"])),
])

waterfall(steps)
caption(f"Residual {w['residual']:.6f}. Exposure movement is measured at the "
        "old coverage, then the coverage change at the new exposure; that "
        "order is fixed so the walk is reproducible each quarter.")

steps["% of opening"] = [
    100 * a / max(w["opening"], 1) if k == "delta" else None
    for a, k in zip(steps["amount"], steps["kind"])
]
st.dataframe(fmt_table(steps[["label", "amount", "% of opening"]],
                       money_cols=("amount",), pct_cols=("% of opening",)),
             use_container_width=True, hide_index=True)

c1, c2, c3 = st.columns(3)
c1.metric("New contracts", money(w["counts"]["arrived"]))
c2.metric("Derecognised", money(w["counts"]["left"]))
c3.metric("In both runs", money(w["counts"]["common"]))


# ------------------------------------------------ flows and the drill-down
st.divider()
by = st.segmented_control("Break the movement down by",
                          ["portfolio", "stage", "rating", "account_type"],
                          default="portfolio", key="mv_by")
with guard():
    f = api.flows(compare_id, run_id, by or "portfolio")

flow_tab, seg_tab, detail_tab = st.tabs(
    ["Arrivals and departures", "By segment", "Behind each step"])

with flow_tab:
    fl = pd.DataFrame(f["flows"])
    if len(fl) == 0:
        st.info("No contracts arrived or left between these two runs.")
    else:
        caption("New business and derecognition are the two steps of the walk "
                "that are not about the existing book changing. Their coverage "
                "is the interesting column: business arriving at a higher "
                "coverage than the book it joins moves the headline on its own.")
        st.dataframe(fmt_table(fl, money_cols=("contracts", "exposure", "ecl"),
                               pct_cols=("coverage",)),
                     use_container_width=True, hide_index=True)

with seg_tab:
    seg = pd.DataFrame(f["by_segment"])
    if len(seg) == 0:
        st.info("Nothing to break down.")
    else:
        bar(seg, "group", "change", diverging=True,
            title="Movement by segment")
        st.dataframe(fmt_table(seg, money_cols=("before", "after", "change")),
                     use_container_width=True, hide_index=True)

with detail_tab:
    caption("The contracts behind each step. Every drill-down sums back to "
            "its own step — that is asserted in the engine's tests, not "
            "hoped for — so these are the names that make up the waterfall.")
    detail = f["detail"]
    if not detail:
        st.info("Nothing to drill into.")
    for label, rowsets in detail.items():
        frame = pd.DataFrame(rowsets)
        if len(frame) == 0:
            continue
        with st.expander(f"{label} — largest {len(frame)}"):
            st.dataframe(fmt_table(frame, money_cols=("amount", "exposure",
                                                      "ecl")),
                         use_container_width=True, hide_index=True)
