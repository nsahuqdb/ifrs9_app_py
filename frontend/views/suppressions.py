"""Accepted findings: the exceptions that let a run through."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected.", icon="👈")
    st.stop()

page_setup("Accepted findings",
           "A validation finding can be accepted rather than fixed, provided "
           "the reason is recorded. The alternative — people learning to "
           "ignore a permanently red screen — is worse than an explicit, "
           "auditable exception.")

with guard():
    v = api.validation(run_id)

issues = pd.DataFrame(v["issues"])
suppressed = issues[issues["suppressed"]] if len(issues) else pd.DataFrame()
open_fails = (issues[~issues["passed"] & ~issues["suppressed"]]
              if len(issues) else pd.DataFrame())

metric_row([
    ("Accepted", money(len(suppressed))),
    ("Still open", money(len(open_fails))),
    ("Verdict", "PASS" if v["summary"]["passed"] else "FAIL"),
])

if len(suppressed):
    st.subheader("Currently accepted")
    st.dataframe(
        suppressed[["id", "severity", "description", "detail",
                    "suppression_reason"]],
        use_container_width=True, hide_index=True,
        column_config={"id": "Id", "severity": "Severity",
                       "description": "Check", "detail": "What was found",
                       "suppression_reason": "Why it is accepted"})
else:
    st.info("Nothing is currently accepted for this run.")

if len(open_fails):
    st.subheader("Open findings")
    caption("Accept one below. The reason and the approver are both required, "
            "and neither is optional by accident: a suppression without them "
            "is an unexplained silence in the audit trail, which is the thing "
            "this page exists to prevent.")
    st.dataframe(open_fails[["id", "severity", "description", "detail"]],
                 use_container_width=True, hide_index=True)

    st.subheader("Accept a finding")
    with st.form("accept_finding"):
        choice = st.selectbox(
            "Finding", list(open_fails["id"]),
            format_func=lambda i: f"{i} — "
            f"{open_fails.loc[open_fails['id'] == i, 'description'].iloc[0]}")
        reason = st.text_area(
            "Why this is accepted", height=90,
            placeholder="What was investigated, what was concluded, and the "
                        "ticket or approval it sits under. This is what "
                        "somebody reads at the next review.")
        c1, c2 = st.columns(2)
        who = c1.text_input("Approved by")
        until = c2.text_input(
            "Expires on (optional)", placeholder="2026-12-31",
            help="Leave blank for no expiry. An expiry is the safer choice: "
                 "an exception that has to be renewed cannot quietly become "
                 "permanent.")
        if st.form_submit_button("Accept this finding", type="primary"):
            if not reason.strip():
                st.error("A reason is required.")
            elif not who.strip():
                st.error("An approver is required.")
            else:
                try:
                    api.add_suppression(run_id, choice, reason.strip(),
                                        who.strip(), until.strip() or None)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.validation.clear()
                    api.suppressions.clear()
                    st.success(f"{choice} accepted and recorded.")
                    st.rerun()
    caption("Some checks cannot be accepted at all — a missing input file, a "
            "duplicate primary key — and the engine refuses those rather than "
            "letting them through quietly.")

with st.expander("Where this is stored"):
    try:
        info = api.suppressions(run_id)
    except api.BackendError as e:
        st.error(str(e))
    else:
        st.code(info["path"], language=None)
        caption("Inside the run's own frozen config, so reproducing this "
                "quarter uses the exceptions it was signed with. Suppressions "
                "do not carry forward to a new config snapshot — an exception "
                "accepted for one quarter has to be accepted again.")
        if info["entries"]:
            st.dataframe(pd.DataFrame(info["entries"]), hide_index=True,
                         use_container_width=True)
