"""Model assumptions: what the selected run assumed, and where the methodology
explains it.

The values are read from the run's frozen config (config_used/), the copy the
run priced with -- not the files in the repository, which may have moved on.
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**.", icon="👈")
    st.stop()
page_setup("Model assumptions", f"The assumptions {run_id} was priced with")

with guard():
    m = api.model_assumptions(run_id)

if not m.get("available"):
    st.info(m.get("reason", "This run has no frozen config."))
    st.stop()

rows = pd.DataFrame(m.get("assumptions") or [])
if rows.empty:
    st.info("The assumptions of this run could not be read.")
    st.stop()

areas = list(dict.fromkeys(rows["area"]))
pick = st.segmented_control("Area", ["All"] + areas, default="All",
                            key="ass_area", label_visibility="collapsed")
show = rows if pick in (None, "All") else rows[rows["area"] == pick]
st.dataframe(
    show.rename(columns={"area": "Area", "assumption": "Assumption",
                         "value": "Value in this run", "source": "Set in",
                         "link": "Methodology"}),
    hide_index=True, width="stretch",
    height=min(760, 38 + 35 * len(show)),
    column_config={
        "Area": st.column_config.TextColumn(width="small"),
        "Assumption": st.column_config.TextColumn(width="large"),
        "Value in this run": st.column_config.TextColumn(width="medium"),
        "Set in": st.column_config.TextColumn(width="small"),
        "Methodology": st.column_config.LinkColumn(width="small",
                                                   display_text="Open ↗")})
caption("Values from the run's frozen config. “Fixed by the method” is part of "
        "the calculation, not a setting.")

fc = pd.DataFrame(m.get("mev_forecast") or [])
if len(fc) and {"label", "year", "value"} <= set(fc.columns):
    st.subheader("Macro forecast")
    wide = fc.pivot_table(index="label", columns="year", values="value",
                          aggfunc="first", sort=False)
    wide.columns = [f"Year {c}" for c in wide.columns]
    st.dataframe(wide.reset_index().rename(columns={"label": "Variable"}),
                 hide_index=True, width="stretch")
