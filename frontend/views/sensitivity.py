"""Lever sensitivity: which lever the provision is most exposed to."""
import pandas as pd
import streamlit as st

import api
from ui import bar, caption, fmt_table, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Lever sensitivity",
           "Each lever moved on its own from the same base, ranked by effect. "
           "The bars are comparable but do NOT add up — combining levers has "
           "interactions, which is what a stress package is for.")

if not st.button("Run", type="primary"):
    with guard():
        sc = api.scope(run_id)
    st.caption("The moves that will be applied, one at a time:")
    st.dataframe(pd.DataFrame(sc["levers"])[["label", "key", "value"]],
                 use_container_width=True, hide_index=True,
                 column_config={"label": "Move", "key": "Lever",
                                "value": "Set to"})
    st.stop()

with guard():
    t = api.tornado(run_id)

lv = pd.DataFrame(t["levers"])
if len(lv) == 0:
    st.error("Nothing could be priced.")
    st.stop()

metric_row([
    ("Provision at base", money(t["base"])),
    ("Most sensitive to", lv.iloc[0]["lever"]),
    ("That lever's effect", money(lv.iloc[0]["change"])),
])
bar(lv, "lever", "change", diverging=True, height=max(300, 34 * len(lv) + 80))
st.dataframe(fmt_table(lv[["lever", "provision", "change", "pct", "moved"]],
                       money_cols=("provision", "change", "moved"),
                       pct_cols=("pct",)),
             use_container_width=True, hide_index=True)
