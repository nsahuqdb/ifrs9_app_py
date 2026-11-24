"""Run the pipeline: the R app's phased workflow on one screen.

    1  Input extracts   a date (its folder under the daily inputs folder,
                        ifrs_inputs, read as saved) or the files uploaded
    2  Run settings     config version, run type and purpose, calculator,
                        portfolio date
    3  Check and start  one Check: the files are all there and readable, then
                        the pre-run validators AND the pricing-readiness dry
                        run -- which contracts would get no ECL, which LIC
                        would leave blank, which are priced from incomplete
                        inputs -- before anything is committed. The results
                        show the input findings first, then the pre-run
                        checks. A blocking
                        finding that can be accepted is accepted here, with a
                        reason, FOR THIS RUN ONLY -- recorded on the run, never
                        saved for the next one, which asks again -- and the
                        checks run again
    4  Review           the run pauses with the customer view: rating, stage
                        (worsening only) and restructuring overrides, a
                        reason each
    5  Finish           the run completes and lands pending approval
                        (official) or unofficial

What the user sets is on the left, what the checks found on the right, so the
answer to "can I start?" is always beside the button that starts.
"""
import time
from datetime import date, datetime

import pandas as pd
import streamlit as st

import api
from ui import (accepted_findings_table, accepted_note, callout, caption,
                card_header, empty_state, flash, guard, kpis, money,
                page_setup, pill, severity_counts, stepper, style_severity)

S = st.session_state
S.setdefault("wf_state", "idle")          # idle | paused | done

page_setup("Run the pipeline",
           "Load the input extracts, check they can be priced, then run. The "
           "run pauses for overrides before it finishes.")

KINDS = {"date": "Folder", "upload": "Upload"}

# =================================================================== jobs ====
# The checks and the two phases run as background jobs in the backend. A
# script run can be cut short while it waits for one -- another click, the
# dialog closing, a page change -- but the job carries on. So what the page is
# waiting for is kept in the session and picked up again by the next run,
# instead of being lost (which once left a stale readiness result on screen).
JOB_KEYS = ("wf_check_req", "wf_check_msg", "wf_ready_job", "wf_phase_req",
            "wf_phase_job")


def _clear_jobs():
    for k in JOB_KEYS:
        S.pop(k, None)


def _fail(e) -> None:
    """A backend error while starting or following a job: forget the job, so
    the page does not retry it on every click, and say what happened."""
    _clear_jobs()
    st.error(str(e))
    st.stop()


def _poll(job_id: str, label: str) -> dict:
    """Wait for a background job, showing its progress."""
    bar = st.progress(0.02, text=label)
    t0 = time.time()
    while True:
        try:
            j = api.wf_job(job_id)
        except api.BackendError as e:
            bar.empty()
            _fail(e)              # a restarted backend has forgotten its jobs
        el = time.time() - t0
        bar.progress(min(0.95, 0.02 + el / 90),
                     text=f"{j.get('message', label)} ({el:.0f}s)")
        if j["status"] in ("done", "failed"):
            bar.empty()
            return j
        time.sleep(1.0)


def _accepted_list() -> list[dict]:
    """The findings accepted for the run being prepared. They live in this
    session only: passed with each check and with Start, recorded on the run
    it starts, and gone after it -- the next run asks again."""
    return list((S.get("wf_accepted") or {}).values())


def _request_checks(req: dict, message: str | None = None) -> None:
    """Ask for the pre-run check and the readiness dry run; the next run of
    the page does them (see _resume_jobs)."""
    _reset_checks()
    req = {**req, "accepted_findings": _accepted_list()}
    S["wf_check_req"] = S["wf_last_req"] = req
    if message:
        S["wf_check_msg"] = message
    st.rerun()


def _resume_jobs() -> None:
    req = S.get("wf_check_req")
    if req:
        if S.get("wf_pre") is None:
            with st.spinner("Checking the inputs and the config…"):
                try:
                    S["wf_pre"] = api.wf_pre_run_check(req)
                except api.BackendError as e:
                    _fail(e)
            ext = S["wf_pre"].get("extract_date")
            if ext:
                # the portfolio date follows the extract's EXTRACTDA; set on
                # the next run, before the date widget is drawn
                try:
                    S["wf_pdate_next"] = date.fromisoformat(str(ext)[:10])
                except ValueError:
                    pass
        if not S.get("wf_ready_job"):
            try:
                S["wf_ready_job"] = api.wf_readiness(req)["job_id"]
            except api.BackendError as e:
                _fail(e)
        S["wf_ready"] = _poll(S["wf_ready_job"],
                              "Pricing readiness: building the LIC files…")
        msg = S.get("wf_check_msg")
        for k in ("wf_check_req", "wf_check_msg", "wf_ready_job"):
            S.pop(k, None)
        if msg:
            flash(msg)
        st.rerun()

    preq = S.get("wf_phase_req")
    if preq:
        first = preq["kind"] == "phase1"
        if not S.get("wf_phase_job"):
            try:
                S["wf_phase_job"] = (api.wf_start(preq["payload"]) if first
                                     else api.wf_continue(preq["run_id"]))["job_id"]
            except api.BackendError as e:
                _fail(e)
        j = _poll(S["wf_phase_job"], "Phase 1: load, validate, transform…" if first
                  else "Phase 2: curves, readiness, pricing…")
        for k in ("wf_phase_req", "wf_phase_job"):
            S.pop(k, None)
        res = j.get("result") or {}
        if first and j["status"] == "done" and res.get("paused"):
            S["wf_state"], S["wf_run_id"] = "paused", res["run_id"]
        elif first:
            S["wf_done"] = {"status": "failed", "result": res.get("result") or {},
                            "message": j.get("message"),
                            "traceback": j.get("traceback")}
            S["wf_state"] = "done"
        else:
            S["wf_done"] = j
            S["wf_state"] = "done"
            if res.get("ok"):
                S["run_id"] = preq["run_id"]      # the new run is the one on screen
            api.clear()
        st.rerun()


def _truthy(v) -> bool:
    return v in (True, 1, "True", "TRUE", "true")


def _sev(r: dict) -> str:
    """The severity a finding counts at: ACCEPTED once suppressed."""
    if _truthy(r.get("suppressed")):
        return "ACCEPTED"
    return str(r.get("effective_severity") or r.get("severity") or "INFO").upper()


