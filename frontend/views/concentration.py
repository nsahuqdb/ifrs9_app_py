"""Concentration: how much of the provision sits with how few names."""
import pandas as pd
import streamlit as st

import api
from ui import (caption, fmt_table, guard, line, metric_row, money,
                page_setup, pct, pill)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Concentration")

level = st.radio("Measure by", ["customer", "contract"], horizontal=True,
                 help="Customer is the right unit: one borrower with ten "
                      "facilities is a single exposure, not ten.")
with guard():
    c = api.concentration(run_id, level)

band = c["band"]
tone = {"ok": "ok", "warn": "warn", "err": "err"}.get(band["tone"], "info")
metric_row([
    ("Concentration index", money(c["hhi"])),
    ("Equivalent equal customers", money(c["equivalent_customers"])),
    ("Assessment", band["band"]),
])
st.markdown(pill(band["band"], tone) + f"  {band['note']}", unsafe_allow_html=True)
caption("The index is the sum of squared shares of the provision. The 1,500 and "
        "2,500 marks are the usual competition-authority bands — a market "
        "convention, not a QCB limit. Single-obligor and large-exposure limits "
        "are not tested here.")

shares = pd.DataFrame(c["shares"])
top = pd.DataFrame(c["top"])
c1, c2 = st.columns(2)
with c1:
    st.subheader("Share of the provision")
    st.dataframe(fmt_table(shares, money_cols=("top_n", "ecl"),
                           pct_cols=("share",)),
                 use_container_width=True, hide_index=True)
with c2:
    st.subheader("Largest contributors")
    cols = [x for x in ("customer", "contract", "portfolio", "rating", "stage",
                        "exposure", "ecl", "share") if x in top.columns]
    st.dataframe(fmt_table(top[cols], money_cols=("exposure", "ecl"),
                           pct_cols=("share",)),
                 use_container_width=True, hide_index=True, height=340)
