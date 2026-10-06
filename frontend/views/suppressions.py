"""Validation suppressions: findings accepted rather than fixed, standing.

The R app's page. A suppression marks a validator as accepted-failing: it
still runs and its finding is still recorded, it just stops blocking the pre-run
check and the run. Every suppression needs a reason and an approver, can carry
an expiry, and is written to the audit log. They live in the project's
config/validation_suppressions.yml -- a config version freezes its own copy --
so they apply to the NEXT pre-run check and run, not to one already made, and
to every run after it until they expire or are removed. Removing one ends it
from today and keeps the entry, with who removed it and why.

A finding accepted on Run the pipeline is different: it is accepted for that
run only and the next run asks again.
"""
from datetime import date

import pandas as pd
import streamlit as st

import api
from ui import (accepted_findings_table, callout, caption, flash, guard,
                metric_row, money, page_setup, pill, style_severity)

page_setup("Validation suppressions",
           "Standing acceptances: a suppression accepts its finding in every run "
           "until it expires or is removed. To accept a finding for one run only, "
           "use Accept for this run on Run the pipeline — the next run asks again.")

with guard():
    sup = api.project_suppressions()
    cat = api.validator_catalog()

entries = pd.DataFrame(sup["entries"])
metric_row([("Suppressions", money(len(entries))),
            ("Active now", money(len(sup["active"]))),
            ("Failed validators in the last runs", money(len(cat["validators"])))])

left, right = st.columns([5, 7])
with left:
    with st.container(border=True):
        st.markdown("**Add suppression**")
        ids = [v["id"] for v in cat["validators"]]
        with st.form("add_supp", clear_on_submit=True):
            choice = st.selectbox("Validator (from the catalogue)",
                                  ["(type one below)"] + ids)
            typed = st.text_input("Validator ID", placeholder="e.g. INPUT_ACA_contract_fk")
            reason = st.text_area("Reason", height=100,
                                  placeholder="Why is it OK to suppress this validator? "
                                              "Reference any ticket / decision date.")
            who = st.text_input("Approved by")
            has_exp = st.checkbox("Expires")
            until = st.date_input("Valid until", value=date.today())
            caption("Leave Expires unticked for no expiry. With an expiry the "
                    "suppression lapses on that date and the validator is back to "
                    "ERROR/WARN — the safer choice.")
            if st.form_submit_button("Add suppression", type="primary"):
                vid = typed.strip() or ("" if choice.startswith("(") else choice)
                if not vid:
                    st.error("Validator ID is required.")
                elif not reason.strip():
                    st.error("Reason is required (audit trail).")
                else:
                    try:
                        api.add_project_suppression(
                            vid, reason.strip(), who.strip(),
                            until.isoformat() if has_exp else None)
                    except api.BackendError as e:
                        st.error(f"Add failed: {e}")
                    else:
                        api.clear()
                        flash(f"Added suppression for {vid}. It applies from "
                              "the next pre-run check and run.")
                        st.rerun()

with right:
    with st.container(border=True):
        st.markdown("**Validator catalogue** (for reference)")
        if not cat["validators"]:
            caption(f"No failed validators across the most recent {cat['n_runs']} "
                    "runs — nothing to suppress right now. A validator that starts "
                    "failing will show up here automatically.")
        else:
            caption(f"{len(cat['validators'])} unique failed validators across the "
                    f"last {cat['n_runs']} runs. Pick one in the form on the left.")
            df = pd.DataFrame(cat["validators"])
            for stage in df["stage"].unique():
                st.markdown(f"*{stage}*")
                sub = df[df["stage"] == stage]
                st.markdown("\n".join(
                    f"- {pill(r['severity'], {'ERROR': 'err', 'WARN': 'warn'}.get(r['severity'], 'info'))} "
                    f"`{r['id']}` — {r['description']} (last seen in {r['last_seen_run']})"
                    for _, r in sub.iterrows()), unsafe_allow_html=True)

st.markdown("#### Suppressions, and what became of them")
caption(f"file: `{sup['path']}` · {len(entries)} entries · nothing is ever "
        "deleted: an ended suppression stays, with who removed it and why")
hist = pd.DataFrame(sup.get("history") or [])
if hist.empty:
    st.info("No suppressions yet.")
else:
    show = hist[["status", "validator_id", "reason", "approved_by", "approved_at",
                 "valid_until", "removed_by", "removed_at", "removal_reason"]]
    st.dataframe(style_severity(show.assign(status=show["status"].str.upper())
                                .rename(columns={"status": "Status"}),
                                cols=("Status",)),
                 hide_index=True, width="stretch",
                 column_config={"reason": st.column_config.TextColumn(width="large"),
                                "removal_reason": st.column_config.TextColumn(
                                    width="medium")})
    active = sorted(sup["active"])
    if active:
        with st.container(border=True):
            st.markdown("**Remove a suppression**")
            caption("Ends it from today. The finding then blocks again and is "
                    "asked about on each run (Accept for this run on Run the "
                    "pipeline). The audit log records the removal.")
            with st.form("rm_supp", clear_on_submit=True, border=False):
                a, b = st.columns([2, 1])
                vid = a.selectbox("Suppression in force", active)
                who = b.text_input("Removed by",
                                   value=st.session_state.get("_user") or "")
                why = st.text_input("Reason (required)",
                                    placeholder="e.g. findings are now accepted "
                                                "run by run")
                if st.form_submit_button("Remove", type="primary",
                                         icon=":material/delete:"):
                    if not why.strip() or not who.strip():
                        st.error("A reason and a name are required (audit trail).")
                    else:
                        try:
                            api.remove_project_suppression(vid, why.strip(),
                                                           who.strip())
                        except api.BackendError as e:
                            st.error(f"Remove failed: {e}")
                        else:
                            api.clear()
                            flash(f"Removed the suppression of {vid}. From the "
                                  "next pre-run check it blocks again and is "
                                  "asked about on each run.")
                            st.rerun()

run_id = st.session_state.get("run_id")
if run_id:
    with st.expander(f"Findings accepted when {run_id} ran"):
        caption("What that run accepted, with the reasons: for the run on the "
                "pipeline page, or by a standing suppression of its frozen "
                "config. A suppression added or removed now applies from the "
                "next run.")
        with guard():
            acc = api.run_accepted_findings(run_id)
        accepted_findings_table(acc.get("rows"),
                                empty="Nothing was accepted in this run.")
