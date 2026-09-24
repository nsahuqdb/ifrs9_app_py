"""Whether this run is safe to sign."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected.", icon="👈")
    st.stop()

page_setup("Validation",
           "A run that completes is not the same as a run that is safe to "
           "sign. Passes are shown as well as failures, because a report of "
           "failures alone is not evidence that anything was checked.")

with guard():
    v = api.validation(run_id)

s = v["summary"]
metric_row([
    ("Checks", money(s["checks"])),
    ("Verdict", "PASS" if s["passed"] else "FAIL"),
    ("Errors", money(s["errors"])),
    ("Warnings", money(s["warnings"])),
    ("Suppressed", money(s["suppressed"])),
])

if s["passed"]:
    st.success("No unsuppressed errors. The run may proceed.", icon="✅")
else:
    st.error(f"{s['errors']} error-level checks failed. The run should not be "
             "signed until these are resolved or explicitly accepted.", icon="🛑")

issues = pd.DataFrame(v["issues"])
failed = issues[~issues["passed"] & ~issues["suppressed"]]

for sev, label, icon in (("ERROR", "Errors", "🛑"), ("WARN", "Warnings", "⚠️"),
                         ("INFO", "For information", "ℹ️")):
    part = failed[failed["severity"] == sev]
    if len(part) == 0:
        continue
    st.subheader(f"{icon} {label}")
    for _, r in part.iterrows():
        with st.expander(f"**{r['id']}** — {r['description']}"
                         + (f"  ·  {r['count']:,}" if r["count"] else ""),
                         expanded=(sev == "ERROR")):
            st.markdown(f"**What happened.** {r['detail']}")
            if r["rationale"]:
                st.markdown(f"**Why it matters.** {r['rationale']}")
            if r["remediation"]:
                st.markdown(f"**What to do.** {r['remediation']}")
            if r["examples"]:
                st.caption("Examples: " + ", ".join(map(str, r["examples"][:10])))

passed = issues[issues["passed"]]
if len(passed):
    with st.expander(f"{len(passed)} checks passed"):
        st.dataframe(passed[["id", "severity", "description", "detail"]],
                     use_container_width=True, hide_index=True,
                     column_config={"id": "Id", "severity": "Severity",
                                    "description": "Check", "detail": "Result"})

supp = issues[issues["suppressed"]]
if len(supp):
    st.subheader("Accepted findings")
    caption("Suppressed by id, each with the reason recorded. An accepted "
            "finding is an auditable exception, not a hidden one.")
    st.dataframe(supp[["id", "severity", "description", "suppression_reason"]],
                 use_container_width=True, hide_index=True)
