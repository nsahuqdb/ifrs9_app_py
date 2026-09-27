"""The shape of the book, one histogram per question asked at a review.

Each profile conserves its total — every contract lands in exactly one band —
so a band showing nothing is genuinely empty rather than dropped.
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
page_setup("Distributions", "How the book is spread, band by band")

with guard():
    d = api.distributions(run_id)

delinquency, size, security, vintage, params = st.tabs(
    ["Delinquency", "Ticket size", "Security", "Vintage", "Risk parameters"])

with delinquency:
    dpd = pd.DataFrame(d["dpd"])
    if len(dpd) == 0:
        st.info("This report carries no days-past-due.")
    else:
        caption("Coverage should climb steeply across the buckets. Where it "
                "does not, staging is being driven by something other than "
                "delinquency — which on this book it largely is.")
        bar(dpd, "band", "coverage", title="Coverage by DPD band (%)", dp=2)
        st.dataframe(fmt_table(dpd, money_cols=("contracts", "exposure", "ecl"),
                               pct_cols=("coverage",)),
                     use_container_width=True, hide_index=True)

with size:
    ex = pd.DataFrame(d["exposure"])
    if len(ex) == 0:
        st.info("Nothing to band.")
    else:
        caption("Many small facilities or a few large ones. It decides whether "
                "a concentration limit or a portfolio rule is the right "
                "instrument.")
        bar(ex, "band", "exposure", title="Exposure by ticket size")
        st.dataframe(fmt_table(ex, money_cols=("contracts", "exposure", "ecl"),
                               pct_cols=("coverage",)),
                     use_container_width=True, hide_index=True)

with security:
    cb = pd.DataFrame(d["collateral"])
    if len(cb) == 0:
        st.info("This report carries no collateral coverage.")
    else:
        caption("Over 100% coverage still sits on the LGD floor: past roughly "
                "50% the floor binds and more collateral changes nothing. "
                "That flat stretch is the floor, not a data problem.")
        bar(cb, "band", "exposure", title="Exposure by collateral coverage")
        st.dataframe(fmt_table(cb, money_cols=("contracts", "exposure", "ecl"),
                               pct_cols=("coverage",)),
                     use_container_width=True, hide_index=True)

with vintage:
    v = pd.DataFrame(d["vintage"])
    if len(v) == 0:
        st.info("This report carries no origination dates.")
    else:
        caption("By the year the facility was written. A single year standing "
                "out is an underwriting question, not a macro one.")
        bar(v, "vintage", "coverage", horizontal=False,
            title="Coverage by origination year (%)", dp=2)
        st.dataframe(fmt_table(v, money_cols=("contracts", "exposure", "ecl"),
                               pct_cols=("coverage",)),
                     use_container_width=True, hide_index=True)

with params:
    pr = pd.DataFrame(d["pd_by_rating"])
    if len(pr):
        caption("PD should rise monotonically as the rating worsens. A kink "
                "usually means a rating or PD-curve mapping broke — it is the "
                "quickest check there is on the term structure.")
        bar(pr, "group", "pd_weighted", title="Weighted PD by rating",
            dp=4)
        st.dataframe(fmt_table(pr, money_cols=("contracts", "exposure", "ecl"),
                               pct_cols=("coverage",)),
                     use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    pdd = pd.DataFrame(d["pd"])
    if len(pdd):
        with c1:
            bar(pdd, "band", "contracts", title="PD distribution")
    lgd = pd.DataFrame(d["lgd"])
    if len(lgd):
        with c2:
            bar(lgd, "band", "contracts", title="LGD distribution")
            caption("The spike at 0.225 is the floor. A book where almost "
                    "everything sits there is one where collateral, not the "
                    "model, sets the loss.")

    lz = pd.DataFrame(d["lorenz"])
    if len(lz):
        st.subheader("Concentration")
        line(lz, "pct_contracts", "pct_ecl",
             title="Share of the provision held by the largest customers (%)",
             yfmt=".0f")
