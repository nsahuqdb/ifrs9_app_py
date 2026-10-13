"""The five scenario runs behind the booked figure.

"The provision is 2.28bn" means little beside "it is 2.28bn, and it would be
2.44bn in the severe downturn we give 15% weight to". This page is the second
sentence. What a different weighting would cost is a stress question, on
Stress testing -> Scenario weights.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money, page_setup,
                signed)

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
    caption("The five reports are the record of what the run priced. Where "
            "they are missing, the PD chain can be rebuilt from the config "
            "the run froze and the book repriced on each scenario in turn — "
            "a reconstruction rather than a record, and slower, but it "
            "answers the same question.")
    if st.button("Rebuild from the frozen config", type="primary"):
        with guard():
            r = api.scenarios_rebuild(run_id)
        rebuilt = pd.DataFrame(r["comparison"])
        bar(rebuilt, "scenario", "ecl", title="Provision by scenario (rebuilt)")
        st.dataframe(fmt_table(rebuilt, money_cols=("ecl",),
                               pct_cols=("vs_base_pct",)),
                     use_container_width=True, hide_index=True)
        st.info(r["note"], icon="ℹ️")
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
                            aggfunc="sum")
    # in the severity order of the table above, not alphabetically
    order = [x for x in comp["scenario"] if x in piv.index]
    piv = piv.reindex(order + [x for x in piv.index if x not in order]).reset_index()
    piv.columns = ["scenario"] + [f"Stage {int(c)}" for c in piv.columns[1:]]
    st.dataframe(fmt_table(piv, money_cols=piv.columns[1:]),
                 use_container_width=True, hide_index=True)

caption("What a different weighting would cost is on Stress testing → "
        "Scenario weights.")
