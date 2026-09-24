"""Stress packages: combine levers, apply, and see who moved."""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money, page_setup,
                pct)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Stress packages",
           "Every lever reprices the book through the same engine the run "
           "used, so the EAD waterfall, the LGD formula and floor, the "
           "horizons and the exposure cap all still apply. Nothing is re-run "
           "and nothing is written.")

with guard():
    sc = api.scope(run_id)

internal, external = sc["internal"], sc["external"]
if external:
    st.info(f"**{', '.join(external)}** are externally rated and do not price "
            "against the internal PD curves, so a stress leaves them "
            "unchanged. They are excluded by default.", icon="ℹ️")

with st.form("stress"):
    name = st.text_input("Package name", "Stress 1")
    portfolios = st.multiselect("Scope", sc["all"], default=internal)

    st.markdown("**Credit quality**")
    a = st.columns(4)
    pd_mult = a[0].number_input("PD multiplier", 0.0, 10.0, 1.0, 0.05)
    notches = a[1].number_input("Rating notches", -10, 10, 0, 1,
                                help="Positive is a downgrade, along each "
                                     "contract's own scale.")
    lgd_base = a[2].number_input("LGD base", 0.0, 1.0, 0.45, 0.01)
    lgd_floor = a[3].number_input("LGD floor", 0.0, 1.0, 0.5, 0.05,
                                  help="Raising this bites on SECURED lending: "
                                       "only contracts already at the floor move.")

    st.markdown("**Exposure and term**")
    b = st.columns(4)
    coll = b[0].number_input("Collateral %", 0.0, 200.0, 100.0, 5.0)
    expo = b[1].number_input("Exposure %", 0.0, 300.0, 100.0, 5.0)
    mat = b[2].number_input("Extend maturity (years)", -10.0, 30.0, 0.0, 0.25)
    topn = b[3].number_input("Largest N default", 0, 50, 0, 1,
                             help="Largest customers by exposure forced to "
                                  "Stage 3, booking their full outstanding.")

    st.markdown("**Staging policy**")
    c = st.columns(4)
    dpd = c[0].number_input("DPD threshold", 0, 90, 60, 5)
    contagion = c[1].checkbox("Contagion", True)
    tasdeer = c[2].checkbox("Tasdeer collective", True)
    local = c[3].checkbox("Local flags trigger", True)

    go = st.form_submit_button("Apply", type="primary", use_container_width=True)

if not go:
    st.stop()

spec = dict(name=name, portfolios=portfolios, dpd_threshold=dpd,
            contagion=contagion, tasdeer_collective=tasdeer,
            local_triggers=local, pd_multiplier=pd_mult, lgd_base=lgd_base,
            lgd_floor=lgd_floor, collateral_pct=coll, exposure_pct=expo,
            rating_notches=int(notches), maturity_years=mat,
            default_top_n=int(topn))

with guard():
    r = api.apply_stress(run_id, spec)

metric_row([
    ("Provision now", money(r["before"])),
    ("Under this stress", money(r["after"])),
    ("Change", money(r["delta"])),
    ("% change", pct(100 * r["delta"] / max(r["before"], 1))),
    ("Customers moved", money(r["customers_moved"])),
])
if abs(r["delta"]) < 1e-6:
    st.info("Nothing was changed, so the provision is unchanged.", icon="ℹ️")
if r["defaulted"]:
    caption("Forced to default: " + ", ".join(map(str, r["defaulted"])))

c1, c2 = st.columns([2, 3])
with c1:
    st.subheader("By portfolio")
    bar(pd.DataFrame(r["by_portfolio"]), "portfolio", "change", diverging=True)
with c2:
    st.subheader("Customers affected")
    bc = pd.DataFrame(r["by_customer"])
    if len(bc):
        bc = bc[bc["change"].abs() > 0]
    if len(bc) == 0:
        st.info("No customer's provision moved.")
    else:
        st.dataframe(
            fmt_table(bc[["customer", "facilities", "exposure", "ecl_before",
                          "ecl_after", "change"]],
                      money_cols=("facilities", "exposure", "ecl_before",
                                  "ecl_after", "change")),
            use_container_width=True, hide_index=True, height=440)
