"""Approval queue: what a second person signs off.

Three kinds, one step each:

    Runs                 an OFFICIAL run, once it has finished
    Config versions      a version its maker marked tested
    Management overlays  an overlay its maker marked tested

Each is approved or rejected with a name and a reason. Where separation of
duties is enforced, whoever made it cannot decide it. Unofficial runs, drafts
and the live config never come here.
"""
import pandas as pd
import streamlit as st

import api
from ui import (accepted_findings_table, caption, flash, guard, kpis, money,
                overlay_impact, overlay_rules_frame, page_setup, pill,
                style_severity)

S = st.session_state

page_setup("Approval queue",
           "Official runs, and the config versions and management overlays their "
           "makers marked tested, approved or rejected by somebody else.")

with guard():
    qr, qv, qo = api.queue_runs(), api.queue_versions(), api.queue_overlays()

runs_p, runs_d = pd.DataFrame(qr["pending"]), pd.DataFrame(qr["decided"])
ver_p, ver_d = pd.DataFrame(qv["pending"]), pd.DataFrame(qv["decided"])
ovl_p, ovl_d = qo["pending"], qo["decided"]

k, r = st.columns([8, 1], vertical_alignment="center")
with k:
    kpis([("Runs to sign off", money(len(runs_p)), "warn" if len(runs_p) else "ok", ""),
          ("Config versions to approve", money(len(ver_p)),
           "warn" if len(ver_p) else "ok", ""),
          ("Overlays to approve", money(len(ovl_p)), "warn" if ovl_p else "ok", "")])
if r.button("Refresh", key="aq_refresh", icon=":material/refresh:", width="stretch"):
    api.clear()
    st.rerun()

S.setdefault("aq_who", S.get("_user") or "")
# one name for the whole page: a run, a config version and an overlay can be
# open at once, each in its tab, and each decision records this name
st.text_input("Your name", key="aq_who", width=320,
              help="Recorded with every approval or rejection on this page.")


def _decide(key: str, approve, reject, can: bool = True, why_not: str = "") -> None:
    """A reason, and Approve / Reject, under the page's name."""
    who = S.get("aq_who") or ""
    reason = st.text_input("Reason (required)", key=f"aq_reason_{key}")
    b1, b2, _ = st.columns([1, 1, 4])
    go_a = b1.button("Approve", type="primary", disabled=not can, key=f"aq_a_{key}",
                     width="stretch")
    go_r = b2.button("Reject", key=f"aq_r_{key}", width="stretch")
    if not can and why_not:
        caption(f"Approve is disabled: {why_not}.")
    if go_a or go_r:
        if not who.strip() or not reason.strip():
            st.warning("Your name and a reason are both required.")
            return
        try:
            (approve if go_a else reject)(who.strip(), reason.strip())
        except api.BackendError as e:
            st.error(str(e))
        else:
            api.clear()
            flash(f"{key.split(':', 1)[-1]}: {'approved' if go_a else 'rejected'}.")
            st.rerun()


def _pick(df: pd.DataFrame, key: str) -> int | None:
    ev = st.dataframe(df, hide_index=True, use_container_width=True,
                      on_select="rerun", selection_mode="single-row", key=key)
    rows = ev.selection.rows if ev and ev.selection else []
    return rows[0] if rows else None


def _when(v) -> str:
    return str(v or "")[:16].replace("T", " ")


t_runs, t_ver, t_ovl = st.tabs([f"Runs · {len(runs_p)}",
                                f"Config versions · {len(ver_p)}",
                                f"Management overlays · {len(ovl_p)}"])

# =================================================================== runs ===
with t_runs:
    if runs_p.empty:
        st.info("No official run is waiting. Only an official run is signed off; "
                "an unofficial run needs no approval.")
    else:
        show = pd.DataFrame({
            "Run": runs_p["run_id"],
            "Started": runs_p.get("started_at", runs_p["requested_at"]).map(_when),
            "Run by": runs_p.get("user", runs_p["requested_by"]),
            "Config version": runs_p["snapshot_label"].replace("", None)
            .fillna("(live config)"),
            "Validation fails": runs_p.get("n_validation_failures"),
            "Overrides": runs_p["n_overrides_total"]})
        i = _pick(show, "aq_runs")
        if i is None:
            caption("Select a run to review it and sign it off.")
        else:
            run_id = show.iloc[i]["Run"]
            with guard():
                ctx = api.queue_run_context(run_id, S.get("aq_who") or None)
            st.subheader(f"Run {run_id}")
            caption(f"Run by {ctx['maker'] or '(not recorded)'} · `{ctx['path']}`")
            with guard():
                rd = api.run_readiness(run_id)
            if rd.get("exists"):
                s = rd["summary"]
                st.markdown(
                    f"Readiness: {s['contracts']:,} contracts · "
                    f"{pill(str(s['No ECL']['contracts']) + ' no ECL', 'err' if s['No ECL']['contracts'] else 'ok')} "
                    f"{pill(str(s['Blank in LIC']['contracts']) + ' blank in LIC', 'err' if s['Blank in LIC']['contracts'] else 'ok')}",
                    unsafe_allow_html=True)
            t1, t2, t3 = st.tabs(["Validation", "Overrides", "Outputs"])
            with t1:
                with guard():
                    v = api.run_validation_table(run_id)
                if not v["exists"]:
                    caption("No validation report.")
                else:
                    c = v["counts"]
                    st.markdown(
                        f"{c['passed']}/{c['checks']} passed &nbsp; "
                        + pill(f"{c['errors']} errors", "err" if c["errors"] else "ok")
                        + " " + pill(f"{c['warnings']} warnings",
                                     "warn" if c["warnings"] else "ok"),
                        unsafe_allow_html=True)
                    with guard():
                        acc = api.run_accepted_findings(run_id)
                    if acc.get("rows"):
                        st.markdown(f"**Accepted findings · {len(acc['rows'])}**: "
                                    "approving the run accepts them.")
                        accepted_findings_table(acc["rows"])
                    st.dataframe(style_severity(pd.DataFrame(v["rows"])[
                        ["status", "stage", "id", "description", "message"]]),
                        hide_index=True, width="stretch", height=300)
            with t2:
                with guard():
                    o = api.run_overrides(run_id)
                if not o["exists"]:
                    caption("No overrides.")
                for f in o.get("files") or []:
                    st.markdown(f"**{f['file']}**")
                    if f["rows"]:
                        st.dataframe(pd.DataFrame(f["rows"]), hide_index=True,
                                     use_container_width=True)
                    else:
                        caption("(none applied)")
            with t3:
                with guard():
                    outs = api.run_outputs(run_id)["files"]
                if outs:
                    st.dataframe(pd.DataFrame(outs)[["file", "size_kb"]],
                                 hide_index=True, use_container_width=True)
            _decide(f"run:{run_id}",
                    lambda who, why: api.decide_run(run_id, "approve", who, why),
                    lambda who, why: api.decide_run(run_id, "reject", who, why),
                    ctx["can_approve"], ctx["blocked_reason"])
    if not runs_d.empty:
        with st.expander(f"Decided runs · {len(runs_d)}"):
            st.dataframe(pd.DataFrame({
                "Decision": runs_d["status"].str.upper(), "Run": runs_d["run_id"],
                "By": runs_d["decided_by"], "When": runs_d["decided_at"].map(_when),
                "Reason": runs_d["decision_comment"],
                "Run by": runs_d["requested_by"]}),
                hide_index=True, use_container_width=True)

