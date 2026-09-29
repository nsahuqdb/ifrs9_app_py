"""ECL overlays: post-model adjustments, built as bundles of rules.

The R app's overlay page. A bundle is a set of rules under one overlay id --
each rule a method, the level it applies at, a target, a value and a reason --
with an approval flow of its own (draft -> pending -> approved). Stage 3 is
never touched, and a contract matched by two rules blocks the overlay rather
than being adjusted twice. Saving a bundle always returns it to draft: an
edited overlay cannot keep an approval given to different rules.
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pill, flash

page_setup("ECL overlays",
           "Build a bundle of post-model adjustment rules and save it under one "
           "overlay id. Overlays are applied to a completed run from the Runs "
           "page (or the Apply tab here); the model report is kept and the "
           "overlaid one written beside it.")

run_id = st.session_state.get("run_id")

METHODS = {"Uplift %": "uplift_pct",
           "Higher-of (floor % of exposure)": "higher_of",
           "Absolute add (QAR)": "absolute_add"}
M_LABEL = {v: k for k, v in METHODS.items()}
LEVELS = {"Whole book": "whole_book", "Stage": "stage", "Portfolio": "portfolio",
          "Rating": "rating", "Flag": "flag", "Sector": "sector",
          "Customer": "customer", "Contract": "contract"}
L_LABEL = {v: k for k, v in LEVELS.items()}
TARGETS = {
    "whole_book": "no target — all Stage 1 and 2 contracts",
    "stage": "1, 2 (Stage 3 is never touched)",
    "portfolio": "Business Finance, Off BS, Al Dhameen, Tasdeer, Investments, "
                 "Banks and Fis",
    "flag": "watchlist, default, default_gcc, insolvency, local1 … local6",
    "sector": "sector names — inert: the report carries no sector, so it "
              "matches nothing (as in R)",
    "rating": "rating grades, e.g. QDB 7, QDB 8",
    "customer": "customer ids, comma-separated",
    "contract": "contract ids, comma-separated",
}
STATUS_TONE = {"draft": "info", "pending": "warn", "approved": "ok",
               "rejected": "err"}

st.info("**Value guide.** Uplift % — enter the percentage (15 = +15% of model "
        "ECL). Higher-of — the floor as a percentage of exposure (5 = 5% of "
        "exposure). Absolute add — the amount in QAR (1,000,000), spread across "
        "the matched contracts by exposure. **Stage 3 is never touched**, and a "
        "contract hit by two rules blocks the overlay.", icon="ℹ️")

with guard():
    reg = api.overlay_bundles()
bundles = reg["bundles"]
by_id = {b.get("id"): b for b in bundles}
caption(f"Stored in `{reg['path']}`")


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


def _rule_line(r: dict) -> str:
    m, v = r.get("method"), float(r.get("value") or 0)
    vtxt = {"uplift_pct": f"+{v * 100:.4g}%",
            "higher_of": f"floor {v * 100:.4g}% of exposure",
            "absolute_add": f"QAR {v:,.0f}"}.get(m, str(v))
    tgt = "whole book" if r.get("level") == "whole_book" else \
        f"{r.get('level')}: {r.get('target')}"
    return (f"**{M_LABEL.get(m, m)}** — {vtxt} on {tgt}"
            + (f"  *({r.get('comment')})*" if r.get("comment") else ""))


builder, saved, apply_tab, applied_tab = st.tabs(
    ["Builder", "Saved overlays", "Preview & apply", "Applied to this run"])

# ================================================================ builder ==
with builder:
    editing = st.session_state.get("ovl_edit")
    current = by_id.get(editing, {}) if editing else {}
    st.markdown(f"**{'Editing: ' + editing if current else 'New overlay'}**")
    if current:
        st.markdown(f"Currently {pill(current.get('status', 'draft'), STATUS_TONE.get(current.get('status', 'draft'), 'info'))} "
                    "— saving returns it to **draft** for re-approval.",
                    unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    oid = c1.text_input("Overlay ID", value=current.get("id", ""),
                        placeholder="e.g. OV-2026Q2", key=f"b_id_{editing}")
    owner = c2.text_input("Owner", value=current.get("owner", "FRM"),
                          key=f"b_owner_{editing}")
    ref = c3.text_input("Approval reference", value=current.get("approval_ref", ""),
                        key=f"b_ref_{editing}")
    c4, c5, c6 = st.columns(3)
    eff = c4.text_input("Effective from", value=current.get("effective_date", ""),
                        placeholder="2026-06-30", key=f"b_eff_{editing}")
    exp = c5.text_input("Expires", value=current.get("expiry", ""),
                        placeholder="2026-12-31", key=f"b_exp_{editing}")
    who = c6.text_input("Your name", key="b_who")
    st.markdown("**Rules**")
    with st.expander("Targets by level"):
        st.table(pd.DataFrame({"what to enter": list(TARGETS.values())},
                              index=[L_LABEL[k] for k in TARGETS]))
    edited = st.data_editor(
        _to_display(current.get("rules")), num_rows="dynamic",
        use_container_width=True, key=f"rules_{editing}",
        column_config={
            "Method": st.column_config.SelectboxColumn(options=list(METHODS),
                                                       required=True),
            "Level": st.column_config.SelectboxColumn(options=list(LEVELS),
                                                      required=True),
            "Target": st.column_config.TextColumn(
                help="Comma-separate several: Off BS, Tasdeer"),
            "Value": st.column_config.NumberColumn(
                help="Uplift / higher-of in percent; absolute add in QAR",
                format="%.4g"),
            "Reason": st.column_config.TextColumn("Reason (required)", width="large")})
    exists = oid.strip() in by_id and oid.strip() != (editing or "")
    mode = "replace"
    if exists:
        n_rules = len(by_id[oid.strip()].get("rules") or [])
        st.warning(f"Overlay '{oid.strip()}' already exists with {n_rules} rule(s).",
                   icon="⚠️")
        mode = {"Replace its rules": "replace",
                "Append these rules to it": "append"}[
            st.radio("Save as", ["Replace its rules", "Append these rules to it"],
                     horizontal=True)]
    b1, b2, b3, _ = st.columns([1, 1, 1, 3])
    if b1.button("Save overlay", type="primary", icon=":material/save:"):
        if not oid.strip():
            st.error("Overlay ID is required.")
        else:
            payload = {"id": oid.strip(), "owner": owner, "approval_ref": ref,
                       "effective_date": eff, "expiry": exp, "by": who,
                       "mode": mode, "rules": _from_display(edited)}
            if not payload["rules"]:
                st.error("Add at least one rule.")
            else:
                try:
                    api.save_overlay_bundle(payload)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.clear()
                    st.session_state.pop("ovl_edit", None)
                    flash(f"Saved overlay '{oid.strip()}' "
                          f"({len(payload['rules'])} rule(s), status: draft).")
                    st.rerun()
    if b2.button("Clear", icon=":material/ink_eraser:"):
        st.session_state.pop("ovl_edit", None)
        st.rerun()
    if b3.button("Preview impact", icon=":material/science:"):
        if not run_id:
            st.warning("Select a run at the top to preview against.")
        else:
            with guard():
                prev = api.overlay_preview_rules(run_id, oid.strip() or "PREVIEW",
                                                 _from_display(edited))
            if not prev.get("ok"):
                st.error("Conflict or invalid rules: "
                         + "; ".join(prev.get("errors", [])), icon="⚠️")
                if prev.get("contracts"):
                    st.dataframe(pd.DataFrame({"contract": prev["contracts"][:10]}),
                                 hide_index=True)
            else:
                t = prev["total"]
                metric_row([("Model", money(t["model"])),
                            ("Overlay", "+" + money(t["overlay"])),
                            ("Final", money(t["final"])),
                            ("Change", f"+{100 * t['overlay'] / max(t['model'], 1):.2f}%")])
                if prev.get("summary"):
                    st.dataframe(pd.DataFrame(prev["summary"]), hide_index=True,
                                 use_container_width=True)

# ================================================================== saved ==
with saved:
    caption("Edit loads a bundle back into the builder. Submit, approve and "
            "reject move it through draft → pending → approved; each is recorded "
            "with who and why.")
    if not bundles:
        st.info("No overlays yet.")
    actor = st.text_input("Acting as (your name)", key="ovl_actor")
    for b in bundles:
        stt = b.get("status") or "draft"
        with st.container(border=True):
            h1, h2 = st.columns([3, 2])
            h1.markdown(f"#### {b['id']} &nbsp;{pill(stt.upper(), STATUS_TONE.get(stt, 'info'))}",
                        unsafe_allow_html=True)
            h2.caption(f"{len(b.get('rules') or [])} rule(s) · owner "
                       f"{b.get('owner') or '—'}")
            for r in b.get("rules") or []:
                st.markdown("- " + _rule_line(r))
            reason = st.text_input("Reason for the status change", key=f"why_{b['id']}")
            cols = st.columns(5)

            def _move(to, oid=b["id"], rkey=f"why_{b['id']}"):
                why = st.session_state.get(rkey, "").strip()
                if not actor.strip() or not why:
                    st.warning("Your name and a reason are both required.")
                    return
                try:
                    api.set_bundle_status(oid, to, actor.strip(), why)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.clear()
                    flash(f"Overlay '{oid}' is now {to}.")
                    st.rerun()
            if stt in ("draft", "rejected") and cols[0].button(
                    "Submit for approval", key=f"sub_{b['id']}"):
                _move("pending")
            if stt == "pending":
                if cols[0].button("Approve", type="primary", key=f"app_{b['id']}"):
                    _move("approved")
                if cols[1].button("Reject", key=f"rej_{b['id']}"):
                    _move("rejected")
            if cols[2].button("Edit", key=f"ed_{b['id']}"):
                st.session_state["ovl_edit"] = b["id"]
                st.rerun()
            with cols[3].popover("Remove"):
                st.write(f"Remove overlay '{b['id']}' and all its rules?")
                if st.button("Remove", type="primary", key=f"del_{b['id']}"):
                    try:
                        api.delete_overlay_bundle(b["id"])
                    except api.BackendError as e:
                        st.error(str(e))
                    else:
                        api.clear()
                        st.rerun()
            if b.get("transitions"):
                with st.expander("History"):
                    st.dataframe(pd.DataFrame(b["transitions"]), hide_index=True,
                                 use_container_width=True)

# ========================================================= preview & apply ==
with apply_tab:
    if not run_id:
        st.info("No run selected.", icon="👈")
    elif not bundles:
        caption("Define an overlay first.")
    else:
        pick = st.selectbox("Overlay", list(by_id), key="apply_pick",
                            format_func=lambda i: f"{i} [{(by_id[i].get('status') or 'draft').upper()}]")
        if st.button("Preview", type="primary"):
            try:
                pv = api.preview_bundle(pick, run_id)
            except api.BackendError as e:
                st.error(str(e))
            else:
                if not pv.get("ok"):
                    st.error("Conflict: " + "; ".join(pv.get("errors", []))
                             + " — resolve before applying.", icon="⚠️")
                    if pv.get("contracts"):
                        st.dataframe(pd.DataFrame({"contract": pv["contracts"][:10]}),
                                     hide_index=True)
                else:
                    t = pv["total"]
                    metric_row([("Model ECL", money(t["model"])),
                                ("Overlay", "+" + money(t["overlay"])),
                                ("Final ECL", money(t["final"])),
                                ("Contracts", money(pv.get("contracts_touched", 0)))])
                    if pv.get("summary"):
                        st.dataframe(pd.DataFrame(pv["summary"]), hide_index=True,
                                     use_container_width=True)
        status = (by_id.get(pick) or {}).get("status", "draft")
        if status != "approved":
            st.warning(f"This overlay is **{status}**. Applying an unapproved "
                       "overlay is allowed — the status travels with the output — "
                       "but it should be approved before the figure is used.",
                       icon="⚠️")
        if st.button("Apply to this run"):
            try:
                res = api.apply_bundle(pick, run_id)
            except api.BackendError as e:
                st.error(str(e))
            else:
                if not res.get("ok"):
                    st.error("Conflict: " + "; ".join(res.get("errors", [])), icon="⚠️")
                else:
                    t = res["totals"]
                    st.success(f"Applied. Model {money(t['model'])} → overlay "
                               f"+{money(t['overlay'])} → final {money(t['final'])} "
                               f"(+{100 * t['overlay'] / max(t['model'], 1):.2f}%).")
                    api.clear()

# ================================================================ applied ==
with applied_tab:
    if not run_id:
        st.info("No run selected.", icon="👈")
    else:
        with guard():
            ap = api.applied_overlays(run_id)
        rows = ap["applied"]
        if not rows:
            caption("No overlay has been applied to this run.")
        else:
            st.dataframe(pd.DataFrame(rows)[["overlay_id", "report_file", "applied_at"]],
                         hide_index=True, use_container_width=True)
            caption("Read from what is on disk, so an overlay whose files were "
                    "removed stops showing up. The analytics pages read the "
                    "overlaid report while one is applied, as the R app does.")
            drop = st.selectbox("Remove", [r["overlay_id"] for r in rows],
                                key="drop_applied")
            if st.button("Remove its outputs"):
                try:
                    api.remove_applied_overlay(run_id, drop)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.clear()
                    flash(f"Removed {drop}. The model report is untouched.")
                    st.rerun()