def _nice(d) -> str:
    try:
        return date.fromisoformat(str(d)[:10]).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return "—"


def _reset_checks():
    """The inputs or the settings changed: earlier results no longer apply,
    and neither does a check still running for the old ones."""
    for k in ("wf_pre", "wf_ready", "wf_check_req", "wf_check_msg", "wf_ready_job"):
        S.pop(k, None)


def _reset_val():
    """Other inputs: another run being prepared, so nothing is accepted."""
    S.pop("wf_val", None)
    S.pop("wf_accepted", None)
    _reset_checks()


def _settings_changed():
    """Another config version or run type: another run being prepared."""
    S.pop("wf_accepted", None)
    _reset_checks()


def _check_rows() -> list[dict]:
    """Every finding of the pre-run check and of the readiness dry run, each
    accepted one with what accepted it."""
    rows = [dict(f) for f in (S.get("wf_pre") or {}).get("flagged") or []]
    res = (S.get("wf_ready") or {}).get("result") or {}
    for f in res.get("ready_findings") or []:
        rows.append({**f, "where": "Found by the pricing-readiness dry run"})
    for r in rows:
        if _truthy(r.get("suppressed")):
            r["accepted_note"] = accepted_note(r)
    return rows


def _blocking(rows) -> list[dict]:
    return [r for r in rows if _sev(r) == "ERROR"]


# ===================================================== accept a finding ====
@st.dialog("Accept for this run", width="large")
def _accept_dialog(rows: list[dict]) -> None:
    opts = {r["id"]: r for r in rows}
    caption("Accepted for **this run only**. The finding stays on the run's "
            "record, marked ACCEPTED with your reason, your name and the time — "
            "in its validation report, its list of accepted findings and the "
            "audit log — and no longer blocks this run. Nothing is kept for "
            "later runs: the next run asks again. Use it for a known source "
            "issue the run has to live with, not to get past a real error.")
    pick = st.multiselect(
        "Findings to accept", list(opts), default=list(opts),
        format_func=lambda i: f"{i} — {opts[i].get('description') or ''}"[:120])
    reason = st.text_area(
        "Reason (required)", height=90,
        placeholder="e.g. Repayment schedule dates carry two-digit years in the "
                    "source system; IT ticket #1234 raised. Accepted for this "
                    "quarter's run pending the re-extract.")
    who = st.text_input("Accepted by", value=S.get("_user") or "")
    if st.button("Accept for this run and re-check", type="primary",
                 disabled=not pick, icon=":material/verified:"):
        if not reason.strip():
            st.error("A reason is required: it goes on the run's record and the "
                     "audit trail.")
            return
        if not who.strip():
            st.error("Say who is accepting them.")
            return
        now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        acc = S.setdefault("wf_accepted", {})
        for vid in pick:
            acc[vid] = {"validator_id": vid, "reason": reason.strip(),
                        "accepted_by": who.strip(), "accepted_at": now}
        # The checks run again on the page, not in the dialog, with the request
        # the findings on screen came from; the message shows once they have.
        msg = (f"Accepted {len(pick)} finding(s) for this run, and ran the checks "
               "again. The next run will ask again.")
        if S.get("wf_last_req"):
            _request_checks(S["wf_last_req"], msg)
        flash(msg)
        st.rerun()


@st.dialog("Stop accepting these automatically", width="large")
def _remove_dialog(entries: list[dict]) -> None:
    opts = {e["validator_id"]: e for e in entries}
    caption("Each of these is a standing suppression in "
            "`validation_suppressions.yml`, which accepts its finding in **every** "
            "run, without asking, until it expires. Ending one stops that from "
            "today: the entry stays in the file with who ended it and why, and the "
            "audit log records it. The finding then blocks again, and each run "
            "asks whether to accept it, for that run only.")
    pick = st.multiselect(
        "Suppressions to end", list(opts), default=list(opts),
        format_func=lambda i: f"{i} — saved by {opts[i].get('approved_by') or '?'}"
                              f": {opts[i].get('reason') or ''}"[:140])
    reason = st.text_area("Reason (required)", height=70,
                          value="Accept findings run by run, not for every run.")
    who = st.text_input("Ended by", value=S.get("_user") or "")
    if st.button("End them and check again", type="primary", disabled=not pick,
                 icon=":material/block:"):
        if not reason.strip() or not who.strip():
            st.error("A reason and a name are required: they go on the audit trail.")
            return
        failed = []
        for vid in pick:
            try:
                api.remove_project_suppression(vid, reason.strip(), who.strip())
            except api.BackendError as e:
                failed.append(f"{vid}: {e}")
        if failed:
            st.error("Not ended: " + "; ".join(failed))
            return
        msg = (f"Ended {len(pick)} standing suppression(s). Those findings are no "
               "longer accepted automatically: each run asks.")
        _forget_standing(set(pick))
        if S.get("wf_pre") is not None and S.get("wf_last_req"):
            _request_checks(S["wf_last_req"], msg + " The checks ran again.")
        flash(msg)
        st.rerun()


def _forget_standing(ids: set) -> None:
    """Suppressions ended: the input preview drawn with them now reads as a
    fresh one would -- those findings no longer accepted, nor offered to end
    -- without reading the files again (ending one changes nothing else)."""
    dq = (S.get("wf_val") or {}).get("dq")
    if not dq:
        return
    for k in ("standing", "standing_other"):
        dq[k] = [e for e in dq.get(k) or [] if e["validator_id"] not in ids]
    for f in dq.get("findings") or []:
        if f.get("id") in ids and f.get("accepted_source") == "standing":
            f.update(suppressed=False, effective_severity=f.get("severity"),
                     accepted_source="", accepted_reason="", accepted_by="",
                     accepted_at="", valid_until="")


def _saved(e: dict) -> str:
    return (f"`{e['validator_id']}` — saved by {e.get('approved_by') or '?'}"
            + (f" on {_nice(e.get('approved_at'))}" if e.get("approved_at") else "")
            + (f", until {_nice(e.get('valid_until'))}" if e.get("valid_until") else "")
            + f": *{e.get('reason') or 'no reason given'}*")


