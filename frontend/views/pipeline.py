"""Run the pipeline: the R app's phased workflow, step by step.

    1  Input source    configured folder, a data-drop folder, or a zip upload;
                       Validate inputs checks the bundle and previews every
                       INPUT finding
    2  Configuration   config version, run type and purpose, calculator,
                       portfolio date
    3  Pre-run check   the INPUT validators AND the pricing-readiness dry run:
                       which contracts would get no ECL, which LIC would leave
                       blank, which are priced from incomplete inputs --
                       before anything is committed
    4  Phase 1         the run pauses with the customer view for review
    5  Overrides       rating, stage (worsening only), restructuring; a reason
                       each
    6  Phase 2         the run finishes and lands pending approval (official)
                       or unofficial
"""
import time
from datetime import date

import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pill

page_setup("Run the pipeline",
           "Pick the inputs and a config version, run the pre-run check, then "
           "start. The run pauses after the customer-level view is computed so "
           "overrides can be recorded, then finishes and lands pending approval "
           "(official) or unofficial.")

S = st.session_state
S.setdefault("wf_state", "idle")          # idle | paused | done


def _poll(job_id: str, label: str) -> dict:
    """Wait for a background job, showing its progress."""
    bar = st.progress(0.02, text=label)
    t0 = time.time()
    while True:
        try:
            j = api.wf_job(job_id)
        except api.BackendError as e:
            bar.empty()
            st.error(str(e))
            st.stop()
        el = time.time() - t0
        bar.progress(min(0.95, 0.02 + el / 90), text=f"{j.get('message', label)} "
                                                     f"({el:.0f}s)")
        if j["status"] in ("done", "failed"):
            bar.empty()
            return j
        time.sleep(1.0)


def _sev_pill(s: str) -> str:
    return pill(s, {"ERROR": "err", "WARN": "warn", "INFO": "info",
                    "PASS": "ok"}.get(str(s).upper(), "info"))


def _reset_prerun():
    for k in ("wf_pre", "wf_ready"):
        S.pop(k, None)


