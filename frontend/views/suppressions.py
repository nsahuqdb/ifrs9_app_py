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
    caption("To accept one, add it to the run's `suppressions.yml` with a "
            "reason. A suppression without a reason is ignored — the point is "
            "an auditable exception, not a quieter screen.")
    st.dataframe(open_fails[["id", "severity", "description", "detail"]],
                 use_container_width=True, hide_index=True)

    st.subheader("suppressions.yml")
    body = "suppressions:\n" + "".join(
        f'  {r["id"]}:\n    reason: "state why this is accepted"\n'
        for _, r in open_fails.iterrows())
    st.code(body, language="yaml")
    caption(f"Save this as `suppressions.yml` in the run folder, then reload. "
            "Non-suppressible checks cannot be accepted this way.")
