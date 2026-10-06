"""Whether this run is safe to sign: what it checked, and whether every
contract got a number."""
import pandas as pd
import streamlit as st

import api
from ui import (accepted_findings_table, accepted_note, callout, caption,
                findings, guard, kpis, money, page_setup, style_severity)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected.", icon="👈")
    st.stop()

page_setup("Validation",
           "A run that completes is not the same as a run that is safe to sign: "
           "every check at every stage, and whether every contract got a number.")

STATUS_TONE = {"ERROR": "err", "WARN": "warn", "INFO": "info", "SUPPR": "muted",
               "PASS": "ok"}
LABEL = {"err": "Errors", "warn": "Warnings", "info": "Info", "muted": "Accepted",
         "ok": "Passed"}

with guard():
    acc = api.run_accepted_findings(run_id)
acc_rows = acc.get("rows") or []
acc_by_id = {}
for a in acc_rows:
    acc_by_id.setdefault(a["validator_id"], a)

tab_rep, tab_acc, tab_rdy, tab_post = st.tabs([
    "Run validation report", f"Accepted findings · {len(acc_rows)}",
    "Pricing readiness", "Post-run checks"])

# ======================================================= accepted findings ====
with tab_acc:
    caption("Every finding accepted in this run and why: accepted **for this "
            "run** on the pipeline page, or by a **standing suppression** in "
            "validation_suppressions.yml that took effect. Each is also in the "
            "run's validation report and, with the run id, in the Audit log.")
    if acc_rows and not acc.get("recorded", True):
        callout("info", "This run was made before runs kept their own list. It is "
                "rebuilt from the checks the run recorded as suppressed and the "
                "suppressions file it froze.")
    accepted_findings_table(acc_rows, empty="Nothing was accepted in this run: "
                            "every failed check counts at its own severity.")