def _standing_notice(entries: list[dict], can_remove: bool, key: str,
                     others: list[dict] | None = None) -> None:
    """Findings a standing suppression accepts: without asking, in every run.
    Said plainly -- the page otherwise asks run by run, and a suppression
    saved long ago (the earlier pipeline page saved its acceptances as
    these) is easy to forget -- with who saved each, when and why, and a way
    to end them where the page can. ``others`` are in force for checks not
    run yet (the input preview does not run the pre-run check's): named, and
    ended with the rest."""
    others = others or []
    if not entries and not others:
        return
    if entries:
        tone = "warn"
        title = f"{len(entries)} finding(s) accepted automatically, without asking."
        text = ("They are standing suppressions in `validation_suppressions.yml`, "
                "which apply to every run until they expire or are ended. (The "
                "earlier *Accept with a reason…* button saved its acceptances "
                "there.)")
        items = [_saved(e) for e in entries]
        if others:
            items += ["Also saved, for a check the pre-run check runs: " + _saved(e)
                      for e in others]
    else:
        tone = "muted"
        title = (f"{len(others)} standing suppression(s) in force for checks the "
                 "pre-run check runs.")
        text = ("If those checks fail, the findings are accepted automatically, "
                "without asking, in every run:")
        items = [_saved(e) for e in others]
    if not can_remove:
        callout(tone, text, title=title, items=items,
                after="They belong to this config version's frozen copy, so they "
                      "cannot be ended here.")
        return
    a, b = st.columns([4, 1.35], vertical_alignment="center")
    with a:
        callout(tone, text, title=title, items=items,
                after="End them, and each run asks whether to accept the "
                      "finding — for that run only.")
    if b.button("Stop auto-accepting…", icon=":material/block:",
                type="primary" if entries else "secondary", width="stretch",
                key=key):
        _remove_dialog(entries + others)


# ============================================================== stepper ====
def _stepper() -> None:
    state = S["wf_state"]
    if state == "paused":
        stepper([("Inputs", "done", "validated"), ("Checks", "done", "passed"),
                 ("Review & overrides", "now", "the run is waiting for you"),
                 ("Finish", "", "")])
        return
    if state == "done":
        j = S.get("wf_done") or {}
        bad = j.get("status") == "failed" or not (j.get("result") or {}).get("ok")
        stepper([("Inputs", "done", ""), ("Checks", "done", ""),
                 ("Review & overrides", "done", ""),
                 ("Finish", "err" if bad else "done",
                  "the run failed" if bad else "complete")])
        return
    val, pre, rdy = S.get("wf_val"), S.get("wf_pre"), S.get("wf_ready")
    if val is None:
        s1 = ("now", "choose the date or upload the files")
    elif val["ok"]:
        s1 = ("done", f"{_nice((pre or {}).get('extract_date'))} extract" if pre
              else "all files found")
    else:
        s1 = ("err", f"{val['n_fail']} problem(s) to fix")
    if not val or not val["ok"]:
        s2 = ("", "inputs, config and pricing dry run")
    elif pre is None or rdy is None:
        s2 = ("now", "inputs, config and pricing dry run")
    else:
        n = len(_blocking(_check_rows()))
        s2 = ("err", f"{n} error(s)") if n or rdy.get("status") != "done" \
            else ("done", "ready to start")
    s3 = ("now" if s2[0] == "done" else "", "start, then add overrides")
    stepper([("Inputs", *s1), ("Checks", *s2), ("Review & overrides", *s3),
             ("Finish", "", "approval, if official")])


