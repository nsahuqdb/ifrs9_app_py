"""What a different scenario weighting would cost.

The booked figure is a weighted sum of the five scenario runs, so any other
set of weights can be priced exactly from the same five reports, with nothing
re-run. Moved here from Portfolio -> Scenarios: the portfolio pages show the
run as booked, and a different weighting is a stress question.
"""
import pandas as pd
import streamlit as st

import api
from ui import bar, caption, fmt_table, guard, metric_row, money, page_setup, pct, signed

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Scenario weights", "What a different weighting of the five scenarios "
           "would cost")

with guard():
    s = api.scenarios(run_id)

if not s.get("available"):
    st.info(s.get("reason", "This run wrote no per-scenario reports."))
    caption("Reweighting needs the five per-scenario reports a run writes. "
            "Portfolio → Scenarios can rebuild the scenario provisions from the "
            "run's frozen config.")
    st.stop()

comp = pd.DataFrame(s["comparison"])
caption("Weights are normalised over the scenarios this run actually priced, "
        "so a weight naming one it did not cannot quietly shrink the total. "
        "Anything dropped is listed rather than assumed harmless.")

names = list(comp["scenario"])
default = {n: round(1 / len(names), 4) for n in names}
cols = st.columns(len(names))
weights = {}
for col, n in zip(cols, names):
    weights[n] = col.number_input(n, min_value=0.0, max_value=1.0,
                                  value=float(default[n]), step=0.01,
                                  format="%.4f", key=f"w_{n}")

total = sum(weights.values())
st.caption(f"These weights sum to {total:.4f}.")
if st.button("Reweight", type="primary", disabled=total <= 0):
    with guard():
        r = api.reweight(run_id, weights)
    booked_v = r.get("booked") or 0
    metric_row([
        ("Booked", money(booked_v)),
        ("Reweighted", money(r["total"])),
        ("Difference", signed(r["total"] - booked_v)),
        ("vs booked", pct(100 * (r["total"] - booked_v) / max(booked_v, 1))),
    ])
    if r.get("missing"):
        st.warning(f"Not priced by this run, so dropped: "
                   f"{', '.join(r['missing'])}", icon="⚠️")

    sens = pd.DataFrame(r["sensitivity"])
    if len(sens):
        st.subheader("Moving ten points onto each scenario")
        caption("Each row takes 10% of probability mass from the others — pro "
                "rata, so their relative standing is unchanged — and gives it "
                "to one. That is the question a committee actually asks.")
        bar(sens, "scenario", "change", diverging=True,
            title="Change in provision")
        st.dataframe(fmt_table(sens, money_cols=("ecl_scenario", "ecl_base",
                                                 "ecl_shifted", "change"),
                               pct_cols=("pct",)),
                     use_container_width=True, hide_index=True)
