"""Approval queue: completed runs and config versions awaiting sign-off.

The R app's approval queue. Run approval accepts the whole run, overrides
included; version approval promotes a config bundle to approved, which is what
makes it usable for official runs. A reason is required either way, and where
separation of duties is enforced the person who ran the pipeline (or created
the version) cannot also approve it.
"""
import pandas as pd
import streamlit as st

import api
from ui import (caption, flash, guard, kpis, money, page_setup, pill,
                style_severity)

page_setup("Approval queue",
           "Run approval accepts the entire run, overrides included; version "
           "approval makes a config bundle usable for official runs.")

with guard():
    qr = api.queue_runs()
    qv = api.queue_versions()

pending, decided = pd.DataFrame(qr["pending"]), pd.DataFrame(qr["decided"])
vpend, vdec = pd.DataFrame(qv["pending"]), pd.DataFrame(qv["decided"])
k, r = st.columns([8, 1], vertical_alignment="center")
with k:
    kpis([("Runs awaiting a checker", money(len(pending)),
           "warn" if len(pending) else "ok", ""),
          ("Runs decided", money(len(decided)), "plum", ""),
          ("Versions awaiting approval", money(len(vpend)),
           "warn" if len(vpend) else "ok", ""),
          ("Versions decided", money(len(vdec)), "plum", "")])
if r.button("Refresh", key="aq_refresh", icon=":material/refresh:", width="stretch"):
    api.clear()
    st.rerun()


def _val_tab(run_id: str):
    with guard():
        v = api.run_validation_table(run_id)
    if not v["exists"]:
        caption("No validation report.")
        return
    c = v["counts"]
    st.markdown(f"{c['passed']}/{c['checks']} passed &nbsp; "
                + pill(f"{c['errors']} errors", "err" if c["errors"] else "ok") + " "
                + pill(f"{c['warnings']} warnings", "warn" if c["warnings"] else "ok")
                + " " + pill(f"{c['suppressed']} accepted", "muted"),
                unsafe_allow_html=True)
    st.dataframe(style_severity(pd.DataFrame(v["rows"])[
        ["status", "stage", "id", "description", "message"]]),
                 hide_index=True, width="stretch", height=320,
                 column_config={"message": st.column_config.TextColumn(width="large")})


def _ov_tab(run_id: str):
    with guard():
        o = api.run_overrides(run_id)
    if not o["exists"]:
        caption("No overrides directory.")
        return
    for f in o["files"]:
        st.markdown(f"**{f['file']}**")
        if not f["rows"]:
            caption("(none applied)")
        else:
            st.dataframe(pd.DataFrame(f["rows"]), hide_index=True,
                         use_container_width=True)


def _out_tab(run_id: str):
    with guard():
        outs = api.run_outputs(run_id)["files"]
    if not outs:
        caption("No outputs found.")
    else:
        st.dataframe(pd.DataFrame(outs)[["file", "size_kb"]], hide_index=True,
                     use_container_width=True,
                     column_config={"size_kb": st.column_config.NumberColumn(
                         "Size (KB)", format="%.1f")})


def _readiness_line(run_id: str):
    with guard():
        rd = api.run_readiness(run_id)
    if rd.get("exists"):
        s = rd["summary"]
        st.markdown(
            f"Readiness: {s['contracts']:,} contracts · "
            f"{pill(str(s['No ECL']['contracts']) + ' no ECL', 'err' if s['No ECL']['contracts'] else 'ok')} "
            f"{pill(str(s['Blank in LIC']['contracts']) + ' blank in LIC', 'err' if s['Blank in LIC']['contracts'] else 'ok')} "
            f"{pill(str(s['Priced - check']['contracts']) + ' priced with a gap', 'warn')}",
            unsafe_allow_html=True)


pend_tab, hist_tab = st.tabs(["Pending", "History"])

