"""Runs: every run, where it stands, and everything it recorded.

The R app's "Browse runs" page. The table carries each run's approval status
and health; selecting one shows its manifest, validation, pricing readiness,
overrides and output files (any column sorted over the whole file), with the
export (approved or unofficial runs only) and the overlays applied to it.
"""
import pandas as pd
import streamlit as st

import api
from ui import (accepted_findings_table, callout, caption, column_filters, flash,
                guard, kpis, money, overlay_impact, page_setup, pill, style_severity)

page_setup("Browse runs", "Every run, where it stands in approval, and everything "
           "it recorded. Select one to open it.")

with guard():
    t = api.runs_table()

tiles = t["tiles"]
kpis([("Runs", money(tiles["total"]), "plum", ""),
      ("Approved", money(tiles["approved"]), "ok" if tiles["approved"] else "", ""),
      ("Pending checker", money(tiles["pending_checker"]),
       "warn" if tiles["pending_checker"] else "", "awaiting approval"),
      ("Unofficial", money(tiles["unofficial"]), "info" if tiles["unofficial"] else "",
       "no approval needed"),
      ("With validation fails", money(tiles["with_validation_fails"]),
       "err" if tiles["with_validation_fails"] else "ok", "")])
if not t["exists"]:
    callout("warn", f"The runs folder `{t['runs_dir']}` does not exist. Set "
            "`IFRS9_RUNS_DIR`, or start a run on **Run the pipeline**.")

runs = pd.DataFrame(t["runs"])
if runs.empty:
    st.info("No runs found. Start one on **Run the pipeline**.", icon="ℹ️")
    st.stop()

STATUS_TONE = {"approved": "ok", "pending_checker": "warn",
               "pending_approval": "warn", "unofficial": "info",
               "rejected": "err", "unknown": "info"}
STATUS_ICON = {"approved": "✅ APPROVED", "pending_checker": "⏳ PENDING CHECKER",
               "pending_approval": "⏳ PENDING CHECKER", "unofficial": "ℹ️ UNOFFICIAL",
               "rejected": "🛑 REJECTED", "unknown": "❔ UNKNOWN"}
PURPOSE = {"regulatory": "Regulatory", "non_regulatory": "Non-regulatory",
           "impact": "Impact"}


def _dash(v):
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" else v


def _calc_version(r) -> str:
    """The calculator version, which is the engine version; for a run made
    before the two were one number, the calculator it named."""
    v = _dash(r.get("calculator_version"))
    if v != "—":
        lab = _dash(r.get("calculator_label"))
        return v if lab in ("—", v) else f"{v} ({lab})"
    eng = _dash(r.get("engine"))
    return eng.split()[-1] if eng != "—" else "—"


show = pd.DataFrame({
    "Status": runs["status"].map(lambda s: STATUS_ICON.get(s, str(s).upper())),
    "Run": runs["run_id"],
    "Run date": runs["started_at"].fillna("").astype(str).str[:16].str.replace("T", " "),
    "Purpose": runs["run_purpose"].map(lambda p: PURPOSE.get(p, _dash(p))),
    "Type": runs["run_type"].map(lambda x: str(x).capitalize() if x else "—"),
    "Scenario": runs["ecl_scenario"].map(lambda s: "Weighted" if s in (None, "weighted") else s),
    "Portfolio date": runs["portfolio_date"].map(_dash),
    "Run by": runs["user"].map(_dash),
    "Approver": runs["approver"].map(_dash),
    "Config version": runs["config_version"].map(
        lambda v: "(live config)" if _dash(v) == "—" else v),
    "Calculator version": runs.apply(_calc_version, axis=1),
    "Outputs": runs["n_outputs"],
    "Validation fails": runs["n_validation_failures"],
    "Readiness": runs["has_readiness"].map({True: "yes", False: "—"}),
})
c_f, _, c_r = st.columns([1, 5, 1], vertical_alignment="bottom")
show = column_filters(show, "runs_f", where=c_f)
if c_r.button("Refresh", icon=":material/refresh:", width="stretch"):
    api.clear()
    st.rerun()
STATUS_COLOURS = {"APPROVED": ("#ecfdf3", "#067647"), "PENDING": ("#fffaeb", "#b54708"),
                  "REJECTED": ("#fef3f2", "#b42318"), "UNOFFICIAL": ("#eff8ff", "#175cd3")}


def _status_style(v):
    for k, (bg, fg) in STATUS_COLOURS.items():
        if k in str(v):
            return f"background-color: {bg}; color: {fg}; font-weight: 600"
    return ""


