"""Reconciling this run against another, and packaging it."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pct, waterfall

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected.", icon="👈")
    st.stop()

page_setup("Reconcile and export",
           "Why this run differs from another, and everything needed to "
           "defend the figure in one package.")

tab_rec, tab_files, tab_exp = st.tabs(["Movement", "File by file", "Export"])
other = st.session_state.get("compare_id")

with tab_rec:
    if not other:
        st.info("Select a second run at the top to compare against.")
    else:
        with guard():
            r = api.reconcile(run_id, other)
        w = r.get("walk")
        if not w:
            st.warning("One of the runs has no ECL report.")
        else:
            metric_row([
                ("Opening", money(w["opening"])),
                ("Closing", money(w["closing"])),
                ("Movement", money(w["closing"] - w["opening"])),
                ("% change", pct(100 * (w["closing"] - w["opening"])
                                 / max(w["opening"], 1))),
                ("Files matching", f"{r['files_matching']} of {r['files_compared']}"),
            ])
            waterfall(pd.DataFrame(w["steps"]))
            caption(f"Residual {w['residual']:.6f}. "
                    f"{w['counts']['arrived']:,} contracts arrived, "
                    f"{w['counts']['left']:,} left, "
                    f"{w['counts']['migrated']:,} changed stage.")

with tab_files:
    if not other:
        st.info("Select a second run at the top to compare against.")
    else:
        with guard():
            r = api.reconcile(run_id, other)
        f = pd.DataFrame(r["files"])
        differing = f[f["status"] != "match"]
        if len(differing) == 0:
            st.success("Every file matches.", icon="✅")
        else:
            st.warning(f"{len(differing)} of {len(f)} files differ.", icon="⚠️")
        cols = [c for c in ("file", "status", "rows_this", "rows_reference",
                            "rows_added", "rows_removed", "columns_differing")
                if c in f.columns]
        st.dataframe(f[cols], use_container_width=True, hide_index=True)
        caption("Compared by natural key, not row order — a file written in a "
                "different order is not a difference worth reporting.")

        for _, row in differing.iterrows():
            det = row.get("detail")
            if not det:
                continue
            with st.expander(f"{row['file']} — what differs"):
                st.dataframe(pd.DataFrame(det), use_container_width=True,
                             hide_index=True)

with tab_exp:
    with guard():
        summ = pd.DataFrame(api.output_summary(run_id))
    if len(summ):
        st.dataframe(summ, use_container_width=True, hide_index=True, height=330)
    inc = st.checkbox(
        "Include the raw source extracts", value=False,
        help="Large, and they contain customer data — including them should be "
             "a decision rather than an accident.")
    if st.button("Package this run", type="primary"):
        with guard():
            res = api.export_run(run_id, inc)
        st.success(f"{res['files']} files, {res['bytes']/1e6:.1f} MB", icon="✅")
        st.code(res["zip"], language=None)
        caption("Contains the LIC input files, the report, the frozen "
                "configuration with its hashes, the validation result, the "
                "approvals and the audit trail — plus a README explaining what "
                "each is for.")
        if res.get("skipped"):
            st.info("Not present: " + ", ".join(res["skipped"])
                    + ". A missing approval or validation file means that step "
                      "was never run, not that it passed.", icon="ℹ️")
