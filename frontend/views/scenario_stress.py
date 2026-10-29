"""Scenario stress: a library or saved scenario priced on the run, side by
side with others, and the risk behind them.

    Price          one scenario: the provision under it, through the PD
                   model, stage moves and collateral, by sector, and what
                   drives it
    Compare        several scenarios on the same run
    Sensitivity    each variable moved one standard deviation the adverse
                   way, with its linked effects
    ECL at risk    the provision over thousands of macro paths
    Reverse stress what it takes to raise the provision by a given amount

Scenarios are built on Scenario library. Every price is a repricing of the
run through the function it was priced with (ifrs9qdb.stresstest); nothing in
the run is changed.
"""
import io

import pandas as pd
import streamlit as st

import api
import scenario_ui as su_
from ui import (ERR, OK, PLUM, TEAL, bar, caption, fmt_table, guard, metric_row, money,
                page_setup, pct, signed, waterfall)

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Scenario stress",
           "Price library and saved scenarios on the run, compare them, and measure "
           "the risk behind them. Build scenarios on Scenario library.")

with st.spinner("Reading the run and fitting the linked effects…"):
    with guard():
        su = api.scn_setup()
        cx = api.scn_context(run_id)
H, Y0 = int(cx["horizon"]), int(cx["first_year"])
years = list(range(Y0, Y0 + H))
ALL = {s["id"]: s for s in su["library"] + su["saved"]}
IDS = list(ALL)
st.caption(f"Y1 is {Y0} on this run · macro data {su['vintage']} · provision "
           f"{money(cx['ecl'])}", help=su_.HELP["shock"])
for n in cx.get("notes") or []:
    caption(n)

tab_p, tab_c, tab_s, tab_r, tab_v = st.tabs(
    ["Price", "Compare", "Sensitivity", "ECL at risk", "Reverse stress"])


def _wf_steps(r: dict) -> pd.DataFrame:
    wf = pd.DataFrame(r["waterfall"])
    return pd.concat([pd.DataFrame([{"label": "Provision now", "amount": r["before"],
                                     "kind": "total"}]),
                      pd.DataFrame({"label": wf["layer"], "amount": wf["change"],
                                    "kind": "step"}),
                      pd.DataFrame([{"label": "Under the scenario", "amount": r["after"],
                                     "kind": "total"}])])