# ======================================================== config versions ===
with t_ver:
    if ver_p.empty:
        st.info("No config version is waiting. A version comes here when its maker "
                "marks it tested on Config versions.")
    else:
        show = pd.DataFrame({
            "Version": ver_p["label"], "Description": ver_p["description"],
            "Created by": ver_p["created_by"], "Tested by": ver_p["tested_by"],
            "Tested": ver_p["tested_at"].map(_when),
            "Based on": ver_p["parent"].fillna("(the live config)")})
        i = _pick(show, "aq_ver")
        if i is None:
            caption("Select a version to approve or reject it. Its files are on "
                    "Config versions.")
        else:
            label = show.iloc[i]["Version"]
            with guard():
                ctx = api.promote_context(label, S.get("aq_who") or None)
            st.subheader(f"Config version {label}")
            caption("Every file it froze is on Config versions (Versions tab). Once "
                    "approved it may be used in official runs.")
            _decide(f"version:{label}",
                    lambda who, why: api.promote_snapshot(label, "approved", who, why),
                    lambda who, why: api.promote_snapshot(label, "rejected", who, why),
                    not ctx["creator_cannot_approve"],
                    "who created or tested it cannot approve it")
    if not ver_d.empty:
        with st.expander(f"Decided config versions · {len(ver_d)}"):
            st.dataframe(pd.DataFrame({
                "Status": ver_d["status"], "Version": ver_d["label"],
                "By": ver_d["decided_by"], "When": ver_d["decided_at"].map(_when),
                "Reason": ver_d["decision_comment"],
                "Created by": ver_d["created_by"]}),
                hide_index=True, use_container_width=True)

# ===================================================== management overlays ===
with t_ovl:
    if not ovl_p:
        st.info("No overlay is waiting. An overlay comes here when its maker marks "
                "it tested on Management overlay.")
    else:
        show = pd.DataFrame([{
            "Overlay": o["id"], "Owner": o["owner"], "Rules": o["n_rules"],
            "Created by": o["created_by"], "Tested by": o["tested_by"],
            "Tested": _when(o["tested_at"])} for o in ovl_p])
        i = _pick(show, "aq_ovl")
        if i is None:
            caption("Select an overlay to approve or reject it.")
        else:
            o = ovl_p[i]
            oid = o["id"]
            st.subheader(f"Overlay {oid}")
            st.dataframe(overlay_rules_frame(o["rules"]), hide_index=True,
                         use_container_width=True)
            caption(f"Approval reference {o['approval_ref'] or '—'} · effective "
                    f"{o['effective_date'] or '—'} · expires {o['expiry'] or '—'}. "
                    "Once approved it may be applied to official runs.")
            run_id = S.get("run_id")
            if run_id and st.button(f"Check against run {run_id}",
                                    icon=":material/science:", key=f"aq_chk_{oid}"):
                with guard():
                    S["aq_ovl_chk"] = (oid, run_id, api.preview_bundle(oid, run_id))
            chk = S.get("aq_ovl_chk")
            if chk and chk[0] == oid and chk[1] == run_id:
                overlay_impact(chk[2])
            makers = {str(o.get("created_by") or "").lower(),
                      str(o.get("tested_by") or "").lower()} - {""}
            _decide(f"overlay:{oid}",
                    lambda who, why: api.set_bundle_status(oid, "approved", who, why),
                    lambda who, why: api.set_bundle_status(oid, "rejected", who, why),
                    True, "")
            if (S.get("aq_who") or "").strip().lower() in makers:
                caption("You created or tested this overlay: where separation of "
                        "duties is enforced, somebody else must approve it.")
    if ovl_d:
        with st.expander(f"Decided overlays · {len(ovl_d)}"):
            st.dataframe(pd.DataFrame([{
                "Status": o["status"], "Overlay": o["id"], "By": o["decided_by"],
                "When": _when(o["decided_at"]), "Reason": o["decision_comment"],
                "Created by": o["created_by"]} for o in ovl_d]),
                hide_index=True, use_container_width=True)
