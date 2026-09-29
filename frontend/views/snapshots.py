"""Config versions: the frozen copy of everything a run is told.

The R app's three config pages in one: browse versions (metadata and every
frozen file), manage them (create, move through draft -> tested ->
pending_final -> approved), and edit a draft (CSV tables and YAML), with clone
-to-draft for a version that is locked.
"""
import io
import re

import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, page_setup, pill, flash

page_setup("Config versions",
           "A version freezes the config and the static reference together, "
           "under a label, with a lifecycle of its own. Versions are created "
           "explicitly and are independent of the run history, so a run can be "
           "reproduced exactly months later by pinning a version label.")

if st.button("Refresh", key="sn_refresh"):
    api.clear()
    st.rerun()

with guard():
    reg = api.snapshots()

snaps = pd.DataFrame(reg["snapshots"])
labels = list(snaps["label"]) if not snaps.empty else []

STATUS_TONE = {"draft": "info", "tested": "warn", "pending_final": "warn",
               "approved": "ok", "rejected": "err", "archived": "info",
               "unknown": "err"}

caption(f"versions directory: `{reg['root']}` · {len(snaps)} versions")
metric_row([
    ("Versions", str(len(snaps))),
    ("Approved", str(int((snaps["status"] == "approved").sum()) if not snaps.empty else 0)),
    ("Drafts", str(int((snaps["status"] == "draft").sum()) if not snaps.empty else 0)),
    ("Awaiting approval", str(int(snaps["status"].isin(["pending_final", "pending"]).sum())
                              if not snaps.empty else 0)),
])

versions, manage, editor, compare = st.tabs(
    ["Versions", "Manage", "Edit config", "Compare"])

# ================================================================ versions ==
with versions:
    if snaps.empty:
        st.info("No versions found yet. A version is a frozen, named copy of the "
                "configuration — different from a run. Create one on the Manage tab.")
    else:
        show = snaps[["label", "status", "created_at", "created_by", "parent",
                      "description"]].copy()
        show["code_sha"] = (snaps["code_sha_at_creation"].astype(str).str[:8]
                            if "code_sha_at_creation" in snaps.columns else "")
        ev = st.dataframe(show, hide_index=True, use_container_width=True,
                          on_select="rerun", selection_mode="single-row",
                          key="sn_tbl")
        rows = ev.selection.rows if ev and ev.selection else []
        if not rows:
            caption("Select a version above to see its metadata and files.")
        else:
            lbl = show.iloc[rows[0]]["label"]
            with guard():
                tree = api.snapshot_tree(lbl)
            meta = tree["meta"]
            st.subheader(f"Version {lbl}")
            t_meta, t_files = st.tabs(["Metadata", "Files"])
            with t_meta:
                st.markdown(f"status {pill(meta.get('status') or '?', STATUS_TONE.get(meta.get('status'), 'info'))}",
                            unsafe_allow_html=True)
                st.table(pd.DataFrame({"": [
                    meta.get(k) or "—" for k in
                    ("label", "description", "created_at", "created_by", "parent",
                     "code_sha_at_creation", "approved_by", "approved_at",
                     "approval_reason")]},
                    index=["label", "description", "created_at", "created_by",
                           "parent", "code_sha at creation", "approved_by",
                           "approved_at", "approval_reason"]).astype(str))
                if meta.get("transitions"):
                    st.markdown("**Status history**")
                    st.dataframe(pd.DataFrame(meta["transitions"]), hide_index=True,
                                 use_container_width=True)
            with t_files:
                files = tree["files"]
                if not files:
                    caption("(no files)")
                else:
                    c1, c2 = st.columns([4, 1])
                    rel = c1.selectbox("File", [f["relpath"] for f in files],
                                       key=f"sn_file_{lbl}")
                    if c2.button("Reload from disk", key=f"sn_rl_{lbl}"):
                        api.clear()
                    with guard():
                        raw = api.snapshot_raw(lbl, rel)
                    caption(f"path: `{raw['path']}` · {raw['size']:,} bytes")
                    if raw["too_large"]:
                        st.info(f"(file too large to preview: {raw['size']:,} bytes)")
                    else:
                        st.code(raw["text"], language="yaml" if rel.endswith((".yml", ".yaml"))
                                else None)

