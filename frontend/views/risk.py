"""The risk parameters behind the provision, rather than the provision.

ECL is PD x LGD x EAD, and this page has one tab for each. Where the overview
says how much, this says what of: a provision that moved because PD moved is
a different quarter from one that moved because collateral was revalued.
"""
import pandas as pd
import streamlit as st

import api
from ui import (PLUM, SEQ, bar, caption, fmt_table, guard, line, metric_row,
                money, page_setup, pct)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Risk parameters", "PD, LGD and collateral, and the exposure")

pd_tab, lgd_tab, ead_tab = st.tabs(
    ["Probability of default", "LGD & collateral", "Exposure"])

with pd_tab:
    by = st.segmented_control(
        "Break down by", ["stage", "portfolio", "rating", "account_type"],
        default="stage", key="risk_by",
        format_func=lambda v: {"stage": "Stage", "portfolio": "Portfolio",
                               "rating": "Rating",
                               "account_type": "Account type"}[v])

with guard():
    r = api.risk(run_id, by or "stage")
    coll = api.collateral(run_id)
    dist = api.distributions(run_id)
    mp = pd.DataFrame(api.maturity(run_id))

def _pd_table(df: pd.DataFrame, first: str, first_label: str) -> None:
    """The PD figures in percent, with plain headers."""
    t = df.assign(pd_w=100 * df["pd_w"], pd_mean=100 * df["pd_mean"])
    cols = [first, "contracts", "exposure", "pd_w", "pd_mean", "ecl"]
    if "coverage" in t.columns:
        cols.append("coverage")
    t = fmt_table(t[cols], money_cols=("contracts", "exposure", "ecl"),
                  pct_cols=("pd_w", "pd_mean", "coverage"))
    t = t.rename(columns={first: first_label, "contracts": "Contracts",
                          "exposure": "Exposure",
                          "pd_w": "Lifetime PD, exposure-weighted",
                          "pd_mean": "Lifetime PD, simple mean",
                          "ecl": "ECL", "coverage": "ECL coverage"})
    st.dataframe(t, use_container_width=True, hide_index=True)


def _curves_chart(df: pd.DataFrame, y: str, title: str, yfmt: str,
                  order: list[str]) -> None:
    """One line per rating, coloured from best to worst along the scale."""
    import plotly.express as px
    from plotly.colors import sample_colorscale

    cols = (sample_colorscale("Viridis", [i / max(len(order) - 1, 1)
                                          for i in range(len(order))])
            if len(order) > 1 else [PLUM])
    fig = px.line(df, x="month", y=y, color="rating", title=title,
                  category_orders={"rating": order},
                  color_discrete_sequence=cols,
                  labels={"month": "Month", y: "%", "rating": "Rating"})
    fig.update_traces(line=dict(width=2.2))
    fig.update_layout(height=380, margin=dict(l=8, r=8, t=40, b=8),
                      plot_bgcolor="white", paper_bgcolor="white",
                      xaxis=dict(showgrid=False),
                      yaxis=dict(gridcolor="#f0eef4", tickformat=yfmt),
                      legend=dict(font=dict(size=11)),
                      font=dict(size=12),
                      title=dict(font=dict(size=13, color="#2a2f3a")))
    st.plotly_chart(fig, use_container_width=True)


with pd_tab:
    prof = pd.DataFrame(r["pd"])
    by_scale = pd.DataFrame(r.get("pd_by_scale", []))
    if len(prof) == 0:
        st.info("This run's report carries no lifetime PD.")
    elif (by or "stage") == "rating" and len(by_scale):
        # The internal and external scales reuse hierarchy 1-21, so one list
        # of ratings mixes two different things: one chart per scale.
        scales = [sc for sc in ("Internal", "External")
                  if sc in set(by_scale["scale"])]
        cols = st.columns(len(scales))
        for col, sc in zip(cols, scales):
            part = by_scale[by_scale["scale"] == sc].sort_values("order")
            with col:
                bar(part.assign(**{"Lifetime PD (%)": 100 * part["pd_w"]})
                    .rename(columns={"rating": "Rating"}),
                    "Rating", "Lifetime PD (%)",
                    title=f"{sc} rating — exposure-weighted lifetime PD (%)",
                    fmt="%{x:.2f}%", dp=2)
        caption("Best grade at the top. Stage 3 contracts count at 100%: "
                "defaulted, so provisioned at the full outstanding.")
        cols = st.columns(len(scales))
        for col, sc in zip(cols, scales):
            part = by_scale[by_scale["scale"] == sc].sort_values("order")
            with col:
                st.markdown(f"**{sc} rating**")
                _pd_table(part, "rating", "Rating")
    else:
        lab = {"stage": "Stage", "portfolio": "Portfolio", "rating": "Rating",
               "account_type": "Account type"}[by or "stage"]
        show = prof.copy()
        if (by or "stage") == "stage":
            show["group"] = "Stage " + show["group"].astype(str)
        bar(show.assign(**{"Lifetime PD (%)": 100 * show["pd_w"]})
            .rename(columns={"group": lab}),
            lab, "Lifetime PD (%)",
            title="Exposure-weighted lifetime PD (%)", fmt="%{x:.2f}%", dp=2)
        caption("Stage 3 counts at 100%: defaulted, so provisioned at the "
                "full outstanding. A weighted PD well above the simple mean "
                "means the large exposures sit in the worse grades.")
        _pd_table(show, "group", lab)

    curves = pd.DataFrame(r.get("pd_curves", []))
    if len(curves):
        st.subheader("PD term structure")
        caption("One set of curves for the internally rated book and one for "
                "the externally rated, each shared by every portfolio on that "
                "scale.")
        scales = [sc for sc in ("Internal", "External")
                  if sc in set(curves["scale"])]
        c1, c2 = st.columns([1, 3])
        with c1:
            sc = st.selectbox("Rating scale", scales, key="risk_curve_scale")
        part = curves[curves["scale"] == sc]
        order = (part.drop_duplicates("rating").sort_values("bucket")["rating"]
                 .tolist())
        # a spread along the scale to start with: best, worst and three between
        k = len(order)
        start = sorted({order[round(i * (k - 1) / 4)] for i in range(5)},
                       key=order.index) if k else []
        with c2:
            picked = st.multiselect("Ratings", order, default=start,
                                    key=f"risk_curve_ratings_{sc}")
        if not picked:
            st.info("Pick one or more ratings to plot.")
        else:
            sel = part[part["rating"].isin(picked)]
            keep = [o for o in order if o in picked]
            c1, c2 = st.columns(2)
            with c1:
                _curves_chart(sel, "cum_pd", "Cumulative PD (%)", ".2f", keep)
            with c2:
                _curves_chart(sel, "marginal_pd", "Marginal PD by month (%)",
                              ".3f", keep)
            caption("A mis-built curve shows in the marginal PD: a step, a "
                    "flat stretch, or a month that goes backwards. A worse "
                    "grade should sit above a better one throughout.")

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
