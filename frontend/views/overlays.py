"""Management overlay: post-model adjustments, kept as sets of rules.

One page, laid out like Config versions: the overlays in a table; select one
to see its rules. A draft is edited, checked against the run selected at the
top, and marked tested by its maker, which locks it: unofficial runs may then
use it, and it goes to the Approval queue, where somebody else approves it for
official runs. A locked overlay is changed by copying it to a new draft. Only
a draft is removed. Stage 3 is never touched, and a contract matched by two
rules blocks the overlay rather than being adjusted twice. An overlay is
applied to a completed run from the Runs page, after the same check there.
"""
import pandas as pd
import streamlit as st

import api
from ui import (OVERLAY_LEVELS, OVERLAY_METHODS, caption, flash, guard, metric_row,
                overlay_impact, overlay_rules_frame, page_setup, pill)

S = st.session_state

page_setup("Management overlay",
           "A post-model adjustment: a set of rules under one id. Draft, then "
           "tested by its maker (locked; unofficial runs), then approved by somebody "
           "else (official runs). Apply it to a run from the Runs page.")

run_id = S.get("run_id")

METHODS, LEVELS = OVERLAY_METHODS, OVERLAY_LEVELS
L_LABEL = {v: k for k, v in LEVELS.items()}
TARGETS = {
    "whole_book": "no target: all Stage 1 and 2 contracts",
    "stage": "1, 2 (Stage 3 is never touched)",
    "portfolio": "Business Finance, Off BS, Al Dhameen, Tasdeer, Investments, "
                 "Banks and Fis",
    "flag": "watchlist, default, default_gcc, insolvency, local1 … local6",
    "sector": "sector names: the report carries no sector, so this matches "
              "nothing (as in R)",
    "rating": "rating grades, e.g. QDB 7, QDB 8",
    "customer": "customer ids, comma-separated",
    "contract": "contract ids, comma-separated",
}
STATUS_TONE = {"draft": "info", "tested": "warn", "approved": "ok",
               "rejected": "err"}
STATUS_NOTE = {
    "draft": "Edit it, check it against a run, then mark it tested. Marking it "
             "tested locks it: unofficial runs may then use it, and it goes to the "
             "Approval queue.",
    "tested": "Locked. Unofficial runs may use it; it awaits approval in the "
              "Approval queue. To change it, copy it to a new draft.",
    "approved": "Locked. Official and unofficial runs may use it. To change it, "
                "copy it to a new draft.",
    "rejected": "Locked and applied to no run. To change it, copy it to a new draft.",
}


