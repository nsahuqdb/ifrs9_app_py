"""What produced this run, and who has touched it."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected.", icon="👈")
    st.stop()

page_setup("Audit trail",
           "So that months later someone can say what produced a figure, who "
           "touched it and who signed it off — without guesswork.")

tab_snap, tab_log, tab_diff = st.tabs(["Frozen configuration", "Activity",
                                       "Compare runs"])

with tab_snap:
    with guard():
        s = api.snapshot(run_id)
    if not s.get("exists"):
        st.warning(s.get("note", "No snapshot for this run."), icon="⚠️")
    else:
        metric_row([("Taken", s.get("taken", "—")),
                    ("By", s.get("by", "—")),
                    ("Files", money(len(s.get("files", {}))))])
        rows = [{"file": k, "hash": v.get("sha256_16"), "bytes": v.get("bytes")}
                for k, v in s.get("files", {}).items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True,
                     column_config={"file": "File", "hash": "SHA-256 (16)",
                                    "bytes": "Bytes"})
        caption("Hashes, not just copies: a copy can be edited afterwards and "
                "still look original.")

with tab_log:
    with guard():
        entries = api.audit(run_id)
    if not entries:
        st.info("Nothing recorded against this run yet.")
    else:
        st.dataframe(pd.DataFrame(entries), use_container_width=True,
                     hide_index=True)
        caption("Append-only. An audit trail that can be edited is not one.")

with tab_diff:
    other = st.session_state.get("compare_id")
    if not other:
        st.info("Select a second run at the top to compare configurations.")
    else:
        with guard():
            d = api.snapshot_compare(other, run_id)
        if not d:
            st.warning("One of the runs has no frozen configuration.")
        else:
            df = pd.DataFrame(d)
            changed = df[df["status"] == "CHANGED"]
            if len(changed):
                st.error(f"{len(changed)} configuration files differ between "
                         f"{other} and {run_id}.", icon="⚠️")
            else:
                st.success("The configuration is identical between the two "
                           "runs, so any change in the numbers came from the "
                           "data.", icon="✅")
            st.dataframe(df, use_container_width=True, hide_index=True)