# ======================================================== paused / done ====
def _paused_page(run_id: str):
    with guard():
        ps = api.wf_paused_run(run_id)
    st.subheader(f"Run {run_id} — paused for review")
    metric_row([("Customers", money(ps["customers"])),
                ("Investments", money(ps["investments"])),
                ("Validation findings so far", money(ps["findings"])),
                ("Run type", ps["run_type"]),
                ("Pending overrides", money(sum(ps["pending"].values())))])
    caption("Below is the calculated customer-level view. Select a customer to "
            "add an override for its rating, stage or restructuring — each needs "
            "a reason. When done, Continue finishes the run with them applied.")

    c1, c2, c3 = st.columns([3, 1, 1])
    q = c1.text_input("Find a customer (id or name)", key="cv_q")
    stage = c2.selectbox("Stage", ["(all)", "Stage 1", "Stage 2", "Stage 3"],
                         key="cv_stage")
    page = c3.number_input("Page", min_value=1, value=1, key="cv_page")
    with guard():
        cv = api.wf_customers(run_id, q=q or None,
                              stage=None if stage.startswith("(") else stage,
                              offset=(page - 1) * 50, limit=50)
    df = pd.DataFrame(cv["rows"])
    caption(f"{cv['total']:,} customers match · page {page} of "
            f"{max(1, -(-cv['total'] // 50))} · largest exposure first")
    ev = st.dataframe(df, hide_index=True, use_container_width=True, height=330,
                      on_select="rerun", selection_mode="single-row", key="cv_tbl",
                      column_config={
                          "customer_id": "Customer", "customer_name": "Name",
                          "rating_final": "Rating", "stage_final": "Stage",
                          "restructuring_final": "Restructuring",
                          "watchlist_status": "Watchlist",
                          "exposure_total": st.column_config.NumberColumn(
                              "Exposure", format="%,.0f"),
                          "dpd_status": st.column_config.NumberColumn(
                              "Worst DPD", format="%d")})
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**Add override**")
            rows = ev.selection.rows if ev and ev.selection else []
            if not rows:
                caption("Select a customer above to add overrides.")
            else:
                cid = str(df.iloc[rows[0]]["customer_id"])
                with guard():
                    info = api.wf_customer(run_id, cid)
                c, ch = info["customer"], info["choices"]
                st.markdown(f"Override for customer **{cid}** — "
                            f"{c.get('customer_name') or ''}")
                st.table(pd.DataFrame({
                    "calculated": [c.get("rating_final") or "—",
                                   c.get("stage_final") or "—",
                                   c.get("restructuring_final") or "Not Restructured"]},
                    index=["rating", "stage", "restructuring"]))
                with st.form(f"ov_{cid}", clear_on_submit=True):
                    a, b, d = st.columns(3)
                    r_val = a.selectbox("Override rating", ["(no change)"] + ch["rating"])
                    s_val = b.selectbox("Override stage", ["(no change)"] + ch["stage"])
                    x_val = d.selectbox("Override restructuring",
                                        ["(no change)"] + ch["restructuring"])
                    if c.get("stage_final") == "Stage 3":
                        caption("Stage 3 cannot be overridden — it is already the "
                                "worst stage.")
                    reason = st.text_area("Reason (required)", height=70,
                                          placeholder="e.g. credit committee "
                                                      "decision 2026-Q2, ticket #...")
                    who = st.text_input("Your name", value="")
                    if st.form_submit_button("Add override", type="primary"):
                        payload = {"customer_id": cid, "reason": reason, "by": who,
                                   "rating": None if r_val.startswith("(") else r_val,
                                   "stage": None if s_val.startswith("(") else s_val,
                                   "restructuring": None if x_val.startswith("(") else x_val}
                        try:
                            api.wf_add_override(run_id, payload)
                        except api.BackendError as e:
                            st.error(str(e))
                        else:
                            st.success(f"Override added for {cid}")
    with right:
        with st.container(border=True):
            with guard():
                po = api.wf_overrides(run_id)
            n = po["counts"]
            st.markdown(f"**Pending overrides:** rating={n['rating']}, "
                        f"stage={n['stage']}, restructuring={n['restructuring']}")
            for kind, label in (("rating", "Rating overrides"),
                                ("stage", "Stage overrides"),
                                ("restructuring", "Restructuring overrides")):
                items = po["overrides"][kind]
                if not items:
                    continue
                st.markdown(f"*{label}*")
                st.dataframe(pd.DataFrame(items)[["customer_id", "prior_value", "value",
                                                  "reason", "created_by"]],
                             hide_index=True, use_container_width=True)
                drop = st.selectbox(f"Remove a {kind} override",
                                    ["(keep all)"] + [i["customer_id"] for i in items],
                                    key=f"drop_{kind}")
                if not drop.startswith("(") and st.button(f"Remove {kind} override "
                                                          f"for {drop}", key=f"db_{kind}"):
                    with guard():
                        api.wf_drop_override(run_id, kind, drop)
                    st.rerun()

    st.divider()
    b1, b2, _ = st.columns([2, 1, 3])
    if b1.button("Continue (apply overrides + finish)", type="primary",
                 use_container_width=True):
        with guard():
            job = api.wf_continue(run_id)
        j = _poll(job["job_id"], "Phase 2: curves, readiness, pricing…")
        S["wf_done"] = j
        S["wf_state"] = "done"
        api.clear()
        st.rerun()
    with b2.popover("Cancel run", use_container_width=True):
        st.write("Abandon this run? Its partial folder is removed and nothing "
                 "is priced.")
        if st.button("Cancel the run", type="primary"):
            with guard():
                api.wf_cancel(run_id)
            S["wf_state"] = "idle"
            S.pop("wf_run_id", None)
            st.rerun()


