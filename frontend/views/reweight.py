"""What a different scenario weighting would cost.

Repriced, not interpolated: the PD chain is rebuilt from the run's frozen
config with the weights entered, exactly as a run builds it, and the book is
priced with the engine's own ECL function (ifrs9qdb.stress.
scenario_weights_stress). At the run's own weights that is the booked figure.
The weights are the internal scale's -- the QDB grades; Investments and Banks
& FIs keep their own, which follow GCC growth year by year. Moved here from
Portfolio -> Scenarios: the portfolio pages show the run as booked, and a
different weighting is a stress question.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, callout, caption, fmt_table, guard, metric_row, money,
                page_setup, pct, signed)

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Scenario weights", "What a different weighting of the five scenarios "
           "would cost")

with guard():
    rw = api.scenario_weights(run_id)
if not rw.get("ok"):
    st.info(rw.get("reason", "This run's scenario weights could not be resolved."))
    caption("Reweighting rebuilds the PD chain from the run's frozen config, "
            "so it needs the config the run froze (config_used).")
    st.stop()

own = rw["internal"]
names = list(own)
caption("The weights the run was priced with, as the engine works them out "
        "from its frozen config. These are the internal scale's (the QDB "
        "grades); Investments and Banks & FIs keep their own, which follow GCC "
        "growth year by year. Weights are normalised to 100%.")

cols = st.columns(len(names))
entered = {}
for col, n in zip(cols, names):
    entered[n] = col.number_input(n, min_value=0.0, max_value=100.0,
                                  value=round(100 * own[n], 2), step=0.5,
                                  format="%.2f", key=f"w_{run_id}_{n}")
# An input left at its (rounded) starting value means the run's own weight,
# exactly, so the run's own weights reprice to the booked figure to the cent.
weights = {n: own[n] if v == round(100 * own[n], 2) else v / 100
           for n, v in entered.items()}
total = 100 * sum(weights.values())
st.caption(f"These weights sum to {total:.2f}%. The run's own: "
           + ", ".join(f"{n} {100 * own[n]:.2f}%" for n in names) + ".")

key = (run_id, tuple(round(v, 6) for v in weights.values()))
c1, c2 = st.columns([1, 3])
if c1.button("Reprice at these weights", type="primary", disabled=total <= 0):
    with guard(), st.spinner("Rebuilding the PD curves and repricing the book…"):
        S["rw_result"] = (key, api.reweight(run_id, weights))
if c2.button("Move ten points onto each scenario", disabled=total <= 0):
    with guard(), st.spinner("Repricing the book once per scenario…"):
        S["rw_sens"] = (key, api.reweight_sensitivity(run_id, weights))

res = S.get("rw_result")
if res and res[0] == key:
    r = res[1]
    metric_row([
        ("This run", money(r["before"])),
        ("At these weights", money(r["after"])),
        ("Difference", signed(r["delta"])),
        ("vs this run", pct(100 * r["delta"] / r["before"]) if r["before"] else "—"),
    ])
    if r.get("note"):
        callout("info", r["note"])
    by = pd.DataFrame(r.get("by_portfolio") or [])
    if len(by):
        st.dataframe(fmt_table(by, money_cols=("contracts", "before", "after",
                                               "change")),
                     use_container_width=True, hide_index=True)
    caption("Every contract repriced with the engine's ECL function on PD "
            "curves rebuilt with these weights. Investments and Banks & FIs "
            "do not move: their weights are their own.")

sens = S.get("rw_sens")
if sens and sens[0] == key:
    sv = pd.DataFrame(sens[1])
    if len(sv):
        st.subheader("Moving ten points onto each scenario")
        caption("Each row takes 10% of probability mass from the others — pro "
                "rata, so their relative standing is unchanged — gives it to "
                "one, and reprices the book. That is the question a committee "
                "actually asks.")
        bar(sv, "scenario", "change", diverging=True, title="Change in provision")
        show = sv.assign(weight_before=100 * sv["weight_before"],
                         weight_after=100 * sv["weight_after"])
        st.dataframe(fmt_table(show, money_cols=("ecl_scenario", "ecl_base",
                                                 "ecl_shifted", "change"),
                               pct_cols=("weight_before", "weight_after", "pct")),
                     use_container_width=True, hide_index=True)
