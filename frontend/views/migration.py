"""Who moved between two runs, on rating and on stage.

Counted as CUSTOMERS by default, because rating and stage are customer
attributes at QDB: a contract view counts one customer once per facility and
inflates every cell by that customer's facility count.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money, page_setup,
                pct, signed)

run_id = st.session_state.get("run_id")
compare_id = st.session_state.get("compare_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
if not compare_id:
    st.info("Two runs are needed. Add another run to the runs folder.")
    st.stop()
page_setup("Migration", f"{compare_id} → {run_id}")

by_customer = st.toggle("Count customers rather than contracts", value=True,
                        help="Rating and stage are customer attributes; a "
                             "contract count over-weights large relationships.")

with guard():
    m = api.migration(compare_id, run_id, by_customer=by_customer)

rating_tab, stage_tab, movers_tab = st.tabs(
    ["Rating", "Stage", "Who moved"])

with rating_tab:
    summary = pd.DataFrame(m["rating_summary"])
    if len(summary) == 0:
        st.info("No rating appears in both runs.")
    else:
        total = summary["n"].sum()
        row = {r["direction"]: r for _, r in summary.iterrows()}
        metric_row([
            ("Upgraded", money(row.get("upgrade", {}).get("n", 0))),
            ("Stable", money(row.get("stable", {}).get("n", 0))),
            ("Downgraded", money(row.get("downgrade", {}).get("n", 0))),
            ("Downgrade rate", pct(100 * row.get("downgrade", {}).get("n", 0)
                                   / max(total, 1))),
        ])
        st.dataframe(fmt_table(summary, money_cols=("n", "exposure", "ecl")),
                     use_container_width=True, hide_index=True)

    grid = pd.DataFrame(m["rating"])
    if len(grid):
        st.subheader("From / to")
        caption("Without the scale's own order the axes fall back to "
                "frequency, where direction would only be a string "
                "comparison. Diagonal cells are names that did not move.")
        piv = (grid.pivot_table(index="from", columns="to", values="n",
                                aggfunc="sum").fillna(0).astype(int))
        st.dataframe(piv, use_container_width=True)
        moved = grid[grid["direction"] != "stable"]
        if len(moved):
            st.dataframe(fmt_table(moved.sort_values("exposure",
                                                     ascending=False),
                                   money_cols=("n", "exposure", "ecl")),
                         use_container_width=True, hide_index=True)

with stage_tab:
    stage = pd.DataFrame(m["stage"])
    if len(stage) == 0:
        st.info("No customer appears in both runs.")
    else:
        moved = stage[stage["from"] != stage["to"]]
        metric_row([
            ("Customers in both runs", money(stage["customers"].sum())),
            ("Changed stage", money(moved["customers"].sum())),
            ("Deteriorated", money(
                stage[stage["to"] > stage["from"]]["customers"].sum())),
            ("Improved", money(
                stage[stage["to"] < stage["from"]]["customers"].sum())),
        ])
        piv = (stage.pivot_table(index="from", columns="to", values="customers",
                                 aggfunc="sum").fillna(0).astype(int))
        piv.index = [f"Stage {i}" for i in piv.index]
        piv.columns = [f"Stage {c}" for c in piv.columns]
        st.dataframe(piv, use_container_width=True)
        if len(moved):
            bar(moved.assign(
                cell=[f"{a} → {b}" for a, b in zip(moved["from"], moved["to"])]),
                "cell", "ecl", title="Provision carried by each migration")

with movers_tab:
    movers = pd.DataFrame(m["movers"])
    if len(movers) == 0:
        st.info("No customer changed stage between these two runs.")
    else:
        caption("The matrix says how many moved; a review asks which. Sorted "
                "by the size of the provision move, so the names that explain "
                "the headline come first.")
        show = movers.copy()
        show["ecl_change"] = show["ecl_change"].map(signed)
        st.dataframe(
            fmt_table(show[["customer", "stage_prev", "stage_curr", "direction",
                            "exposure_curr", "ecl_prev", "ecl_curr",
                            "ecl_change"]],
                      money_cols=("exposure_curr", "ecl_prev", "ecl_curr")),
            use_container_width=True, hide_index=True)