def _done_page():
    j = S.get("wf_done") or {}
    res = j.get("result") or {}
    if j.get("status") == "failed" or not res.get("ok"):
        st.error(res.get("error") or j.get("message") or "The run failed.", icon="🛑")
        if res.get("steps"):
            st.dataframe(pd.DataFrame(res["steps"])[["step", "ok", "detail"]],
                         hide_index=True, use_container_width=True)
        if res.get("traceback") or j.get("traceback"):
            with st.expander("Technical detail"):
                st.code(res.get("traceback") or j.get("traceback"), language=None)
    else:
        official = res.get("run_type") == "official"
        st.subheader(f"Run {res['run_id']} complete — "
                     + ("pending approval" if official
                        else "unofficial (auto-approved)"))
        ov = res.get("overrides_applied") or {}
        metric_row([("Duration", f"{res.get('seconds', 0):.1f}s"),
                    ("Outputs", money(len(res.get("written") or []))),
                    ("Overrides applied", money(sum(int(v or 0) for v in ov.values()))),
                    ("Rating / stage / restr.",
                     f"{ov.get('rating', 0)} / {ov.get('stage', 0)} / "
                     f"{ov.get('restructuring', 0)}")])
        caption(f"Path: `{res.get('run_dir')}`"
                + (" · produced by the archived calculator code" if res.get("archived")
                   else ""))
        if res.get("dropped_args"):
            st.warning("The archived calculator does not support: "
                       + ", ".join(res["dropped_args"])
                       + ". The run was produced without them.", icon="⚠️")
        rd = res.get("readiness")
        if rd:
            metric_row([("Contracts", money(rd.get("contracts"))),
                        ("No ECL", money((rd.get("No ECL") or {}).get("contracts"))),
                        ("Blank in LIC", money((rd.get("Blank in LIC") or {}).get("contracts"))),
                        ("Priced — check", money((rd.get("Priced - check") or {}).get("contracts")))])
        st.dataframe(pd.DataFrame(res.get("steps") or [])[["step", "ok", "detail"]],
                     hide_index=True, use_container_width=True)
        if official:
            st.info("Visit **Approval** to approve or reject this run, or **Runs** "
                    "to view its manifest, validation, readiness and outputs.",
                    icon="👉")
        else:
            st.info("This was an unofficial run — no approval needed. Open **Runs** "
                    "to view its manifest, validation, readiness and outputs.",
                    icon="👉")
    if st.button("Start another run", type="primary"):
        for k in ("wf_done", "wf_run_id", "wf_val", "wf_pre", "wf_ready"):
            S.pop(k, None)
        S["wf_state"] = "idle"
        st.rerun()


if S["wf_state"] == "paused" and S.get("wf_run_id"):
    _paused_page(S["wf_run_id"])
    st.stop()
if S["wf_state"] == "done":
    _done_page()
    st.stop()

# A run paused in an earlier browser session is still held by the backend.
try:
    held = api.wf_paused()
except api.BackendError:
    held = []
if held:
    with st.container(border=True):
        st.markdown(f"**{len(held)} run(s) paused for review**")
        for h in held:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"`{h['run_id']}` · {h['run_type']} · started {h['started']} "
                        f"by {h['user']} · {h['customers']:,} customers")
            if c2.button("Resume", key=f"res_{h['run_id']}"):
                S["wf_state"], S["wf_run_id"] = "paused", h["run_id"]
                st.rerun()

# =============================================================== idle ====
with guard():
    src = api.wf_sources()
    vers = api.wf_versions()
    calcs = api.wf_calculators()