# ------------------------------------------------------------------ price --
with tab_p:
    if S.get("scn_pick") not in IDS:
        S["scn_pick"] = IDS[0]
    c = st.columns([5, 2], vertical_alignment="bottom")
    c[0].selectbox("Scenario", IDS, key="scn_pick", format_func=lambda i: su_.option(ALL[i]))
    scn = ALL[S["scn_pick"]]
    with st.spinner(f"Pricing {scn['name']}…"):
        with guard():
            r = api.scn_price(run_id, scn)
    metric_row([("Provision now", money(r["before"])),
                ("Under the scenario", money(r["after"])),
                ("Change", signed(r["delta"])), ("% change", pct(r["pct"]))])
    left, right = st.columns([3, 2], gap="large")
    with left:
        waterfall(_wf_steps(r), zoom=True)
    with right:
        stg, col = r["staging"], r["collateral"]
        pdx = r.get("pd12") or {}
        lines = []
        if pdx.get("before") is not None:
            lines.append(f"**PD model** — the average 12-month PD of the performing book "
                         f"goes from {100 * pdx['before']:.2f}% to {100 * pdx['after']:.2f}%.")
        lines.append(f"**Stage moves** — about {stg['expected_moves']:,.0f} of "
                     f"{stg['eligible']:,} Stage 1 contracts move to Stage 2 "
                     f"({money(stg['expected_exposure'])} of exposure)"
                     + (f", {100 * stg['restructured']:.0f}% of them through the deferral "
                        "programme." if stg["restructured"] else "."))
        tr = [v for v in (col.get("trough") or {}).values()]
        if tr and min(tr) < 0:
            lines.append(f"**Collateral** — property prices at their lowest "
                         f"{min(tr):.1f}% below today's, on {col.get('contracts', 0):,} "
                         "contracts with property collateral.")
        else:
            lines.append("**Collateral** — property prices never fall below today's.")
        for ln in lines:
            st.markdown(ln)
        if st.button("What drives it", icon=":material/account_tree:",
                     help="The change split by main variable: each one's moves and what "
                          "they move through the linked effects."):
            with st.spinner("Pricing each main variable's part (up to a minute the first "
                            "time for a scenario with many)…"):
                with guard():
                    S["scn_drv"] = (run_id, S["scn_pick"], api.scn_drivers(run_id, scn))
    dv = S.get("scn_drv")
    if dv and dv[0] == run_id and dv[1] == S["scn_pick"]:
        d = dv[2]
        parts = pd.DataFrame(d["parts"])[["label", "change"]]
        bar(parts, "label", "change", diverging=True, title="What drives the change")
        caption("Each main variable's part is its own moves and everything they move "
                "through the linked effects, averaged over every order the parts could be "
                "added in, so the parts add up to the change.")
    c1, c2 = st.columns(2)
    with c1:
        bs = pd.DataFrame(r["by_segment"]).rename(columns={"segment": "sector"})
        bar(bs.head(10), "sector", "change", diverging=True, title="By sector")
    with c2:
        bp = pd.DataFrame(r["by_portfolio"])
        bar(bp, "portfolio", "change", diverging=True, title="By portfolio")
    with st.expander(f"The scenario on this run, {years[0]}–{years[-1]}"):
        st.markdown("**Forecast and scenario**",
                    help="Each moved variable's forecast in the macro data for the run's "
                         "years, and its value once the scenario's shocks are added.")
        su_.level_grid(r["paths"], su_.level_units(su["variables"]))
        st.markdown("**Shocks**", help=su_.HELP["shock"] + " " + su_.HELP["set"])
        su_.show_path_table(r["paths"], scn.get("refs") or {}, actual=True)
    bc = pd.DataFrame(r.get("by_customer") or [])
    if len(bc):
        cols = [x for x in ("customer", "facilities", "stage", "exposure", "ecl_before",
                            "ecl_after", "change") if x in bc]
        with st.expander("Customers most affected"):
            st.dataframe(fmt_table(bc[cols], money_cols=("facilities", "exposure",
                                                         "ecl_before", "ecl_after", "change")),
                         use_container_width=True, hide_index=True)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame([{"scenario": scn["name"], "category": su_.CAT.get(scn["category"]),
                       "run": run_id, "macro_data": su["vintage"], "first_year": Y0,
                       "before": r["before"], "after": r["after"], "change": r["delta"],
                       "change_pct": r["pct"], "stage_moves": r["staging"]["expected_moves"],
                       "deferral_share": r["staging"]["restructured"]}]
                     ).to_excel(xw, sheet_name="Summary", index=False)
        pd.DataFrame(r["waterfall"]).to_excel(xw, sheet_name="Channels", index=False)
        pd.DataFrame(r["paths"]).to_excel(xw, sheet_name="Paths", index=False)
        for k in ("by_segment", "by_portfolio", "by_book", "by_stage"):
            pd.DataFrame(r.get(k) or []).to_excel(
                xw, sheet_name=k.replace("by_", "By ").title(), index=False)
        if dv and dv[0] == run_id and dv[1] == S["scn_pick"]:
            pd.DataFrame(dv[2]["parts"]).to_excel(xw, sheet_name="Drivers", index=False)
    st.download_button("Download (Excel)", buf.getvalue(),
                       f"scenario_{scn['name'][:40]}.xlsx".replace(" ", "_"))

