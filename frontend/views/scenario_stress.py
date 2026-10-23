"""Scenario stress: shocks on any macro variable, several at once, priced on
the run.

A scenario is a set of shocks (a variable, a size, a shape over the forecast
years); the macro model moves every other variable with them unless that is
switched off, and says how unusual the combination is. The paths reach the
provision through the PD model's drivers, a credit factor by sector, ratings
and stages, collateral, rates, drawn exposure and the external book, and the
book is repriced with the function the run priced with
(ifrs9qdb.stresstest.transmit). Scenarios are saved to the project's
config/stress_scenarios.yml, the file the R app uses.
"""
import io

import numpy as np
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money, page_setup, pct,
                signed, waterfall)

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Scenario stress",
           "Shock any macro variable, alone or together, and reprice the run. "
           "Nothing in the run is changed.")

with st.spinner("Reading the run and the macro model…"):
    with guard():
        su = api.scn_setup()
        cx = api.scn_context(run_id)
vint, H, Y0 = su["vintage"], int(su["horizon"]), int(cx["first_year"])
years = list(range(Y0, Y0 + H))
cons = pd.DataFrame(su["concepts"])
cons = cons[cons["in_model"]]
label_of = dict(zip(cons["concept"], cons["label"]))
concept_of = {v: k for k, v in label_of.items()}
unit_of = dict(zip(cons["concept"], cons["unit"]))
SHAPES = {"one_year": "One year", "held": "Held", "build": "Builds up",
          "recover": "Recovers", "custom": "Year by year"}
SHAPE_OF = {v: k for k, v in SHAPES.items()}
caption(f"Forecast years {Y0}–{Y0 + H - 1} · macro data {vint} · "
        f"provision {money(cx['ecl'])}")
for n in cx.get("notes") or []:
    caption(n)

library = {s["name"]: s for s in su["library"]}
saved = {s["name"]: s for s in su["saved"]}


def _editor_rows(scn: dict) -> pd.DataFrame:
    rows = []
    for s in scn.get("shocks") or []:
        if s["concept"] not in label_of:
            continue
        rows.append({"Variable": label_of[s["concept"]],
                     "Size": float(s.get("size") or 0),
                     "In": "sd" if s.get("unit") == "sd" else "units",
                     "Shape": SHAPES.get(s.get("shape", "one_year"), "One year"),
                     "From year": int(s.get("start") or 1),
                     "Over years": int(s.get("years") or 2),
                     "Year by year": ", ".join(f"{v:g}" for v in (s.get("path") or []))})
    return pd.DataFrame(rows, columns=["Variable", "Size", "In", "Shape", "From year",
                                       "Over years", "Year by year"])


def _num(v, d):
    return d if v is None or pd.isna(v) else v