# ---- 1. input source ------------------------------------------------------
with st.container(border=True):
    st.markdown("#### 1. Input source")
    caption("Pick where the 12 input files come from and validate the choice. "
            "The pre-run check stays disabled until the input validation passes.")
    kinds = {"Use the configured input directory": "configured",
             "Pick a folder from the data drop": "drop_folder",
             "Upload a zip from my computer": "upload",
             "A folder on the server": "folder"}
    kind_label = st.radio("Input source", list(kinds), label_visibility="collapsed",
                          key="wf_kind", on_change=lambda: S.pop("wf_val", None))
    kind = kinds[kind_label]
    body = {"kind": kind}
    if kind == "configured":
        caption(f"Reads from `{src['configured_dir']}`"
                + ("" if src["configured_exists"] else " — **that folder does not exist**"))
    elif kind == "drop_folder":
        if not src["drops"]:
            st.warning(f"No data drop folders found at `{src['drop_root'] or '(unset)'}`. "
                       "Set `paths.data_drop_root` in config.yml to the data team's "
                       "drop folder, or use the configured directory or a zip upload.")
        else:
            labels = {f"{d['name']} — {d['n_files']} files "
                      f"({'complete' if d['looks_complete'] else 'INCOMPLETE'})": d["path"]
                      for d in src["drops"]}
            pick = st.selectbox("Pick a drop folder", list(labels), key="wf_drop",
                                on_change=lambda: S.pop("wf_val", None))
            body["path"] = labels[pick]
            caption(f"Listing the folders under `{src['drop_root']}`, newest first.")
    elif kind == "upload":
        up = st.file_uploader("Choose a zip file", type=["zip"], key="wf_zip")
        caption(f"Upload limit: {src['upload_limit_mb']} MB. The zip should hold "
                "the 12 input files at the top level or inside one folder (e.g. "
                "`Input/AccountMaster.xlsx`). Each file may be Excel (.xlsx) or "
                "Oracle SQL*Plus HTML (.xls) — the format is detected from the "
                "bytes. Raise the limit with `run.max_upload_size_mb` in config.yml.")
        if up is not None:
            key = f"{up.name}:{up.size}"
            if S.get("wf_zip_key") != key:
                with st.spinner("Uploading and unpacking…"):
                    with guard():
                        S["wf_zip_res"] = api.wf_upload_zip(up)
                S["wf_zip_key"] = key
                S.pop("wf_val", None)
            z = S.get("wf_zip_res") or {}
            body.update({"path": z.get("path"), "source_zip": z.get("source_zip"),
                         "extracted_at": z.get("extracted_at")})
            caption(f"Unpacked to `{z.get('path')}`")
    else:
        body["path"] = st.text_input("Folder on the backend machine", key="wf_folder",
                                     on_change=lambda: S.pop("wf_val", None))

    version_pick = S.get("wf_version", vers["default_pick"])
    if st.button("Validate inputs", icon=":material/check_circle:"):
        body["version"] = version_pick
        with st.spinner("Validating inputs and checking data quality…"):
            with guard():
                S["wf_val"] = api.wf_validate_inputs(body)
        _reset_prerun()
        if S["wf_val"].get("extract_date"):
            # The widget's own key: a keyed date_input ignores a changed
            # default, so the extract date is written straight into its state
            # (allowed here, before the widget is drawn in this run).
            S["wf_pdate_in"] = date.fromisoformat(S["wf_val"]["extract_date"])

    val = S.get("wf_val")
    if val is None:
        caption("Click **Validate inputs** to enable the pre-run check.")
    else:
        if val["ok"]:
            st.markdown(pill(f"All {val['n_pass']} checks passed", "ok"),
                        unsafe_allow_html=True)
        else:
            st.markdown(pill(f"{val['n_fail']} FAIL, {val['n_pass']} PASS — "
                             "Pre-run check disabled", "err"), unsafe_allow_html=True)
            fails = pd.DataFrame(val["structural"])
            fails = fails[fails["status"] == "FAIL"]
            st.markdown("**Failures:**\n" + "\n".join(
                f"- `{r['check']}` — {r['detail']}" for _, r in fails.iterrows()))
        strips = val.get("strip_log") or {}
        if sum(strips.values()):
            st.markdown(pill(f"Auto-fixed: removed {sum(strips.values())} repeated "
                             "header row(s)", "ok"), unsafe_allow_html=True)
            caption("Removed before validation from: " + ", ".join(
                f"{k} ({v})" for k, v in strips.items()) + ". They recur at the "
                "export's page interval and are stripped automatically.")
        dq = val.get("dq")
        if dq:
            findings = pd.DataFrame(dq["findings"])
            if findings.empty:
                st.markdown(pill("Data-quality checks: all clear", "ok"),
                            unsafe_allow_html=True)
            else:
                by = findings["effective_severity"].value_counts().to_dict()
                st.markdown(pill(f"Data-quality preview: {len(findings)} finding(s) ("
                                 + " · ".join(f"{k} {v}" for k, v in by.items()) + ")",
                                 "warn"), unsafe_allow_html=True)
                caption("Advisory — these do not block here. They are re-checked "
                        "in the pre-run check and during the run. Duplicates show "
                        "the offending rows so they can be fixed at source.")
                show = pd.DataFrame({
                    "severity": findings["effective_severity"],
                    "check": findings["id"], "context": findings["context"],
                    "detail": findings["message"].where(
                        findings["message"].astype(str) != "", findings["description"])
                    + findings["where"].map(lambda w: f" — {w}" if w else "")})
                st.dataframe(show, hide_index=True, use_container_width=True,
                             column_config={"detail": st.column_config.TextColumn(width="large")})
        if val.get("dq_error"):
            st.warning(f"The data-quality preview could not run: {val['dq_error']}")