# ================================================================ paused ====
def _paused_page(run_id: str) -> None:
    with guard():
        ps = api.wf_paused_run(run_id)
        po = api.wf_overrides(run_id)
    n = po["counts"]
    pending = sum(n.values())

    top = st.columns([6, 2, 1.2], vertical_alignment="center")
    with top[0]:
        callout("plum", "The customer-level view is computed. Record any "
                "rating, stage or restructuring overrides — each needs a reason "
                "— then continue to finish the run.",
                title=f"Run {run_id} is paused for your review.")
    go = top[1].button("Continue and finish" + (f" · {pending} override(s)"
                                                if pending else ""),
                       type="primary", icon=":material/play_arrow:", width="stretch")
    with top[2].popover("Cancel run", icon=":material/close:", width="stretch"):
        st.write("Abandon this run? Its partial folder is removed and nothing "
                 "is priced.")
        if st.button("Cancel the run", type="primary"):
            with guard():
                api.wf_cancel(run_id)
            S["wf_state"] = "idle"
            S.pop("wf_run_id", None)
            flash(f"Run {run_id} cancelled; its folder was removed.")
            st.rerun()
    if go:
        S["wf_phase_req"] = {"kind": "phase2", "run_id": run_id}
        st.rerun()

    kpis([("Customers", money(ps["customers"]), "plum", ""),
          ("Investment book", money(ps["investments"]), "plum", "banks and investments"),
          ("Findings so far", money(ps["findings"]),
           "warn" if ps["findings"] else "ok", "recorded on the run"),
          ("Run type", str(ps["run_type"]).capitalize(),
           "info" if ps["run_type"] == "official" else "", ""),
          ("Pending overrides", money(pending), "info" if pending else "",
           f"rating {n['rating']} · stage {n['stage']} · "
           f"restructuring {n['restructuring']}")])
    acc = ps.get("accepted") or []
    if acc:
        with st.expander(f"Findings accepted in this run so far · {len(acc)}"):
            accepted_findings_table(acc)

    left, right = st.columns([7, 5], gap="medium")
    with left, st.container(border=True):
        card_header("Customers", None,
                    right=pill("select one to override", "plum"))
        c1, c2, c3, c4 = st.columns([2.4, 2.4, 1.3, 0.9])
        q = c1.text_input("Find a customer", key="cv_q",
                          placeholder="customer id or name")
        books = S.get("cv_books") or []
        pf = c2.multiselect("Portfolio", books, key="cv_pf",
                            placeholder="every portfolio",
                            help="Customers with a contract in any portfolio picked. "
                                 "A customer in two books (a loan and a guarantee) "
                                 "shows under both.")
        stage = c3.selectbox("Stage", ["(all)", "Stage 1", "Stage 2", "Stage 3"],
                             key="cv_stage")
        page = c4.number_input("Page", min_value=1, value=1, key="cv_page")
        with guard():
            cv = api.wf_customers(run_id, q=q or None,
                                  stage=None if stage.startswith("(") else stage,
                                  offset=(page - 1) * 50, limit=50,
                                  portfolios=pf or None)
        if cv.get("portfolios") and cv["portfolios"] != books:
            # the list comes with the first answer; the picker is drawn
            # before it, so it is handed to the next rerun
            S["cv_books"] = cv["portfolios"]
            st.rerun()
        df = pd.DataFrame(cv["rows"])
        if "portfolios" in df.columns:
            lead = [c for c in ("customer_id", "customer_name", "book", "portfolios")
                    if c in df.columns]
            df = df[lead + [c for c in df.columns if c not in lead]]
        ev = st.dataframe(
            df, hide_index=True, width="stretch", height=420, on_select="rerun",
            selection_mode="single-row", key="cv_tbl",
            column_config={
                "customer_id": "Customer", "customer_name": "Name",
                "portfolios": "Portfolio", "book": "Book",
                "rating_final": "Rating", "stage_final": "Stage",
                "restructuring_final": "Restructuring",
                "watchlist_status": "Watchlist",
                "exposure_total": st.column_config.NumberColumn(
                    "Exposure", format="%,.0f"),
                "dpd_status": st.column_config.NumberColumn("Worst DPD",
                                                            format="%d")})
        caption(f"{cv['total']:,} customers match · page {page} of "
                f"{max(1, -(-cv['total'] // 50))} · largest exposure first")
        caption("Lending customers and investment counterparties (Book). An "
                "investment counterparty is rated on the external scale, so its "
                "rating override is an agency grade; its holdings all take it.")

    with right:
        with st.container(border=True):
            rows = ev.selection.rows if ev and ev.selection else []
            if not rows:
                card_header("Add an override")
                empty_state("No customer selected",
                            "Select a row in the table to override its rating, "
                            "stage or restructuring.")
            else:
                cid = str(df.iloc[rows[0]]["customer_id"])
                book = str(df.iloc[rows[0]].get("book") or "Lending")
                with guard():
                    info = api.wf_customer(run_id, cid, book)
                c, ch = info["customer"], info["choices"]
                card_header(("Override counterparty " if book == "Investments"
                             else "Override customer ") + cid, None,
                            right=pill(c.get("stage_final") or "—", "plum"))
                if book == "Investments":
                    caption(f"Investment book · {c.get('portfolios') or ''} · "
                            "rating on the external scale")
                caption(f"**{c.get('customer_name') or ''}** · calculated rating "
                        f"**{c.get('rating_final') or '—'}**, "
                        f"**{c.get('stage_final') or '—'}**, "
                        f"{c.get('restructuring_final') or 'Not Restructured'}")
                # A fresh form after each override; one that is refused keeps
                # what was typed, so a missing value costs no retyped reason.
                with st.form(f"ov_{book}_{cid}_{S.get('ov_n', 0)}", border=False):
                    a, b, d = st.columns(3)
                    r_val = a.selectbox("Override rating", ["(no change)"] + ch["rating"])
                    s_val = b.selectbox("Override stage", ["(no change)"] + ch["stage"])
                    x_val = d.selectbox("Override restructuring",
                                        ["(no change)"] + ch["restructuring"])
                    if c.get("stage_final") == "Stage 3":
                        caption("Stage 3 cannot be overridden: it is already the "
                                "worst stage.")
                    reason = st.text_area("Reason (required)", height=70,
                                          placeholder="e.g. credit committee "
                                                      "decision 2026-Q2, ticket #…")
                    who = st.text_input("Your name", value=S.get("_user") or "")
                    if st.form_submit_button("Add override", type="primary",
                                             icon=":material/add:"):
                        payload = {"customer_id": cid, "book": book,
                                   "reason": reason, "by": who,
                                   "rating": None if r_val.startswith("(") else r_val,
                                   "stage": None if s_val.startswith("(") else s_val,
                                   "restructuring": None if x_val.startswith("(")
                                   else x_val}
                        try:
                            api.wf_add_override(run_id, payload)
                        except api.BackendError as e:
                            st.error(str(e))
                        else:
                            S["ov_n"] = S.get("ov_n", 0) + 1
                            flash(f"Override added for customer {cid}.")
                            st.rerun()

        with st.container(border=True):
            card_header("Pending overrides", None,
                        right=pill(f"{pending} pending", "info" if pending else "muted"))
            if not pending:
                caption("None yet. The run finishes with the calculated values "
                        "when there are none.")
            for kind, label in (("rating", "Rating"), ("stage", "Stage"),
                                ("restructuring", "Restructuring")):
                items = po["overrides"][kind]
                if not items:
                    continue
                st.markdown(f"**{label}**")
                it = pd.DataFrame(items)
                if "book" not in it.columns:
                    it["book"] = "Lending"
                it["book"] = it["book"].fillna("Lending")
                st.dataframe(it[["customer_id", "book", "prior_value",
                                 "value", "reason", "created_by"]],
                             hide_index=True, width="stretch",
                             column_config={"customer_id": "Customer", "book": "Book",
                                            "prior_value": "Calculated",
                                            "value": "Override", "reason": "Reason",
                                            "created_by": "By"})
                d1, d2 = st.columns([3, 2], vertical_alignment="bottom")
                keys = {f"{i['customer_id']} ({i.get('book') or 'Lending'})":
                        (i["customer_id"], i.get("book") or "Lending") for i in items}
                drop = d1.selectbox(f"Remove a {kind} override",
                                    ["(keep all)"] + list(keys), key=f"drop_{kind}")
                if d2.button("Remove", key=f"db_{kind}", disabled=drop.startswith("("),
                             icon=":material/delete:", width="stretch"):
                    with guard():
                        api.wf_drop_override(run_id, kind, *keys[drop])
                    st.rerun()


# ================================================================== done ====
def _steps_table(steps: pd.DataFrame) -> None:
    st.dataframe(style_severity(steps.assign(
        status=steps["ok"].map({True: "PASS", False: "FAIL"}))[
            ["status", "step", "detail"]]), hide_index=True, width="stretch",
        column_config={"status": st.column_config.TextColumn("Status", width="small"),
                       "step": "Step",
                       "detail": st.column_config.TextColumn("Detail", width="large")})