# ---------------------------------------------------------------- compare --
with tab_c:
    S.setdefault("scn_cmp_pick", [i for i in IDS if ALL[i]["category"] != "mine"][:6])
    chosen = st.multiselect("Scenarios", IDS, key="scn_cmp_pick",
                            format_func=lambda i: su_.option(ALL[i]))
    if st.button("Compare", type="primary", disabled=not chosen):
        with st.spinner(f"Pricing {len(chosen)} scenarios…"):
            with guard():
                S["scn_cmp"] = (run_id, api.scn_compare(run_id, [ALL[i] for i in chosen]))
    cm = S.get("scn_cmp")
    if cm and cm[0] == run_id:
        import plotly.express as px
        t = pd.DataFrame(cm[1]["table"]).sort_values("change", ascending=False)
        ch = pd.DataFrame(cm[1]["channels"])
        order = list(t["scenario"])[::-1]
        fig = px.bar(ch, x="change", y="scenario", color="channel", orientation="h",
                     category_orders={"scenario": order[::-1],
                                      "channel": ["PD model", "Stage moves", "Collateral"]},
                     color_discrete_map={"PD model": PLUM, "Stage moves": TEAL,
                                         "Collateral": "#c9a9d8"},
                     height=max(260, 44 * len(t) + 90))
        fig.update_layout(margin=dict(l=8, r=8, t=8, b=8), plot_bgcolor="white",
                          paper_bgcolor="white", legend_title_text="",
                          legend=dict(orientation="h", y=-0.12),
                          xaxis=dict(tickformat=",", title="Change in provision"),
                          yaxis=dict(title=""))
        st.plotly_chart(fig, use_container_width=True)
        show = t[["scenario", "change", "change_pct", "pd", "staging", "collateral",
                  "stage_moves"]]
        st.dataframe(fmt_table(show, money_cols=("change", "pd", "staging", "collateral",
                                                 "stage_moves"), pct_cols=("change_pct",))
                     .rename(columns={"change_pct": "% change", "pd": "PD model",
                                      "staging": "stage moves", "stage_moves": "contracts to Stage 2"}),
                     use_container_width=True, hide_index=True)
        pt = pd.DataFrame(cm[1]["paths"])
        drv = (cm[1].get("drivers") or {}).get("internal")
        nn = pt[pt["variable"] == drv] if len(pt) and drv else pd.DataFrame()
        if len(nn):
            name = str(nn["label"].iloc[0]) if "label" in nn else drv
            unit = f" ({nn['unit'].iloc[0]})" if "unit" in nn else ""
            fig = px.line(nn, x="year", y="move", color="scenario", markers=True, height=300)
            fig.update_layout(margin=dict(l=8, r=8, t=30, b=8), plot_bgcolor="white",
                              paper_bgcolor="white", legend_title_text="",
                              title=dict(text=f"{name}, shock against the run's forecast{unit}",
                                         font=dict(size=13)),
                              xaxis=dict(tickformat="d", dtick=1, title=""),
                              yaxis=dict(gridcolor="#f2eff6", title=""))
            st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------ sensitivity --
