"""Several stress packages side by side.

One package answers "what if". Several answer "which of these hurts most",
which is the question a committee actually puts. Pricing them together keeps
them on identical inputs, so the ranking means something.

The packages here are the standard severities. Anything bespoke belongs on
Stress packages, one at a time, where every lever is visible.
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
page_setup("Package comparison", "The standard severities, priced together")

with guard():
    sc = api.scope(run_id)
internal = sc.get("internal", [])
if sc.get("external"):
    caption(f"{', '.join(sc['external'])} are externally rated and do not "
            "price against the internal PD curves, so a rating or PD lever "
            "leaves them unchanged. They are out of scope by default.")

# The levers each package moves, and why that combination. Each is a single
# coherent story rather than an arbitrary bundle.
PACKAGES = {
    "Mild downturn": dict(pd_multiplier=1.25, rating_notches=1,
                          collateral_pct=90),
    "Severe downturn": dict(pd_multiplier=2.0, rating_notches=3,
                            collateral_pct=70, exposure_pct=110),
    "Collateral revaluation": dict(collateral_pct=50),
    "Staging tightened to 30 days": dict(dpd_threshold=30),
    "Largest five default": dict(default_top_n=5),
}

chosen = st.multiselect("Packages to price", list(PACKAGES),
                        default=list(PACKAGES))
scope = st.multiselect("Scope", sc.get("all", []), default=internal)
caption("Each package is a full repricing of the book, so several take a "
        "little time.")

if st.button("Price them", type="primary", disabled=not chosen):
    packages = [{"name": n, "portfolios": scope, **PACKAGES[n]} for n in chosen]
    with guard():
        rows = pd.DataFrame(api.compare_packages(run_id, packages))

    base = rows["before"].iloc[0]
    worst = rows.iloc[0]
    metric_row([
        ("Provision now", money(base)),
        ("Worst package", worst["name"]),
        ("Under it", money(worst["after"])),
        ("Change", signed(worst["delta"])),
        ("As a share", pct(worst["pct"])),
    ])

    bar(rows, "name", "delta", diverging=True,
        title="Change in provision by package")
    caption("Ranked by how much each adds. A package that moves less than "
            "expected is a finding in itself — on this book the staging "
            "levers move far less than the PD and collateral ones, because "
            "most contracts are staged by watchlist and contagion rather "
            "than by days past due.")
    st.dataframe(fmt_table(rows, money_cols=("before", "after", "delta",
                                             "moved"),
                           pct_cols=("pct",)),
                 use_container_width=True, hide_index=True)

    with st.expander("What each package changes"):
        spec = pd.DataFrame([{"package": n, **PACKAGES[n]} for n in chosen])
        st.dataframe(spec.fillna(""), use_container_width=True,
                     hide_index=True)
