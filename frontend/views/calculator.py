"""Calculator versions: the engine version a run uses, and the earlier ones."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, page_setup

page_setup("Calculator versions",
           "The calculator version is the engine version. A run records it "
           "with a fingerprint of the code that ran, so a change to the code "
           "without a new version shows as drift.")

with guard():
    reg = api.calculator_versions()
    code = api.code_status()

versions = pd.DataFrame(reg["versions"])
for_run = reg["for_run"] or {}
matches = for_run.get("matches_registered")
state = ("Matches" if matches is True
         else "Changed" if matches is False else "Not registered")

metric_row([
    ("Calculator version", reg.get("engine_version") or for_run.get("id") or "—"),
    ("Code fingerprint", (reg.get("live_fingerprint") or "—")[:12]),
    ("Against the archive", state),
    ("Working tree", "modified" if code.get("dirty") else
     "clean" if code.get("available") else "not a checkout"),
])

if matches is False:
    st.error(
        f"The deployed code is not the code archived for "
        f"**{for_run.get('id')}**: `{(for_run.get('registered_hash') or '')[:12]}` "
        f"archived, `{(for_run.get('code_hash') or '')[:12]}` running. The code "
        "changed without a new version number.", icon="⚠️")

st.markdown("## Versions")
caption("A version is added, and its code archived, the first time it is used. "
        "An earlier version can be picked on Run the pipeline to run again from "
        "its archive.")
if versions.empty:
    caption("Nothing yet.")
else:
    show = versions.copy()
    show["current"] = show.get("current", False)
    show["current"] = show["current"].map({True: "●", False: ""})
    show["archived"] = show["archived"].map({True: "yes", False: "no"})
    show["code_hash"] = show["code_hash"].astype(str).str[:12]
    show = show.sort_values("created_at", ascending=False, kind="stable")
    st.dataframe(
        show[["current", "id", "code_hash", "archived", "created_at",
              "created_by", "description"]],
        hide_index=True, use_container_width=True,
        column_config={
            "current": st.column_config.TextColumn("Running", width="small"),
            "id": st.column_config.TextColumn("Version"),
            "code_hash": st.column_config.TextColumn("Fingerprint"),
            "archived": st.column_config.TextColumn("Code archived"),
            "created_at": st.column_config.TextColumn("First used"),
            "created_by": st.column_config.TextColumn("By"),
            "description": st.column_config.TextColumn("Description"),
        })

with st.expander("The deployed code, as git sees it"):
    if not code.get("available"):
        caption("This deployment is not a git checkout: the fingerprint above "
                "is the record.")
    else:
        st.write(pd.DataFrame([{
            "commit": code.get("sha"),
            "branch": code.get("branch"),
            "last commit": code.get("last_commit_at"),
            "working tree": "modified" if code.get("dirty") else "clean",
        }]).T.rename(columns={0: ""}))
