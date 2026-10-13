"""The risk parameters behind the provision, rather than the provision.

ECL is PD x LGD x EAD, and this page has one tab for each. Where the overview
says how much, this says what of: a provision that moved because PD moved is
a different quarter from one that moved because collateral was revalued.
"""
import pandas as pd
import streamlit as st

import api
from ui import (SEQ, bar, caption, fmt_table, guard, line, metric_row, money,
                page_setup, pct)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Risk parameters", "PD, LGD and collateral, and the exposure")

pd_tab, lgd_tab, ead_tab = st.tabs(
    ["Probability of default", "LGD & collateral", "Exposure"])

with pd_tab:
    by = st.segmented_control("Break down by",
                              ["stage", "portfolio", "rating", "account_type"],
                              default="stage", key="risk_by")

with guard():
    r = api.risk(run_id, by or "stage")
    coll = api.collateral(run_id)
    dist = api.distributions(run_id)
    mp = pd.DataFrame(api.maturity(run_id))

with pd_tab:
    prof = pd.DataFrame(r["pd"])
    if len(prof) == 0:
        st.info("This run's report carries no lifetime PD.")
    else:
        bar(prof, "group", "pd_w", title="Exposure-weighted lifetime PD",
            fmt="%{x:.4f}", dp=4)
        caption("A weighted PD well above the simple mean means the large "
                "exposures sit in the worse grades.")
        st.dataframe(
            fmt_table(prof, money_cols=("exposure", "ecl", "contracts")),
            use_container_width=True, hide_index=True)

    ts = pd.DataFrame(r["term_structure"])
    if len(ts):
        st.subheader("Term structure")
        curves = sorted(ts["curve"].unique())
        pick = st.selectbox("Curve", curves, key="risk_curve")
        one = ts[ts["curve"] == pick]
        c1, c2 = st.columns(2)
        with c1:
            line(one, "month", "cum_pd", title=f"Cumulative PD — {pick} (%)",
                 yfmt=".2f")
        with c2:
            line(one, "month", "marginal_pd", title="Marginal PD by month (%)",
                 yfmt=".4f")
        caption("A mis-built curve shows in the marginal PD: a step, a flat "
                "stretch, or a month that goes backwards.")

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

    scatter = pd.DataFrame(r["lgd_scatter"])
    if len(scatter):
        import plotly.express as px
        # a stage is a category, not a scale
        scatter["stage"] = "Stage " + scatter["stage"].astype(str).str.replace(
            r"\.0$", "", regex=True)
        fig = px.scatter(scatter.sort_values("stage"), x="collcov", y="lgd",
                         color="stage", color_discrete_sequence=SEQ,
                         opacity=0.55,
                         labels={"collcov": "Collateral coverage (%)",
                                 "lgd": "LGD"})
        fig.update_layout(height=380, plot_bgcolor="white",
                          paper_bgcolor="white",
                          margin=dict(l=8, r=8, t=8, b=8),
                          font=dict(size=12, color="#4a5162"))
        st.plotly_chart(fig, use_container_width=True)
        caption("The floor is 0.45 × 0.5 = 0.225: past roughly 50% coverage "
                "more collateral changes nothing, so that flat line is the "
                "floor, not an error. Coverage is capped at 200% on the axis.")

    st.subheader("Collateral")
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
        bt = pd.DataFrame(coll["by_type"])
        if len(bt):
            c1, c2 = st.columns([3, 2])
            with c1:
                bar(bt.head(12), "type", "value", title="Collateral value by type")
            with c2:
                st.dataframe(fmt_table(bt, money_cols=("records", "value")),
                             use_container_width=True, hide_index=True)

with ead_tab:
    ex = pd.DataFrame(dist["exposure"])
    v = pd.DataFrame(dist["vintage"])
    dpd = pd.DataFrame(dist["dpd"])
    c1, c2 = st.columns(2)
    with c1:
        if len(mp):
            bar(mp, "band", "exposure", horizontal=False, height=340,
                title="Exposure by remaining maturity")
        if len(v):
            bar(v, "vintage", "coverage", horizontal=False, height=340,
                title="Coverage by origination year (%)", dp=2)
    with c2:
        if len(ex):
            bar(ex, "band", "exposure", title="Exposure by ticket size")
        if len(dpd):
            bar(dpd, "band", "coverage", title="Coverage by days past due (%)",
                dp=2)
    caption("Longer-dated exposure normally carries higher coverage, because "
            "lifetime PD accumulates over more months. A single origination "
            "year standing out is an underwriting question, not a macro one.")
    with st.expander("The figures behind these charts"):
        for title, df, money_cols in (
                ("Remaining maturity", mp, ("contracts", "exposure")),
                ("Ticket size", ex, ("contracts", "exposure", "ecl")),
                ("Origination year", v, ("contracts", "exposure", "ecl")),
                ("Days past due", dpd, ("contracts", "exposure", "ecl"))):
            if len(df):
                st.markdown(f"**{title}**")
                st.dataframe(fmt_table(df, money_cols=money_cols,
                                       pct_cols=("coverage",)),
                             use_container_width=True, hide_index=True)

    runoff = pd.DataFrame(r["ead_runoff"])
    if len(runoff):
        st.subheader("Run-off of the supplied EAD curves")
        c1, c2 = st.columns(2)
        with c1:
            line(runoff, "month", "pct_of_today",
                 title="Exposure remaining, % of today", yfmt=".0f")
        with c2:
            line(runoff, "month", "contracts", title="Contracts still on book")
        caption("Exposure falling as facilities mature is run-off; falling "
                "while the count holds is amortisation. Off BS, Al Dhameen "
                "and Tasdeer carry no curve, so they are not in it.")
