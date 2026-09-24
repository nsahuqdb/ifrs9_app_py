"""Reprice the book on a different macroeconomic path.

The whole PD chain is rebuilt from the run's own frozen config with the
forecast edited, so the shift factors, the scenario curves and the monthly
StPD all follow from the new path exactly as they would in a real run. Nothing
is adjusted afterwards.
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
page_setup("Macro path", "Reprice on a different forecast")

with guard():
    m = api.model_assumptions(run_id)

if not m.get("available"):
    st.info(m.get("reason", "This run has no frozen config, so the PD chain "
                            "cannot be rebuilt."))
    st.stop()

fc = pd.DataFrame(m["mev_forecast"])
mw = pd.DataFrame(m["mev_weights"])
if len(fc) == 0:
    st.info("This run's config carries no macro forecast.")
    st.stop()

labels = fc.drop_duplicates("idx").set_index("idx")["label"].to_dict()
weight_of = (mw.set_index("idx")["weight"].to_dict() if len(mw) else {})

st.subheader("Shock a variable")
caption("A shock moves the variable by the same amount in every forecast "
        "year. Variables weighted zero in this model are shown greyed: "
        "shocking them changes nothing, and that is the model rather than a "
        "broken control.")

shock = {}
for idx, label in labels.items():
    w = weight_of.get(idx, 0) or 0
    suffix = "" if w else "  · weight 0, inert"
    shock[str(idx)] = st.slider(f"{label}{suffix}", -10.0, 10.0, 0.0, 0.25,
                                key=f"shock_{idx}", disabled=not w)

mode = st.radio(
    "Scenario weights", ["auto", "hold"], horizontal=True, key="mev_mode",
    format_func=lambda k: {"auto": "Follow the new path (as configured)",
                           "hold": "Hold this run's weights"}[k])
# caption() renders HTML, not markdown, so bold is a tag here.
caption("This matters more than it looks. The internal weights run on "
        "auto_non_oil_gdp_cdf, derived from the first forecast years of this "
        "very matrix &mdash; so on <strong>auto</strong>, editing non-oil GDP "
        "moves the weights AND the curves, and the two can point in opposite "
        "directions. <strong>Hold</strong> pins the weights to what this run "
        "used and isolates the PD effect. Showing them apart is the point of "
        "the switch.")

if st.button("Reprice", type="primary",
             disabled=not any(v for v in shock.values())):
    with guard():
        r = api.mev_stress(run_id, [], {k: v for k, v in shock.items() if v},
                           mode)
    metric_row([
        ("Before", money(r["before"])),
        ("After", money(r["after"])),
        ("Change", signed(r["delta"])),
        ("vs before", pct(100 * r["delta"] / max(r["before"], 1))),
        ("Priced", money(r["priced"])),
    ])
    if mode == "auto" and r["delta"] < 0 and any(v < 0 for v in shock.values()):
        st.warning(
            "A worse forecast has LOWERED the provision. That is the weighting "
            "effect outrunning the PD effect and pointing the other way. Run "
            "it again on **Hold this run's weights** to see the PD effect "
            "alone — the two answers together are the finding.", icon="⚠️")

    by_pf = pd.DataFrame(r["by_portfolio"])
    bar(by_pf, "portfolio", "change", diverging=True,
        title="Change by portfolio")
    caption("Investments and Banks and FIs price off GCC growth rather than "
            "the domestic variables, so a domestic shock should leave them "
            "flat. If it does not, the two rating scales have been crossed "
            "somewhere in the chain.")
    st.dataframe(fmt_table(by_pf, money_cols=("contracts", "before", "after",
                                              "change")),
                 use_container_width=True, hide_index=True)

    movers = pd.DataFrame(r["movers"])
    if len(movers):
        st.subheader("Largest movers")
        st.dataframe(
            fmt_table(movers[["customer", "facilities", "portfolio", "rating",
                              "stage", "exposure", "ecl_before", "ecl_after",
                              "change"]],
                      money_cols=("exposure", "ecl_before", "ecl_after",
                                  "change", "facilities")),
            use_container_width=True, hide_index=True)

    st.subheader("The path priced")
    st.dataframe(pd.DataFrame(r["path"]), use_container_width=True,
                 hide_index=True)

st.divider()
st.subheader("The forecast as it stands")
st.dataframe(fc, use_container_width=True, hide_index=True)
