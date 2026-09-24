"""Name the customers, say what changes for them, and reprice.

Where a stress changes a policy across a portfolio, a what-if names specific
exposures: this customer restructures, that portfolio's collateral is
revalued, these facilities extend.

Rules do NOT stack. A contract caught by two of them has no defined answer —
applying both would make the result depend on the order, and applying one
silently would hide the other — so it is excluded and listed instead. That is
the same rule the overlay feature applies, for the same reason.
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
page_setup("What-if", "Named exposures, repriced through the engine")

with guard():
    scope = api.scope(run_id)
portfolios = scope.get("all", [])
external = scope.get("external", [])
if external:
    caption(f"{', '.join(external)} are externally rated. A collateral, "
            "exposure, stage or maturity rule reaches them; a rating "
            "downgrade does not, because their grades are not on the "
            "internal scale the PD curves are keyed to.")

if "whatif_rules" not in st.session_state:
    st.session_state["whatif_rules"] = [
        {"label": "Rule 1", "customers": [], "portfolios": [], "stages": [],
         "stage_to": None, "rating_notches": 0, "collateral_pct": 100.0,
         "exposure_pct": 100.0, "maturity_years": 0.0, "pd_scenario": ""}]

c1, c2 = st.columns([1, 6])
if c1.button("Add rule", use_container_width=True):
    n = len(st.session_state["whatif_rules"]) + 1
    st.session_state["whatif_rules"].append(
        {"label": f"Rule {n}", "customers": [], "portfolios": [], "stages": [],
         "stage_to": None, "rating_notches": 0, "collateral_pct": 100.0,
         "exposure_pct": 100.0, "maturity_years": 0.0, "pd_scenario": ""})
if c2.button("Clear all", use_container_width=False):
    st.session_state["whatif_rules"] = []
    st.rerun()

rules = []
for i, r in enumerate(st.session_state["whatif_rules"]):
    with st.expander(r["label"] or f"Rule {i + 1}", expanded=i == 0):
        r["label"] = st.text_input("Name", r["label"], key=f"wl_{i}")
        a, b = st.columns(2)
        r["portfolios"] = a.multiselect("Portfolios", portfolios,
                                        r["portfolios"], key=f"wp_{i}")
        r["stages"] = b.multiselect("Stages", [1, 2, 3], r["stages"],
                                    key=f"ws_{i}")
        ids = st.text_input(
            "Customer ids", ", ".join(r["customers"]), key=f"wc_{i}",
            help="Comma, semicolon or space separated. Leave blank to apply "
                 "to whichever portfolios and stages are selected.")
        r["customers"] = [t for t in
                          ids.replace(";", ",").replace(" ", ",").split(",") if t]

        d, e, f = st.columns(3)
        stage_to = d.selectbox("Move to stage", ["unchanged", 1, 2, 3],
                               key=f"wst_{i}")
        r["stage_to"] = None if stage_to == "unchanged" else int(stage_to)
        r["rating_notches"] = e.number_input("Downgrade notches", -10, 20,
                                             int(r["rating_notches"]),
                                             key=f"wn_{i}")
        r["maturity_years"] = f.number_input("Extend maturity (years)", -10.0,
                                             20.0, float(r["maturity_years"]),
                                             0.5, key=f"wm_{i}")
        g, h = st.columns(2)
        r["collateral_pct"] = g.slider("Collateral value %", 0, 300,
                                       int(r["collateral_pct"]), 5,
                                       key=f"wcp_{i}")
        r["exposure_pct"] = h.slider("Exposure %", 0, 300,
                                     int(r["exposure_pct"]), 5, key=f"wep_{i}")
    rules.append(r)

if not rules:
    st.info("Add a rule to begin.")
    st.stop()

with guard():
    m = api.whatif_match(run_id, rules)

metric_row([
    ("Contracts in the run", money(m["contracts"])),
    ("Claimed by a rule", money(m["matched"])),
    ("Conflicted", money(len(m["conflicts"]))),
])
st.dataframe(fmt_table(pd.DataFrame(m["by_rule"]),
                       money_cols=("contracts",)),
             use_container_width=True, hide_index=True)

conflicts = pd.DataFrame(m["conflicts"])
if len(conflicts):
    st.warning(
        f"{len(conflicts):,} contracts are claimed by more than one rule. "
        "They are excluded from the repricing — narrow the rules so each "
        "contract falls to one of them.", icon="⚠️")
    st.dataframe(conflicts.head(50), use_container_width=True,
                 hide_index=True)

if st.button("Reprice", type="primary", disabled=m["matched"] == 0):
    with guard():
        r = api.whatif(run_id, rules)
    metric_row([
        ("Before", money(r["before"])),
        ("After", money(r["after"])),
        ("Change", signed(r["delta"])),
        ("vs before", pct(100 * r["delta"] / max(r["before"], 1))),
        ("Repriced", money(r["matched"])),
    ])
    caption("Both sides are priced by the same function, so the baseline and "
            "the what-if agree by construction. Taking the baseline from the "
            "report's own ECL column would show a difference whenever the "
            "report predates the current config — and that difference would "
            "read as the what-if having done something.")

    by_rule = pd.DataFrame(r["by_rule"])
    if len(by_rule):
        bar(by_rule, "rule", "change", diverging=True, title="Change by rule")
        st.dataframe(fmt_table(by_rule, money_cols=("contracts", "customers",
                                                    "exposure", "before",
                                                    "after", "change")),
                     use_container_width=True, hide_index=True)

    movers = pd.DataFrame(r["movers"])
    if len(movers):
        st.subheader("Largest movers")
        cols = [c for c in ("customer", "facilities", "portfolio", "rating",
                            "stage", "exposure", "ecl_before", "ecl_after",
                            "change") if c in movers.columns]
        st.dataframe(fmt_table(movers[cols],
                               money_cols=("facilities", "exposure",
                                           "ecl_before", "ecl_after",
                                           "change")),
                     use_container_width=True, hide_index=True)
