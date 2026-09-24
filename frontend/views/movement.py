"""Movement between two runs. The steps sum exactly to the closing balance."""
import pandas as pd
import streamlit as st

import api
from ui import (caption, fmt_table, guard, metric_row, money, page_setup, pct,
                waterfall)

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
