"""Staging: the split, and why each contract is in its stage.

Read on the run's own staging policy. What a different threshold would cost
is a stress question, answered on Stress testing -> Sensitivity (Staging
threshold), or any policy on Stress test.
"""
import pandas as pd
import streamlit as st

import api
from ui import bar, caption, fmt_table, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Staging",
           "Decided per customer. Tasdeer is assessed collectively, and a "
           "customer with any Stage 2 facility has its Stage 1 facilities "
           "bumped by contagion.")

with guard():
    d = api.staging(run_id)
    detail = api.staging_detail(run_id)

thr = d.get("dpd_threshold")
sd = pd.DataFrame(d["distribution"])
st.dataframe(
    fmt_table(sd[["stage", "customers", "contracts", "exposure", "ecl",
                  "coverage", "pct_ecl"]],
              money_cols=("customers", "contracts", "exposure", "ecl"),
              pct_cols=("coverage", "pct_ecl")),
    use_container_width=True, hide_index=True)
if thr is not None:
    caption(f"Days past due under this run's policy: Stage 2 above {thr:g}, "
            "Stage 3 above 90. The other triggers are below.")

t = pd.DataFrame(d["triggers"])
if len(t) == 0:
    # Not a reason to stop: the Stage 3 drivers and the check against the
    # rule below are about the rest of the book.
    st.info("No Stage 2 contracts in this run.")
else:
    st.subheader("Why each Stage 2 contract is in Stage 2")
    cols = ["trigger", "contracts", "customers", "pct_contracts", "exposure",
            "ecl"]
    tab1, tab2 = st.tabs(["Has trigger", "Sole reason"])
    for tab, basis, note in (
        (tab1, "any", "Triggers overlap, so these shares add to more than 100%."),
        (tab2, "sole", "Only where that trigger is the single cause, so these "
                       'add up. "Stage override" is a stage forced in the '
                       "source data."),
    ):
        with tab:
            caption(note)
            part = t[t["basis"] == basis]
            c1, c2 = st.columns([2, 3])
            with c1:
                bar(part[part["contracts"] > 0], "trigger", "contracts")
            with c2:
                st.dataframe(
                    fmt_table(part[cols],
                              money_cols=("contracts", "customers", "exposure",
                                          "ecl"),
                              pct_cols=("pct_contracts",)),
                    use_container_width=True, hide_index=True)

st.divider()
overlap_tab, dpd_tab, s3_tab, check_tab = st.tabs(
    ["Trigger combinations", "Days past due", "Stage 3 drivers",
     "Against the rule"])

with overlap_tab:
    caption("Each Stage 2 contract once, under its combination of triggers, so "
            "the rows add up. One with no trigger is there by contagion or an "
            "override.")
    ov = pd.DataFrame(detail["trigger_overlap"])
    if len(ov) == 0:
        st.info("No Stage 2 contracts in this run.")
    else:
        bar(ov.head(12), "combination", "contracts")
        st.dataframe(
            fmt_table(ov, money_cols=("contracts", "customers", "exposure",
                                      "ecl")),
            use_container_width=True, hide_index=True)

with dpd_tab:
    caption("Customers by stage and days past due: staging is decided per "
            "customer.")
    dd = pd.DataFrame(detail["dpd_by_stage"])
    if len(dd):
        piv = dd.pivot(index="stage", columns="band", values="customers")
        st.dataframe(piv, use_container_width=True)

with s3_tab:
    caption("A defaulted customer is usually over 90 days and flagged, so the "
            "drivers overlap and do not add to 100%.")
    s3 = pd.DataFrame(detail["stage3_drivers"])
    if len(s3) == 0:
        st.info("No Stage 3 customers in this run.")
    else:
        st.dataframe(fmt_table(s3, money_cols=("customers", "exposure"),
                               pct_cols=("pct_customers",)),
                     use_container_width=True, hide_index=True)

with check_tab:
    c = detail["consistency"]
    if not c.get("rule_available"):
        st.info("The staging rule could not be re-applied to this report.")
    else:
        metric_row([
            ("Contracts checked", money(c["checked"])),
            ("Disagreements", money(c["mismatches"])),
        ])
        findings = pd.DataFrame(detail["findings"])
        if len(findings) == 0:
            st.success(
                f"The engine's own staging rule, re-applied to this finished "
                f"report, reproduces the stage on all {c['checked']:,} "
                "contracts.")
        else:
            caption("The report does not carry AccountMaster.Stage, so a "
                    "manual override shows here as a difference. Staged "
                    "better than the rule is the one worth chasing.")
            for _, f in findings.iterrows():
                icon = "⚠️" if f["severity"] == "warn" else "ℹ️"
                with st.expander(f"{icon}  {f['check']} — "
                                 f"{int(f['contracts']):,} contracts"):
                    st.write(f["note"])
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Customers", money(f["customers"]))
                    c2.metric("Exposure", money(f["exposure"]))
                    c3.metric("ECL", money(f["ecl"]))