ev = st.dataframe(show.style.map(_status_style, subset=["Status"]),
                  hide_index=True, width="stretch",
                  height=min(420, 38 + 35 * max(len(show), 1)),
                  on_select="rerun", selection_mode="single-row", key="runs_tbl",
                  column_config={
                      "Outputs": st.column_config.NumberColumn(format="%d"),
                      "Validation fails": st.column_config.NumberColumn(format="%d")})
sel = ev.selection.rows if ev and ev.selection else []
if not sel:
    caption("Select a run above to see its manifest, validation, readiness, "
            "overrides and outputs.")
    st.stop()

run = runs.loc[show.index[sel[0]]]
run_id = run["run_id"]
status = run["status"] or "unknown"

st.markdown(f'<div class="pg-head" style="margin-top:.6rem"><div class="pg-title" '
            f'style="font-size:1.15rem">Run {run_id}</div>'
            f"{pill(status.replace('_', ' ').upper(), STATUS_TONE.get(status, 'info'))}"
            "</div>", unsafe_allow_html=True)
caption(f"`{run['path']}`")

# ---- export -------------------------------------------------------------
c_exp, c_ovl = st.columns(2)
with c_exp:
    with st.container(border=True):
        st.markdown("**Export**")
        with guard():
            gate = api.run_export_status(run_id)
        if not gate["exportable"]:
            st.info(f"**Export not available.** {gate['reason']}", icon="🔒")
        else:
            if gate["unofficial"]:
                st.info("**Unofficial run.** The export bundle is marked UNOFFICIAL.",
                        icon="ℹ️")
            inc = st.checkbox("Include input files (~30-80 MB extra)", value=True,
                              key=f"inc_{run_id}")
            if st.button("Build run package (zip)", key=f"exp_{run_id}"):
                with st.spinner("Building run package…"):
                    with guard():
                        res = api.run_export(run_id, inc)
                st.session_state[f"zip_{run_id}"] = res
            res = st.session_state.get(f"zip_{run_id}")
            if res:
                st.success(f"Exported {res['files']} files "
                           f"({res['bytes'] / 1e6:.1f} MB)", icon="✅")
                try:
                    data = api.run_export_bytes(run_id)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    st.download_button("Download ifrs9_run_%s.zip" % run_id, data,
                                       file_name=f"ifrs9_run_{run_id}.zip",
                                       mime="application/zip", type="primary")
                if res.get("skipped"):
                    caption("Not present: " + ", ".join(res["skipped"]))

# ---- apply a management overlay to this run ------------------------------
with c_ovl:
    with st.container(border=True):
        st.markdown("**Management overlay**")
        official = str(run.get("run_type") or "") == "official"
        caption("Check an overlay's impact on this run, then apply it. The model "
                "report is kept and the overlaid report written beside it. To "
                "correct an applied overlay, remove it below and apply the "
                "corrected one. "
                + ("An official run takes approved overlays only." if official else
                   "An unofficial run takes tested or approved overlays."))
        with guard():
            bundles = api.overlay_bundles()["bundles"]
        usable = ("approved",) if official else ("tested", "approved")
        status = {b["id"]: (b.get("status") or "draft") for b in bundles
                  if (b.get("status") or "draft") in usable}
        pick = st.selectbox("Overlay", list(status), index=None,
                            placeholder="Select an overlay" if status else
                            "No overlay can be applied to this run yet",
                            format_func=lambda i: f"{i} [{status[i].upper()}]",
                            label_visibility="collapsed", key=f"ovp_{run_id}")
        chk_key = f"ovchk_{run_id}"
        if pick:
            if status[pick] != "approved":
                st.warning(f"{pick} is tested, not yet approved: fine for this "
                           "unofficial run; an official run needs it approved.",
                           icon="⚠️")
            c1, c2 = st.columns(2)
            if c1.button("Check impact", key=f"ovc_{run_id}", width="stretch",
                         icon=":material/science:"):
                with guard():
                    pv = api.preview_bundle(pick, run_id)
                st.session_state[chk_key] = (pick, pv)
            chk = st.session_state.get(chk_key)
            checked = bool(chk and chk[0] == pick)
            ok = overlay_impact(chk[1]) if checked else False
            if c2.button("Apply", type="primary", key=f"ova_{run_id}",
                         width="stretch", disabled=not ok,
                         help=None if ok else "Check the impact first."):
                try:
                    r = api.apply_bundle(pick, run_id)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    if not r.get("ok"):
                        st.error("Not applied: " + "; ".join(r.get("errors", [])),
                                 icon="⚠️")
                    else:
                        tt = r["totals"]
                        st.session_state.pop(chk_key, None)
                        api.clear()
                        flash(f"{pick} [{(r.get('status') or 'draft').upper()}] "
                              f"applied: model {money(tt['model'])} + overlay "
                              f"{money(tt['overlay'])} = {money(tt['final'])}.")
                        st.rerun()
        st.markdown("**Overlays applied to this run**")
        with guard():
            ap = api.applied_overlays(run_id)["applied"]
        if not ap:
            caption("None applied yet. Applying one writes a report alongside the "
                    "model report.")
        for a in ap:
            ca, cb = st.columns([4, 1])
            ca.markdown(f"**{a['overlay_id']}** — {a['report_file']} · applied "
                        f"{a['applied_at']}")
            with cb.popover("Remove"):
                st.write(f"Remove the overlaid output for '{a['overlay_id']}'? The "
                         "model report and everything else are untouched.")
                if st.button("Remove", type="primary", key=f"rm_{run_id}_{a['overlay_id']}"):
                    try:
                        api.remove_applied_overlay(run_id, a["overlay_id"])
                    except api.BackendError as e:
                        st.error(str(e))
                    else:
                        api.clear()
                        st.rerun()

