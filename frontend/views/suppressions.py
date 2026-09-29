"""Validation suppressions: findings accepted rather than fixed.

The R app's page. A suppression marks a validator as accepted-failing: it
still runs and its finding is still recorded, it just stops blocking the pre-run
check and the run. Every suppression needs a reason and an approver, can carry
an expiry, and is written to the audit log. They live in the project's
config/validation_suppressions.yml -- a config version freezes its own copy --
so they apply to the NEXT pre-run check and run, not to one already made.
"""
from datetime import date

import pandas as pd
import streamlit as st

import api
from ui import caption, flash, guard, metric_row, money, page_setup, pill

page_setup("Validation suppressions",
           "A suppression marks a validator as accepted-failing. The validator "
           "still runs and the finding is still recorded; it just stops blocking "
           "the run. Use this for known data issues that have been investigated "
           "and accepted. Every suppression requires a reason and an approver — "
           "the audit log captures both.")

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

st.markdown("#### Active suppressions")
caption(f"file: `{sup['path']}` · {len(entries)} entries")
if entries.empty:
    st.info("No suppressions yet.")
else:
    entries["active"] = entries["validator_id"].isin(sup["active"]).map(
        {True: "active", False: "lapsed"})
    st.dataframe(entries, hide_index=True, use_container_width=True)

run_id = st.session_state.get("run_id")
if run_id:
    with st.expander(f"Findings suppressed when {run_id} ran"):
        caption("Read from the run's validation report: what its frozen config "
                "accepted at the time. A suppression added now applies from the "
                "next run.")
        with guard():
            v = api.run_validation_table(run_id)
        rows = pd.DataFrame(v["rows"]) if v.get("exists") else pd.DataFrame()
        if rows.empty or not (rows["status"] == "SUPPR").any():
            caption("Nothing was suppressed in this run.")
        else:
            st.dataframe(rows[rows["status"] == "SUPPR"][["stage", "id", "description",
                                                          "message"]],
                         hide_index=True, use_container_width=True)
