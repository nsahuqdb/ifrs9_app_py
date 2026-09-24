"""Why the provision moved, split into the things that caused it.

The walk says how much moved and in which direction. This says what moved it.
Two answers, deliberately: an indicative split that is instant, and an exact
one that reprices every contract through the engine.
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
page_setup("Attribution", f"{compare_id} → {run_id}")

by = st.segmented_control("Coverage bridge by",
                          ["portfolio", "stage", "rating"],
                          default="portfolio", key="attr_by")
exact = st.toggle("Reprice through the engine (exact)", value=False,
                  help="Slower, but the effects sum to the move by "
                       "construction rather than being rescaled to fit.")

with guard():
    a = api.attribution(compare_id, run_id, by or "portfolio", exact)

ind = pd.DataFrame(a["indicative"])
if len(ind):
    st.subheader("Exposure, PD and LGD")
    metric_row([
        ("Movement", signed(ind["actual_change"].iloc[0])),
        ("On contracts in both runs", money(ind["contracts"].iloc[0])),
    ])
    bar(ind, "factor", "effect", diverging=True)
    caption("Indicative. ECL is not exposure × PD × LGD — there is "
            "discounting, the exposure cap and the Stage 3 treatment — so the "
            "three raw effects do not add up on their own and are rescaled to "
            "the actual move. A guide to where the movement came from, not an "
            "identity.")
    st.dataframe(fmt_table(ind[["factor", "effect", "raw_effect"]],
                           money_cols=("effect", "raw_effect")),
                 use_container_width=True, hide_index=True)

if exact:
    st.divider()
    st.subheader("Through the engine")
    ex = a.get("exact")
    if not ex:
        st.info(a.get("exact_reason", "The exact attribution could not be built."))
    else:
        eff = pd.DataFrame(ex["effects"])
        metric_row([
            ("Opening (repriced)", money(ex["opening"])),
            ("Closing (repriced)", money(ex["closing"])),
            ("Contracts priced", f"{ex['covered']:,} of {ex['contracts']:,}"),
            ("Unattributable", signed(ex["uncovered"])),
            ("Residual", f"{ex['residual']:.2e}"),
        ])
        bar(eff, "factor", "effect", diverging=True)
        caption("Each contract is repriced five times, substituting one "
                "ingredient at a time — horizon, then EAD curve, then PD "
                "curve, then LGD and EIR. Each effect is the difference "
                "between two repricings, so they sum to the move exactly. "
                "Opening and closing are the repriced totals over the covered "
                "contracts, not the reports' headline, so they will not match "
                "the walk and are not meant to.")
        st.dataframe(fmt_table(eff, money_cols=("effect",)),
                     use_container_width=True, hide_index=True)

st.divider()
st.subheader("Coverage: mix or rate")
bridge = pd.DataFrame(a["bridge"])
if len(bridge) == 0:
    st.info("Nothing to bridge between these two runs.")
else:
    caption("Coverage can move without a single contract changing. If the "
            "book shifts toward a segment that was always provisioned more "
            "heavily, the headline rate rises while every segment's own rate "
            "is flat. Only one of those is a credit event. Both are in "
            "percentage points of overall coverage, so they add to the total.")
    metric_row([
        ("Mix effect", pct(bridge["mix_effect"].sum())),
        ("Rate effect", pct(bridge["rate_effect"].sum())),
        ("Total change", pct(bridge["total_effect"].sum())),
    ])
    bar(bridge, "group", "total_effect", diverging=True,
        title="Contribution to the change in coverage (pp)", fmt="%{x:.4f}",
        dp=4)
    show = bridge.copy()
    for c in ("cov_a", "cov_b"):
        show[c] = 100 * show[c]
    st.dataframe(fmt_table(show, money_cols=("exposure_a", "exposure_b"),
                           pct_cols=("cov_a", "cov_b", "mix_effect",
                                     "rate_effect", "total_effect")),
                 use_container_width=True, hide_index=True)
