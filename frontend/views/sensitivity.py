"""Sensitivity: which lever the provision turns on, and how far it would go.

Three questions about the same levers, each answered by repricing through the
one stress function (ifrs9qdb.stress.apply_stress), so their numbers agree
with a stress test built by hand:

* Each lever    every lever moved on its own from the same base, ranked
* To a target   how far each lever must move to raise the provision by a
                given share (reverse stress)
* Staging threshold
                the book repriced at each candidate Stage 2 days-past-due
                threshold, everything else held

They were three pages (Lever sensitivity, Reverse stress, Staging threshold).
Only the open tab is priced; a result stays on screen until the run changes.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, line, metric_row, money,
                page_setup, pct, signed)

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Sensitivity", "Which lever the provision turns on, and how far it "
           "would have to move")

with guard():
    sc = api.scope(run_id)
base_book = ", ".join(sc["internal"]) or "the internally rated portfolios"

each, target, threshold = st.tabs(["Each lever", "To a target",
                                   "Staging threshold"],
                                  key="sens_tab", on_change="rerun")

if each.open:
    with each:
        caption(f"Each lever moved on its own from the same base ({base_book}) "
                "and ranked by effect. The bars are comparable but do NOT add "
                "up: levers interact when combined, which is what a stress "
                "test with several levers is for.")
        if st.button("Price each lever", type="primary", key="sens_each_go"):
            S["sens_each"] = run_id
        if S.get("sens_each") != run_id:
            st.caption("The moves that will be applied, one at a time:")
            st.dataframe(pd.DataFrame(sc["levers"])[["label", "key", "value"]],
                         use_container_width=True, hide_index=True,
                         column_config={"label": "Move", "key": "Lever",
                                        "value": "Set to"})
        else:
            with guard():
                t = api.tornado(run_id)
            lv = pd.DataFrame(t["levers"])
            if len(lv) == 0:
                st.error("Nothing could be priced.")
            else:
                metric_row([
                    ("Provision at base", money(t["base"])),
                    ("Most sensitive to", lv.iloc[0]["lever"]),
                    ("That lever's effect", money(lv.iloc[0]["change"])),
                ])
                bar(lv, "lever", "change", diverging=True,
                    height=max(300, 34 * len(lv) + 80))
                st.dataframe(
                    fmt_table(lv[["lever", "provision", "change", "pct", "moved"]],
                              money_cols=("provision", "change", "moved"),
                              pct_cols=("pct",)),
                    use_container_width=True, hide_index=True)

if target.open:
    with target:
        caption("Instead of asking what a shock does, this asks how bad things "
                "would have to get. Each lever is solved on its own by "
                f"repricing {base_book} repeatedly and narrowing in, so the "
                "answer is found rather than read off a grid.")
        c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
        tgt = c1.number_input("Target provision increase (%)", 1.0, 500.0, 25.0,
                              5.0, key="sens_target_pct")
        if c2.button("Solve", type="primary", key="sens_target_go"):
            S["sens_target"] = (run_id, tgt)
        if S.get("sens_target") == (run_id, tgt):
            with guard():
                out = pd.DataFrame(api.reverse(run_id, tgt))
            if len(out) == 0:
                st.error("Nothing could be solved for this run.")
            else:
                reached = out[out["found"]]
                if len(reached):
                    st.success(f"The provision is most exposed to "
                               f"**{reached.iloc[0]['lever']}** — the smallest "
                               f"move needed to reach +{tgt:.0f}%.", icon="✅")
                else:
                    st.warning(f"No single lever reaches +{tgt:.0f}% on its "
                               "own. A combination would be needed; build it "
                               "on **Stress test**.", icon="⚠️")
                show = out.copy()
                show["reaches target"] = show["found"].map({True: "yes",
                                                            False: "no"})
                st.dataframe(
                    fmt_table(show[["lever", "required", "reaches target",
                                    "achieved_pct", "provision"]],
                              money_cols=("provision",),
                              pct_cols=("achieved_pct",)),
                    use_container_width=True, hide_index=True)
                caption("A lever that cannot reach the target reports the most "
                        "it achieves, rather than returning its boundary as if "
                        "it were an answer.")

if threshold.open:
    with threshold:
        caption("A policy debate about 30 versus 60 days is usually conducted "
                "without anybody having priced it. This prices it: "
                f"{base_book} restaged and repriced at each candidate Stage 2 "
                "days-past-due threshold, everything else held.")
        choices = st.multiselect(
            "Thresholds to price (days)", [0, 15, 30, 45, 60, 75, 90],
            default=[0, 30, 60, 90], key="sens_thr_days",
            help=f"The policy this run used ({sc['run_threshold']:g} days) is "
                 "always included.")
        days = ",".join(str(c) for c in sorted(choices))
        if st.button("Reprice", type="primary", disabled=not choices,
                     key="sens_thr_go"):
            S["sens_thr"] = (run_id, days)
        if choices and S.get("sens_thr") == (run_id, days):
            with guard():
                r = api.threshold_sweep(run_id, days)
            rows = pd.DataFrame(r["rows"])
            used = r["run_threshold"]
            base = rows.loc[rows["threshold"] == used, "ecl"]
            base = float(base.iloc[0]) if len(base) else float("nan")
            metric_row([
                ("Policy in force", f"{used:g} days"),
                ("Provision at that policy", money(base)),
                ("Widest alternative", signed(rows["ecl"].max() - base)),
                ("As a share",
                 pct(100 * (rows["ecl"].max() - base) / max(base, 1))),
            ])
            line(rows, "threshold", "ecl", title="Provision by threshold (days)")
            caption("Rarely a straight line, and usually much flatter than "
                    "people expect: most of the book is staged by watchlist, "
                    "restructuring and contagion rather than by days past due, "
                    "so moving the threshold moves comparatively little. That "
                    "is the finding.")
            col = f"vs_{used:g}"
            show = rows.copy()
            if col in show.columns:
                show[col] = show[col].map(signed)
            st.dataframe(
                fmt_table(show, money_cols=("ecl", "moved", "customers_moved"),
                          pct_cols=(f"{col}_pct",)),
                use_container_width=True, hide_index=True)
            bar(rows.assign(label=[f"{t:g} days" for t in rows["threshold"]]),
                "label", "customers_moved", title="Customers restaged")
