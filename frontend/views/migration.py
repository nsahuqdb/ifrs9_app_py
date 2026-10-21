"""Who moved between two runs, on stage and on rating.

Counted as CUSTOMERS, because rating and stage are customer attributes at QDB:
a contract view counts one customer once per facility and inflates every cell
by that customer's facility count. What the moves cost is on Movement (Stage
migration and Rating migration), priced by the ECL bridge.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money, page_setup,
                pct)

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
caption("Customers, not contracts: stage and rating are set per customer. "
        "What each move cost, and which contracts carried it, is on Movement "
        "(Stage migration and Rating migration).")

with guard():
    m = api.migration(compare_id, run_id)

stage_tab, rating_tab = st.tabs(["Stage", "Rating"])

DIRECTION = {"upgrade": "Upgraded", "stable": "Stable", "downgrade": "Downgraded"}


def _scale_column(name: str, part: dict) -> None:
    """One rating scale: the summary, the from/to grid and the moves."""
    st.markdown(f"#### {name} rating")
    summary = pd.DataFrame(part.get("summary") or [])
    grid = pd.DataFrame(part.get("grid") or [])
    if len(summary) == 0:
        st.info("No customer on this scale is rated in both runs.")
        return
    total = summary["n"].sum()
    row = {r["direction"]: r for _, r in summary.iterrows()}
    metric_row([
        ("Upgraded", money(row.get("upgrade", {}).get("n", 0))),
        ("Stable", money(row.get("stable", {}).get("n", 0))),
        ("Downgraded", money(row.get("downgrade", {}).get("n", 0))),
        ("Downgrade rate", pct(100 * row.get("downgrade", {}).get("n", 0)
                               / max(total, 1))),
    ])
    st.dataframe(
        fmt_table(summary.assign(direction=summary["direction"].map(DIRECTION))
                  .rename(columns={"direction": "Direction", "n": "Customers",
                                   "exposure": "Exposure now",
                                   "ecl": "ECL now"}),
                  money_cols=("Customers", "Exposure now", "ECL now")),
        use_container_width=True, hide_index=True)

    if len(grid):
        st.markdown("**From / to** — customers; rows are the previous run's "
                    "rating, columns this run's, best grade first.")
        levels = part.get("levels") or sorted(set(grid["from"]) | set(grid["to"]))
        piv = (grid.pivot_table(index="from", columns="to", values="n",
                                aggfunc="sum").fillna(0).astype(int))
        piv = piv.reindex(index=[r for r in levels if r in piv.index],
                          columns=[r for r in levels if r in piv.columns])
        piv.index.name = "Previous ↓ / now →"
        st.dataframe(piv, use_container_width=True,
                     height=35 * (len(piv) + 1) + 3)   # every grade, no scroll

        moved = grid[grid["direction"] != "stable"]
        if len(moved):
            st.markdown("**The moves**, largest exposure first")
            show = (moved.sort_values("exposure", ascending=False)
                    .assign(direction=lambda f: f["direction"].map(DIRECTION))
                    [["from", "to", "direction", "n", "exposure", "ecl"]]
                    .rename(columns={"from": "From", "to": "To",
                                     "direction": "Direction",
                                     "n": "Customers", "exposure": "Exposure now",
                                     "ecl": "ECL now"}))
            st.dataframe(fmt_table(show, money_cols=("Customers", "Exposure now",
                                                     "ECL now")),
                         use_container_width=True, hide_index=True)


with rating_tab:
    by_scale = m.get("rating_by_scale") or {}
    if not by_scale:
        st.info("No rating appears in both runs.")
    else:
        caption("The internal (QDB) and external (agency) scales side by side: "
                "they cannot share an axis, and an upgrade is only meaningful "
                "along a scale's own order. Exposure and ECL are this run's.")
        names = [n for n in ("Internal", "External") if n in by_scale]
        for col, name in zip(st.columns(len(names)), names):
            with col:
                _scale_column(name, by_scale[name])

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
        piv.index.name = "Previous ↓ / now →"
        caption("Customers in both runs: rows are the stage in the previous "
                "run, columns the stage now. The diagonal did not move.")
        st.dataframe(piv, use_container_width=True)
        if len(moved):
            st.subheader("What the customers who moved carry")
            caption("For each move (for example Stage 1 → Stage 2), the "
                    "customers who made it: their provision in the previous "
                    "run and in this one. The difference is everything that "
                    "changed for them -- the stage, but also repayments, "
                    "rating and PD curves. The stage move alone is priced on "
                    "Movement, as Stage migration.")
            mv = moved.assign(cell=[f"Stage {a} → Stage {b}" for a, b in
                                    zip(moved["from"], moved["to"])])
            if "ecl_prev" in mv.columns:
                import plotly.graph_objects as go
                fig = go.Figure([
                    go.Bar(name="Previous run", y=mv["cell"], x=mv["ecl_prev"],
                           orientation="h", marker_color="#c9a9d8"),
                    go.Bar(name="This run", y=mv["cell"], x=mv["ecl"],
                           orientation="h", marker_color="#5b1f6e")])
                fig.update_layout(barmode="group", height=110 + 60 * len(mv),
                                  plot_bgcolor="white", paper_bgcolor="white",
                                  margin=dict(l=8, r=8, t=8, b=8),
                                  xaxis=dict(gridcolor="#f0eef4",
                                             title="ECL", tickformat=","),
                                  yaxis=dict(autorange="reversed"),
                                  legend=dict(orientation="h", y=-0.2),
                                  font=dict(size=12, color="#4a5162"))
                st.plotly_chart(fig, use_container_width=True)
                tbl = mv.assign(change=mv["ecl"] - mv["ecl_prev"])[
                    ["cell", "customers", "exposure_prev", "exposure",
                     "ecl_prev", "ecl", "change"]].rename(columns={
                        "cell": "Move", "customers": "Customers",
                        "exposure_prev": "Exposure, previous",
                        "exposure": "Exposure, now",
                        "ecl_prev": "ECL, previous", "ecl": "ECL, now",
                        "change": "Change in ECL"})
                st.dataframe(fmt_table(tbl, money_cols=[c for c in tbl.columns
                                                        if c != "Move"]),
                             use_container_width=True, hide_index=True)
            else:
                bar(mv, "cell", "ecl",
                    title="This run's provision on the customers who moved")
