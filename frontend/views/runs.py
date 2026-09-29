"""Runs: every run, where it stands, and everything it recorded.

The R app's "Browse runs" page. The table carries each run's approval status
and health; selecting one shows its manifest, validation, pricing readiness,
overrides, reconciliation and output files, with the export (approved or
unofficial runs only) and the overlays applied to it.
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pill

page_setup("Runs")

c_top1, c_top2 = st.columns([6, 1])
if c_top2.button("Refresh", use_container_width=True):
    api.clear()
    st.rerun()

with guard():
    t = api.runs_table()

c_top1.caption(f"runs directory: `{t['runs_dir']}`  ·  exists: "
               f"{'yes' if t['exists'] else 'NO — set IFRS9_RUNS_DIR'}  ·  "
               f"{t['tiles']['total']} runs found")

tiles = t["tiles"]
metric_row([("Total runs", money(tiles["total"])),
            ("Approved", money(tiles["approved"])),
            ("Pending checker", money(tiles["pending_checker"])),
            ("Unofficial", money(tiles["unofficial"])),
            ("With validation fails", money(tiles["with_validation_fails"]))])

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
    "Config version": runs["config_version"].map(lambda v: v or "(live config)"),
    "Calculator": runs.apply(lambda r: r["calculator_label"] or r["calculator_version"]
                             or "—", axis=1),
    "Engine": runs["engine"].map(_dash),
    "Outputs": runs["n_outputs"],
    "Validation fails": runs["n_validation_failures"],
    "Recon": runs["has_reconciliation"].map({True: "yes", False: "no"}),
    "Readiness": runs["has_readiness"].map({True: "yes", False: "—"}),
})
q = st.text_input("Search runs", placeholder="run id, user, purpose, version…",
                  label_visibility="collapsed")
if q:
    mask = show.apply(lambda r: q.lower() in " ".join(map(str, r.values)).lower(),
                      axis=1)
    show = show[mask]
ev = st.dataframe(show, hide_index=True, use_container_width=True, height=360,
                  on_select="rerun", selection_mode="single-row", key="runs_tbl",
                  column_config={
                      "Outputs": st.column_config.NumberColumn(format="%d"),
                      "Validation fails": st.column_config.NumberColumn(format="%d")})
sel = ev.selection.rows if ev and ev.selection else []
if not sel:
    caption("Select a run above to see its manifest, validation, readiness, "
            "overrides, reconciliation and outputs.")
    st.stop()

run = runs.loc[show.index[sel[0]]]
run_id = run["run_id"]
status = run["status"] or "unknown"

st.markdown(f"### Run {run_id} &nbsp; {pill(status.replace('_', ' ').upper(), STATUS_TONE.get(status, 'info'))}",
            unsafe_allow_html=True)
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

# ---- apply an overlay to this run ---------------------------------------
with c_ovl:
    with st.container(border=True):
        st.markdown("**Apply ECL overlay to this run**")
        caption("Apply a saved overlay to this completed run without re-running "
                "the pipeline. The model report is preserved; a new overlaid "
                "report is written alongside it. To correct a wrong overlay, "
                "remove it below and apply the corrected one.")
        with guard():
            bundles = api.overlay_bundles()["bundles"]
        choices = {f"{b['id']} [{(b.get('status') or 'draft').upper()}]": b["id"]
                   for b in bundles}
        c1, c2 = st.columns([3, 1])
        pick = c1.selectbox("Overlay", ["(select an overlay)"] + list(choices),
                            label_visibility="collapsed", key=f"ovp_{run_id}")
        if c2.button("Apply overlay", type="primary", key=f"ova_{run_id}",
                     use_container_width=True):
            if pick.startswith("("):
                st.warning("Pick an overlay to apply.")
            else:
                try:
                    r = api.apply_bundle(choices[pick], run_id)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    if not r.get("ok"):
                        st.error("Conflict: " + "; ".join(r.get("errors", []))
                                 + ". Overlay not applied — resolve it on the "
                                   "Overlays page.", icon="⚠️")
                        if r.get("contracts"):
                            st.dataframe(pd.DataFrame({"contract": r["contracts"][:10]}),
                                         hide_index=True)
                    else:
                        tt = r["totals"]
                        st.success(
                            f"Overlay '{choices[pick]}' [{(r.get('status') or 'draft').upper()}] "
                            f"applied. Model {money(tt['model'])} → overlay "
                            f"+{money(tt['overlay'])} → final {money(tt['final'])} "
                            f"(+{100 * tt['overlay'] / max(tt['model'], 1):.2f}%).",
                            icon="✅")
                        api.clear()
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
t_man, t_val, t_rdy, t_ov, t_rec, t_out = st.tabs(
    ["Manifest", "Validation", "Readiness", "Overrides", "Reconciliation", "Outputs"])

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
        metric_row([("Checks", money(c["checks"])), ("Passed", money(c["passed"])),
                    ("Failed", money(c["failed"])), ("Errors", money(c["errors"])),
                    ("Warnings", money(c["warnings"])),
                    ("Suppressed", money(c["suppressed"]))])
        vf = pd.DataFrame(v["rows"])
        fq = st.text_input("Filter checks", key=f"vq_{run_id}",
                           placeholder="id, stage, message…")
        if fq:
            vf = vf[vf.apply(lambda r: fq.lower() in " ".join(map(str, r.values)).lower(),
                             axis=1)]
        st.dataframe(vf, hide_index=True, use_container_width=True, height=460,
                     column_config={"message": st.column_config.TextColumn(width="large"),
                                    "description": st.column_config.TextColumn(width="medium")})

with t_rdy:
    with guard():
        rd = api.run_readiness(run_id)
    if not rd.get("exists"):
        st.info("This run has no readiness report (runs made before the "
                "readiness check was added do not).")
    else:
        s = rd["summary"]
        metric_row([("Contracts", money(s["contracts"])),
                    ("No ECL", money(s["No ECL"]["contracts"])),
                    ("Blank in LIC", money(s["Blank in LIC"]["contracts"])),
                    ("Priced — check", money(s["Priced - check"]["contracts"])),
                    ("Priced", money(s["Priced"]["contracts"]))])
        if s["No ECL"]["contracts"] or s["Blank in LIC"]["contracts"]:
            st.error(f"{s['No ECL']['contracts']} contract(s) get no ECL and "
                     f"{s['Blank in LIC']['contracts']} would be BLANK in LIC.",
                     icon="🛑")
        if rd["reasons"]:
            st.markdown("**Why**")
            st.dataframe(pd.DataFrame(rd["reasons"])[
                ["severity", "check", "contracts", "exposure", "text", "fix"]],
                hide_index=True, use_container_width=True,
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

with t_rec:
    with guard():
        rc = api.run_reconciliation(run_id)
    if not rc.get("markdown"):
        caption("No reconciliation for this run. Configure "
                "`paths.reference_outputs` in config.yml to enable it, or use "
                "**Reconcile & export** to compare two runs.")
    else:
        st.markdown(rc["markdown"])
        st.markdown("**Mismatches**")
        if rc["mismatches"]:
            st.dataframe(pd.DataFrame(rc["mismatches"])[["file", "size_bytes"]],
                         hide_index=True)
        else:
            caption("(no mismatch CSVs)")

with t_out:
    with guard():
        outs = api.run_outputs(run_id)["files"]
    if not outs:
        st.info("No output CSVs found.")
    else:
        names = [f["file"] for f in outs]
        c1, c2, c3 = st.columns([2, 2, 1])
        pick = c1.selectbox("File", names, key=f"of_{run_id}")
        fq = c2.text_input("Find (contract, customer, any value)", key=f"oq_{run_id}")
        page = c3.number_input("Page", min_value=1, value=1, step=1,
                               key=f"op_{run_id}")
        with guard():
            pv = api.run_output_preview(run_id, pick, offset=(page - 1) * 200,
                                        limit=200, q=fq or None)
        caption(f"path: `{pv['path']}` · size {pv['size_kb']:,.1f} KB · "
                f"{pv['lines']:,} rows"
                + (" (first 20,000 searchable)" if pv["truncated"] else "")
                + f" · {pv['total']:,} match · showing "
                  f"{pv['offset'] + 1 if pv['total'] else 0}–"
                  f"{min(pv['offset'] + 200, pv['total'])}")
        st.dataframe(pd.DataFrame(pv["rows"], columns=pv["columns"]),
                     hide_index=True, use_container_width=True, height=440)
