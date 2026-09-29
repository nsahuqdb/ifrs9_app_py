"""Audit log: who did what, when -- the project's, and one run's.

The project log (logs/etl_audit.jsonl) is the R app's audit page: every run
started, paused, finished, approved or rejected; every validation stage; every
pre-run check; every config version created, edited or promoted; every
suppression and overlay -- filterable by event, run and user, one readable line
per event. Both engines write it, so runs made by either appear here.
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup

page_setup("Audit log",
           "So that months later someone can say what produced a figure, who "
           "touched it and who signed it off — without guesswork.")

tab_log, tab_snap, tab_run, tab_diff = st.tabs(
    ["Project log", "Frozen configuration", "This run's activity", "Compare runs"])

with tab_log:
    c1, c2, c3, c4 = st.columns([3, 3, 3, 1])
    with guard():
        base = api.audit_log()
    ev_opts = {"(all)": ""} | {e["label"]: e["id"] for e in base["events"]}
    ev = ev_opts[c1.selectbox("Event type", list(ev_opts))]
    run = c2.selectbox("Run ID", ["(all)"] + base["runs"])
    usr = c3.selectbox("User", ["(all)"] + base["users"])
    if c4.button("Refresh", use_container_width=True):
        api.clear()
        st.rerun()
    with guard():
        log = api.audit_log(ev or None, None if run.startswith("(") else run,
                            None if usr.startswith("(") else usr)
    caption(f"audit log: `{log['path']}`"
            + (f" · {base['n_events']:,} events" if log["exists"]
               else " (does not exist yet)"))
    rows = pd.DataFrame(log["rows"])
    if rows.empty:
        st.info("No audit events match. Run the pipeline, or edit versions, "
                "suppressions or overlays." if base["n_events"] == 0
                else "No events match the current filter.")
    else:
        metric_row([("Events shown", money(len(rows))),
                    ("Runs", money(rows["run"].replace("", pd.NA).nunique())),
                    ("Users", money(rows["user"].nunique()))])
        st.dataframe(rows[["time", "action", "user", "run", "details"]],
                     hide_index=True, use_container_width=True, height=520,
                     column_config={
                         "time": st.column_config.TextColumn("Time", width="small"),
                         "action": st.column_config.TextColumn("Action", width="small"),
                         "details": st.column_config.TextColumn("Details", width="large")})

run_id = st.session_state.get("run_id")

with tab_snap:
    if not run_id:
        st.info("Select a run at the top.", icon="👈")
    else:
        with guard():
            s = api.snapshot(run_id)
        if not s.get("exists"):
            st.warning(s.get("note", "No snapshot for this run."), icon="⚠️")
        else:
            metric_row([("Taken", s.get("taken", "—")), ("By", s.get("by", "—")),
                        ("Files", money(len(s.get("files", {}))))])
            st.dataframe(pd.DataFrame([{"file": k, "hash": v.get("sha256_16"),
                                        "bytes": v.get("bytes")}
                                       for k, v in s.get("files", {}).items()]),
                         use_container_width=True, hide_index=True)
            caption("Hashes, not just copies: a copy can be edited afterwards and "
                    "still look original.")

with tab_run:
    if not run_id:
        st.info("Select a run at the top.", icon="👈")
    else:
        with guard():
            entries = api.audit(run_id)
        if not entries:
            st.info("Nothing recorded against this run yet.")
        else:
            st.dataframe(pd.DataFrame(entries), use_container_width=True,
                         hide_index=True)
            caption("The run's own audit.jsonl. Append-only.")

with tab_diff:
    other = st.session_state.get("compare_id")
    if not run_id or not other:
        st.info("Select a run and a second run at the top to compare their "
                "configurations.")
    else:
        with guard():
            d = api.snapshot_compare(other, run_id)
        if not d:
            st.warning("One of the runs has no frozen configuration.")
        else:
            df = pd.DataFrame(d)
            changed = df[df["status"] == "CHANGED"]
            if len(changed):
                st.warning(f"{len(changed)} configuration file(s) differ between "
                           f"{other} and {run_id}, so part of any change in the "
                           "numbers may come from the configuration rather than "
                           "the data.", icon="⚠️")
            else:
                st.success("The configuration is identical between the two runs, so "
                           "any change in the numbers came from the data.", icon="✅")
            st.dataframe(df, use_container_width=True, hide_index=True)