# ---- 2. configuration / 3. pre-run -----------------------------------------
left, right = st.columns([1, 1])
with left:
    with st.container(border=True):
        st.markdown("#### 2. Configuration")
        vrows = vers["versions"]
        vlabels = {}
        for r in vrows:
            vlabels[f"{r['label']} [{r['status']}]{' · active' if r.get('active') else ''}"
                    f" — {str(r.get('description') or '')[:50]}"] = r["label"]
        default_label = "(default config)"
        opts = list(vlabels) + [default_label] if vers["active"] else \
            [default_label] + list(vlabels)
        cur = next((k for k, v in vlabels.items() if v == version_pick), default_label)
        vsel = st.selectbox("Config version", opts, index=opts.index(cur),
                            key="wf_vsel", on_change=_reset_prerun)
        version = vlabels.get(vsel, "__LIVE__")
        S["wf_version"] = version
        if version == "__LIVE__":
            caption("Default config: reads `config/` and `data-raw/static/` as they "
                    "currently sit on disk.")
        else:
            meta = next(r for r in vrows if r["label"] == version)
            st.markdown(f"status {pill(meta['status'], 'ok' if meta['status'] == 'approved' else 'info')}"
                        f" — {meta.get('description') or '—'}", unsafe_allow_html=True)

        rt_label = st.radio("Run type", ["Unofficial — for testing / what-if analysis",
                                         "Official — sanctioned deliverable (needs approved version)"],
                            key="wf_rt", on_change=_reset_prerun)
        run_type = "official" if rt_label.startswith("Official") else "unofficial"
        with guard():
            gate = api.wf_run_type_check(run_type, version)
        purposes = {p["label"]: p["id"] for p in gate["purposes"]}
        purpose = purposes[st.selectbox("Run purpose", list(purposes), key=f"wf_pp_{run_type}")]
        caption("Every run is priced on the probability-weighted PD curve and on "
                "each scenario. The weighted figure is the provision; the "
                "per-scenario files are written alongside it for analysis.")

        clabels = {"(active)": ""}
        for c in calcs["versions"]:
            clabels[f"{c['label']}{' — ACTIVE' if c.get('active') else ''}"] = c["id"]
        csel = st.selectbox("Calculator version", list(clabels), key="wf_calc")
        calc_id = clabels[csel]
        crow = next((c for c in calcs["versions"] if c["id"] == calc_id), None)
        act = calcs["active"] or {}
        if crow is None:
            st.markdown(f"Calculator {act.get('label') or act.get('id') or '(unregistered)'} · "
                        f"fingerprint `{(act.get('code_hash') or '?')[:10]}` "
                        + pill("runs the live deployed code", "ok"), unsafe_allow_html=True)
        else:
            st.markdown(f"Calculator {crow['label']} · fingerprint "
                        f"`{(crow.get('code_hash') or '?')[:10]}` "
                        + (pill("runs this version's archived code", "info")
                           if crow["runs_archived_code"]
                           else pill("runs the live deployed code", "ok")),
                        unsafe_allow_html=True)
        caption("ECL overlays are applied after the run, from the Runs page.")
        S.setdefault("wf_pdate_in", date.today())
        pdate = st.date_input("Portfolio (as-of) date", key="wf_pdate_in")
        caption("Filled from the inputs' EXTRACTDA when they are validated.")

        if gate["ok"]:
            (st.success if run_type == "official" else st.info)(gate["note"])
        else:
            st.warning(f"**Cannot start an Official run:** {gate['reason']}")

        val = S.get("wf_val")
        can_pre = bool(val and val["ok"])
        if st.button("Pre-run check", type="primary", disabled=not can_pre,
                     help=None if can_pre else "Validate inputs first",
                     icon=":material/search:"):
            payload = {"input_dir": val["input_dir"], "version": version,
                       "run_type": run_type}
            with st.spinner("Running the pre-run validators…"):
                with guard():
                    S["wf_pre"] = api.wf_pre_run_check(payload)
            with guard():
                job = api.wf_readiness(payload)
            S["wf_ready"] = _poll(job["job_id"],
                                  "Pricing readiness: building the LIC files…")
        pre, rdy = S.get("wf_pre"), S.get("wf_ready")
        rdy_res = (rdy or {}).get("result") or {}
        ready_err = [f for f in rdy_res.get("ready_findings") or []
                     if f.get("effective_severity") == "ERROR"]
        can_run = bool(pre and not pre["blocked"] and rdy
                       and rdy.get("status") == "done" and not ready_err and gate["ok"])
        start_label = "Start OFFICIAL run" if run_type == "official" else "Start unofficial run"
        if st.button(start_label, type="primary", disabled=not can_run,
                     icon=":material/play_arrow:"):
            payload = {"input_dir": val["input_dir"],
                       "input_source": val["input_source"], "version": version,
                       "run_type": run_type, "run_purpose": purpose,
                       "portfolio_date": pdate.isoformat(),
                       "calculator_version": calc_id or None}
            with guard():
                job = api.wf_start(payload)
            j = _poll(job["job_id"], "Phase 1: load + validate + transform…")
            res = j.get("result") or {}
            if j["status"] == "done" and res.get("paused"):
                S["wf_state"], S["wf_run_id"] = "paused", res["run_id"]
                st.rerun()
            else:
                S["wf_done"] = {"status": "failed",
                                "result": res.get("result") or {},
                                "message": j.get("message"),
                                "traceback": j.get("traceback")}
                S["wf_state"] = "done"
                st.rerun()
        if not can_run and pre:
            caption("Start stays disabled while the pre-run check or the readiness "
                    "check has an unsuppressed ERROR, or the run type is not allowed. "
                    "Fix at source, or accept a finding with a reason on "
                    "**Accepted findings**.")

