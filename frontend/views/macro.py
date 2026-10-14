"""Macro & scenarios: reprice on a different forecast or scenario weighting.

The whole PD chain is rebuilt from the run's own frozen config with the edit,
so the shift factors, the scenario curves and the monthly StPD all follow from
it exactly as they would in a real run, and the book is priced with the
engine's own ECL function (ifrs9qdb.stress.mev_stress). Nothing is adjusted
afterwards. A different weighting is the same repricing with the forecast
untouched, so the former Scenario weights page lives here: Set my own, and
Ten points onto each scenario.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, callout, caption, fmt_table, guard, metric_row, money,
                page_setup, pct, signed)

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Macro & scenarios", "Reprice on a different forecast or a "
           "different weighting of the scenarios")

with guard():
    m = api.model_assumptions(run_id)
    rw = api.scenario_weights(run_id)

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

st.subheader("Shock the forecast")
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
shocked = {k: v for k, v in shock.items() if v}

st.subheader("Scenario weights")
modes = {"auto": "Follow the new path (as configured)",
         "hold": "Hold this run's weights",
         "custom": "Set my own"}
if not rw.get("ok"):
    modes.pop("custom")
mode = st.radio("Scenario weights", list(modes), horizontal=True,
                key="mev_mode", format_func=modes.get,
                label_visibility="collapsed")
# caption() renders HTML, not markdown, so bold is a tag here.
caption("This matters more than it looks. The internal weights run on "
        "auto_non_oil_gdp_cdf, derived from the first forecast years of this "
        "very matrix &mdash; so on <strong>Follow</strong>, editing non-oil "
        "GDP moves the weights AND the curves, and the two can point in "
        "opposite directions. <strong>Hold</strong> pins the weights to what "
        "this run used and isolates the PD effect. <strong>Set my own</strong> "
        "prices the weights you enter.")

weights = None
if rw.get("ok"):
    own = rw["internal"]
    names = list(own)
    if mode == "custom":
        cols = st.columns(len(names))
        entered = {}
        for col, n in zip(cols, names):
            entered[n] = col.number_input(n, min_value=0.0, max_value=100.0,
                                          value=round(100 * own[n], 2),
                                          step=0.5, format="%.2f",
                                          key=f"w_{run_id}_{n}")
        # An input left at its (rounded) starting value means the run's own
        # weight, exactly, so the run's own weights reprice to the booked
        # figure to the cent.
        weights = {n: own[n] if v == round(100 * own[n], 2) else v / 100
                   for n, v in entered.items()}
        st.caption(f"These weights sum to {100 * sum(weights.values()):.2f}% "
                   "and are normalised to 100%.")
    caption("The run's own, as the engine works them out from its frozen "
            "config: " + ", ".join(f"{n} {100 * own[n]:.2f}%" for n in names)
            + ". These are the internal scale's (the QDB grades); Investments "
            "and Banks &amp; FIs keep their own, which follow GCC growth year "
            "by year.")

total_ok = weights is None or sum(weights.values()) > 0
key = (run_id, tuple(sorted(shocked.items())), mode,
       tuple(round(v, 8) for v in (weights or {}).values()))
c1, c2 = st.columns([1, 3])
if c1.button("Reprice", type="primary",
             disabled=not total_ok or not (shocked or mode == "custom")):
    with guard(), st.spinner("Rebuilding the PD curves and repricing the book…"):
        S["mev_result"] = (key, api.mev_stress(run_id, [], shocked, mode,
                                               weights))
if c2.button("Ten points onto each scenario", disabled=not total_ok
             or not rw.get("ok")):
    with guard(), st.spinner("Repricing the book once per scenario…"):
        S["mev_sens"] = (key, api.weights_sensitivity(run_id, weights))

res = S.get("mev_result")
if res and res[0] == key:
    r = res[1]
    metric_row([
        ("Before", money(r["before"])),
        ("After", money(r["after"])),
        ("Change", signed(r["delta"])),
        ("vs before", pct(100 * r["delta"] / max(r["before"], 1))),
        ("Priced", money(r["priced"])),
    ])
    if r.get("note"):
        # a run priced by an earlier version of the calculation: the change is
        # measured from the run rebuilt on this engine, not its own provision
        callout("info", r["note"])
    if mode == "auto" and r["delta"] < 0 and any(v < 0 for v in shocked.values()):
        st.warning(
            "A worse forecast has LOWERED the provision. That is the weighting "
            "effect outrunning the PD effect and pointing the other way. Run "
            "it again on **Hold this run's weights** to see the PD effect "
            "alone — the two answers together are the finding.", icon="⚠️")
    if r.get("weights_used"):
        caption("Priced with internal weights "
                + ", ".join(f"{n} {100 * v:.2f}%"
                            for n, v in r["weights_used"].items()) + ".")

    by_pf = pd.DataFrame(r["by_portfolio"])
    bar(by_pf, "portfolio", "change", diverging=True,
        title="Change by portfolio")
    caption("Investments and Banks and FIs price off GCC growth and their own "
            "weights rather than the domestic variables, so a domestic shock "
            "or a new internal weighting should leave them flat. If it does "
            "not, the two rating scales have been crossed somewhere in the "
            "chain.")
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

    if shocked:
        st.subheader("The path priced")
        st.dataframe(pd.DataFrame(r["path"]), use_container_width=True,
                     hide_index=True)

sens = S.get("mev_sens")
if sens and sens[0] == key:
    sv = pd.DataFrame(sens[1])
    if len(sv):
        st.subheader("Ten points onto each scenario")
        caption("Each row takes 10% of probability from the others — pro "
                "rata, so their relative standing is unchanged — gives it to "
                "one, and reprices the book on the run's own forecast"
                + (" (the shocks above are not applied)" if shocked else "")
                + ". If we thought the downturn ten points more likely, what "
                "would we book?")
        bar(sv, "scenario", "change", diverging=True, title="Change in provision")
        show = sv.assign(weight_before=100 * sv["weight_before"],
                         weight_after=100 * sv["weight_after"])
        st.dataframe(fmt_table(show, money_cols=("ecl_scenario", "ecl_base",
                                                 "ecl_shifted", "change"),
                               pct_cols=("weight_before", "weight_after", "pct")),
                     use_container_width=True, hide_index=True)

st.divider()
st.subheader("The forecast as it stands")
st.dataframe(fc, use_container_width=True, hide_index=True)