with tab_s:
    c = st.columns([2, 2, 3, 2], vertical_alignment="bottom")
    size = c[0].number_input("Adverse move (standard deviations)", 0.25, 4.0, 1.0, 0.25)
    shape = c[1].selectbox("Shape", ["one_year", "recover", "held"],
                           format_func=su_.SHAPES.get)
    lk = c[2].toggle("With the linked effects", value=True)
    if c[3].button("Run", type="primary", use_container_width=True, key="sens_go"):
        with st.spinner("One repricing per variable…"):
            with guard():
                S["scn_sens"] = (run_id, api.scn_sensitivity(run_id, size, shape, lk))
    se = S.get("scn_sens")
    if se and se[0] == run_id:
        t = pd.DataFrame(se[1]["table"])
        t["moved"] = [f"{lb} ({m:+.1f} {su_.unit(u)})"
                      for lb, m, u in zip(t["label"], t["move"], t["unit"])]
        bar(t, "moved", "change", diverging=True,
            title=f"Change in provision for a {se[1]['size_sd']:g} sd adverse move")
        caption("A standard deviation is each variable's own, from its yearly history: "
                "the move in brackets.")
        st.markdown("**One variable over a range**")
        c = st.columns([3, 2], vertical_alignment="bottom")
        vv = c[0].selectbox("Variable", list(t["variable"]),
                            format_func=dict(zip(t["variable"], t["label"])).get)
        if c[1].button("Draw", use_container_width=True):
            with st.spinner("Seven repricings…"):
                with guard():
                    S["scn_curve"] = (run_id, api.scn_curve(run_id, vv, shape, lk))
        cv = S.get("scn_curve")
        if cv and cv[0] == run_id:
            k = pd.DataFrame(cv[1]["curve"])
            k["label"] = [f"{m:+.1f}" for m in k["move"]]
            import plotly.graph_objects as go
            fig = go.Figure(go.Scatter(x=k["move"], y=k["change"], mode="lines+markers",
                                       line=dict(color=PLUM, width=3), marker=dict(size=7)))
            fig.update_layout(height=300, margin=dict(l=8, r=8, t=36, b=8),
                              title=dict(text=f"{cv[1]['label']}: change in provision",
                                         font=dict(size=13)),
                              plot_bgcolor="white", paper_bgcolor="white",
                              xaxis=dict(title=f"Move in year 1 ({su_.unit(cv[1]['unit'])})",
                                         zerolinecolor="#ded9e6"),
                              yaxis=dict(tickformat=",", gridcolor="#f2eff6"))
            st.plotly_chart(fig, use_container_width=True)
    st.markdown("**How sure: the PD model's link to non-oil growth**")
    c = st.columns([5, 2], vertical_alignment="bottom")
    c[0].caption(f"Prices *{ALL[S.get('scn_pick', IDS[0])]['name']}* (the scenario on the "
                 "Price tab) with the PD model's slope at each end of the range QDB's own "
                 "default history supports.")
    if c[1].button("Price the range", use_container_width=True):
        with st.spinner("Two more repricings…"):
            with guard():
                S["scn_pdl"] = (run_id, S.get("scn_pick"),
                                api.scn_pd_link(run_id, ALL[S.get("scn_pick", IDS[0])]))
    pl = S.get("scn_pdl")
    if pl and pl[0] == run_id and pl[1] == S.get("scn_pick"):
        x = pl[2]
        metric_row([(f"Slope {x['range'][0]:.3f}", signed(x["low"])),
                    (f"Model slope {x['slope']:.4f}", signed(x["central"])),
                    (f"Slope {x['range'][1]:.3f}", signed(x["high"]))])

