"""Staging: the split, and why each Stage 2 contract is there."""
import pandas as pd
import streamlit as st

import api
from ui import bar, caption, fmt_table, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Staging",
           "Decided per customer. Tasdeer is assessed collectively, and a "
           "customer with any Stage 2 facility has its Stage 1 facilities "
           "bumped by contagion.")

threshold = st.slider("Stage 2 DPD threshold", 0, 90, 60, 5,
                      help="The rule is DPD greater than this, up to 90.")
with guard():
    d = api.staging(run_id, threshold)

sd = pd.DataFrame(d["distribution"])
metric_row([(r["stage"], f"{int(r['customers']):,}",
             f"{int(r['contracts']):,} contracts") for _, r in sd.iterrows()])
st.dataframe(
    fmt_table(sd[["stage", "customers", "contracts", "exposure", "ecl",
                  "coverage", "pct_ecl"]],
              money_cols=("customers", "contracts", "exposure", "ecl"),
              pct_cols=("coverage", "pct_ecl")),
    use_container_width=True, hide_index=True)

t = pd.DataFrame(d["triggers"])
if len(t) == 0:
    st.info("No Stage 2 contracts in this run.")
    st.stop()

st.subheader("Why each Stage 2 contract is in Stage 2")
cols = ["trigger", "contracts", "customers", "pct_contracts", "exposure", "ecl"]
tab1, tab2 = st.tabs(["Has trigger", "Sole reason"])
for tab, basis, note in (
    (tab1, "any", "Triggers overlap, so these shares add to more than 100%."),
    (tab2, "sole", "Only where that trigger is the single cause, so these are "
                   'additive. "Stage override" is a stage forced in the source data.'),
):
    with tab:
        caption(note)
        part = t[t["basis"] == basis]
        c1, c2 = st.columns([2, 3])
        with c1:
            bar(part[part["contracts"] > 0], "trigger", "contracts")
        with c2:
            st.dataframe(
                fmt_table(part[cols],
                          money_cols=("contracts", "customers", "exposure", "ecl"),
                          pct_cols=("pct_contracts",)),
                use_container_width=True, hide_index=True)