def _done_page() -> None:
    j = S.get("wf_done") or {}
    res = j.get("result") or {}
    steps = pd.DataFrame(res.get("steps") or [])
    if j.get("status") == "failed" or not res.get("ok"):
        callout("err", res.get("error") or j.get("message") or "The run failed.",
                title="The run did not finish.")
        if len(steps):
            _steps_table(steps)
        if res.get("traceback") or j.get("traceback"):
            with st.expander("Technical detail"):
                st.code(res.get("traceback") or j.get("traceback"), language=None)
    else:
        official = res.get("run_type") == "official"
        callout("ok", ("It is **pending approval**: a checker approves or rejects "
                       "it on the Approval queue." if official
                       else "An unofficial run needs no approval; its exports are "
                            "marked UNOFFICIAL."),
                title=f"Run {res['run_id']} is complete.")
        ov = res.get("overrides_applied") or {}
        rd = res.get("readiness") or {}
        no_ecl = (rd.get("No ECL") or {}).get("contracts") or 0
        blank = (rd.get("Blank in LIC") or {}).get("contracts") or 0
        kpis([("Duration", f"{res.get('seconds', 0):.0f}s", "plum", ""),
              ("Outputs written", money(len(res.get("written") or [])), "plum", ""),
              ("Overrides applied", money(sum(int(v or 0) for v in ov.values())),
               "info", f"rating {ov.get('rating', 0)} · stage {ov.get('stage', 0)} · "
                       f"restructuring {ov.get('restructuring', 0)}"),
              ("Contracts", money(rd.get("contracts")), "plum", ""),
              ("No ECL", money(no_ecl), "err" if no_ecl else "ok", ""),
              ("Blank in LIC", money(blank), "err" if blank else "ok", "")])
        if res.get("dropped_args"):
            callout("warn", "The archived calculator does not support: "
                    + ", ".join(res["dropped_args"])
                    + ". The run was produced without them.")
        try:
            acc = api.run_accepted_findings(res["run_id"]).get("rows") or []
        except api.BackendError:
            acc = []
        if acc:
            st.markdown(f"**Findings accepted in this run · {len(acc)}** — on its "
                        "record and in the audit log, with the reasons")
            accepted_findings_table(acc)
        links = st.columns([1, 1, 1, 2])
        links[0].page_link("frontend/views/overview.py", label="See the results",
                           icon=":material/dashboard:", width="stretch")
        links[1].page_link("frontend/views/runs.py", label="Open in Browse runs",
                           icon=":material/list_alt:", width="stretch")
        if official:
            links[2].page_link("frontend/views/approval.py", label="Approval queue",
                               icon=":material/how_to_reg:", width="stretch")
        caption(f"Folder: `{res.get('run_dir')}`"
                + (" · produced by the archived calculator code"
                   if res.get("archived") else ""))
        if len(steps):
            with st.expander("What the run did, step by step"):
                _steps_table(steps)
    if st.button("Start another run", type="primary", icon=":material/restart_alt:"):
        for k in ("wf_done", "wf_run_id", "wf_val", "wf_pre", "wf_ready",
                  "wf_last_req"):
            S.pop(k, None)
        S["wf_state"] = "idle"
        st.rerun()


# ========================================================== idle: cards ====
def _date_changed():
    """Another input date: other inputs, and the portfolio date follows it
    until the check reads the extract's own date."""
    _reset_val()
    if S.get("wf_in_date"):
        S["wf_pdate_next"] = S["wf_in_date"]


def _inputs_card(src: dict) -> tuple[dict, bool]:
    """Where the 12 files come from: the folder of a date under the daily
    inputs folder, or the files uploaded. Returns the source and whether it
    can be checked (the button is in Check and start)."""
    val = S.get("wf_val")
    with st.container(border=True):
        card_header("Input extracts", None, right=(
            "" if val is None or val["ok"]
            else pill(f"{val['n_fail']} problem(s)", "err")))
        kind = st.segmented_control(
            "Inputs", list(KINDS), format_func=KINDS.get, default="date",
            required=True, key="wf_kind", on_change=_reset_val, width="stretch",
            label_visibility="collapsed")
        body, ready = {"kind": kind}, False
        if kind == "date":
            dates = {date.fromisoformat(d["date"]): d for d in src.get("dates") or []}
            if "wf_in_date" not in S:
                S["wf_in_date"] = max(dates) if dates else date.today()
                S.setdefault("wf_pdate_next", S["wf_in_date"])
            day = st.date_input("Date of the inputs", key="wf_in_date",
                                format="DD/MM/YYYY", on_change=_date_changed)
            hit = dates.get(day)
            root = src.get("inputs_root") or ""
            if hit:
                body["date"] = day.isoformat()
                ready = True
                n, m = hit["found"], hit["expected"]
                caption(f"`{hit['path']}` · {n} of {m} files"
                        + ("" if hit["complete"] else " — **some files are missing**"))
            elif not dates:
                callout("warn", f"No date folders in `{root}` yet. Save each day's "
                        "extracts, as they are, in a folder named by its date, "
                        "for example `2026-11-24`.",
                        title="No inputs found.")
            else:
                last = max(dates)
                callout("warn", f"There is no folder for {day:%d %b %Y} in `{root}`. "
                        f"Latest inputs: {last:%d %b %Y}.",
                        title=f"No inputs for {day:%d %b %Y}.")
        else:
            ups = st.file_uploader(
                f"The input files (up to {src['upload_limit_mb']} MB in all)",
                type=["xlsx", "xls", "xlsm", "csv", "xml", "html", "htm", "zip"],
                accept_multiple_files=True, key="wf_files",
                help="The 12 extracts as they are (Excel, csv or the SQL*Plus "
                     "exports), or one zip of them. The format is read from "
                     "the file itself.")
            if ups:
                key = "|".join(f"{u.name}:{u.size}" for u in ups)
                if S.get("wf_up_key") != key:
                    with st.spinner("Uploading…"):
                        with guard():
                            S["wf_up_res"] = api.wf_upload_files(ups)
                    S["wf_up_key"] = key
                    _reset_val()
                z = S.get("wf_up_res") or {}
                body.update({"kind": "upload", "path": z.get("path"),
                             "source_zip": z.get("source_zip"),
                             "extracted_at": z.get("extracted_at")})
                ready = bool(z.get("path"))
    return body, ready