# ---- detail tabs --------------------------------------------------------
t_man, t_val, t_rdy, t_ov, t_out = st.tabs(
    ["Manifest", "Validation", "Readiness", "Overrides", "Outputs"])

with t_man:
    with guard():
        m = api.run_manifest(run_id)
    if not m.get("exists"):
        st.info("No manifest.json found.")
    else:
        s = m["summary"]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Run**")
            dur = s.get("duration_seconds")
            st.table(pd.DataFrame([
                ("run_id", s.get("run_id")), ("started_at", s.get("started_at")),
                ("finished_at", s.get("finished_at")),
                ("duration", f"{dur:.1f} s" if isinstance(dur, (int, float)) else "—"),
                ("user", s.get("user")), ("hostname", s.get("hostname")),
                ("code_sha", s.get("code_sha")), ("engine", s.get("engine_detail")),
            ], columns=["field", "value"]).fillna("—").set_index("field"))
        with c2:
            st.markdown("**Run metadata**")
            st.table(pd.DataFrame([
                ("run type", s.get("run_type")), ("purpose", s.get("run_purpose")),
                ("ECL basis", s.get("ecl_scenario")),
                ("portfolio date", s.get("portfolio_date")),
                ("config version", s.get("config_version") or "(live config)"),
                ("calculator", s.get("calculator_label") or s.get("calculator_version")),
                ("calculator fingerprint", (s.get("calculator_code_hash") or "")[:16]),
                ("matches registered", s.get("calculator_matches_registered")),
            ], columns=["field", "value"]).astype(str).replace("None", "—")
                .set_index("field"))
            snap = m.get("snapshot")
            if snap:
                st.markdown(f"**Version** {snap.get('label')} "
                            f"{pill(snap.get('status') or '?', 'ok' if snap.get('status') == 'approved' else 'info')}",
                            unsafe_allow_html=True)
                caption(f"code sha at creation: `{snap.get('code_sha_at_creation') or '—'}`")
            else:
                caption("No version — the run used the live config.")
        src = m.get("input_source")
        if src:
            st.markdown(f"**Input source:** {src.get('kind')} — "
                        f"`{(src.get('details') or {}).get('path', '')}`")
        st.markdown("**Inputs**")
        if m["inputs"]:
            st.dataframe(pd.DataFrame(m["inputs"]), hide_index=True,
                         use_container_width=True)
        else:
            caption("(none recorded)")
        if m.get("messages"):
            with st.expander("Run log"):
                st.code("\n".join(m["messages"]), language=None)

with t_val:
    with guard():
        v = api.run_validation_table(run_id)
    if not v["exists"]:
        st.info("No validation report for this run.")
    else:
        c = v["counts"]
        kpis([("Checks", money(c["checks"]), "plum", ""),
              ("Passed", money(c["passed"]), "ok", ""),
              ("Errors", money(c["errors"]), "err" if c["errors"] else "ok", ""),
              ("Warnings", money(c["warnings"]), "warn" if c["warnings"] else "ok", ""),
              ("Accepted", money(c["suppressed"]), "plum" if c["suppressed"] else "",
               "listed below, with the reasons")])
        with guard():
            acc = api.run_accepted_findings(run_id)
        if acc.get("rows"):
            st.markdown(f"**Accepted findings · {len(acc['rows'])}** — accepted for "
                        "this run, or by a standing suppression that took effect")
            accepted_findings_table(acc["rows"])
        vf = pd.DataFrame(v["rows"])
        vf = column_filters(vf, f"vq_{run_id}", where=st.columns([1, 6])[0])
        st.dataframe(style_severity(vf), hide_index=True, width="stretch", height=460,
                     column_config={"message": st.column_config.TextColumn(width="large"),
                                    "description": st.column_config.TextColumn(width="medium")})
        caption("The Validation page lists these as readable findings, with why "
                "each matters and what to do.")

