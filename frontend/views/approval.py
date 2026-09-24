"""Sign-off: who released this provision, and on what basis."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, page_setup

page_setup("Approval",
           "Maker-checker on the run itself, and two sign-offs on top of it. "
           "One person should not be able to release a provision alone.")

with guard():
    queue = api.approval_queue()
    mc = api.approval_queue_status()

pending, decided = pd.DataFrame(mc["pending"]), pd.DataFrame(mc["decided"])

st.subheader("Awaiting a checker")
if pending.empty:
    caption("Nothing is waiting. Only an OFFICIAL run enters this queue — an "
            "unofficial or scenario run is terminal by design.")
else:
    show = pending[["run_id", "status", "run_type", "requested_by",
                    "requested_at", "n_overrides_total"]]
    st.dataframe(show, use_container_width=True, hide_index=True,
                 column_config={
                     "run_id": "Run", "status": "Status",
                     "run_type": "Type", "requested_by": "Run by",
                     "requested_at": "Run at",
                     "n_overrides_total": "Overrides"})
    if (pending["status"] == "unknown").any():
        st.warning(
            "A run listed as **unknown** has no `reports/run_status.yml`. It "
            "is shown rather than hidden because that is the case most worth "
            "seeing: something wrote a run and did not record that it needs "
            "approving.", icon="⚠️")

if not decided.empty:
    with st.expander(f"Decided ({len(decided)})"):
        st.dataframe(
            decided[["run_id", "status", "requested_by", "decided_by",
                     "decided_at", "decision_comment"]],
            use_container_width=True, hide_index=True,
            column_config={"run_id": "Run", "status": "Outcome",
                           "requested_by": "Run by", "decided_by": "Decided by",
                           "decided_at": "When",
                           "decision_comment": "Reason"})

run_id = st.session_state.get("run_id")
if not run_id:
    st.stop()

# ---- maker-checker on the selected run ------------------------------------
with guard():
    rs = api.run_status(run_id)

st.subheader(f"{run_id} — run status")
state = rs["status"]
tone = {"approved": "✅", "rejected": "🛑", "pending_checker": "⏳",
        "unofficial": "ℹ️", "unknown": "⚠️"}.get(state, "ℹ️")
metric_row([("Status", state.replace("_", " ")),
            ("Type", (rs.get("meta") or {}).get("run_type", "—")),
            ("ECL basis", (rs.get("meta") or {}).get("ecl_scenario", "—")),
            ("Run by", rs.get("maker") or "—")])

if rs["detail"]:
    st.warning(rs["detail"], icon="⚠️")
elif state == "pending_checker":
    with st.form("decide_run"):
        st.markdown("**Decide this run**")
        caption("A reason is required either way. An approval with no reason "
                "records that somebody clicked, not that somebody decided. "
                "Where separation of duties is enforced, whoever ran the "
                "pipeline cannot also approve it — but they may always "
                "withdraw it.")
        who = st.text_input("Your name")
        reason = st.text_area("Reason", height=80)
        c1, c2 = st.columns(2)
        do_approve = c1.form_submit_button("Approve", type="primary",
                                           use_container_width=True)
        do_reject = c2.form_submit_button("Reject", use_container_width=True)
        if do_approve or do_reject:
            if not who.strip() or not reason.strip():
                st.error("Both your name and a reason are required.")
            else:
                try:
                    api.decide_run(run_id,
                                   "approve" if do_approve else "reject",
                                   who.strip(), reason.strip())
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.run_status.clear()
                    api.approval_queue_status.clear()
                    st.rerun()
elif state == "unofficial":
    st.info("This is an unofficial run: terminal by design, and not a number "
            "anybody books. Re-run it as official to put it in the queue.",
            icon="ℹ️")
else:
    st.success(f"{tone} This run is **{state}**.")

meta = rs.get("meta") or {}
if meta.get("transitions"):
    with st.expander("History"):
        st.dataframe(pd.DataFrame(meta["transitions"]), hide_index=True,
                     use_container_width=True,
                     column_config={"at": "When", "by": "Who", "to": "To",
                                    "reason": "Reason"})

st.divider()

st.subheader(f"Sign off {run_id}")
with guard():
    st_ = api.approval(run_id)
    v = api.validation(run_id)

if not v["summary"]["passed"]:
    st.error(
        f"Validation is failing with {v['summary']['errors']} error-level "
        "checks. Approval is refused until these are resolved or explicitly "
        "accepted — a gate that can be waved through on a bad run is "
        "decoration.", icon="🛑")
else:
    st.success("Validation passes.", icon="✅")

got = st_["approvals"]
c1, c2 = st.columns(2)
for col, stage, owner in ((c1, "risk", "Risk"), (c2, "finance", "Finance")):
    with col:
        st.markdown(f"**{owner}**")
        if stage in got:
            a = got[stage]
            st.success(f"{a['approver']} · {a['time']}", icon="✅")
            if a.get("comment"):
                st.caption(a["comment"])
        else:
            approver = st.text_input(f"{owner} approver", key=f"who_{stage}")
            comment = st.text_input(f"{owner} comment", key=f"cm_{stage}")
            if st.button(f"Approve as {owner}", key=f"btn_{stage}",
                         disabled=not approver or not v["summary"]["passed"]):
                try:
                    api.approve(run_id, stage, approver, comment)
                    api.approval.clear()
                    api.approval_queue.clear()
                    st.rerun()
                except api.BackendError as e:
                    st.error(str(e))

if st_["complete"]:
    st.success("Both sign-offs recorded. This run is released.", icon="🎉")