def _from_editor(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.dropna(subset=["Variable"]).iterrows():
        c = concept_of.get(r["Variable"])
        if not c:
            continue
        shape = SHAPE_OF.get(r["Shape"], "one_year")
        sh = {"concept": c, "size": float(_num(r["Size"], 0)),
              "unit": "sd" if r["In"] == "sd" else "native", "shape": shape,
              "start": int(_num(r["From year"], 1)), "years": int(_num(r["Over years"], 2))}
        if shape == "custom":
            txt = str(_num(r["Year by year"], "")).replace(";", ",")
            try:
                sh["path"] = [float(t) for t in txt.split(",") if t.strip()]
            except ValueError:
                st.warning(f"{r['Variable']}: the year-by-year moves are not numbers.")
                sh["path"] = []
        out.append(sh)
    return out


def _load(scn: dict) -> None:
    S["scn_name"] = scn.get("name", "Scenario")
    S["scn_desc"] = scn.get("description", "")
    S["scn_knock"] = bool(scn.get("knock_on", True))
    S["scn_rows"] = _editor_rows(scn)
    S["scn_levers"] = scn.get("levers") or {}
    S["scn_ver"] = S.get("scn_ver", 0) + 1
    S.pop("scn_result", None)
    S.pop("scn_split", None)


if "scn_rows" not in S:
    _load(library[next(iter(library))])

tab_b, tab_c, tab_s, tab_r, tab_rev = st.tabs(
    ["Build and price", "Compare", "Sensitivity", "ECL at risk", "Reverse stress"])

# --------------------------------------------------------------- build --
with tab_b:
    c = st.columns([4, 1], vertical_alignment="bottom")
    opts = ([f"Library: {n}" for n in library] + [f"Saved: {n}" for n in saved]
            + ["Blank"])
    pick = c[0].selectbox("Start from", opts, key="scn_pick")
    if c[1].button("Load", use_container_width=True):
        if pick == "Blank":
            _load({"name": "New scenario", "shocks": []})
        else:
            kind, name = pick.split(": ", 1)
            _load((library if kind == "Library" else saved)[name])
        st.rerun()

    c = st.columns([2, 4])
    name = c[0].text_input("Name", key="scn_name")
    desc = c[1].text_input("Description", key="scn_desc")
    rows = st.data_editor(
        S["scn_rows"], key=f"scn_ed_{S['scn_ver']}", num_rows="dynamic",
        use_container_width=True, hide_index=True,
        column_config={
            "Variable": st.column_config.SelectboxColumn(
                options=sorted(label_of.values()), required=True, width="large"),
            "Size": st.column_config.NumberColumn(
                format="%.2f", help="In the variable's own unit (points or %), or in "
                                    "standard deviations of its history."),
            "In": st.column_config.SelectboxColumn(options=["units", "sd"], default="units"),
            "Shape": st.column_config.SelectboxColumn(options=list(SHAPES.values()),
                                                      default="One year"),
            "From year": st.column_config.NumberColumn(min_value=1, max_value=H, step=1,
                                                       default=1),
            "Over years": st.column_config.NumberColumn(
                min_value=1, max_value=H, step=1, default=2,
                help="Builds up: years to full size. Recovers: years back to zero."),
            "Year by year": st.column_config.TextColumn(
                help="For 'Year by year': the move in each forecast year, "
                     "comma separated."),
        })
    knock = st.toggle("Move the other variables with the shocks (macro model)",
                      key="scn_knock")
    with guard():
        pk = api.packages_saved()
    pk_names = ["None"] + [p["name"] for p in pk]
    cur_lev = S.get("scn_levers") or {}
    lev_pick = st.selectbox(
        "Parameter stress on top", pk_names,
        pk_names.index(cur_lev.get("name")) if cur_lev.get("name") in pk_names else 0,
        help="A saved package from Stress test, applied after the macro paths.")
    levers = {} if lev_pick == "None" else next(p for p in pk if p["name"] == lev_pick)
    scn = {"name": name or "Scenario", "description": desc, "shocks": _from_editor(rows),
           "knock_on": knock, "levers": levers}

    if scn["shocks"]:
        with guard():
            pv = api.scn_preview(scn, None, Y0)
        sev = pv["severity"]
        caption(f"Severity: {sev['distance']:.2f} standard deviations from the "
                f"baseline jointly, about 1 in {sev['one_in']:,.0f}.")
        pt = pd.DataFrame(pv["paths"])
        if len(pt):
            show = pt[["label"] + [str(y) for y in years]].copy()
            show.insert(1, "set", np.where(pt["given"], "shock", "knock-on"))
            show = show.rename(columns={"label": "variable"})
            with st.expander("Paths: change from the baseline forecast", expanded=False):
                st.dataframe(show.style.format({str(y): "{:+.2f}" for y in years}),
                             use_container_width=True, hide_index=True)

    b = st.columns(3)
    go = b[0].button("Price", type="primary", use_container_width=True,
                     disabled=not (scn["shocks"] or levers))
    split = b[1].button("Split by shock", use_container_width=True,
                        disabled=len(scn["shocks"]) + bool(levers) < 2,
                        help="Each shock's share of the change (Shapley values): "
                             "2^n repricings, a few seconds each.")
    if b[2].button("Save", use_container_width=True,
                   help="To config/stress_scenarios.yml. The R app reads the same file."):
        keep = [s for n, s in saved.items() if n != scn["name"]] + [scn]
        with guard():
            api.scn_saved_put(keep)
        st.success(f"Saved {scn['name']}.", icon="✅")
    if go:
        with st.spinner("Repricing…"):
            with guard():
                S["scn_result"] = (run_id, api.scn_run(run_id, scn))
        S.pop("scn_split", None)
    if split:
        with st.spinner("Pricing every combination of the shocks…"):
            with guard():
                S["scn_split"] = (run_id, api.scn_shapley(run_id, scn))

    res = S.get("scn_result")
    if res and res[0] == run_id:
        r = res[1]
        sev = r.get("severity") or {}
        metric_row([("Provision now", money(r["before"])),
                    ("Under the scenario", money(r["after"])),
                    ("Change", signed(r["delta"])), ("% change", pct(r["pct"])),
                    ("Severity", f"1 in {sev.get('one_in', 1):,.0f}")])
        wf = pd.DataFrame(r["waterfall"])
        wf = wf[wf["change"].abs() >= 0.5]
        steps = pd.concat([pd.DataFrame([{"label": "Provision now", "amount": r["before"],
                                          "kind": "total"}]),
                           pd.DataFrame({"label": wf["layer"], "amount": wf["change"],
                                         "kind": "step"}),
                           pd.DataFrame([{"label": "Under the scenario",
                                          "amount": r["after"], "kind": "total"}])])
        waterfall(steps, zoom=True)
        c1, c2 = st.columns(2)
        with c1:
            bs = pd.DataFrame(r["by_segment"]).rename(columns={"segment": "sector"})
            bar(bs.head(12), "sector", "change", diverging=True, title="By sector")
        with c2:
            bp = pd.DataFrame(r["by_portfolio"])
            bar(bp, "portfolio", "change", diverging=True, title="By portfolio")
        mig = pd.DataFrame(r.get("migration") or [])
        if len(mig):
            st.markdown("**Stage moves**")
            st.dataframe(fmt_table(mig, money_cols=("contracts", "customers", "exposure",
                                                    "ecl_change")),
                         use_container_width=True, hide_index=True)
        bc = pd.DataFrame(r.get("by_customer") or [])
        if len(bc):
            bc = bc[bc["change"].abs() > 0]
            cols = [x for x in ("customer", "facilities", "stage", "stage_after", "exposure",
                                "ecl_before", "ecl_after", "change") if x in bc]
            with st.expander("Customers most affected"):
                st.dataframe(fmt_table(bc[cols], money_cols=("facilities", "exposure",
                                                             "ecl_before", "ecl_after",
                                                             "change")),
                             use_container_width=True, hide_index=True)
        sp = S.get("scn_split")
        if sp and sp[0] == run_id:
            parts = pd.DataFrame(sp[1]["parts"])
            st.markdown("**Split by shock**")
            bar(parts, "part", "shapley", diverging=True)
            caption(f"Alone the shocks add to {signed(sp[1]['sum_alone'])}; together "
                    f"{signed(sp[1]['total'])}. The difference, "
                    f"{signed(sp[1]['interaction'])}, is how they compound, shared out "
                    "in the split.")
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            pd.DataFrame([{"scenario": r["name"], "before": r["before"], "after": r["after"],
                           "change": r["delta"], "change_pct": r["pct"],
                           "one_in": sev.get("one_in"), "macro_data": vint}]
                         ).to_excel(xw, sheet_name="Summary", index=False)
            pd.DataFrame(scn["shocks"]).to_excel(xw, sheet_name="Shocks", index=False)
            pd.DataFrame(r["paths"]).to_excel(xw, sheet_name="Paths", index=False)
            pd.DataFrame(r["waterfall"]).to_excel(xw, sheet_name="Waterfall", index=False)
            for k in ("by_segment", "by_portfolio", "by_book", "by_stage", "migration"):
                pd.DataFrame(r.get(k) or []).to_excel(
                    xw, sheet_name=k.replace("by_", "By ").replace("_", " ").title(),
                    index=False)
            if sp and sp[0] == run_id:
                pd.DataFrame(sp[1]["parts"]).to_excel(xw, sheet_name="Split", index=False)
        st.download_button("Download (Excel)", buf.getvalue(),
                           f"scenario_{r['name'][:40]}.xlsx".replace(" ", "_"))

# ------------------------------------------------------------- compare --
with tab_c:
    allsc = {**{f"Library: {n}": s for n, s in library.items()},
             **{f"Saved: {n}": s for n, s in saved.items()}}
    chosen = st.multiselect("Scenarios", list(allsc), list(allsc)[:4])
    if st.button("Compare", type="primary", disabled=not chosen):
        with st.spinner(f"Repricing {len(chosen)} scenarios…"):
            with guard():
                S["scn_cmp"] = (run_id, api.scn_compare(run_id, [allsc[k] for k in chosen]))
    cm = S.get("scn_cmp")
    if cm and cm[0] == run_id:
        t = pd.DataFrame(cm[1]["table"])
        t = t.sort_values("change", ascending=False)
        bar(t, "scenario", "change", diverging=True, title="Change in provision")
        lay = pd.DataFrame(cm[1]["layers"])
        if len(lay):
            import plotly.express as px
            fig = px.bar(lay, x="change", y="scenario", color="layer", orientation="h",
                         height=max(260, 46 * len(t) + 100))
            fig.update_layout(margin=dict(l=8, r=8, t=8, b=8), plot_bgcolor="white",
                              paper_bgcolor="white", legend_title_text="",
                              xaxis=dict(tickformat=","), yaxis=dict(title=""))
            st.plotly_chart(fig, use_container_width=True)
        t["one_in"] = t["one_in"].map(lambda v: f"1 in {v:,.0f}" if v else "—")
        st.dataframe(fmt_table(t, money_cols=("ecl", "change", "moved"),
                               pct_cols=("change_pct",))
                     .rename(columns={"ecl": "provision", "change_pct": "% change",
                                      "one_in": "severity", "moved": "re-staged"}),
                     use_container_width=True, hide_index=True)
        caption("Each scenario is priced on its own from the same run.")

# --------------------------------------------------------- sensitivity --
with tab_s:
    c = st.columns([2, 3, 2], vertical_alignment="bottom")
    size = c[0].number_input("Adverse move (standard deviations)", 0.25, 5.0, 1.0, 0.25)
    kn = c[1].toggle("Move the other variables with it", value=False, key="sens_knock")
    if c[2].button("Run", type="primary", use_container_width=True, key="sens_go"):
        with st.spinner("One repricing per variable…"):
            with guard():
                S["scn_sens"] = (run_id, api.scn_sensitivity(run_id, size, kn))
    se = S.get("scn_sens")
    if se and se[0] == run_id:
        t = pd.DataFrame(se[1]["table"])
        if len(t):
            t["variable"] = t["label"] + " (" + t["move"] + ")"
            bar(t, "variable", "change", diverging=True)
            st.dataframe(fmt_table(t[["label", "channel", "move", "move_native", "change",
                                      "change_pct"]],
                                   money_cols=("change",), pct_cols=("change_pct",))
                         .rename(columns={"label": "variable", "move_native": "in units",
                                          "change_pct": "% change"}),
                         use_container_width=True, hide_index=True)
            hm = pd.DataFrame(se[1]["heat"])
            if len(hm):
                pv = hm.pivot_table(index="label", columns="segment", values="change_pct")
                with st.expander("By sector (% change)"):
                    st.dataframe(pv.style.format("{:+.1f}%", na_rep="—")
                                 .background_gradient(cmap="Reds", axis=None),
                                 use_container_width=True)

# ---------------------------------------------------------- ECL at risk --
with tab_r:
    c = st.columns(4, vertical_alignment="bottom")
    n = c[0].number_input("Paths", 200, 20000, 2000, 200)
    seed = c[1].number_input("Seed", 1, 2 ** 31 - 2, 20261023, 1)
    thr = c[2].number_input("Provision threshold (QAR m, optional)", 0.0, value=0.0,
                            step=50.0)
    if c[3].button("Simulate", type="primary", use_container_width=True):
        with st.spinner("Drawing macro paths and pricing them (a minute or two the "
                        "first time)…"):
            with guard():
                S["scn_risk"] = (run_id, api.scn_risk(run_id, int(n), int(seed),
                                                      thr * 1e6 if thr else None))
    rk = S.get("scn_risk")
    if rk and rk[0] == run_id:
        r = rk[1]
        sm = pd.DataFrame(r["summary"])
        items = [("Provision now", money(r["base"])), ("Mean over paths", money(r["mean"]))]
        for _, x in sm.iterrows():
            items.append((f"{x['measure']} ({signed(x['change'])})", money(x["value"])))
        if r.get("p_exceed") is not None:
            items.append(("Chance above threshold", pct(100 * r["p_exceed"], 1)))
        metric_row(items)
        import plotly.graph_objects as go_
        h = pd.DataFrame(r["histogram"])
        fig = go_.Figure(go_.Bar(x=(h["from"] + h["to"]) / 2, y=h["count"],
                                 width=(h["to"] - h["from"]), marker_color="#7a4b8c"))
        for _, x in sm.iterrows():
            fig.add_vline(x=x["value"], line_dash="dash", line_color="#c0392b",
                          annotation_text=x["measure"].replace("ECL at ", ""))
        fig.add_vline(x=r["base"], line_color="#2a2f3a", annotation_text="now")
        fig.update_layout(height=320, margin=dict(l=8, r=8, t=24, b=8),
                          plot_bgcolor="white", paper_bgcolor="white", bargap=0,
                          xaxis=dict(tickformat=",", title="Provision"),
                          yaxis=dict(title="Paths"))
        st.plotly_chart(fig, use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            ch = pd.DataFrame(r["by_channel"]).rename(columns={"tail_change": "change"})
            bar(ch, "channel", "change", diverging=True, title="What drives the tail")
        with c2:
            bs = pd.DataFrame(r["by_segment"]).rename(columns={"tail_change": "change",
                                                                "segment": "sector"})
            bar(bs.head(10), "sector", "change", diverging=True, title="Tail by sector")
        nm = pd.DataFrame(r["named"])
        if len(nm):
            st.markdown("**Where the scenarios fall**")
            st.dataframe(fmt_table(nm, money_cols=("proxy_change",))
                         .assign(percentile=nm["percentile"].map(lambda v: f"{v:.1f}"))
                         .rename(columns={"proxy_change": "change"}),
                         use_container_width=True, hide_index=True)
        ls = pd.DataFrame(r.get("loss_summary") or [])
        if len(ls):
            st.markdown("**Credit loss over the next year** (customers defaulting at "
                        "their stressed PD)")
            metric_row([("Expected loss", money(r.get("expected_loss")))] +
                       [(x["measure"], money(x["value"])) for _, x in ls.iterrows()])
            cu = pd.DataFrame(r.get("customers") or [])
            if len(cu):
                with st.expander("Customers behind the tail"):
                    st.dataframe(fmt_table(cu, money_cols=("exposure", "tail_loss"))
                                 .assign(pd12=cu["pd12"].map(lambda v: f"{100 * v:.2f}%"),
                                         lgd=cu["lgd"].map(lambda v: f"{100 * v:.0f}%")),
                                 use_container_width=True, hide_index=True)
        with st.expander("Check the path pricing against full repricing"):
            if st.button("Run the check"):
                with st.spinner("Repricing the library in full…"):
                    with guard():
                        S["scn_pc"] = (run_id, api.scn_proxy_check(run_id))
            pc = S.get("scn_pc")
            if pc and pc[0] == run_id:
                t = pd.DataFrame(pc[1]["table"])
                st.dataframe(fmt_table(t, money_cols=("full", "proxy", "gap"),
                                       pct_cols=("gap_pct_of_full",)),
                             use_container_width=True, hide_index=True)

# ------------------------------------------------------- reverse stress --
with tab_rev:
    c = st.columns([3, 1], vertical_alignment="bottom")
    tgt = c[0].number_input("Increase in provision to reach (QAR m)", 1.0, value=300.0,
                            step=50.0)
    if c[1].button("Find the path", type="primary", use_container_width=True):
        with st.spinner("Searching, then confirming with a full repricing…"):
            with guard():
                S["scn_rev"] = (run_id, api.scn_reverse(run_id, tgt * 1e6))
    rv = S.get("scn_rev")
    if rv and rv[0] == run_id:
        r = rv[1]
        if not r.get("found"):
            st.info(r.get("reason") or "No path found.")
        else:
            metric_row([("Target", signed(r["target"])),
                        ("Confirmed change", signed(r.get("full_change"))),
                        ("Distance", f"{r['distance']:.2f} sd"),
                        ("Likelihood", f"1 in {r['one_in']:,.0f}")])
            caption("The most likely combination of macro moves that raises the "
                    "provision by the target: the one nearest the baseline, given how "
                    "the variables have moved together.")
            t = pd.DataFrame(r["paths"])
            if len(t):
                yc = [c_ for c_ in t.columns if c_.isdigit()]
                st.dataframe(t[["label", "worst_sd"] + yc]
                             .rename(columns={"label": "variable", "worst_sd": "worst (sd)"})
                             .style.format({"worst (sd)": "{:+.2f}",
                                            **{y: "{:+.2f}" for y in yc}}),
                             use_container_width=True, hide_index=True)
            if r.get("waterfall"):
                wf = pd.DataFrame(r["waterfall"])
                wf = wf[wf["change"].abs() >= 0.5]
                bar(wf, "layer", "change", diverging=True, title="Through which channel")