def _settings_card(vers: dict, calcs: dict) -> dict:
    with st.container(border=True):
        card_header("Run settings")
        # a draft is used in no run: it is offered once its maker marks it tested
        vrows = [r for r in vers["versions"] if r.get("usable", True)]
        vlabels = {}
        for r in vrows:
            vlabels[f"{r['label']} · {r['status']}"
                    + (" · active" if r.get("active") else "")] = r["label"]
        live = "Default config (as on disk)"
        opts = list(vlabels) + [live] if vers["active"] else [live] + list(vlabels)
        cur_pick = S.get("wf_version", vers["default_pick"])
        cur = next((k for k, v in vlabels.items() if v == cur_pick), live)
        vhelp = ("The default config reads `config/` and `data-raw/static/` as "
                 "they sit on disk now. A config version is a frozen copy of both: "
                 "tested ones for unofficial runs, approved ones for official runs. "
                 "Drafts are not offered.")
        if cur_pick != "__LIVE__":
            meta = next((r for r in vrows if r["label"] == cur_pick), {})
            vhelp = (f"{cur_pick} ({meta.get('status')}): "
                     f"{meta.get('description') or 'no description'}")

        c1, c2 = st.columns([3, 2])
        vsel = c1.selectbox("Config version", opts, index=opts.index(cur),
                            key="wf_vsel", on_change=_settings_changed, help=vhelp)
        version = vlabels.get(vsel, "__LIVE__")
        S["wf_version"] = version
        run_type = S.get("wf_rt2") or "unofficial"
        with guard():
            gate = api.wf_run_type_check(run_type, version)
        c2.segmented_control(
            "Run type", ["unofficial", "official"], default="unofficial",
            required=True, key="wf_rt2", on_change=_settings_changed,
            width="stretch",
            format_func=lambda v: {"unofficial": "Unofficial",
                                   "official": "Official"}[v],
            help=("Unofficial: for testing and what-if; skips approval, and its "
                  "exports are marked UNOFFICIAL. Official: the sanctioned "
                  "deliverable; needs an approved config version and a checker's "
                  "approval."))

        c3, c4, c5 = st.columns(3)
        purposes = {p["label"]: p["id"] for p in gate["purposes"]}
        purpose = purposes[c3.selectbox(
            "Run purpose", list(purposes), key=f"wf_pp_{run_type}",
            help="Every run is priced on the probability-weighted PD curve and "
                 "on each scenario; the weighted figure is the provision.")]
        now = calcs.get("engine_version") or (calcs["active"] or {}).get("id") or ""
        clabels = {f"{now} (this engine)": ""}
        for c in calcs["versions"]:
            if not c.get("current") and c["runs_archived_code"]:
                clabels[f"{c['id']} (archived)"] = c["id"]
        cur_calc = clabels.get(S.get("wf_calc"), "")
        crow = next((c for c in calcs["versions"] if c["id"] == cur_calc), None)
        code = (crow or calcs["active"] or {}).get("code_hash") or "?"
        calc_id = clabels[c4.selectbox(
            "Calculator version", list(clabels), key="wf_calc",
            help=f"Fingerprint {code[:10]}: "
                 + ("runs this version's archived code." if crow
                    else "runs the deployed code."))]
        # the extract date of the last validation, set before the widget is
        # drawn: Streamlit refuses a keyed widget's state written after it
        if "wf_pdate_next" in S:
            S["wf_pdate_in"] = S.pop("wf_pdate_next")
        S.setdefault("wf_pdate_in", S.get("wf_in_date") or date.today())
        pdate = c5.date_input("Portfolio date", key="wf_pdate_in",
                              format="DD/MM/YYYY",
                              help="The as-of date. Filled from the inputs' "
                                   "EXTRACTDA when they are checked.")
        if not gate["ok"]:
            callout("warn", gate["reason"], title="An official run cannot start.")
    return {"version": version, "run_type": run_type, "purpose": purpose,
            "calc_id": calc_id, "pdate": pdate, "gate": gate}


def _check(body: dict, cfg: dict) -> None:
    """One check: the files are all there and readable; if so, the pre-run
    validators and the pricing dry run (run by _resume_jobs)."""
    _reset_checks()
    try:
        with st.spinner("Finding the files…"):
            S["wf_val"] = api.wf_validate_inputs(
                {**body, "version": cfg["version"], "preview": False})
    except api.BackendError as e:
        S.pop("wf_val", None)
        st.error(str(e))
        return
    if S["wf_val"]["ok"]:
        _request_checks({"input_dir": S["wf_val"]["input_dir"],
                         "version": cfg["version"], "run_type": cfg["run_type"]})
    st.rerun()


def _actions_card(val, cfg: dict, body: dict, ready: bool) -> None:
    """Check and Start, side by side."""
    pre, rdy = S.get("wf_pre"), S.get("wf_ready")
    checked = bool(val and val["ok"]) and pre is not None and rdy is not None
    rdy_failed = checked and rdy.get("status") != "done"
    blocking = _blocking(_check_rows()) if checked else []
    can_run = (checked and not rdy_failed and not blocking and cfg["gate"]["ok"])
    with st.container(border=True):
        card_header("Check and start", None, right=(
            "" if not checked else pill("blocked", "err") if blocking or rdy_failed
            else pill("ready", "ok")))
        b1, b2 = st.columns(2)
        go = b1.button("Check" if val is None else "Check again",
                       type="primary" if not checked else "secondary",
                       disabled=not ready, icon=":material/fact_check:",
                       width="stretch")
        official = cfg["run_type"] == "official"
        start_go = b2.button("Start official run" if official else "Start unofficial run",
                             type="primary", disabled=not can_run,
                             icon=":material/play_arrow:", width="stretch")
        if not ready:
            caption("Choose the inputs above.")
        elif val is None:
            caption("Checks the input files, the config and which contracts would "
                    "get no ECL, before anything is committed.")
        elif not val["ok"]:
            caption("Fix the problems on the right and check again.")
        elif rdy_failed:
            callout("err", f"The pricing dry run failed: {rdy.get('message')}")
        elif blocking:
            callout("err", f"Start is locked by {len(blocking)} error(s). See them "
                    "on the right.")
        elif not cfg["gate"]["ok"]:
            callout("warn", "Start is locked: " + cfg["gate"]["reason"])
        elif checked:
            caption("Ready. The run pauses after phase 1 for overrides, then "
                    "finishes.")
    if go:
        _check(body, cfg)
    if start_go:
        S["wf_phase_req"] = {"kind": "phase1", "payload": {
            "input_dir": val["input_dir"], "input_source": val["input_source"],
            "version": cfg["version"], "run_type": cfg["run_type"],
            "run_purpose": cfg["purpose"],
            "portfolio_date": cfg["pdate"].isoformat(),
            "calculator_version": cfg["calc_id"] or None,
            "accepted_findings": _accepted_list()}}
        # recorded on the run it starts; the next run asks again
        S.pop("wf_accepted", None)
        st.rerun()


