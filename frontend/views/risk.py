"""The risk parameters behind the provision, rather than the provision.

Where the overview says how much, this says what of. A provision that moved
because PD moved is a different quarter from one that moved because
collateral was revalued, and the two look identical on a headline.
"""
import pandas as pd
import streamlit as st

import api
from ui import bar, caption, fmt_table, guard, line, metric_row, money, page_setup, pct

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Risk parameters", "PD, LGD, collateral and the exposure run-off")

by = st.segmented_control("Break down by",
                          ["stage", "portfolio", "rating", "account_type"],
                          default="stage", key="risk_by")

with guard():
    r = api.risk(run_id, by or "stage")
    coll = api.collateral(run_id)

pd_tab, lgd_tab, coll_tab, ead_tab = st.tabs(
    ["Probability of default", "Loss given default", "Collateral", "Run-off"])

with pd_tab:
    prof = pd.DataFrame(r["pd"])
    if len(prof) == 0:
        st.info("This run's report carries no lifetime PD.")
    else:
        bar(prof, "group", "pd_w", title="Exposure-weighted lifetime PD",
            fmt="%{x:.4f}", dp=4)
        caption("Weighted by exposure, not by contract. The unweighted mean "
                "beside it is the tell: a weighted PD well above the mean "
                "means the large exposures sit in the worse grades.")
        st.dataframe(
            fmt_table(prof, money_cols=("exposure", "ecl", "contracts")),
            use_container_width=True, hide_index=True)

    ts = pd.DataFrame(r["term_structure"])
    if len(ts):
        st.subheader("Term structure")
        curves = sorted(ts["curve"].unique())
        pick = st.selectbox("Curve", curves, key="risk_curve")
        one = ts[ts["curve"] == pick]
        line(one, "month", "cum_pd", title=f"Cumulative PD — {pick} (%)",
             yfmt=".2f")
        caption("The marginal curve is where a mis-built term structure shows: "
                "a step, a flat stretch, or a month that goes backwards. The "
                "cumulative curve hides all three.")
        line(one, "month", "marginal_pd", title="Marginal PD by month (%)",
             yfmt=".4f")

with lgd_tab:
    floor = pd.DataFrame(r["lgd_floor"])
    if len(floor) == 0:
        st.info("This run's report carries no LGD.")
    else:
        metric_row([
            ("Weighted LGD", pct(100 * (floor["lgd_w"] * floor["exposure"]).sum()
                                 / max(floor["exposure"].sum(), 1))),
            ("On the floor", money(floor["on_floor"].sum())),
            ("Of contracts", pct(100 * floor["on_floor"].sum()
                                 / max(floor["contracts"].sum(), 1))),
        ])
        st.dataframe(fmt_table(floor, money_cols=("exposure", "contracts",
                                                  "on_floor"),
                               pct_cols=("pct_on_floor",)),
                     use_container_width=True, hide_index=True)
        caption("The floor is 0.45 × 0.5 = 0.225. A segment sitting almost "
                "entirely on it is one where collateral, not the model, sets "
                "the loss — so a move in its LGD is a collateral event.")

    scatter = pd.DataFrame(r["lgd_scatter"])
    if len(scatter):
        import plotly.express as px
        fig = px.scatter(scatter, x="collcov", y="lgd", color="stage",
                         opacity=0.55,
                         labels={"collcov": "Collateral coverage (%)",
                                 "lgd": "LGD"})
        fig.update_layout(height=380, plot_bgcolor="white",
                          paper_bgcolor="white",
                          margin=dict(l=8, r=8, t=8, b=8),
                          font=dict(size=12, color="#4a5162"))
        st.plotly_chart(fig, use_container_width=True)
        caption("Capped at 200% coverage so the axis keeps the range that "
                "matters. Past roughly 50% the floor binds and more collateral "
                "changes nothing — that flat line is the floor, not an error.")

with coll_tab:
    if not coll.get("available"):
        st.info(coll.get("reason", "No collateral tables in this run."))
    else:
        metric_row([
            ("Collateral records", money(coll["collateral_records"])),
            ("Allocations", money(coll["allocations"])),
            ("Orphan allocations", money(coll["orphan_allocations"])),
            ("Contracts affected", money(coll["orphan_contracts"])),
        ])
        if coll["orphan_allocations"]:
            st.warning(
                f"{coll['orphan_allocations']:,} allocations point at a "
                "collateral record that is not in the extract. Those contracts "
                "price as unsecured — no error is raised, their LGD simply "
                "goes to the model maximum.", icon="⚠️")
        else:
            caption("Every allocation found its collateral record. An orphan "
                    "here would price a secured contract as unsecured without "
                    "raising anything.")
        bt = pd.DataFrame(coll["by_type"])
        if len(bt):
            bar(bt.head(12), "type", "value", title="Collateral value by type")
            st.dataframe(fmt_table(bt, money_cols=("records", "value")),
                         use_container_width=True, hide_index=True)

with ead_tab:
    runoff = pd.DataFrame(r["ead_runoff"])
    if len(runoff) == 0:
        st.info("This run supplied no EAD curves.")
    else:
        line(runoff, "month", "pct_of_today",
             title="Exposure remaining, % of today", yfmt=".0f")
        caption("The contract count beside it separates two different things: "
                "exposure falling because facilities MATURE is run-off; "
                "exposure falling while the count holds is amortisation. A "
                "provision measured against the wrong one is measured against "
                "the wrong term.")
        line(runoff, "month", "contracts", title="Contracts still on book")
        st.dataframe(fmt_table(runoff, money_cols=("exposure", "contracts"),
                               pct_cols=("pct_of_today",)),
                     use_container_width=True, hide_index=True)
