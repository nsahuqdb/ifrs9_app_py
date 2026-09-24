"""Run the ETL: source extracts to a priced ECL report."""
import time

import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup

page_setup("Run the pipeline",
           "Upload the twelve Oracle extracts, or point at a folder. Builds "
           "the LIC input files, prices the book and writes a new run. An "
           "existing run is never overwritten.")

tab_up, tab_folder = st.tabs(["Upload files", "Use a folder"])

with tab_up:
    st.caption("Drop the twelve extracts here. Format is detected from each "
               "file's contents, so `.xls` files that are really SQL\\*Plus "
               "HTML are handled.")
    files = st.file_uploader(
        "Source extracts", accept_multiple_files=True,
        type=["xlsx", "xls", "csv", "htm", "html"],
        label_visibility="collapsed")
    c1, c2 = st.columns([1, 4])
    if c1.button("Upload", type="primary", disabled=not files,
                 use_container_width=True):
        with guard():
            res = api.etl_upload(files)
        st.session_state["etl_dir"] = res["upload_dir"]
        st.success(f"{len(res['saved'])} files staged in `{res['upload_dir']}`")
        st.dataframe(pd.DataFrame(res["saved"]), use_container_width=True,
                     hide_index=True,
                     column_config={"name": "File", "size_mb": "Size (MB)",
                                    "format": "Detected format"})
        api.etl_inputs.clear()
    if c2.button("Clear staged files"):
        with guard():
            n = api.etl_clear_uploads()
        st.info(f"Removed {n['removed']} files.")
        api.etl_inputs.clear()

with tab_folder:
    folder = st.text_input(
        "Input folder on the backend machine", value="",
        placeholder="e.g. C:\\\\Users\\\\nsahu\\\\Downloads\\\\ifrs9_etl\\\\input")
    if st.button("Use this folder"):
        st.session_state["etl_dir"] = folder or None

st.divider()

# ---- what the backend can see -----------------------------------------
src = st.session_state.get("etl_dir")
with guard():
    info = api.etl_inputs(src)
    cov = api.etl_coverage()

st.subheader("Inputs")
caption(f"Reading from `{info['input_dir']}`")
files_df = pd.DataFrame(info["files"])
found = int(files_df["found"].notna().sum())
metric_row([
    ("Files found", f"{found} of {len(files_df)}"),
    ("Ready", "yes" if info["ready"] else "no"),
    ("Next run id", info["next_run_id"]),
])
show = files_df.copy()
show["status"] = show["found"].map(lambda v: "found" if v else "MISSING")
st.dataframe(
    show[["name", "expected", "found", "format", "size_mb", "status", "description"]],
    use_container_width=True, hide_index=True, height=430,
    column_config={"name": "Input", "expected": "Expected file", "found": "Found",
                   "format": "Format",
                   "size_mb": st.column_config.NumberColumn("MB", format="%.2f"),
                   "status": "Status", "description": "What it holds"})

if not info["ready"]:
    st.error("Missing: " + ", ".join(info["missing"]))
    st.stop()

# ---- run ---------------------------------------------------------------
st.subheader("Run")
if st.button("Start run", type="primary"):
    with guard():
        job = api.etl_start(src)
    bar = st.progress(0.0, text="Starting…")
    steps = ["read", "date", "lending", "investments", "collateral", "customers",
             "origination", "curves", "stpd", "static", "write",
             "snapshot", "price"]
    while True:
        s = api.etl_status(job["job_id"])
        frac = ((steps.index(s.get("step")) + 1) / len(steps)
                if s.get("step") in steps else 0.05)
        bar.progress(min(frac, 1.0), text=s.get("message", "Working…"))
        if s["status"] in ("done", "failed"):
            break
        time.sleep(1.0)
    bar.empty()

    if s["status"] == "failed":
        st.error(s.get("message", "The run failed."))
        res = s.get("result") or {}
        if res.get("steps"):
            st.caption("How far it got:")
            st.dataframe(pd.DataFrame(res["steps"])[["step", "ok", "detail"]],
                         use_container_width=True, hide_index=True,
                         column_config={"step": "Step", "ok": "OK",
                                        "detail": "Result"})
        tb = res.get("traceback") or s.get("traceback")
        if tb:
            with st.expander("Technical detail"):
                st.code(tb, language=None)
        st.stop()

    r = s["result"]
    st.success(f"**{r['run_id']}** written in {r['seconds']}s", icon="✅")
    st.dataframe(pd.DataFrame(r["steps"])[["step", "ok", "detail"]],
                 use_container_width=True, hide_index=True,
                 column_config={"step": "Step", "ok": "OK", "detail": "Result"})
    st.caption(f"Run folder: `{r['run_dir']}`  ·  {len(r['written'])} files")
    api.clear()
    st.info("Select the new run at the top right to analyse it.", icon="👉")