# ================================================================== manage ==
with manage:
    left, right = st.columns([5, 7])
    with left:
        with st.container(border=True):
            st.markdown("**Create version**")
            with st.form("create_snapshot"):
                label = st.text_input("Label", placeholder="e.g. 2026-Q2-draft-1",
                                      help="Letters, digits, '.', '_' and '-' only.")
                desc = st.text_area("Description",
                                    placeholder="What's in this version? Why was it created?",
                                    height=80)
                base = st.selectbox("Base version (content copied from)",
                                    ["(default config — first version)"]
                                    + [f"{r['label']} [{r['status']}]"
                                       for r in reg["snapshots"]])
                who = st.text_input("Created by")
                caption("The new version starts as a copy of the base version's "
                        "config/ and static/. Pick the version to build on (v3 = "
                        "v2 + your edits); the default config only for the very "
                        "first version.")
                if st.form_submit_button("Create version", type="primary"):
                    lab = label.strip()
                    if not lab:
                        st.error("Label is required.")
                    elif not re.fullmatch(r"[A-Za-z0-9._-]+", lab):
                        st.error("Label must contain only letters, digits, '.', '_', '-'.")
                    elif not desc.strip():
                        st.error("Description is required (audit trail).")
                    else:
                        parent = None if base.startswith("(") else base.split(" [")[0]
                        try:
                            api.create_snapshot(lab, desc.strip(), who, parent)
                        except api.BackendError as e:
                            st.error(str(e))
                        else:
                            api.clear()
                            flash(f"Created version: {lab}")
                            st.rerun()
    with right:
        with st.container(border=True):
            st.markdown("**Promote version**")
            caption("draft → tested → pending_final → approved. Each move needs a "
                    "reason and is recorded in the audit log. Use a draft in "
                    "unofficial runs to test its impact, mark it tested, submit it, "
                    "and a different user approves it for official runs.")
            if not labels:
                caption("Create a version first.")
            else:
                rank = {"draft": 0, "tested": 1, "pending_final": 2, "approved": 3,
                        "rejected": 4, "archived": 5}
                ordered = sorted(reg["snapshots"],
                                 key=lambda r: (rank.get(r["status"], 9), r["created_at"]))
                opts = {f"{r['label']} [{r['status']}]": r["label"] for r in ordered}
                pick = opts[st.selectbox("Version", list(opts), key="sn_promote")]
                acting = st.text_input("Acting as (your name)", key="sn_actor")
                with guard():
                    ctx = api.promote_context(pick, acting or None)
                m = ctx["meta"]
                st.table(pd.DataFrame({"": [
                    ctx["status"], m.get("description") or "—",
                    ctx["created_by"] or "?", ctx["acting_as"],
                    "Yes" if ctx["enforced"] else "No (dev mode)",
                    m.get("approved_by") or "—", m.get("approved_at") or "—",
                    m.get("approval_reason") or "—"]},
                    index=["status", "description", "created by", "acting as",
                           "separation enforced", "approved_by", "approved_at",
                           "approval_reason"]).astype(str))
                if not ctx["allowed"]:
                    caption(f"No transitions allowed from status '{ctx['status']}'.")
                else:
                    reason = st.text_area("Reason / notes (required)", height=70,
                                          key=f"sn_reason_{pick}")
                    cols = st.columns(len(ctx["allowed"]))
                    for col, target in zip(cols, ctx["allowed"]):
                        blocked = target == "approved" and ctx["creator_cannot_approve"]
                        if col.button(f"→ {target}", key=f"sn_to_{target}",
                                      disabled=blocked,
                                      type="primary" if target == "approved" else "secondary"):
                            if not reason.strip():
                                st.warning("Reason is required for any transition.")
                            else:
                                try:
                                    api.promote_snapshot(pick, target, ctx["acting_as"],
                                                         reason.strip())
                                except api.BackendError as e:
                                    st.error(str(e))
                                else:
                                    api.clear()
                                    flash(f"Version {pick} -> {target}")
                                    st.rerun()
                        if blocked:
                            col.caption("(maker can't approve own work)")
    st.markdown("#### Config version history")
    if snaps.empty:
        caption("No versions yet. Create one above.")
    else:
        st.dataframe(pd.DataFrame({
            "version": snaps["label"], "status": snaps["status"],
            "created_by": snaps["created_by"].replace("", "—"),
            "approved_by": snaps["approved_by"].replace("", "—"),
            "date": snaps["created_at"].astype(str).str[:16].str.replace("T", " ")}),
            hide_index=True, use_container_width=True)

