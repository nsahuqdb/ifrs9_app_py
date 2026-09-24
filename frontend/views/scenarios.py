"""The five scenario runs behind the booked figure.

"The provision is 2.28bn" means little beside "it is 2.28bn, and it would be
2.44bn in the severe downturn we give 15% weight to". This page is the second
sentence, and the reweighting lets a committee ask what a different view of
the world would cost before it argues about one.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money, page_setup,
                pct, signed)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Scenarios", "What the book costs under each macro scenario")

with guard():
    s = api.scenarios(run_id)

if not s.get("available"):
    st.info(s.get("reason", "This run wrote no per-scenario reports."))
    st.stop()

comp = pd.DataFrame(s["comparison"])
booked = s.get("weighted")

metric_row([
    ("Booked (weighted)", money(booked)),
    ("Worst scenario", money(comp["ecl"].max())),
    ("Best scenario", money(comp["ecl"].min())),
    ("Spread", money(comp["ecl"].max() - comp["ecl"].min())),
    ("Priced", f"{s['files']} scenarios"),
])

bar(comp, "scenario", "ecl", title="Provision by scenario")
caption("Ordered by severity, not alphabetically — the first thing anyone "
        "looks for is whether the provision climbs monotonically as the world "
        "gets worse, and alphabetical order hides it.")

if s.get("unreadable"):
    st.warning(f"Could not read: {', '.join(s['unreadable'])}", icon="⚠️")

show = comp.copy()
if "vs_base" in show.columns:
    show["vs_base"] = show["vs_base"].map(signed)
st.dataframe(fmt_table(show, money_cols=("ecl",), pct_cols=("vs_base_pct",)),
             use_container_width=True, hide_index=True)

split = pd.DataFrame(s["stage_split"])
if len(split):
    st.subheader("Where the movement sits")
    caption("The headline moves for two reasons — the curves get worse, and "
            "contracts change stage. This is the split that separates them.")
    piv = split.pivot_table(index="scenario", columns="stage", values="ecl",
                            aggfunc="sum").reset_index()
    piv.columns = ["scenario"] + [f"Stage {int(c)}" for c in piv.columns[1:]]
    st.dataframe(fmt_table(piv, money_cols=piv.columns[1:]),
                 use_container_width=True, hide_index=True)

st.divider()
st.subheader("What a different weighting would cost")
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
