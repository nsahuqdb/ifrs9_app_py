"""Whether this run is safe to sign: what it checked, and whether every
contract got a number."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pill

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected.", icon="👈")
    st.stop()

page_setup("Validation",
           "A run that completes is not the same as a run that is safe to sign. "
           "The run's own report records every check at every stage — the inputs, "
           "the transformed book, the curves, pricing readiness and the priced "
           "report — passes as well as failures.")

tab_rep, tab_rdy, tab_post = st.tabs(["Run validation report", "Pricing readiness",
                                      "Post-run checks"])

# ============================================================ run report ====
with tab_rep:
    with guard():
        v = api.run_validation_table(run_id)
    if not v.get("exists"):
        st.info("This run has no reports/validation.csv.")
    else:
        c = v["counts"]
        metric_row([("Checks", money(c["checks"])), ("Passed", money(c["passed"])),
                    ("Errors", money(c["errors"])), ("Warnings", money(c["warnings"])),
                    ("Info", money(c["info"])), ("Suppressed", money(c["suppressed"]))])
        if c["errors"]:
            st.error(f"{c['errors']} ERROR-level check(s) failed. The run should not "
                     "be signed until they are resolved or explicitly accepted.",
                     icon="🛑")
        else:
            st.success("No unsuppressed errors.", icon="✅")
        rows = pd.DataFrame(v["rows"])
        order = ["INPUT", "TRANSFORM", "DERIVED", "READY", "REPORT"]
        stages = [s for s in order if s in set(rows["stage"])] + \
            sorted(set(rows["stage"]) - set(order))
        by = rows.groupby(["stage", "status"]).size().unstack(fill_value=0)
        st.markdown("**By stage**")
        st.dataframe(by.reindex(stages), use_container_width=True)
        f1, f2 = st.columns([2, 3])
        stage = f1.selectbox("Stage", ["(all)"] + stages)
        show_pass = f2.checkbox("Show passed checks too", value=False)
        sub = rows if stage.startswith("(") else rows[rows["stage"] == stage]
        failed = sub[sub["status"] != "PASS"]
        for sev, label, icon in (("ERROR", "Errors", "🛑"), ("WARN", "Warnings", "⚠️"),
                                 ("INFO", "For information", "ℹ️"),
                                 ("SUPPR", "Suppressed (accepted)", "🔕")):
            part = failed[failed["status"] == sev]
            if part.empty:
                continue
            st.markdown(f"#### {icon} {label} ({len(part)})")
            for _, r in part.iterrows():
                with st.expander(f"**{r['id']}** [{r['stage']}] — {r['description']}",
                                 expanded=(sev == "ERROR")):
                    st.markdown(f"**What was found.** {r['message'] or '—'}")
                    if r.get("rationale"):
                        st.markdown(f"**Why it matters.** {r['rationale']}")
                    if r.get("remediation"):
                        st.markdown(f"**What to do.** {r['remediation']}")
                    if r.get("context"):
                        caption(f"context: {r['context']}")
        if show_pass:
            ok = sub[sub["status"] == "PASS"]
            st.markdown(f"#### ✅ Passed ({len(ok)})")
            st.dataframe(ok[["stage", "id", "description", "message"]],
                         hide_index=True, use_container_width=True)

# ============================================================= readiness ====
with tab_rdy:
    with guard():
        rd = api.run_readiness(run_id)
    if not rd.get("exists"):
        st.info("This run has no readiness report (runs made before the readiness "
                "check was added do not). Run the pre-run check on the Run the "
                "pipeline page to assess a set of inputs.")
    else:
        s = rd["summary"]
        metric_row([("Contracts", money(s["contracts"])),
                    ("Exposure", money(s["exposure"])),
                    ("No ECL", money(s["No ECL"]["contracts"])),
                    ("Blank in LIC", money(s["Blank in LIC"]["contracts"])),
                    ("Priced — check", money(s["Priced - check"]["contracts"])),
                    ("Priced", money(s["Priced"]["contracts"]))])
        if s["No ECL"]["contracts"] or s["Blank in LIC"]["contracts"]:
            st.error(f"{s['No ECL']['contracts']} contract(s) got no ECL and "
                     f"{s['Blank in LIC']['contracts']} would come out BLANK in LIC.",
                     icon="🛑")
        else:
            st.success("Every contract has an ECL in both engines; LIC would price "
                       "them all.", icon="✅")
        caption("Outcomes: **No ECL** — the engines cannot price it (no PD curve, no "
                "EIR); **Blank in LIC** — the engines price it but LIC would return "
                "a blank (e.g. an allocation to a collateral record that does not "
                "exist); **Priced — check** — priced from an incomplete input; "
                "**Priced** — nothing missing.")
        if rd["reasons"]:
            st.markdown("**Why, and what to do**")
            st.dataframe(pd.DataFrame(rd["reasons"])[
                ["severity", "check", "outcome", "contracts", "exposure", "text", "fix"]],
                hide_index=True, use_container_width=True,
                column_config={"exposure": st.column_config.NumberColumn(format="%,.0f"),
                               "text": st.column_config.TextColumn("what it does", width="large"),
                               "fix": st.column_config.TextColumn("what to do", width="large")})
        st.markdown("**Row funnel** — every input row accounted for")
        st.dataframe(pd.DataFrame(rd["funnel"]), hide_index=True,
                     use_container_width=True)
        flagged = pd.DataFrame(rd["flagged"])
        if not flagged.empty:
            st.markdown(f"**Contracts with a gap** ({rd['n_flagged']:,})")
            c1, c2 = st.columns(2)
            oc = c1.selectbox("Outcome", ["(all)"] + sorted(flagged["Outcome"].unique()))
            codes = sorted({c for x in flagged["Reasons"].fillna("") for c in x.split()})
            rc = c2.selectbox("Reason", ["(all)"] + codes)
            f = flagged
            if not oc.startswith("("):
                f = f[f["Outcome"] == oc]
            if not rc.startswith("("):
                f = f[f["Reasons"].fillna("").str.split().map(lambda l: rc in l)]
            st.dataframe(f, hide_index=True, use_container_width=True, height=380)
            st.download_button("Download these contracts (CSV)",
                               f.to_csv(index=False), file_name=f"{run_id}_readiness.csv",
                               mime="text/csv")

# ============================================================ post-run ======
with tab_post:
    caption("Checks that can still be run from the run folder alone, after the "
            "fact — useful for a run copied in from elsewhere.")
    with guard():
        pv = api.validation(run_id)
    ps = pv["summary"]
    metric_row([("Checks", money(ps["checks"])),
                ("Verdict", "PASS" if ps["passed"] else "FAIL"),
                ("Errors", money(ps["errors"])), ("Warnings", money(ps["warnings"])),
                ("Suppressed", money(ps["suppressed"]))])
    issues = pd.DataFrame(pv["issues"])
    if not issues.empty:
        failed = issues[~issues["passed"] & ~issues["suppressed"]]
        for _, r in failed.iterrows():
            with st.expander(f"**{r['id']}** — {r['description']}"
                             + (f"  ·  {r['count']:,}" if r["count"] else "")):
                st.markdown(f"**What happened.** {r['detail']}")
                if r["rationale"]:
                    st.markdown(f"**Why it matters.** {r['rationale']}")
                if r["remediation"]:
                    st.markdown(f"**What to do.** {r['remediation']}")
                if r["examples"]:
                    caption("Examples: " + ", ".join(map(str, r["examples"][:10])))
        passed = issues[issues["passed"]]
        if len(passed):
            with st.expander(f"{len(passed)} checks passed"):
                st.dataframe(passed[["id", "severity", "description", "detail"]],
                             use_container_width=True, hide_index=True)