with right:
    with st.container(border=True):
        st.markdown("#### 3. Pre-run findings")
        pre = S.get("wf_pre")
        if pre is None:
            caption("Click **Pre-run check** to run the input validators and the "
                    "pricing-readiness check.")
        else:
            tone, text = pre["pill"]
            st.markdown(pill(text, {"error": "err", "warn": "warn",
                                    "pass": "ok"}[tone]), unsafe_allow_html=True)
            fl = pd.DataFrame(pre["flagged"])
            if not fl.empty:
                st.dataframe(pd.DataFrame({
                    "severity": fl["effective_severity"] + fl["suppressed"].map(
                        lambda s: " (suppressed)" if s else ""),
                    "id": fl["id"], "context": fl["context"],
                    "finding": fl["message"].where(fl["message"].astype(str) != "",
                                                   fl["description"]),
                    "where": fl["where"]}), hide_index=True,
                    use_container_width=True, height=300,
                    column_config={"finding": st.column_config.TextColumn(width="large")})

        rdy = S.get("wf_ready")
        if rdy is not None:
            st.markdown("**Pricing readiness** — will every contract get an ECL?")
            if rdy.get("status") != "done":
                st.error(f"The readiness check failed: {rdy.get('message')}")
            else:
                rr = rdy["result"]
                p = rr.get("readiness") or {}
                if not p.get("exists"):
                    st.warning(rr.get("error") or "Readiness could not be assessed.")
                else:
                    s = p["summary"]
                    metric_row([("Contracts", money(s["contracts"])),
                                ("No ECL", money(s["No ECL"]["contracts"])),
                                ("Blank in LIC", money(s["Blank in LIC"]["contracts"])),
                                ("Priced — check", money(s["Priced - check"]["contracts"]))])
                    if s["No ECL"]["contracts"] or s["Blank in LIC"]["contracts"]:
                        st.error(f"{s['No ECL']['contracts']} contract(s) would get NO "
                                 f"ECL and {s['Blank in LIC']['contracts']} would come "
                                 "out BLANK in LIC. See the reasons below.", icon="🛑")
                    else:
                        st.success("Every contract will be priced.", icon="✅")
                    if rr.get("ready_findings"):
                        st.dataframe(pd.DataFrame(rr["ready_findings"])[
                            ["effective_severity", "id", "message"]],
                            hide_index=True, use_container_width=True,
                            column_config={"message": st.column_config.TextColumn(width="large")})
                    with st.expander("Reasons, fixes and the row funnel"):
                        if p["reasons"]:
                            st.dataframe(pd.DataFrame(p["reasons"])[
                                ["severity", "check", "contracts", "exposure", "text", "fix"]],
                                hide_index=True, use_container_width=True,
                                column_config={"exposure": st.column_config.NumberColumn(format="%,.0f")})
                        st.dataframe(pd.DataFrame(p["funnel"]), hide_index=True,
                                     use_container_width=True)
                    if p.get("flagged"):
                        with st.expander(f"Contracts with a gap ({p['n_flagged']:,})"):
                            st.dataframe(pd.DataFrame(p["flagged"]), hide_index=True,
                                         use_container_width=True, height=320)
