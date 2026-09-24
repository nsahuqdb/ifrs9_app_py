"""Management adjustments applied after the model."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pill

page_setup("Overlays",
           "Applied after the engine, never in place of it. The report keeps "
           "the model figure, the overlay amount and the final figure side by "
           "side, and every overlay records what it moved and why — an "
           "adjustment nobody can trace back is indistinguishable from an "
           "error.")

run_id = st.session_state.get("run_id")

with guard():
    reg = api.overlay_bundles()

bundles = reg["bundles"]
by_id = {b.get("id"): b for b in bundles}
labels = list(by_id)

METHODS = ["uplift_pct", "higher_of", "absolute_add"]
LEVELS = ["whole_book", "stage", "portfolio", "rating", "flag", "customer",
          "contract"]
STATUS_TONE = {"draft": "info", "pending": "warn", "approved": "ok",
               "rejected": "err"}

st.info(
    "**Stage 3 is never touched** — those provisions are booked manually "
    "outside the tool, and an overlay on top would double-count. "
    "**At most one overlay per contract**: overlapping overlays are rejected "
    "rather than compounded, because the order of application would otherwise "
    "decide the provision.", icon="ℹ️")

define, apply_tab, applied_tab = st.tabs(["Define", "Preview & apply",
                                          "Applied to this run"])

# ------------------------------------------------------------------ define --
with define:
    pick = st.selectbox("Overlay", ["(new)"] + labels)
    current = by_id.get(pick, {}) if pick != "(new)" else {}

    if current:
        st.markdown(
            f"Status {pill(current.get('status', 'draft'), STATUS_TONE.get(current.get('status', 'draft'), 'info'))}",
            unsafe_allow_html=True)

    with st.form("overlay_bundle"):
        c1, c2, c3 = st.columns(3)
        oid = c1.text_input("Id", current.get("id", ""),
                            disabled=bool(current))
        owner = c2.text_input("Owner", current.get("owner", "FRM"))
        ref = c3.text_input("Approval reference",
                            current.get("approval_ref", ""))
        c4, c5 = st.columns(2)
        eff = c4.text_input("Effective from", current.get("effective_date", ""),
                            placeholder="2026-06-30")
        exp = c5.text_input("Expires", current.get("expiry", ""),
                            placeholder="2026-12-31")

        st.markdown("**Rules**")
        caption("Each rule picks a level, a target, a method and a value. A "
                "comment is mandatory on every one. Targets accept a list: "
                "`Off BS, Tasdeer`.")
        rules = pd.DataFrame(current.get("rules") or [
            {"method": "uplift_pct", "level": "portfolio",
             "target": "Business Finance", "value": 0.1, "comment": ""}])
        for c in ("method", "level", "target", "value", "comment"):
            if c not in rules.columns:
                rules[c] = ""
        edited = st.data_editor(
            rules[["method", "level", "target", "value", "comment"]],
            num_rows="dynamic", use_container_width=True, key="rule_editor",
            column_config={
                "method": st.column_config.SelectboxColumn("Method",
                                                           options=METHODS),
                "level": st.column_config.SelectboxColumn("Level",
                                                          options=LEVELS),
                "target": st.column_config.TextColumn("Target"),
                "value": st.column_config.NumberColumn("Value", format="%.4f"),
                "comment": st.column_config.TextColumn("Comment (required)",
                                                       width="large")})
        if st.form_submit_button("Save", type="primary"):
            if not oid.strip():
                st.error("An id is required.")
            else:
                payload = {"id": oid.strip(), "owner": owner,
                           "approval_ref": ref, "effective_date": eff,
                           "expiry": exp,
                           "rules": edited.fillna("").to_dict(orient="records")}
                for r in payload["rules"]:
                    r["value"] = float(r.get("value") or 0)
                try:
                    api.save_overlay_bundle(payload)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.overlay_bundles.clear()
                    st.success(f"Saved {oid.strip()}.")
                    st.rerun()

    if current:
        st.markdown("### Approval")
        caption("The trail is append-only: an overlay rejected and later "
                "approved reads as exactly that.")
        with st.form("overlay_status"):
            c1, c2 = st.columns(2)
            to = c1.selectbox("Move to", ["draft", "pending", "approved",
                                          "rejected"])
            by = c2.text_input("Your name")
            reason = st.text_area("Reason", height=70)
            if st.form_submit_button("Record"):
                if not by.strip() or not reason.strip():
                    st.error("Both your name and a reason are required.")
                else:
                    try:
                        api.set_bundle_status(pick, to, by.strip(),
                                              reason.strip())
                    except api.BackendError as e:
                        st.error(str(e))
                    else:
                        api.overlay_bundles.clear()
                        st.rerun()
        if current.get("transitions"):
            with st.expander("History"):
                st.dataframe(pd.DataFrame(current["transitions"]),
                             hide_index=True, use_container_width=True)
        if st.button(f"Delete {pick}"):
            try:
                api.delete_overlay_bundle(pick)
            except api.BackendError as e:
                st.error(str(e))
            else:
                api.overlay_bundles.clear()
                st.rerun()

# --------------------------------------------------------- preview & apply --
with apply_tab:
    if not run_id:
        st.info("No run selected.", icon="👈")
    elif not labels:
        caption("Define an overlay first.")
    else:
        pick = st.selectbox("Overlay", labels, key="apply_pick")
        st.markdown("### Preview")
        caption("What it would do to this run. Nothing is written.")
        if st.button("Preview", type="primary"):
            try:
                pv = api.preview_bundle(pick, run_id)
            except api.BackendError as e:
                st.error(str(e))
            else:
                if not pv.get("ok"):
                    for err in pv.get("errors", []):
                        st.error(err)
                else:
                    t = pv["total"]
                    metric_row([("Model ECL", money(t["model"])),
                                ("Overlay", money(t["overlay"])),
                                ("Final ECL", money(t["final"])),
                                ("Contracts", money(pv.get("contracts_touched", 0)))])
                    if pv.get("summary"):
                        st.dataframe(pd.DataFrame(pv["summary"]),
                                     hide_index=True, use_container_width=True)

        st.markdown("### Apply")
        caption("Writes `FinalEclReport_overlay_<id>.csv` and its audit log "
                "beside the model report. The model report is never modified, "
                "so both numbers stay on disk and the difference between them "
                "is a file anybody can open.")
        status = (by_id.get(pick) or {}).get("status", "draft")
        if status != "approved":
            st.warning(f"This overlay is **{status}**. Applying an unapproved "
                       "overlay is allowed — the status travels with the "
                       "output — but it should be approved before the figure "
                       "is used.", icon="⚠️")
        if st.button("Apply to this run"):
            try:
                res = api.apply_bundle(pick, run_id)
            except api.BackendError as e:
                st.error(str(e))
            else:
                if not res.get("ok"):
                    for err in res.get("errors", []):
                        st.error(err)
                else:
                    t = res["totals"]
                    st.success(f"Applied. Model {money(t['model'])} → final "
                               f"{money(t['final'])}.")
                    api.applied_overlays.clear()

# ------------------------------------------------------------------ applied --
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
            st.dataframe(
                pd.DataFrame(rows)[["overlay_id", "report_file", "applied_at"]],
                hide_index=True, use_container_width=True,
                column_config={"overlay_id": "Overlay",
                               "report_file": "Report", "applied_at": "Applied"})
            caption("Read from what is on disk rather than from a register, so "
                    "an overlay whose files were removed stops showing up.")
            drop = st.selectbox("Remove", [r["overlay_id"] for r in rows],
                                key="drop_applied")
            if st.button("Remove its outputs"):
                try:
                    api.remove_applied_overlay(run_id, drop)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.applied_overlays.clear()
                    st.success(f"Removed {drop}. The model report is untouched.")
                    st.rerun()
