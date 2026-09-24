"""Reverse stress: how far would each lever have to move."""
import pandas as pd
import streamlit as st

import api
from ui import caption, fmt_table, guard, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Reverse stress",
           "Instead of asking what a shock does, this asks how bad things "
           "would have to get. Each lever is solved on its own by repricing "
           "repeatedly and narrowing in, so the answer is found rather than "
           "read off a grid.")

c1, c2 = st.columns([1, 3])
target = c1.number_input("Target provision increase (%)", 1.0, 500.0, 25.0, 5.0)
if not c2.button("Solve", type="primary"):
    st.stop()

with guard():
    out = pd.DataFrame(api.reverse(run_id, target))

if len(out) == 0:
    st.error("Nothing could be solved for this run.")
    st.stop()

reached = out[out["found"]]
if len(reached):
    st.success(f"The provision is most exposed to **{reached.iloc[0]['lever']}** "
               f"— the smallest move needed to reach +{target:.0f}%.", icon="✅")
else:
    st.warning(f"No single lever reaches +{target:.0f}% on its own. A "
               "combination would be needed; use a stress package.", icon="⚠️")

show = out.copy()
show["reaches target"] = show["found"].map({True: "yes", False: "no"})
st.dataframe(
    fmt_table(show[["lever", "required", "reaches target", "achieved_pct",
                    "provision"]],
              money_cols=("provision",), pct_cols=("achieved_pct",)),
    use_container_width=True, hide_index=True)
caption("A lever that cannot reach the target reports the most it achieves, "
        "rather than returning its boundary as if it were an answer.")
