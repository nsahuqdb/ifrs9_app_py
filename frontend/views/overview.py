"""Overview: the headline provision and how it splits."""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, donut, fmt_table, guard, metric_row, money,
                page_setup, pct)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Overview", "The headline provision and how it splits")

with guard():
    s = api.summary(run_id)
    pf = pd.DataFrame(api.profile(run_id, "portfolio"))
    mp = pd.DataFrame(api.maturity(run_id))

metric_row([
    ("Contracts", money(s["contracts"])),
    ("Customers", money(s["customers"])),
    ("Exposure", money(s["exposure"])),
    ("ECL provision", money(s["ecl"])),
    ("ECL coverage", pct(s["coverage"])),
])

st.subheader("By stage")
caption("Customers and contracts both shown. Staging is decided per customer, "
        "so a contract count overstates Stage 2.")
sd = pd.DataFrame(s["stages"])
c1, c2 = st.columns([3, 2])
with c1:
    st.dataframe(
        fmt_table(sd[["stage", "customers", "contracts", "exposure", "ecl",
                      "coverage"]],
                  money_cols=("customers", "contracts", "exposure", "ecl"),
                  pct_cols=("coverage",)),
        use_container_width=True, hide_index=True)
with c2:
    donut(sd["stage"], sd["ecl"], title="Share of provision")

st.subheader("By portfolio")
c1, c2 = st.columns([3, 2])
with c1:
    bar(pf, "group", "ecl", title="ECL")
with c2:
    st.dataframe(
        fmt_table(pf[["group", "contracts", "exposure", "ecl", "coverage"]],
                  money_cols=("contracts", "exposure", "ecl"),
                  pct_cols=("coverage",)),
        width="stretch", hide_index=True, height=min(320, 38 + 35 * len(pf)))

if len(mp):
    st.subheader("Run-off profile")
    caption("Longer-dated exposure normally carries higher coverage, because "
            "lifetime PD accumulates over more months.")
    c1, c2 = st.columns([3, 2])
    with c1:
        bar(mp, "band", "exposure", horizontal=False, title="Exposure")
    with c2:
        st.dataframe(
            fmt_table(mp[["band", "contracts", "exposure", "coverage"]],
                      money_cols=("contracts", "exposure"),
                      pct_cols=("coverage",)),
            width="stretch", hide_index=True, height=min(330, 38 + 35 * len(mp)))