# ======================================================== idle: results ====
def _welcome() -> None:
    empty_state("Nothing checked yet",
                "Choose the inputs and press **Check**. It looks at:")
    st.markdown(
        '<div class="howto">'
        '<div><b>1 · Inputs</b><span>All 12 files there and readable; every '
        'row: dates, amounts, keys, duplicates, and the links between files.'
        '</span></div>'
        '<div><b>2 · Config</b><span>The chosen config version and its '
        'reference tables are complete.</span></div>'
        '<div><b>3 · Pricing</b><span>A dry run: which contracts would get no '
        'ECL, or a blank, before anything is committed.</span></div></div>',
        unsafe_allow_html=True)


_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2, "ACCEPTED": 3}


def _is_input(r: dict) -> bool:
    """A finding about the input files (their fields and the links between
    them); the rest are about the config, the reference tables and pricing."""
    return str(r.get("id") or "").split("_", 1)[0] in ("INPUT", "XFILE")


def _findings_table(rows: list[dict], key: str) -> None:
    """Findings as one table, errors first."""
    df = pd.DataFrame([{
        "Severity": r.get("_sev") or _sev(r),
        "Where": str(r.get("context") or ""),
        "Check": str(r.get("description") or r.get("id") or ""),
        "Detail": " — ".join(x for x in (str(r.get("message") or ""),
                                          str(r.get("accepted_note") or "")) if x),
    } for r in rows])
    df = df.sort_values("Severity", key=lambda s: s.map(_ORDER).fillna(9),
                        kind="stable")
    st.dataframe(style_severity(df), hide_index=True, width="stretch", key=key,
                 height=min(320, 38 + 35 * len(df)),
                 column_config={
                     "Severity": st.column_config.TextColumn(width="small"),
                     "Where": st.column_config.TextColumn(width="small"),
                     "Check": st.column_config.TextColumn(width="medium"),
                     "Detail": st.column_config.TextColumn(width="large")})


def _section(title: str, rows: list[dict]) -> None:
    c = severity_counts([r for r in rows if not r.get("_sev")])
    c["err"] += sum(1 for r in rows if r.get("_sev") == "ERROR")
    bits = [pill(f"{c['err']} error(s)", "err") if c["err"] else "",
            pill(f"{c['warn']} warning(s)", "warn") if c["warn"] else "",
            pill(f"{c['info']} info", "info") if c["info"] else "",
            pill(f"{c['muted']} accepted", "muted") if c["muted"] else ""]
    st.markdown(f"**{title}** " + (" ".join(b for b in bits if b)
                                   or pill("no findings", "ok")),
                unsafe_allow_html=True)


def _structural_rows(val: dict) -> list[dict]:
    """The file checks that failed, as findings."""
    out = []
    for r in val.get("structural") or []:
        if r.get("status") != "FAIL":
            continue
        chk = str(r["check"])
        if chk.endswith(" present"):
            name = chk[:-len(" present")]
            out.append({"_sev": "ERROR", "context": name,
                        "description": "File missing",
                        "message": "looked for " + str(r["detail"]).removeprefix("tried ")})
        else:
            out.append({"_sev": "ERROR", "context": "", "description": chk,
                        "message": r["detail"]})
    return out



_CLEANED = {"header": "repeated header", "trailer": "row-count trailer",
            "blank": "blank", "total": "total line",
            "duplicate": "exact duplicate"}


def _cleaned(detail: dict) -> str:
    """'OriginationInvestments.xls: 1 exact duplicate row; ...'."""
    out = []
    for f, kinds in detail.items():
        bits = [f"{int(n)} {_CLEANED.get(k, k)} row{'s' if int(n) != 1 else ''}"
                for k, n in kinds.items() if int(n)]
        if bits:
            out.append(f"{f}: " + ", ".join(bits))
    return "; ".join(out)


def _readiness_tab(rdy: dict) -> None:
    rr = rdy.get("result") or {}
    p = rr.get("readiness") or {}
    if not p.get("exists"):
        callout("warn", rr.get("error") or "Readiness could not be assessed.")
        return
    s = p["summary"]

    def cnt(k):
        return (s.get(k) or {}).get("contracts") or 0

    def exp(k):
        return (s.get(k) or {}).get("exposure") or 0
    kpis([("Contracts", money(s["contracts"]), "plum",
           f"exposure {money(s.get('exposure'))}"),
          ("Priced", money(cnt("Priced")), "ok", f"exposure {money(exp('Priced'))}"),
          ("Priced — check", money(cnt("Priced - check")),
           "warn" if cnt("Priced - check") else "",
           "priced from incomplete inputs"),
          ("Blank in LIC", money(cnt("Blank in LIC")),
           "err" if cnt("Blank in LIC") else "ok", "the LIC would leave it blank"),
          ("No ECL", money(cnt("No ECL")), "err" if cnt("No ECL") else "ok",
           "no provision at all")])
    if p["reasons"]:
        st.markdown("**Why, and what fixes it**")
        rs = pd.DataFrame(p["reasons"])[["severity", "check", "contracts",
                                         "exposure", "text", "fix"]]
        st.dataframe(style_severity(rs), hide_index=True, width="stretch",
                     column_config={
                         "severity": st.column_config.TextColumn("Severity", width="small"),
                         "check": "Check", "contracts": "Contracts",
                         "exposure": st.column_config.NumberColumn("Exposure",
                                                                   format="%,.0f"),
                         "text": st.column_config.TextColumn("What happens", width="large"),
                         "fix": st.column_config.TextColumn("Fix", width="large")})
    if p.get("funnel"):
        with st.expander("Row funnel: rows in and out of each file"):
            st.dataframe(pd.DataFrame(p["funnel"]), hide_index=True, width="stretch")


