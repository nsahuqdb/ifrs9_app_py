"""Calculator versions: which code a run would claim, and which it would run."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, page_setup, pill

page_setup("Calculator versions",
           "Deployment does not always go through git, so the calculation "
           "code is tracked in a registry. A run records the version it "
           "selected AND a fingerprint of the code that actually executed — "
           "either alone can be misleading, and together they make drift "
           "visible.")

with guard():
    reg = api.calculator_versions()
    code = api.code_status()

versions = pd.DataFrame(reg["versions"])
for_run = reg["for_run"] or {}
live = reg.get("live_fingerprint") or ""
matches = for_run.get("matches_registered")

state = ("Matches" if matches is True
         else "DRIFTED" if matches is False else "Not registered")
tone = "ok" if matches is True else "err" if matches is False else "warn"

metric_row([
    ("Active version", for_run.get("id") or "—"),
    ("Deployed code", (live or "—")[:12]),
    ("Against the registry", state),
    ("Working tree", "modified" if code.get("dirty") else
     "clean" if code.get("available") else "not a checkout"),
])

if matches is False:
    st.error(
        f"The deployed code does not match what **{for_run.get('id')}** was "
        f"registered with: `{(for_run.get('registered_hash') or '')[:12]}` "
        f"registered, `{(for_run.get('code_hash') or '')[:12]}` running. A run "
        "started now would claim a version it is not executing.", icon="⚠️")
elif matches is None:
    st.info("Nothing to compare against yet. Register the deployed code below "
            "to stamp it with a fingerprint, after which drift becomes "
            "visible.", icon="ℹ️")

st.markdown("## Registered versions")
if versions.empty:
    caption("Nothing registered yet.")
else:
    show = versions.copy()
    show["active"] = show["active"].map({True: "●", False: ""})
    show["archived"] = show["archived"].map({True: "yes", False: "no"})
    show["code_hash"] = show["code_hash"].astype(str).str[:12]
    st.dataframe(
        show[["active", "id", "label", "code_hash", "archived", "created_at",
              "created_by", "description"]],
        hide_index=True, use_container_width=True,
        column_config={
            "active": st.column_config.TextColumn("", width="small"),
            "code_hash": st.column_config.TextColumn("Fingerprint"),
            "archived": st.column_config.TextColumn("Code archived"),
        })

    ids = list(versions["id"])
    current = for_run.get("id")
    others = [i for i in ids if i != current]
    if others:
        st.markdown("### Make another version active")
        caption("The active version is the one new runs select by default. "
                "Switching it does not change any run already produced.")
        c1, c2 = st.columns([3, 1])
        pick = c1.selectbox("Version", others, label_visibility="collapsed")
        if c2.button("Activate", use_container_width=True):
            with guard():
                api.activate_calculator(pick)
            api.calculator_versions.clear()
            st.success(f"{pick} is now the active calculator version.")
            st.rerun()

st.markdown("## Register the deployed code")
caption("Registering stamps the current code with a fingerprint and archives "
        "an immutable copy, so a future run can be compared against it — and "
        "so the code behind a past number can still be read.")

with st.form("register_calculator"):
    c1, c2 = st.columns(2)
    vid = c1.text_input("Version id", placeholder="v1.1",
                        help="Letters, digits, '.', '_' and '-' only.")
    label = c2.text_input("Label", placeholder="v1.1 — collateral join fixed")
    desc = st.text_area("What changed", height=80,
                        placeholder="Why this version exists, in a sentence or "
                                    "two. This is what somebody reads when a "
                                    "number from this quarter is questioned.")
    who = st.text_input("Registered by", value="")
    make_active = st.checkbox("Make this the active version", value=True)
    if st.form_submit_button("Register", type="primary"):
        if not vid.strip():
            st.error("A version id is required.")
        else:
            try:
                api.register_calculator(vid.strip(), label, desc, who,
                                        make_active)
            except api.BackendError as e:
                st.error(str(e))
            else:
                api.calculator_versions.clear()
                st.success(f"Registered {vid.strip()}.")
                st.rerun()

with st.expander("What the deployed code is, as git sees it"):
    if not code.get("available"):
        caption("This deployment is not a git checkout, which is why the "
                "registry exists: the fingerprint above is the record.")
    else:
        st.write(pd.DataFrame([{
            "commit": code.get("sha"),
            "branch": code.get("branch"),
            "last commit": code.get("last_commit_at"),
            "working tree": "modified" if code.get("dirty") else "clean",
        }]).T.rename(columns={0: ""}))
        if code.get("dirty"):
            st.warning("The working tree has uncommitted changes, so a run "
                       "produced now cannot be reproduced from its commit "
                       "alone.", icon="⚠️")