def _from_display(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        if pd.isna(r.get("Method")) and pd.isna(r.get("Value")):
            continue
        m = METHODS.get(r["Method"], "uplift_pct")
        lvl = LEVELS.get(r["Level"], "whole_book")
        v = pd.to_numeric(r["Value"], errors="coerce")
        out.append({"method": m, "level": lvl,
                    "target": "" if lvl == "whole_book" else str(r["Target"] or ""),
                    "value": (float(v) if m == "absolute_add" else float(v) / 100)
                    if pd.notna(v) else 0.0,
                    "comment": str(r["Reason"] or "")})
    return out


def _rules_editor(rules: list, key: str) -> list[dict]:
    """The rules as an editable table; returns them in the engine's form."""
    df = st.data_editor(
        overlay_rules_frame(rules, blank_row=True), num_rows="dynamic",
        use_container_width=True, key=key,
        column_config={
            "Method": st.column_config.SelectboxColumn(options=list(METHODS),
                                                       required=True),
            "Level": st.column_config.SelectboxColumn(options=list(LEVELS),
                                                      required=True),
            "Target": st.column_config.TextColumn(
                help="Comma-separate several: Off BS, Tasdeer"),
            "Value": st.column_config.NumberColumn(
                help="Uplift and higher-of in percent; absolute add in QAR"),
            "Reason": st.column_config.TextColumn("Reason (required)", width="large")})
    return _from_display(df)


def _last(b: dict) -> str:
    tr = b.get("transitions") or []
    return str(tr[-1].get("at") or "")[:16].replace("T", " ") if tr else ""


def _detail(b: dict) -> None:
    oid, stt = b["id"], b.get("status") or "draft"
    editable = stt == "draft"
    st.subheader(f"Overlay {oid}")
    st.markdown(f"status {pill(stt, STATUS_TONE.get(stt, 'info'))} · "
                + STATUS_NOTE.get(stt, ""), unsafe_allow_html=True)
    S.setdefault("ovl_who", S.get("_user") or "")
    ver = len(b.get("transitions") or [])          # resets the editor on save

    # ---- rules
    st.markdown("**Rules**")
    if editable:
        c1, c2, c3, c4 = st.columns(4)
        owner = c1.text_input("Owner", b.get("owner") or "", key=f"ovo_{oid}_{ver}")
        ref = c2.text_input("Approval reference", b.get("approval_ref") or "",
                            key=f"ovr_{oid}_{ver}")
        eff = c3.text_input("Effective from", b.get("effective_date") or "",
                            placeholder="2026-12-31", key=f"ove_{oid}_{ver}")
        exp = c4.text_input("Expires", b.get("expiry") or "",
                            placeholder="2027-03-31", key=f"ovx_{oid}_{ver}")
        rules = _rules_editor(b.get("rules"), key=f"ovt_{oid}_{ver}")
        if st.button("Save", type="primary", icon=":material/save:", key=f"ovs_{oid}"):
            if not rules:
                st.error("Add at least one rule.")
            else:
                try:
                    api.save_overlay_bundle({
                        "id": oid, "owner": owner, "approval_ref": ref,
                        "effective_date": eff, "expiry": exp, "by": S.get("ovl_who", ""),
                        "mode": "replace", "rules": rules})
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.clear()
                    flash(f"Saved {oid} ({len(rules)} rule(s), draft).")
                    st.rerun()
    else:
        rules = b.get("rules") or []
        st.dataframe(overlay_rules_frame(rules), hide_index=True,
                     use_container_width=True)
        caption(f"Owner {b.get('owner') or '—'} · approval reference "
                f"{b.get('approval_ref') or '—'} · effective "
                f"{b.get('effective_date') or '—'} · expires {b.get('expiry') or '—'}")

    # ---- check against the selected run
    st.markdown("**Check against a run**")
    if not run_id:
        caption("Select a run at the top to check this overlay against it.")
    elif st.button(f"Check against run {run_id}", icon=":material/science:",
                   key=f"ovc_{oid}"):
        with guard():
            pv = (api.overlay_preview_rules(run_id, oid, rules) if editable
                  else api.preview_bundle(oid, run_id))
        S["ovl_check"] = (oid, run_id, pv)
    chk = S.get("ovl_check")
    if chk and chk[0] == oid and chk[1] == run_id:
        overlay_impact(chk[2])
        if editable:
            caption("Checked with the rules as they stand in the table, saved or not. "
                    "Nothing is written to the run.")

    if editable:
        # ---- mark tested, or remove
        st.markdown("**Mark tested**")
        c1, c2 = st.columns([1, 2])
        who = c1.text_input("Your name", key="ovl_who")
        reason = c2.text_input("Reason", key=f"ovw_{oid}",
                               placeholder="e.g. impact checked on run …")
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("Mark tested", type="primary", key=f"ovm_{oid}", width="stretch"):
            if not who.strip() or not reason.strip():
                st.warning("Your name and a reason are both required.")
            else:
                try:
                    api.set_bundle_status(oid, "tested", who.strip(), reason.strip())
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.clear()
                    flash(f"{oid} is tested and locked; it is in the Approval queue.")
                    st.rerun()
        with b2.popover("Remove", width="stretch"):
            st.write(f"Remove the draft {oid} and its rules?")
            if st.button("Remove", type="primary", key=f"ovd_{oid}"):
                try:
                    api.delete_overlay_bundle(oid)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.clear()
                    flash(f"Removed {oid}.")
                    st.rerun()
    else:
        # ---- a locked overlay changes as a new draft
        st.markdown("**Copy to a new draft**")
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        new_id = c1.text_input("New overlay id", key=f"ovcp_{oid}",
                               placeholder=f"{oid}-v2").strip()
        if c2.button("Copy to a new draft", key=f"ovcpb_{oid}", width="stretch",
                     disabled=not new_id):
            try:
                api.copy_overlay_bundle(oid, new_id, S.get("ovl_who") or "")
            except api.BackendError as e:
                st.error(str(e))
            else:
                api.clear()
                flash(f"Copied {oid} to the draft {new_id}. Select it below to edit it.")
                st.rerun()
    if b.get("transitions"):
        with st.expander("History"):
            st.dataframe(pd.DataFrame(b["transitions"]), hide_index=True,
                         use_container_width=True)


# ===================================================================== page ==
with guard():
    reg = api.overlay_bundles()
bundles = reg["bundles"]
by_id = {b.get("id"): b for b in bundles}
n = pd.Series([b.get("status") or "draft" for b in bundles], dtype="object")
metric_row([("Overlays", str(len(bundles))),
            ("Approved", str(int((n == "approved").sum()))),
            ("Drafts", str(int((n == "draft").sum()))),
            ("Tested, awaiting approval", str(int((n == "tested").sum())))])

with st.expander("Values and targets"):
    st.markdown("Uplift %: the percentage of model ECL (15 = +15%). Higher-of: the "
                "floor as a percentage of exposure (5 = 5%). Absolute add: the "
                "amount in QAR, spread over the matched contracts by exposure.")
    st.table(pd.DataFrame({"Target to enter": list(TARGETS.values())},
                          index=[L_LABEL[k] for k in TARGETS]))

with st.expander("New overlay", icon=":material/add:"):
    c1, c2 = st.columns(2)
    nid = c1.text_input("Overlay id", placeholder="OV-2026Q4", key="ovn_id").strip()
    nowner = c2.text_input("Owner", "FRM", key="ovn_owner")
    nrules = _rules_editor([], key="ovn_rules")
    if st.button("Create as draft", type="primary", key="ovn_go"):
        if not nid:
            st.error("An overlay id is required.")
        elif nid in by_id:
            st.error(f"{nid} already exists: select it below to edit it.")
        elif not nrules:
            st.error("Add at least one rule.")
        else:
            try:
                api.save_overlay_bundle({"id": nid, "owner": nowner, "mode": "new",
                                         "by": S.get("ovl_who") or S.get("_user") or "",
                                         "rules": nrules})
            except api.BackendError as e:
                st.error(str(e))
            else:
                api.clear()
                for k in ("ovn_id", "ovn_rules"):
                    S.pop(k, None)
                flash(f"Created {nid} as a draft. Select it below to check it and "
                      "mark it tested.")
                st.rerun()

if not bundles:
    st.info("No overlays yet. Create one above.")
else:
    table = pd.DataFrame([{
        "Overlay": b["id"], "Status": b.get("status") or "draft",
        "Rules": len(b.get("rules") or []), "Owner": b.get("owner") or "",
        "Effective": b.get("effective_date") or "", "Expires": b.get("expiry") or "",
        "Last change": _last(b)} for b in bundles])
    ev = st.dataframe(table, hide_index=True, use_container_width=True,
                      on_select="rerun", selection_mode="single-row", key="ovl_tbl")
    rows = ev.selection.rows if ev and ev.selection else []
    if not rows:
        caption("Select an overlay to see its rules, edit a draft, check it and "
                "mark it tested.")
    else:
        _detail(by_id[table.iloc[rows[0]]["Overlay"]])
caption(f"Stored in `{reg['path']}`")