# ================================================================== editor ==
with editor:
    with st.expander("How to use this page"):
        st.markdown("1. Pick a **draft** version (any other status shows a "
                    "clone-to-draft form).\n2. Pick a file: CSVs open as an "
                    "editable table (or download, edit in Excel, re-upload); YAML "
                    "in a text editor.\n3. Save is atomic — the whole file writes "
                    "or nothing changes.\n4. When done: **Manage** → tested → "
                    "pending_final; a reviewer approves on the **Approval queue**.")
    if not labels:
        caption("Nothing to edit yet.")
    else:
        rank = {"draft": 0, "tested": 1, "pending_final": 2, "approved": 3}
        ordered = sorted(reg["snapshots"], key=lambda r: (rank.get(r["status"], 9),
                                                          r["created_at"]))
        eopts = {f"{r['label']} [{r['status']}]": r["label"] for r in ordered}
        epick = eopts[st.selectbox("Version", list(eopts), key="sn_edit")]
        with guard():
            d = api.snapshot_detail(epick)
        meta = d["meta"] or {}
        status = meta.get("status", "unknown")
        if status != "draft":
            st.warning(f"This version is in status '{status}'. Edits are locked. "
                       "Clone it to a new draft below to make a revision.", icon="🔒")
            with st.form("clone_form"):
                st.markdown("**Clone to a new draft**")
                caption("The new draft inherits everything and is free to edit; "
                        "the lineage (parent) is preserved.")
                new_label = st.text_input("New label", placeholder="e.g. 2026-Q3-draft-1")
                new_desc = st.text_area("Description", height=60,
                                        placeholder="What's the goal of this revision?")
                who = st.text_input("Created by")
                if st.form_submit_button("Clone to new draft", type="primary"):
                    try:
                        api.clone_snapshot(epick, new_label.strip(), new_desc.strip(), who)
                    except api.BackendError as e:
                        st.error(str(e))
                    else:
                        api.clear()
                        flash(f"Cloned {epick} -> {new_label.strip()} (draft)")
                        st.rerun()
        else:
            base_src = str(meta.get("base_source") or "")
            based = (f"based on {base_src.split(':', 1)[1]}" if base_src.startswith("snapshot:")
                     else f"based on {meta.get('parent')}" if meta.get("parent")
                     else "based on the live config (first version)")
            st.markdown(f"**Draft: {epick}** · {based}"
                        + (f" · *{meta.get('description')}*" if meta.get("description") else ""))
            files = pd.DataFrame(d["editable"])
            if files.empty:
                caption("This version has no editable files.")
            else:
                show_adv = st.checkbox("Advanced files", value=False)
                visible = files if show_adv else files[~files["advanced"].astype(bool)]
                groups = list(dict.fromkeys(visible["group"]))
                group = st.selectbox("Group", groups)
                sub = visible[visible["group"] == group]
                rel = st.selectbox("File", list(sub["relpath"]),
                                   format_func=lambda r: f"{sub.loc[sub['relpath'] == r, 'label'].iloc[0]}"
                                                         f"  ({r.split('/')[-1]})")
                helptext = sub.loc[sub["relpath"] == rel, "help"].iloc[0]
                if helptext:
                    with st.expander(f"{rel.split('/')[-1]} — what is this?"):
                        st.write(helptext)
                with guard():
                    content = api.snapshot_file(epick, rel)
                who = st.text_input("Edited by", key=f"who_{rel}")
                if content["kind"] == "csv":
                    buf_key = f"csvbuf_{epick}_{rel}"
                    if buf_key not in st.session_state:
                        st.session_state[buf_key] = pd.DataFrame(content["rows"],
                                                                 columns=content.get("columns"))
                    t1, t2, t3, t4 = st.columns([1, 1, 2, 1])
                    header = content.get("comment_header") or []
                    csv_text = ("\n".join(header) + "\n" if header else "") + \
                        st.session_state[buf_key].to_csv(index=False)
                    t1.download_button("Download", csv_text, file_name=rel.split("/")[-1],
                                       mime="text/csv")
                    if t2.button("Discard", key=f"disc_{rel}"):
                        st.session_state.pop(buf_key, None)
                        api.clear()
                        st.rerun()
                    up = t3.file_uploader("Upload CSV", type=["csv"], key=f"up_{rel}",
                                          label_visibility="collapsed")
                    if up is not None and st.session_state.get(f"upk_{rel}") != up.file_id:
                        st.session_state[f"upk_{rel}"] = up.file_id
                        lines = up.getvalue().decode("utf-8-sig").splitlines()
                        skip = 0
                        while skip < len(lines) and lines[skip].lstrip().startswith("#"):
                            skip += 1
                        new = pd.read_csv(io.StringIO("\n".join(lines[skip:])), dtype=str,
                                          keep_default_na=False)
                        cur = st.session_state[buf_key]
                        if [c.strip() for c in new.columns] != [str(c).strip() for c in cur.columns]:
                            st.error("Columns do not match. Expected: "
                                     + ", ".join(map(str, cur.columns)))
                        else:
                            for c in cur.columns:
                                if pd.api.types.is_numeric_dtype(cur[c]):
                                    new[c] = pd.to_numeric(new[c], errors="coerce")
                            st.session_state[buf_key] = new
                            st.success(f"Loaded {len(new)} rows — review, then Save.")
                    if header:
                        with st.expander("Provenance header (kept on save)"):
                            st.code("\n".join(header), language=None)
                    edited = st.data_editor(st.session_state[buf_key],
                                            use_container_width=True, num_rows="dynamic",
                                            key=f"ed_{epick}_{rel}")
                    if t4.button("Save", type="primary", key=f"save_{rel}"):
                        keep = ~edited.apply(lambda r: all(pd.isna(v) or str(v).strip() == ""
                                                           for v in r), axis=1)
                        edited = edited[keep]
                        try:
                            r = api.edit_snapshot(epick, rel,
                                                  rows=edited.astype(object).where(
                                                      pd.notna(edited), None).to_dict(orient="records"),
                                                  edited_by=who)
                        except api.BackendError as e:
                            st.error(f"Save failed: {e}")
                        else:
                            st.session_state[buf_key] = edited.reset_index(drop=True)
                            api.clear()
                            st.success(f"Saved ({len(edited)} rows). {r['message']}")
                else:
                    tkey = f"yaml_{epick}_{rel}"
                    if tkey not in st.session_state:
                        st.session_state[tkey] = content["text"]
                    text = st.text_area("Contents", key=tkey, height=460)
                    c1, c2, _ = st.columns([1, 1, 4])
                    if c1.button("Discard", key=f"ydisc_{rel}"):
                        st.session_state.pop(tkey, None)
                        api.clear()
                        st.rerun()
                    if c2.button("Save (validated)", type="primary", key=f"ysave_{rel}"):
                        try:
                            r = api.edit_snapshot(epick, rel, text=text, edited_by=who)
                        except api.BackendError as e:
                            msg = str(e)
                            st.error("YAML save failed — the file on disk was NOT "
                                     "changed.\n\n" + msg)
                            m = re.findall(r"line\s+(\d+),\s*column\s+(\d+)", msg)
                            if m:
                                ln = int(m[-1][0])
                                lines = text.splitlines()
                                lo, hi = max(1, ln - 4), min(len(lines), ln + 4)
                                snippet = "\n".join(
                                    f"{'▶' if i == ln else ' '} {i:4d} | {lines[i - 1]}"
                                    for i in range(lo, hi + 1))
                                st.markdown(f"**Context around line {ln} (▶ marks the line):**")
                                st.code(snippet, language=None)
                        else:
                            api.clear()
                            st.success(f"Saved {rel.split('/')[-1]}. {r['message']}")
                    caption("YAML is parsed before it is written: an unparseable "
                            "config is refused here rather than failing the next run.")

# ================================================================= compare ==
with compare:
    if len(labels) < 2:
        caption("Two versions are needed to compare.")
    else:
        c1, c2 = st.columns(2)
        a = c1.selectbox("From", labels, key="diff_a")
        b = c2.selectbox("To", [x for x in labels if x != a], key="diff_b")
        with guard():
            dd = api.diff_snapshots(a, b)
        metric_row([("Modified", str(len(dd["files_modified"]))),
                    ("Added", str(len(dd["files_added"]))),
                    ("Removed", str(len(dd["files_removed"])))])
        caption("Compared by content hash, so a file carried forward unchanged "
                "does not read as a change.")
        if dd["files_modified"]:
            mm = pd.DataFrame(dd["files_modified"])
            mm["a_sha"] = mm["a_sha"].str[:12]
            mm["b_sha"] = mm["b_sha"].str[:12]
            st.dataframe(mm, hide_index=True, use_container_width=True)
        for title, items in (("Added", dd["files_added"]),
                             ("Removed", dd["files_removed"])):
            if items:
                st.markdown(f"**{title}**")
                for f in items:
                    st.text(f"  {f}")
        if not any((dd["files_modified"], dd["files_added"], dd["files_removed"])):
            st.success("These two versions hold identical content.", icon="✅")
