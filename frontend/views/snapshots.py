"""Config snapshots: the frozen copy of everything a run is told."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, page_setup, pill

page_setup("Config snapshots",
           "A snapshot freezes the config and the static reference together, "
           "under a label, with a lifecycle of its own. \"What changed?\" is "
           "the first question asked of a provision that moved, and the "
           "answer has to be a file rather than a memory.")

with guard():
    reg = api.snapshots()

snaps = pd.DataFrame(reg["snapshots"])
labels = list(snaps["label"]) if not snaps.empty else []

STATUS_TONE = {"draft": "info", "tested": "warn", "pending_final": "warn",
               "approved": "ok", "rejected": "err", "archived": "info",
               "unknown": "err"}
NEXT = {"draft": ["tested"], "tested": ["pending_final", "draft"],
        "pending_final": ["approved", "rejected", "tested"],
        "approved": ["archived"], "rejected": ["draft"], "archived": []}

metric_row([
    ("Snapshots", str(len(snaps))),
    ("Approved", str(int((snaps["status"] == "approved").sum()) if not snaps.empty else 0)),
    ("Drafts", str(int((snaps["status"] == "draft").sum()) if not snaps.empty else 0)),
    ("Root", reg["root"].split("/")[-1] or "—"),
])

versions, editor, compare = st.tabs(["Versions", "Editor", "Compare"])

# ---------------------------------------------------------------- versions --
with versions:
    if snaps.empty:
        caption("No snapshots yet. Cut one below to freeze the live config.")
    else:
        st.dataframe(
            snaps[["label", "status", "description", "created_by", "created_at",
                   "parent", "base_source", "approved_by", "n_transitions"]],
            use_container_width=True, hide_index=True,
            column_config={"label": "Label", "status": "Status",
                           "description": "Description", "created_by": "Created by",
                           "created_at": "Created", "parent": "Based on",
                           "base_source": "Base", "approved_by": "Approved by",
                           "n_transitions": "Moves"})

    st.markdown("### Cut a new snapshot")
    caption("With a parent, the new version starts from THAT snapshot's frozen "
            "content rather than from the live config — so \"v3 based on v2\" "
            "literally begins as v2.")
    with st.form("create_snapshot"):
        c1, c2 = st.columns(2)
        label = c1.text_input("Label", placeholder="2026Q1",
                              help="Letters, digits, '.', '_' and '-' only.")
        parent = c2.selectbox("Based on", ["(the live config)"] + labels)
        desc = st.text_area("What this version is for", height=70)
        who = st.text_input("Created by")
        if st.form_submit_button("Create", type="primary"):
            if not label.strip():
                st.error("A label is required.")
            else:
                try:
                    api.create_snapshot(
                        label.strip(), desc, who,
                        None if parent.startswith("(") else parent)
                except api.BackendError as e:
                    st.error(str(e))
                else:
                    api.snapshots.clear()
                    st.success(f"Created {label.strip()}.")
                    st.rerun()

    if labels:
        st.markdown("### Move one along")
        caption("Every move needs a user and a reason — knowing who marked a "
                "snapshot tested, and why, is what makes the trail readable "
                "later. Where separation of duties is enforced, the creator "
                "may test and submit their own snapshot but somebody else "
                "must give the final approval.")
        pick = st.selectbox("Snapshot", labels, key="promote_pick")
        row = snaps[snaps["label"] == pick].iloc[0]
        st.markdown(f"Currently {pill(row['status'], STATUS_TONE.get(row['status'], 'info'))}",
                    unsafe_allow_html=True)
        options = NEXT.get(row["status"], [])
        if not options:
            caption("This snapshot is terminal — there is nowhere further to "
                    "take it.")
        else:
            with st.form("promote_snapshot"):
                target = st.selectbox("Move to", options)
                by = st.text_input("Your name")
                reason = st.text_area("Reason", height=70)
                if st.form_submit_button("Move", type="primary"):
                    if not by.strip() or not reason.strip():
                        st.error("Both your name and a reason are required.")
                    else:
                        try:
                            api.promote_snapshot(pick, target, by.strip(),
                                                 reason.strip())
                        except api.BackendError as e:
                            st.error(str(e))
                        else:
                            api.snapshots.clear()
                            api.snapshot_detail.clear()
                            st.success(f"{pick} is now {target}.")
                            st.rerun()

        with st.expander("History"):
            with guard():
                d = api.snapshot_detail(pick)
            trans = (d["meta"] or {}).get("transitions") or []
            if trans:
                st.dataframe(pd.DataFrame(trans), hide_index=True,
                             use_container_width=True)
            else:
                caption("No moves recorded yet.")

# ------------------------------------------------------------------ editor --
with editor:
    if not labels:
        caption("Nothing to edit yet.")
    else:
        pick = st.selectbox("Snapshot", labels, key="edit_pick")
        with guard():
            d = api.snapshot_detail(pick)
        status = (d["meta"] or {}).get("status", "unknown")
        if status != "draft":
            st.info(
                f"This snapshot is **{status}** and cannot be edited. Only a "
                "draft is editable — that is what `tested` is for, so the "
                "numbers being impact-tested cannot move underneath the test. "
                "Clone it to a new draft to make changes.", icon="🔒")

        files = pd.DataFrame(d["editable"])
        if files.empty:
            caption("This snapshot has no editable files.")
        else:
            show_adv = st.checkbox("Show advanced files", value=False)
            visible = files if show_adv else files[~files["advanced"].astype(bool)]
            groups = list(dict.fromkeys(visible["group"]))
            group = st.selectbox("Group", groups)
            sub = visible[visible["group"] == group]
            rel = st.selectbox("File", list(sub["relpath"]),
                               format_func=lambda r:
                               sub.loc[sub["relpath"] == r, "label"].iloc[0])
            helptext = sub.loc[sub["relpath"] == rel, "help"].iloc[0]
            if helptext:
                caption(helptext)

            with guard():
                content = api.snapshot_file(pick, rel)
            editable = status == "draft"

            if content["kind"] == "csv":
                if content["comment_header"]:
                    with st.expander("Provenance header (kept on save)"):
                        st.code("\n".join(content["comment_header"]),
                                language=None)
                df = pd.DataFrame(content["rows"])
                edited = st.data_editor(df, use_container_width=True,
                                        num_rows="dynamic" if editable else "fixed",
                                        disabled=not editable, key=f"ed_{rel}")
                who = st.text_input("Edited by", key=f"who_{rel}")
                if st.button("Save", type="primary", disabled=not editable,
                             key=f"save_{rel}"):
                    try:
                        r = api.edit_snapshot(
                            pick, rel, rows=edited.to_dict(orient="records"),
                            edited_by=who)
                    except api.BackendError as e:
                        st.error(str(e))
                    else:
                        api.snapshot_file.clear()
                        st.success(r["message"])
            else:
                text = st.text_area("Contents", content["text"], height=380,
                                    disabled=not editable, key=f"txt_{rel}")
                who = st.text_input("Edited by", key=f"who_{rel}")
                if st.button("Save", type="primary", disabled=not editable,
                             key=f"save_{rel}"):
                    try:
                        r = api.edit_snapshot(pick, rel, text=text,
                                              edited_by=who)
                    except api.BackendError as e:
                        st.error(str(e))
                    else:
                        api.snapshot_file.clear()
                        st.success(r["message"])
                caption("YAML is parsed before it is written. An unparseable "
                        "config does not fail at save time — it fails at the "
                        "next run, by which point nobody remembers editing it.")

# ----------------------------------------------------------------- compare --
with compare:
    if len(labels) < 2:
        caption("Two snapshots are needed to compare.")
    else:
        c1, c2 = st.columns(2)
        a = c1.selectbox("From", labels, key="diff_a")
        b = c2.selectbox("To", [x for x in labels if x != a], key="diff_b")
        with guard():
            d = api.diff_snapshots(a, b)
        metric_row([("Modified", str(len(d["files_modified"]))),
                    ("Added", str(len(d["files_added"]))),
                    ("Removed", str(len(d["files_removed"])))])
        caption("Compared by content hash, so a file carried forward unchanged "
                "does not read as a change.")
        if d["files_modified"]:
            m = pd.DataFrame(d["files_modified"])
            m["a_sha"] = m["a_sha"].str[:12]
            m["b_sha"] = m["b_sha"].str[:12]
            st.dataframe(m, hide_index=True, use_container_width=True,
                         column_config={"file": "File", "a_sha": f"{a} hash",
                                        "b_sha": f"{b} hash",
                                        "a_size": f"{a} bytes",
                                        "b_size": f"{b} bytes"})
        for title, items in (("Added", d["files_added"]),
                             ("Removed", d["files_removed"])):
            if items:
                st.markdown(f"**{title}**")
                for f in items:
                    st.text(f"  {f}")
        if not any((d["files_modified"], d["files_added"], d["files_removed"])):
            st.success("These two snapshots hold identical content.", icon="✅")