# ------------------------------------------------------------ ECL at risk --
with tab_r:
    c = st.columns(4, vertical_alignment="bottom")
    n = c[0].number_input("Paths", 200, 20000, 2000, 200)
    seed = c[1].number_input("Seed", 1, 2 ** 31 - 2, 20261027, 1)
    thr = c[2].number_input("Provision threshold (QAR m, optional)", 0.0, value=0.0,
                            step=50.0)
    if c[3].button("Simulate", type="primary", use_container_width=True):
        with st.spinner("Drawing macro paths and pricing them (about a minute the first "
                        "time)…"):
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
                                 width=(h["to"] - h["from"]), marker_color="#c9a9d8"))
        for _, x in sm.iterrows():
            fig.add_vline(x=x["value"], line_dash="dash", line_color=ERR,
                          annotation_text=x["measure"].replace("ECL at ", ""))
        fig.add_vline(x=r["base"], line_color="#2a2f3a", annotation_text="now")
        fig.update_layout(height=320, margin=dict(l=8, r=8, t=24, b=8),
                          plot_bgcolor="white", paper_bgcolor="white", bargap=0,
                          xaxis=dict(tickformat=",", title="Provision"),
                          yaxis=dict(title="Paths"))
        st.plotly_chart(fig, use_container_width=True)
        nm = pd.DataFrame(r["named"])
        if len(nm):
            nm = nm.sort_values("percentile", ascending=False)
            nm["where"] = nm["percentile"].map(
                lambda v: "worse than every path" if v >= 99.95
                else f"worse than {v:.0f}% of paths")
            st.markdown("**Where the scenarios fall**")
            st.dataframe(fmt_table(nm[["scenario", "proxy_change", "where"]],
                                   money_cols=("proxy_change",))
                         .rename(columns={"proxy_change": "change"}),
                         use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        with c1:
            ch = pd.DataFrame(r["by_channel"]).rename(columns={"tail_change": "change"})
            bar(ch, "channel", "change", diverging=True, title="What drives the tail")
        with c2:
            bs = pd.DataFrame(r["by_segment"]).rename(columns={"tail_change": "change",
                                                                "segment": "sector"})
            bar(bs.head(10), "sector", "change", diverging=True, title="Tail by sector")
        ls = pd.DataFrame(r.get("loss_summary") or [])
        if len(ls):
            with st.expander("Credit loss over the next year (customers defaulting at "
                             "their stressed PD)"):
                metric_row([("Expected loss", money(r.get("expected_loss")))] +
                           [(x["measure"], money(x["value"])) for _, x in ls.iterrows()])
                cu = pd.DataFrame(r.get("customers") or [])
                if len(cu):
                    st.dataframe(fmt_table(cu, money_cols=("exposure", "tail_loss"))
                                 .assign(pd12=cu["pd12"].map(lambda v: f"{100 * v:.2f}%"),
                                         lgd=cu["lgd"].map(lambda v: f"{100 * v:.0f}%")),
                                 use_container_width=True, hide_index=True)
        with st.expander("Check the path pricing against full repricing"):
            if st.button("Run the check"):
                with st.spinner("Repricing every scenario in full…"):
                    with guard():
                        S["scn_pc"] = (run_id, api.scn_proxy_check(run_id))
            pc = S.get("scn_pc")
            if pc and pc[0] == run_id:
                t = pd.DataFrame(pc[1]["table"])
                st.dataframe(fmt_table(t[["scenario", "full", "proxy", "gap",
                                          "gap_pct_of_full"]],
                                       money_cols=("full", "proxy", "gap"),
                                       pct_cols=("gap_pct_of_full",))
                             .rename(columns={"gap_pct_of_full": "gap %"}),
                             use_container_width=True, hide_index=True)

# -------------------------------------------------------- reverse stress --
with tab_v:
    c = st.columns([3, 1], vertical_alignment="bottom")
    tgt = c[0].number_input("Increase in provision to reach (QAR m)", 1.0,
                            value=float(round(cx["ecl"] * 0.05 / 1e6, -1) or 100.0), step=10.0)
    if c[1].button("Find", type="primary", use_container_width=True):
        with st.spinner("Searching every scenario and variable, then confirming the "
                        "closest in full…"):
            with guard():
                S["scn_rev"] = (run_id, api.scn_reverse(run_id, tgt * 1e6))
    rv = S.get("scn_rev")
    if rv and rv[0] == run_id:
        r = rv[1]
        metric_row([("Target", signed(r["target"])),
                    ("Paths reaching it", pct(100 * r["probability"], 1)),
                    ("About one in", f"{r['one_in']:,.0f}" if r.get("one_in") else "—")])
        caption(f"Of {r['paths']:,} five-year macro paths drawn from the linked-effects "
                "system, the share that raise the provision by the target or more.")
        sc = pd.DataFrame(r["scenarios"])
        if len(sc):
            sc["needs"] = sc["scale"].map(lambda a: "never, even ×10" if pd.isna(a)
                                          else f"× {a:.2f}")
            st.markdown("**Each scenario, scaled** — how many times its moves it takes")
            st.dataframe(fmt_table(sc[["scenario", "needs", "at_one", "full_change"]],
                                   money_cols=("at_one", "full_change"))
                         .rename(columns={"at_one": "change as it is",
                                          "full_change": "confirmed in full"}),
                         use_container_width=True, hide_index=True)
        vt = pd.DataFrame(r["variables"])
        if len(vt):
            vt["needs"] = [("not within 10 sd" if pd.isna(a) else
                            f"{m:+.1f} {su_.unit(u)} ({a:.1f} sd)")
                           for a, m, u in zip(vt["size_sd"], vt["move"], vt["unit"])]
            st.markdown("**Each variable alone** — the year-1 shock it takes, with its "
                        "linked effects")
            st.dataframe(vt[["label", "needs"]].rename(columns={"label": "variable"}),
                         use_container_width=True, hide_index=True)
