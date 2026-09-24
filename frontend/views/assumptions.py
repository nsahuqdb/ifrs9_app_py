"""What this run froze: its scenarios, its weights, its macro forecast.

A run copies its config and static reference into ``config_used/`` beside its
outputs. That copy is the only honest source for "what assumptions produced
this number" — the files in the repository have moved on since, and reading
them to explain a past quarter explains the wrong thing.
"""
import pandas as pd
import streamlit as st

import api
from ui import bar, caption, fmt_table, guard, metric_row, page_setup, pct

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Model assumptions", f"As frozen by {run_id}")

with guard():
    m = api.model_assumptions(run_id)

if not m.get("available"):
    st.info(m.get("reason", "This run has no frozen config."))
    st.stop()

sev = pd.DataFrame(m["severity"])
weights = pd.DataFrame(m["weights"])

st.subheader("Scenarios")
caption("Severity is expressed as a z-score: −1.28 is a once-in-ten-years "
        "downturn, 0 is neutral.")
st.dataframe(sev, use_container_width=True, hide_index=True)

st.subheader("Scenario weights")
if len(weights) == 0:
    st.info("This config states no explicit weights.")
else:
    caption("The two rating scales carry their OWN weights: the internal scale "
            "is driven by the non-oil GDP forecast, the external one by the "
            "GCC growth path. Applying one set to both is a real defect this "
            "port has already had once. These are what the file states — the "
            "internal scale runs on auto_non_oil_gdp_cdf, so the engine may "
            "compute them instead, and the explicit block is a rounded "
            "snapshot of that calculation.")
    metric_row([
        ("Internal weights sum", f"{weights['internal'].sum():.4f}"),
        ("External weights sum", f"{weights['external'].sum():.4f}"),
    ])
    st.dataframe(weights, use_container_width=True, hide_index=True)
    if abs(weights["internal"].sum() - 1) > 1e-6:
        caption("Not exactly 1.0, and deliberately so — the V4 weights are "
                "stated as written and are not normalised, because the engine "
                "does not normalise them either.")

st.subheader("Macroeconomic variables")
mw = pd.DataFrame(m["mev_weights"])
if len(mw):
    caption("Weight and coefficient together are the model. A variable with a "
            "large coefficient and zero weight moves nothing, however "
            "alarming the coefficient looks.")
    st.dataframe(mw, use_container_width=True, hide_index=True)
    inert = mw[mw["weight"].fillna(0) == 0]
    if len(inert):
        st.info("Weighted zero in this model, so shocking them changes "
                f"nothing: {', '.join(inert['mev'].astype(str))}.", icon="ℹ️")

fc = pd.DataFrame(m["mev_forecast"])
if len(fc):
    st.subheader("The forecast this run priced on")
    for name, g in fc.groupby("label", sort=False):
        bar(g.assign(yr=[f"Year {y}" for y in g["year"]]), "yr", "value",
            horizontal=False, title=str(name), fmt="%{y:.2f}")
    st.dataframe(fc, use_container_width=True, hide_index=True)