# ================================================================ pending ====
with pend_tab:
    r_tab, v_tab = st.tabs(["Runs", "Versions"])
    with r_tab:
        if pending.empty:
            st.info("No runs are awaiting approval. Only an OFFICIAL run enters "
                    "this queue — an unofficial run is terminal by design.")
        else:
            show = pd.DataFrame({
                "status": pending["status"].map(
                    lambda s: "PENDING CHECKER" if s in ("pending_checker",
                                                         "pending_approval")
                    else str(s).upper()),
                "run_id": pending["run_id"],
                "started": pending.get("started_at", pending["requested_at"]),
                "duration_s": pd.to_numeric(pending.get("duration_seconds"),
                                            errors="coerce").round(1),
                "user": pending.get("user", pending["requested_by"]),
                "snapshot": pending["snapshot_label"].replace("", None)
                .fillna("(live config)"),
                "outputs": pending.get("n_outputs"),
                "val_fail": pending.get("n_validation_failures"),
                "overrides": pending["n_overrides_total"]})
            ev = st.dataframe(show, hide_index=True, use_container_width=True,
                              on_select="rerun", selection_mode="single-row",
                              key="aq_pend")
            if (pending["status"] == "unknown").any():
                st.warning("A run listed as UNKNOWN has no reports/run_status.yml — "
                           "something wrote a run and did not record that it needs "
                           "approving.", icon="⚠️")
            rows = ev.selection.rows if ev and ev.selection else []
            if not rows:
                caption("Select a run above to review and approve.")
            else:
                run_id = show.iloc[rows[0]]["run_id"]
                acting = st.text_input("Acting as (your name)", key="aq_actor",
                                       help="Recorded as the checker. Where "
                                            "separation of duties is enforced it "
                                            "must differ from who ran the pipeline.")
                with guard():
                    ctx = api.queue_run_context(run_id, acting or None)
                st.subheader(f"Run {run_id}")
                caption(f"path: `{ctx['path']}`")
                if not ctx["enforced"]:
                    st.info("**Dev mode:** separation of duties is currently "
                            "DISABLED (`approval.enforce_separation_of_duties: "
                            "false`). The user who ran the pipeline can also "
                            "approve it. In production set the flag to `true`.",
                            icon="ℹ️")
                _readiness_line(run_id)
                t1, t2, t3 = st.tabs(["Validation", "Overrides applied", "Outputs"])
                with t1:
                    _val_tab(run_id)
                with t2:
                    _ov_tab(run_id)
                with t3:
                    _out_tab(run_id)
                with st.container(border=True):
                    st.markdown("**Approve / Reject**")
                    st.table(pd.DataFrame({"": [
                        ctx["maker"] or "(not recorded in manifest)",
                        ctx["checker"],
                        "Yes" if ctx["enforced"] else "No (dev mode)"]},
                        index=["Maker (ran the pipeline)", "Acting as",
                               "Separation enforced"]))
                    reason = st.text_area(
                        "Reason (required)", key=f"aq_reason_{run_id}", height=80,
                        placeholder="Document the basis for approval or rejection. "
                                    "It is recorded in the audit log.")
                    b1, b2, _ = st.columns([1, 1, 3])
                    if b1.button("Approve", type="primary",
                                 disabled=not ctx["can_approve"], key="aq_appr"):
                        if not reason.strip():
                            st.warning("Reason is required.")
                        else:
                            try:
                                api.decide_run(run_id, "approve", ctx["checker"],
                                               reason.strip())
                            except api.BackendError as e:
                                st.error(str(e))
                            else:
                                api.clear()
                                flash(f"Run {run_id}: approved")
                                st.rerun()
                    if b2.button("Reject", key="aq_rej"):
                        if not reason.strip():
                            st.warning("Reason is required.")
                        else:
                            try:
                                api.decide_run(run_id, "reject", ctx["checker"],
                                               reason.strip())
                            except api.BackendError as e:
                                st.error(str(e))
                            else:
                                api.clear()
                                flash(f"Run {run_id}: rejected")
                                st.rerun()
                    if not ctx["can_approve"]:
                        caption(f"Approve is disabled: {ctx['blocked_reason']}.")

    with v_tab:
        caption("Versions submitted for final approval (pending_final). Approving "
                "moves the version to approved; rejecting ends it (clone it to a "
                "new draft to fix).")
        if vpend.empty:
            st.info("No versions are awaiting approval.")
        else:
            vshow = pd.DataFrame({
                "label": vpend["label"], "created_by": vpend["created_by"],
                "created_at": vpend["created_at"],
                "parent": vpend["parent"].fillna("—"),
                "description": vpend["description"],
                "code_sha": (vpend["code_sha_at_creation"].astype(str).str[:8]
                             if "code_sha_at_creation" in vpend.columns else "")})
            ev = st.dataframe(vshow, hide_index=True, use_container_width=True,
                              on_select="rerun", selection_mode="single-row",
                              key="aq_vpend")
            rows = ev.selection.rows if ev and ev.selection else []
            if not rows:
                caption("Select a pending version to review and decide.")
            else:
                label = vshow.iloc[rows[0]]["label"]
                sel = vpend.iloc[rows[0]]
                st.subheader(f"Version {label}")
                st.table(pd.DataFrame({"": [
                    sel["created_by"], sel["created_at"], sel["description"],
                    sel["parent"] if isinstance(sel["parent"], str) and sel["parent"]
                    else "(none — first in lineage)",
                    (sel["code_sha_at_creation"] if "code_sha_at_creation" in sel.index
                     else "") or "—"]},
                    index=["Created by", "Created at", "Description",
                           "Parent version", "Code SHA at creation"]))
                caption("To inspect the version's content, open **Config snapshots** "
                        "and pick this version — the Files tab shows every file it "
                        "froze.")
                who = st.text_input("Acting as (your name)", key="aq_vwho")
                reason = st.text_area("Reason (required)", key=f"aq_vr_{label}",
                                      height=70)
                c1, c2, _ = st.columns([1, 2, 2])
                for col, target, text in ((c1, "approved", "Approve"),
                                          (c2, "rejected", "Reject")):
                    if col.button(text, key=f"aq_v_{target}",
                                  type="primary" if target == "approved" else "secondary"):
                        if not reason.strip() or not who.strip():
                            st.warning("Your name and a reason are both required.")
                        else:
                            try:
                                api.promote_snapshot(label, target, who.strip(),
                                                     reason.strip())
                            except api.BackendError as e:
                                st.error(str(e))
                            else:
                                api.clear()
                                flash(f"Version {label}: {target}")
                                st.rerun()