# ============================================================ run report ====
with tab_rep:
    with guard():
        v = api.run_validation_table(run_id)
    if not v.get("exists"):
        st.info("This run has no reports/validation.csv.")
    else:
        c = v["counts"]
        if c["errors"]:
            callout("err", f"**{c['errors']} ERROR-level check(s) failed.** The run "
                    "should not be signed until they are resolved or explicitly "
                    "accepted.", title="Not safe to sign.")
        elif c["warnings"]:
            callout("warn", f"No unaccepted errors; **{c['warnings']} warning(s)** "
                    "to review before signing.", title="Review the warnings.")
        else:
            callout("ok", "No unaccepted errors and no warnings.",
                    title="Every check passed.")
        kpis([("Checks", money(c["checks"]), "plum", ""),
              ("Passed", money(c["passed"]), "ok", ""),
              ("Errors", money(c["errors"]), "err" if c["errors"] else "ok", ""),
              ("Warnings", money(c["warnings"]), "warn" if c["warnings"] else "ok", ""),
              ("Info", money(c["info"]), "info" if c["info"] else "", ""),
              ("Accepted", money(c["suppressed"]), "plum" if c["suppressed"] else "",
               "see Accepted findings")])

        rows = pd.DataFrame(v["rows"])
        order = ["PREFLIGHT", "INPUT", "TRANSFORM", "DERIVED", "READY", "REPORT"]
        stages = [s for s in order if s in set(rows["stage"])] + \
            sorted(set(rows["stage"]) - set(order))
        left, right = st.columns([1, 2.4], gap="medium")
        with left:
            st.markdown("**By stage**")
            by = rows.groupby(["stage", "status"]).size().unstack(fill_value=0)
            by = by.reindex(stages)[[c_ for c_ in ("PASS", "ERROR", "WARN", "INFO",
                                                   "SUPPR") if c_ in by.columns]]
            st.dataframe(by, width="stretch")
            stage = st.selectbox("Stage", ["(all stages)"] + stages)
        with right:
            sub = rows if stage.startswith("(") else rows[rows["stage"] == stage]
            tones = sub["status"].map(lambda x: STATUS_TONE.get(x, "info"))
            counts = tones.value_counts().to_dict()
            avail = [t for t in LABEL if counts.get(t)]
            default = [t for t in avail if t in ("err", "warn")] or \
                [t for t in avail if t != "ok"][:1] or avail[:1]
            sel = st.pills("Show", avail, selection_mode="multi", default=default,
                           format_func=lambda t: f"{LABEL[t]} · {counts[t]}",
                           key=f"val_f_{stage}", label_visibility="collapsed")
            shown = sub[tones.isin(sel or [])]
            recs = [{"severity": "ACCEPTED" if r["status"] == "SUPPR" else
                     ("PASS" if r["status"] == "PASS" else r["status"]),
                     "id": r["id"], "context": f"{r['stage']} · {r['context']}"
                     if r.get("context") else r["stage"],
                     "title": r["description"], "message": r["message"],
                     "rationale": r.get("rationale"),
                     "remediation": r.get("remediation"),
                     # who accepted it, how and why
                     "accepted_note": accepted_note(acc_by_id[r["id"]])
                     if r["status"] == "SUPPR" and r["id"] in acc_by_id else ""}
                    for _, r in shown.iterrows()]
            if not recs:
                caption("Pick a severity above to list its checks.")
            elif len(recs) > 5:
                with st.container(height=min(720, 70 + 100 * len(recs)), border=False):
                    findings(recs, why=True)
            else:
                findings(recs, why=True)

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

        def cnt(k):
            return (s.get(k) or {}).get("contracts") or 0
        lost = cnt("No ECL") + cnt("Blank in LIC")
        if lost:
            callout("err", f"**{cnt('No ECL')}** contract(s) got no ECL and "
                    f"**{cnt('Blank in LIC')}** would come out blank in LIC.",
                    title="Not every contract has a number.")
        else:
            callout("ok", "Every contract has an ECL in both engines; LIC would "
                    "price them all.", title="Every contract is priced.")
        kpis([("Contracts", money(s["contracts"]), "plum",
               f"exposure {money(s['exposure'])}"),
              ("Priced", money(cnt("Priced")), "ok", "nothing missing"),
              ("Priced — check", money(cnt("Priced - check")),
               "warn" if cnt("Priced - check") else "", "from an incomplete input"),
              ("Blank in LIC", money(cnt("Blank in LIC")),
               "err" if cnt("Blank in LIC") else "ok", "LIC returns a blank"),
              ("No ECL", money(cnt("No ECL")), "err" if cnt("No ECL") else "ok",
               "the engines cannot price it")])
        caption("**No ECL**: the engines cannot price it (no PD curve, no EIR). "
                "**Blank in LIC**: the engines price it but LIC would return a "
                "blank (e.g. an allocation to a collateral record that does not "
                "exist). **Priced — check**: priced from an incomplete input.")
        if rd["reasons"]:
            st.markdown("**Why, and what to do**")
            st.dataframe(style_severity(pd.DataFrame(rd["reasons"])[
                ["severity", "check", "outcome", "contracts", "exposure", "text",
                 "fix"]]),
                hide_index=True, width="stretch",
                column_config={
                    "severity": st.column_config.TextColumn("Severity", width="small"),
                    "exposure": st.column_config.NumberColumn(format="%,.0f"),
                    "text": st.column_config.TextColumn("What it does", width="large"),
                    "fix": st.column_config.TextColumn("What to do", width="large")})
        with st.expander("Row funnel: every input row accounted for"):
            st.dataframe(pd.DataFrame(rd["funnel"]), hide_index=True, width="stretch")
        flagged = pd.DataFrame(rd["flagged"])
        if not flagged.empty:
            st.markdown(f"**Contracts with a gap** ({rd['n_flagged']:,})")
            c1, c2, _ = st.columns([1, 1, 2])
            oc = c1.selectbox("Outcome", ["(all)"] + sorted(flagged["Outcome"].unique()))
            codes = sorted({c for x in flagged["Reasons"].fillna("") for c in x.split()})
            rc = c2.selectbox("Reason", ["(all)"] + codes)
            f = flagged
            if not oc.startswith("("):
                f = f[f["Outcome"] == oc]
            if not rc.startswith("("):
                f = f[f["Reasons"].fillna("").str.split().map(lambda l: rc in l)]
            st.dataframe(f, hide_index=True, width="stretch", height=380)
            st.download_button("Download these contracts (CSV)",
                               f.to_csv(index=False), file_name=f"{run_id}_readiness.csv",
                               mime="text/csv", icon=":material/download:")

# ============================================================ post-run ======
with tab_post:
    caption("Checks that can still be run from the run folder alone, after the "
            "fact — useful for a run copied in from elsewhere.")
    with guard():
        pv = api.validation(run_id)
    ps = pv["summary"]
    kpis([("Checks", money(ps["checks"]), "plum", ""),
          ("Verdict", "PASS" if ps["passed"] else "FAIL",
           "ok" if ps["passed"] else "err", ""),
          ("Errors", money(ps["errors"]), "err" if ps["errors"] else "ok", ""),
          ("Warnings", money(ps["warnings"]), "warn" if ps["warnings"] else "ok", ""),
          ("Accepted", money(ps["suppressed"]), "", "")])
    issues = pd.DataFrame(pv["issues"])
    if not issues.empty:
        failed = issues[~issues["passed"] & ~issues["suppressed"]]

        def _msg(r):
            n, ex = r.get("count"), r.get("examples")
            return (str(r.get("detail") or "")
                    + (f" ({int(n):,})" if isinstance(n, (int, float))
                       and pd.notna(n) and n else "")
                    + (" · e.g. " + ", ".join(map(str, list(ex)[:10]))
                       if isinstance(ex, (list, tuple)) and len(ex) else ""))
        findings([{"severity": r["severity"], "id": r["id"],
                   "title": r["description"], "message": _msg(r),
                   "rationale": r.get("rationale"),
                   "remediation": r.get("remediation")}
                  for _, r in failed.iterrows()],
                 empty="Every post-run check passed.", why=True)
        passed = issues[issues["passed"]]
        if len(passed):
            with st.expander(f"{len(passed)} checks passed"):
                st.dataframe(passed[["id", "severity", "description", "detail"]],
                             width="stretch", hide_index=True)