def _accepted_banners(pre: dict) -> None:
    """What is accepted, and how: for this run (with Withdraw), and by
    standing suppressions that apply to every run (with Remove, where the
    page can end them)."""
    mine = _accepted_list()
    if mine:
        items = "; ".join(f"`{m['validator_id']}` ({m['reason']})" for m in mine)
        a, b = st.columns([4, 1.25], vertical_alignment="center")
        with a:
            callout("plum", f"{items} — by {mine[0]['accepted_by']}. Recorded on "
                    "the run with the reasons; the next run asks again.",
                    title=f"{len(mine)} finding(s) accepted for this run.")
        if b.button("Withdraw", icon=":material/undo:", width="stretch",
                    key="wf_withdraw"):
            S.pop("wf_accepted", None)
            _request_checks(S["wf_last_req"],
                            "Withdrew the acceptances; the checks ran again.")
    _standing_notice(_standing_hits(pre), bool(pre.get("can_remove_standing")),
                     "wf_rm_standing")


def _standing_hits(pre: dict) -> list[dict]:
    """The standing suppressions that took effect, in the check or the dry
    run."""
    hit = {r.get("id") for r in _check_rows() if r.get("accepted_source") == "standing"}
    return [e for e in (pre.get("standing") or []) if e["validator_id"] in hit]


def _results(val) -> None:
    pre, rdy = S.get("wf_pre"), S.get("wf_ready")
    if val is None:
        with st.container(border=True):
            _welcome()
        return
    if not val["ok"]:
        with st.container(border=True):
            card_header("Check results", None, right=pill("not usable", "err"))
            callout("err", "Fix these, then check again.",
                    title=f"{val['n_fail']} problem(s) with the input files.")
            rows = _structural_rows(val)
            _section("Inputs", rows)
            _findings_table(rows, "tbl_struct")
        return
    if pre is None or rdy is None:
        with st.container(border=True):
            empty_state("Check again",
                        "The settings changed since the last check.")
        return

    rows = _check_rows()
    blocking = _blocking(rows)
    acceptable = [r for r in blocking if _truthy(r.get("suppressible", True))]
    c = severity_counts(rows)
    rr = (rdy.get("result") or {}).get("readiness") or {}
    s = rr.get("summary") or {}
    lost = sum(((s.get(k) or {}).get("contracts") or 0)
               for k in ("No ECL", "Blank in LIC"))
    gap = (s.get("Priced - check") or {}).get("contracts") or 0
    files = [r for r in val.get("structural") or [] if str(r["check"]).endswith(" present")]
    with st.container(border=True):
        card_header("Check results", None,
                    right=pill("blocked", "err") if blocking or rdy.get("status") != "done"
                    else pill("ready", "ok"))
        if rdy.get("status") != "done":
            callout("err", f"The pricing dry run failed: {rdy.get('message')}",
                    title="Start is locked.")
        elif blocking:
            text = f"**{len(blocking)} error(s)** stop the run. "
            if acceptable:
                text += (f"{len(acceptable)} can be accepted **for this run**, with "
                         "a reason (the next run asks again); ")
                text += ("the rest must be fixed at source." if len(acceptable)
                         < len(blocking) else "otherwise fix them at source.")
            else:
                text += "Fix them at source and check again."
            if acceptable:
                a, b = st.columns([4, 1.25], vertical_alignment="center")
                with a:
                    callout("err", text, title="Start is locked.")
                if b.button("Accept for this run…", icon=":material/verified:",
                            width="stretch"):
                    _accept_dialog(acceptable)
            else:
                callout("err", text, title="Start is locked.")
        elif c["warn"]:
            callout("warn", f"No errors. {c['warn']} warning(s) to review; they do "
                    "not stop the run.", title="Ready to start.")
        else:
            callout("ok", "Every check passed and every contract will be priced.",
                    title="Ready to start.")
        _accepted_banners(pre)
        kpis([("Files", f"{sum(r['status'] == 'PASS' for r in files)} of {len(files)}",
               "ok", _nice(pre.get("extract_date")) + " extract"),
              ("Errors", money(len(blocking)), "err" if blocking else "ok", ""),
              ("Warnings", money(c["warn"]), "warn" if c["warn"] else "ok", ""),
              ("Contracts priced",
               f"{money((s.get('contracts') or 0) - lost)} of {money(s.get('contracts'))}",
               "err" if lost else "ok",
               f"{money(lost)} no ECL or blank" if lost else
               f"{money(gap)} from incomplete inputs" if gap else "every one")])

        inputs = [r for r in rows if _is_input(r)]
        others = [r for r in rows if not _is_input(r)]
        _section("Inputs", inputs)
        if inputs:
            _findings_table(inputs, "tbl_inputs")
        detail = pre.get("clean_log") or {
            k: {"header": v} for k, v in (pre.get("strip_log") or {}).items() if v}
        if detail:
            caption("Removed before checking (not data): " + _cleaned(detail) + ".")

        _section("Pre-run checks", others)
        if others:
            _findings_table(others, "tbl_pre")
        with st.expander("Pricing dry run"):
            _readiness_tab(rdy)
        if rr.get("flagged"):
            with st.expander(f"Contracts with a gap · {money(rr.get('n_flagged') or 0)}"):
                st.dataframe(pd.DataFrame(rr["flagged"]), hide_index=True,
                             width="stretch", height=440)



# ================================================================== page ====
_resume_jobs()
if S["wf_state"] == "paused" and S.get("wf_run_id"):
    _stepper()
    _paused_page(S["wf_run_id"])
    st.stop()
if S["wf_state"] == "done":
    _stepper()
    _done_page()
    st.stop()

_stepper()

# A run paused in an earlier browser session is still held by the backend.
try:
    held = api.wf_paused()
except api.BackendError:
    held = []
for h in held:
    a, b = st.columns([6, 1], vertical_alignment="center")
    with a:
        callout("plum", f"Started {h['started']} by {h['user']} · {h['run_type']} · "
                f"{h['customers']:,} customers. Resume it to add overrides and "
                "finish, or cancel it.", title=f"Run {h['run_id']} is paused.")
    if b.button("Resume", key=f"res_{h['run_id']}", icon=":material/play_arrow:",
                width="stretch"):
        S["wf_state"], S["wf_run_id"] = "paused", h["run_id"]
        st.rerun()

with guard():
    src = api.wf_sources()
    vers = api.wf_versions()
    calcs = api.wf_calculators()

left, right = st.columns([5, 7], gap="medium")
with left:
    body, ready = _inputs_card(src)
    cfg = _settings_card(vers, calcs)
    _actions_card(S.get("wf_val"), cfg, body, ready)
with right:
    _results(S.get("wf_val"))
