"""Sign-off: who released this provision, and on what basis."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, page_setup

page_setup("Approval",
           "Two sign-offs, because one person should not release a provision "
           "alone. Risk owns the model view, Finance owns the booking.")

with guard():
    queue = api.approval_queue()

if queue:
    st.subheader("Queue")
    q = pd.DataFrame(queue)
    q["status"] = q.apply(
        lambda r: "complete" if r["complete"]
        else ("outstanding: " + ", ".join(r["outstanding"])), axis=1)
    st.dataframe(q[["run_id", "status"]], use_container_width=True,
                 hide_index=True,
                 column_config={"run_id": "Run", "status": "Status"})

run_id = st.session_state.get("run_id")
if not run_id:
    st.stop()

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