with t_rdy:
    with guard():
        rd = api.run_readiness(run_id)
    if not rd.get("exists"):
        st.info("This run has no readiness report (runs made before the "
                "readiness check was added do not).")
    else:
        s = rd["summary"]
        n_no, n_blank = s["No ECL"]["contracts"], s["Blank in LIC"]["contracts"]
        kpis([("Contracts", money(s["contracts"]), "plum", ""),
              ("Priced", money(s["Priced"]["contracts"]), "ok", ""),
              ("Priced — check", money(s["Priced - check"]["contracts"]),
               "warn" if s["Priced - check"]["contracts"] else "", ""),
              ("Blank in LIC", money(n_blank), "err" if n_blank else "ok", ""),
              ("No ECL", money(n_no), "err" if n_no else "ok", "")])
        if n_no or n_blank:
            callout("err", f"{n_no} contract(s) get no ECL and {n_blank} would be "
                    "blank in LIC.", title="Not every contract has a number.")
        if rd["reasons"]:
            st.markdown("**Why**")
            st.dataframe(style_severity(pd.DataFrame(rd["reasons"])[
                ["severity", "check", "contracts", "exposure", "text", "fix"]]),
                hide_index=True, width="stretch",
                column_config={"exposure": st.column_config.NumberColumn(format="%,.0f"),
                               "text": st.column_config.TextColumn("what it does", width="large"),
                               "fix": st.column_config.TextColumn("what to do", width="large")})
        st.markdown("**Row funnel** — rows in, rows out, per file")
        st.dataframe(pd.DataFrame(rd["funnel"]), hide_index=True,
                     use_container_width=True)
        st.markdown(f"**Contracts with a gap** ({rd['n_flagged']:,})")
        st.dataframe(pd.DataFrame(rd["flagged"]), hide_index=True,
                     use_container_width=True, height=320)

with t_ov:
    with guard():
        o = api.run_overrides(run_id)
    if not o["exists"]:
        caption("No overrides directory for this run (runs made outside the "
                "phased workflow do not record overrides).")
    for f in o["files"]:
        st.markdown(f"**{f['file']}**")
        if not f["readable"]:
            caption("(could not read file)")
        elif not f["rows"]:
            caption("(none applied)")
        else:
            st.dataframe(pd.DataFrame(f["rows"]), hide_index=True,
                         use_container_width=True)

with t_out:
    with guard():
        outs = api.run_outputs(run_id)["files"]
    if not outs:
        st.info("No output files found.")
    else:
        names = [f["file"] for f in outs]
        main = "FinalEclReport.csv"
        c1, c2 = st.columns([2, 3])
        pick = c1.selectbox("File", names, key=f"of_{run_id}",
                            index=names.index(main) if main in names else 0)
        fq = c2.text_input("Find (contract, customer, any value)", key=f"oq_{run_id}")
        with guard():
            head = api.run_output_preview(run_id, pick, offset=0, limit=1)
        c3, c4, c5 = st.columns([3, 1, 1], vertical_alignment="bottom")
        srt = c3.selectbox("Sort by", head["columns"], index=None,
                           placeholder="File order", key=f"os_{run_id}_{pick}")
        desc = c4.toggle("Largest first", value=True, key=f"od_{run_id}_{pick}")
        page = c5.number_input("Page", min_value=1, value=1, step=1,
                               key=f"op_{run_id}")
        with guard():
            pv = api.run_output_preview(run_id, pick, offset=(page - 1) * 200,
                                        limit=200, q=fq or None, sort=srt,
                                        desc=desc)
        caption(f"{pv['lines']:,} rows"
                + (" (the first 500,000 read)" if pv["truncated"] else "")
                + f" · {pv['total']:,} match · showing "
                  f"{pv['offset'] + 1 if pv['total'] else 0}–"
                  f"{min(pv['offset'] + 200, pv['total'])}"
                + (f" · sorted by {pv['sort']}, "
                   f"{'largest' if pv['desc'] else 'smallest'} first, over the "
                   "whole file" if pv["sort"] else "")
                + f" · `{pv['path']}`")
        st.dataframe(pd.DataFrame(pv["rows"], columns=pv["columns"]),
                     hide_index=True, use_container_width=True, height=440,
                     column_config={c: st.column_config.NumberColumn(format="%,.2f")
                                    for c in pv.get("numeric", [])
                                    if any(w in c.lower() for w in
                                           ("amount", "balance", "bal", "ead",
                                            "exposure", "value", "ecl"))
                                    and not any(w in c.lower() for w in
                                                ("pd", "lgd", "rate"))})