# ================================================================ history ====
with hist_tab:
    hr_tab, hv_tab = st.tabs(["Runs", "Versions"])
    with hr_tab:
        caption("All runs that have been approved or rejected. Newest decision first.")
        if decided.empty:
            st.info("No approved or rejected runs yet.")
        else:
            trunc = lambda s: (str(s)[:60] + "…") if s and len(str(s)) > 60 else s  # noqa: E731
            hshow = pd.DataFrame({
                "decision": decided["status"].str.upper(),
                "run_id": decided["run_id"], "decided_at": decided["decided_at"],
                "decided_by": decided["decided_by"],
                "decision_comment": decided["decision_comment"].map(trunc),
                "requested_by": decided["requested_by"],
                "requested_at": decided["requested_at"],
                "request_comment": decided["request_comment"].map(trunc),
                "snapshot": decided["snapshot_label"].replace("", None)
                .fillna("(live config)"),
                "n_overrides": decided["n_overrides_total"]})
            ev = st.dataframe(hshow, hide_index=True, use_container_width=True,
                              on_select="rerun", selection_mode="single-row",
                              key="aq_hist")
            rows = ev.selection.rows if ev and ev.selection else []
            if not rows:
                caption("Select a row for the full request/decision audit trail and "
                        "the run's outputs.")
            else:
                h = decided.iloc[rows[0]]
                st.subheader(f"Run {h['run_id']} — {str(h['status']).upper()}")
                caption(f"path: `{h['path']}`")
                st.table(pd.DataFrame({"": [
                    h["requested_by"], h["requested_at"],
                    h["request_comment"] or "(none)", h["decided_by"],
                    h["decided_at"], h["decision_comment"] or ""]},
                    index=["Requested by", "Requested at", "Request comment",
                           "Decided by", "Decided at", "Decision comment"]))
                t1, t2, t3 = st.tabs(["Validation", "Overrides applied", "Outputs"])
                with t1:
                    _val_tab(h["run_id"])
                with t2:
                    _ov_tab(h["run_id"])
                with t3:
                    _out_tab(h["run_id"])
    with hv_tab:
        caption("All versions that have been approved or archived. Newest first.")
        if vdec.empty:
            st.info("No approved or archived versions yet.")
        else:
            ev = st.dataframe(vdec[["status", "label", "decided_at", "decided_by",
                                    "decision_comment", "requested_by",
                                    "requested_at", "description"]],
                              hide_index=True, use_container_width=True,
                              on_select="rerun", selection_mode="single-row",
                              key="aq_vhist")
            rows = ev.selection.rows if ev and ev.selection else []
            if rows:
                h = vdec.iloc[rows[0]]
                st.subheader(f"Version {h['label']} — {str(h['status']).upper()}")
                st.table(pd.DataFrame({"": [
                    h["requested_by"], h["requested_at"], h["description"] or "(none)",
                    h["decided_by"] or "(no decider recorded)", h["decided_at"] or "—",
                    h["decision_comment"] or ""]},
                    index=["Created by", "Created at", "Description", "Decided by",
                           "Decided at", "Decision comment"]))

# ===================================================== two sign-offs ========
run_id = st.session_state.get("run_id")
if run_id:
    st.divider()
    with st.expander(f"Risk and Finance sign-off for {run_id}"):
        caption("Beyond the maker-checker decision: Risk signs the model view, "
                "Finance the booking. Refused while validation is failing.")
        with guard():
            st_ = api.approval(run_id)
            v = api.validation(run_id)
        if not v["summary"]["passed"]:
            st.error(f"Validation is failing with {v['summary']['errors']} "
                     "error-level checks; sign-off is refused until they are "
                     "resolved or accepted.", icon="🛑")
        got = st_["approvals"]
        c1, c2 = st.columns(2)
        for col, stage, owner in ((c1, "risk", "Risk"), (c2, "finance", "Finance")):
            with col:
                st.markdown(f"**{owner}**")
                if stage in got:
                    a = got[stage]
                    st.success(f"{a['approver']} · {a['time']}", icon="✅")
                    if a.get("comment"):
                        caption(a["comment"])
                else:
                    approver = st.text_input(f"{owner} approver", key=f"who_{stage}")
                    comment = st.text_input(f"{owner} comment", key=f"cm_{stage}")
                    if st.button(f"Approve as {owner}", key=f"btn_{stage}",
                                 disabled=not approver or not v["summary"]["passed"]):
                        try:
                            api.approve(run_id, stage, approver, comment)
                            api.clear()
                            st.rerun()
                        except api.BackendError as e:
                            st.error(str(e))
        if st_["complete"]:
            st.success("Both sign-offs recorded. This run is released.", icon="🎉")
