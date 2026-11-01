"""Management overlay: post-model adjustments, kept as sets of rules.

One page, laid out like Config versions: the overlays in a table; select one
to see its rules, edit them while it is a draft, check them against the run
selected at the top, and move it through draft -> pending -> approved. Saving
always returns an overlay to draft: an edited overlay cannot keep an approval
given to different rules. Stage 3 is never touched, and a contract matched by
two rules blocks the overlay rather than being adjusted twice. An overlay is
applied to a completed run from the Runs page, after the same check there.
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, flash, guard, metric_row, overlay_impact, page_setup, pill

S = st.session_state

page_setup("Management overlay",
           "A post-model adjustment: a set of rules under one id, approved "
           "before it is used. Check it against a run here, then apply it to "
           "that run from the Runs page.")

run_id = S.get("run_id")

METHODS = {"Uplift %": "uplift_pct",
           "Higher-of (floor % of exposure)": "higher_of",
           "Absolute add (QAR)": "absolute_add"}
M_LABEL = {v: k for k, v in METHODS.items()}
LEVELS = {"Whole book": "whole_book", "Stage": "stage", "Portfolio": "portfolio",
          "Rating": "rating", "Flag": "flag", "Sector": "sector",
          "Customer": "customer", "Contract": "contract"}
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
STATUS_TONE = {"draft": "info", "pending": "warn", "approved": "ok",
               "rejected": "err"}
# The moves the backend allows from each status, as buttons.
MOVES = {"draft": [("Submit for approval", "pending")],
         "rejected": [("Submit for approval", "pending"), ("Back to draft", "draft")],
         "pending": [("Approve", "approved"), ("Reject", "rejected"),
                     ("Back to draft", "draft")],
         "approved": [("Back to draft", "draft")]}


def _to_display(rules: list) -> pd.DataFrame:
    rows = []
    for r in rules or []:
        m = r.get("method") or "uplift_pct"
        v = r.get("value")
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = None
        rows.append({"Method": M_LABEL.get(m, m),
                     "Level": L_LABEL.get(r.get("level") or "whole_book", "Whole book"),
                     "Target": r.get("target") or "",
                     "Value": (v if m == "absolute_add" or v is None else v * 100),
                     "Reason": r.get("comment") or ""})
    if not rows:
        rows = [{"Method": "Uplift %", "Level": "Portfolio",
                 "Target": "Business Finance", "Value": 10.0, "Reason": ""}]
    return pd.DataFrame(rows)


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
        _to_display(rules), num_rows="dynamic", use_container_width=True, key=key,
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
    editable = stt in ("draft", "rejected")
    st.subheader(f"Overlay {oid}")
    st.markdown(f"status {pill(stt, STATUS_TONE.get(stt, 'info'))}"
                + ("" if editable else " · move it back to draft to edit"),
                unsafe_allow_html=True)
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
        st.dataframe(_to_display(rules), hide_index=True, use_container_width=True)
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
            caption("Checked with the rules as they stand in the table, saved or not.")

    # ---- approval
    st.markdown("**Approval**")
    c1, c2 = st.columns([1, 2])
    who = c1.text_input("Your name", key="ovl_who")
    reason = c2.text_input("Reason for the change of status", key=f"ovw_{oid}")
    cols = st.columns(len(MOVES.get(stt, [])) + 1)
    for col, (label, to) in zip(cols, MOVES.get(stt, [])):
        if col.button(label, key=f"ovm_{oid}_{to}",
                      type="primary" if to in ("pending", "approved") else "secondary"):
            if not who.strip() or not reason.strip():
                st.warning("Your name and a reason are both required.")
            else:
                try:
                    api.set_bundle_status(oid, to, who.strip(), reason.strip())
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.clear()
                    flash(f"{oid} is now {to}.")
                    st.rerun()
    with cols[-1].popover("Remove"):
        st.write(f"Remove overlay {oid} and its rules? Runs it was applied to "
                 "keep their overlaid reports.")
        if st.button("Remove", type="primary", key=f"ovd_{oid}"):
            try:
                api.delete_overlay_bundle(oid)
            except api.BackendError as e:
                st.error(str(e))
            else:
                api.clear()
                flash(f"Removed {oid}.")
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
            ("Drafts", str(int(n.isin(["draft", "rejected"]).sum()))),
            ("Awaiting approval", str(int((n == "pending").sum())))])

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
                flash(f"Created {nid} as a draft. Select it below to check and "
                      "submit it.")
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
        caption("Select an overlay to see its rules, edit, check and approve it.")
    else:
        _detail(by_id[table.iloc[rows[0]]["Overlay"]])
caption(f"Stored in `{reg['path']}`")
