"""Macro data: the store every macro figure comes from, and the new quarter's
forecasts filled from it.

The store keeps every IMF dataset of the catalogue for Qatar, the GCC, the
trading partners and the US, plus files from QCB, the Planning and Statistics
Authority and the Ministry of Finance, as dated vintages: a refresh never
overwrites one. The new-quarter fill proposes the forecasts and history a
config needs from the latest vintage -- five years from the first year not yet
confirmed -- and writes them into a draft config version for testing and
approval (ifrs9qdb.macro).
"""
import datetime as dt

import pandas as pd
import streamlit as st

import api
from ui import caption, fmt_table, guard, metric_row, money, page_setup

S = st.session_state


def history_and_forecast(df: pd.DataFrame, title: str) -> None:
    """History as a solid line, the projection dashed from the last actual
    year on."""
    import plotly.graph_objects as go
    d = df.sort_values("year")
    act = d["actual"].astype(bool) if "actual" in d else pd.Series(True, index=d.index)
    hist, fc = d[act], d[~act]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["year"], y=hist["value"], mode="lines+markers",
                             name="History", line=dict(color="#5b1f6e", width=2.5),
                             marker=dict(size=5)))
    if len(fc):
        joined = pd.concat([hist.tail(1), fc]) if len(hist) else fc
        fig.add_trace(go.Scatter(x=joined["year"], y=joined["value"], mode="lines+markers",
                                 name="Projection", line=dict(color="#c0392b", width=2.5,
                                                              dash="dash"),
                                 marker=dict(size=5)))
    fig.update_layout(title=title, height=340, margin=dict(l=8, r=8, t=40, b=8),
                      plot_bgcolor="white", paper_bgcolor="white",
                      legend=dict(orientation="h", y=-0.15),
                      xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#f0eef4"))
    st.plotly_chart(fig, use_container_width=True)


page_setup("Macro data", "The macro store, and the new quarter's forecasts from it")

with guard():
    stt = api.macro_status()
    cat = api.macro_catalogue()

tab_s, tab_v, tab_f, tab_q = st.tabs(["Store", "Variables", "Find a series", "New quarter"])

# ---------------------------------------------------------------- store --
with tab_s:
    vin = pd.DataFrame(stt["vintages"])
    if len(vin):
        last = vin.iloc[0]
        metric_row([("Latest vintage", stt["latest"]), ("Made", str(last["created"])[:16]),
                    ("Series", money(last["series"])),
                    ("Observations", money(last["observations"]))])
    else:
        st.info("The store is empty. Refresh it below, or import a file.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Refresh from the IMF, BIS, World Bank and FRED**")
        ds = pd.DataFrame(cat["datasets"])
        groups = sorted(ds["group"].unique())
        g = st.multiselect("Dataset groups", groups, [],
                           help="Empty: every dataset marked for fetching.")
        allds = st.toggle("Also the datasets not fetched by default", value=False)
        fred = st.text_input("FRED API key (optional)", type="password")
        lab = st.text_input("Label", placeholder="e.g. WEO October 2026")
        if st.button("Refresh", type="primary"):
            import time
            with guard():
                job = api.macro_refresh({"groups": g or None, "fred_key": fred or None,
                                         "label": lab, "all_datasets": allds})["job"]
            bar = st.progress(0.0, text="Starting…")
            n_ds = max(1, len(ds) + 3)
            while True:
                with guard():
                    j = api.macro_refresh_status(job)
                bar.progress(min(len(j["steps"]) / n_ds, 0.99), text=j["step"] or "Starting…")
                if j["status"] != "running":
                    break
                time.sleep(2)
            bar.empty()
            if j["status"] == "failed":
                st.error(j["error"])
            else:
                r = j["result"]
                st.success(f"Saved vintage {r.get('vintage')}: {r.get('series', 0):,} series, "
                           f"{r.get('observations', 0):,} values.", icon="✅")
                stt["log"] = r.get("log") or []
                bad = [x for x in stt["log"] if x.get("status") == "failed"]
                if bad:
                    st.warning("Not fetched, the previous copy kept: "
                               + "; ".join(f"{x.get('dataset')} ({str(x.get('error'))[:120]})"
                                           for x in bad), icon="⚠️")
                api.clear()
    with c2:
        st.markdown("**Import a file**")
        f = st.file_uploader("CSV or Excel: long (date, value) or wide (series by column)",
                             type=["csv", "xlsx", "xls"])
        c = st.columns(2)
        src = c[0].selectbox("Source", ["QCB", "NPC", "MOF", "IMF", "OTHER"],
                             help="NPC is the Planning and Statistics Authority.")
        dsn = c[1].text_input("Dataset", placeholder="e.g. MONETARY")
        c = st.columns(3)
        ctry = c[0].text_input("Country", "QAT")
        freq = c[1].selectbox("Frequency", ["", "A", "Q", "M"],
                              format_func=lambda x: x or "from the dates")
        unit = c[2].text_input("Unit")
        if st.button("Import", disabled=f is None or not dsn):
            with guard():
                r = api.macro_import(f, src, dsn, ctry, freq, unit)
            st.success(f"Saved vintage {r.get('vintage')}.", icon="✅")
    log = pd.DataFrame(stt.get("log") or [])
    if len(log):
        with st.expander("What the last refresh fetched"):
            st.dataframe(log, use_container_width=True, hide_index=True)
    if len(vin) > 1:
        with st.expander("All vintages"):
            st.dataframe(vin, use_container_width=True, hide_index=True)

# ------------------------------------------------------------ variables --
with tab_v:
    cn = pd.DataFrame(stt.get("concepts") or [])
    if not len(cn):
        st.info("No variables resolve yet: refresh the store.")
    else:
        show = cn[["label", "unit", "series_id", "last_actual", "first_year", "last_year",
                   "core"]].copy()
        show["first_year"] = show["first_year"].map(lambda v: "" if pd.isna(v) else int(v))
        show["last_year"] = show["last_year"].map(lambda v: "" if pd.isna(v) else int(v))
        show["series_id"] = show["series_id"].fillna("— not in the store")
        st.dataframe(show.rename(columns={"label": "variable", "series_id": "from",
                                          "last_actual": "last actual", "core": "in the VAR"}),
                     use_container_width=True, hide_index=True)
        pick = st.selectbox("Show", cn.loc[cn["series_id"].notna(), "label"])
        cid = cn.loc[cn["label"] == pick, "concept"].iloc[0]
        with guard():
            cv = api.macro_concept(cid)
        vals = pd.DataFrame(cv["values"])
        if len(vals):
            history_and_forecast(vals, f"{pick} · {cv['series_id']}")
            caption(f"Standard deviation of the actual years: {cv['sd']:.2f}. "
                    "A shock in standard deviations uses this.")

# ---------------------------------------------------------- find series --
with tab_f:
    c = st.columns([3, 1, 1])
    q = c[0].text_input("Search", placeholder="e.g. oil, credit, NPL, policy rate")
    ctry_opts = [""] + [r["code"] for r in cat["countries"]]
    qc = c[1].selectbox("Country", ctry_opts, format_func=lambda x: x or "any")
    qs = c[2].selectbox("Source", ["", "IMF", "BIS", "WB", "FRED", "DM", "DBNOMICS", "STATIC",
                                   "QCB", "NPC", "MOF"], format_func=lambda x: x or "any")
    if q or qc or qs:
        with guard():
            hits = pd.DataFrame(api.macro_search(q, qc or None, qs or None))
        if not len(hits):
            st.info("Nothing found.")
        else:
            st.dataframe(hits[["series_id", "name", "unit", "first", "last", "values",
                               "last_actual"]],
                         use_container_width=True, hide_index=True)
            sid = st.selectbox("Show", hits["series_id"])
            with guard():
                ser = api.macro_series(sid)
            an = pd.DataFrame(ser["annual"])
            if len(an):
                history_and_forecast(an, ser["series"].get("name", sid))

# ----------------------------------------------------------- new quarter --
with tab_q:
    with guard():
        snaps = pd.DataFrame(api.snapshots().get("snapshots") or [])
    labels = list(snaps["label"]) if len(snaps) else []
    status = dict(zip(snaps["label"], snaps["status"])) if len(snaps) else {}
    c = st.columns([2, 3, 1])
    td = dt.date.today()
    qend = dt.date(td.year, 3 * ((td.month - 1) // 3) + 1, 1) - dt.timedelta(days=1)
    rd = c[0].date_input("Reporting date", qend)
    base = c[1].selectbox("Config to start from", ["Live config"] + labels,
                          format_func=lambda x: x if x == "Live config"
                          else f"{x} [{status.get(x, '?')}]")
    fy = c[2].number_input("First forecast year", 0, 2100, 0, 1,
                           help="0: the first year the store does not confirm.")
    payload = {"reporting_date": rd.isoformat(),
               "snapshot": None if base == "Live config" else base,
               "first_year": int(fy) or None}
    if st.button("Propose", type="primary"):
        with st.spinner("Reading the store…"):
            with guard():
                S["mq_prop"] = (payload, api.macro_propose(payload))
    mp = S.get("mq_prop")
    if mp and mp[0] == payload:
        p = mp[1]
        st.markdown(f"**{p['rule']}**")
        metric_row([("Vintage", p["vintage"]), ("Values that change", money(p["changed"])),
                    ("Non-oil GDP from", p["nonoil"]["series_id"])])
        for w in p.get("warnings") or []:
            st.warning(w, icon="⚠️")
        bad = [x["check"] for x in p.get("checks") or [] if not x["ok"]]
        if bad:
            st.error("Failed: " + "; ".join(bad))
        ch = pd.DataFrame(p.get("changes") or [])
        if len(ch):
            st.dataframe(ch.style.format({"current": "{:.2f}", "proposed": "{:.2f}",
                                          "change": "{:+.2f}"}, na_rep="—"),
                         use_container_width=True, hide_index=True, height=360)
        hg = p.get("history_gcc") or {}
        hist = [f"{len(p.get('history_nonoil_add') or [])} non-oil GDP year(s)"] + \
               [f"{v['changed']} row(s) of {k}" for k, v in hg.items() if v["changed"]]
        caption("History added or corrected from confirmed years: " + ", ".join(hist) + ".")

        st.markdown("**Write into a draft config version**")
        if payload["snapshot"] and status.get(payload["snapshot"]) == "draft":
            target, new = payload["snapshot"], False
            caption(f"{target} is a draft: the proposal is written into it.")
        else:
            new = True
            yq = f"{rd.year}-Q{(rd.month - 1) // 3 + 1}"
            target = st.text_input("New draft", f"{yq}-macro-draft",
                                   help="Made from the config you started from.")
        if st.button("Write", disabled=bool(bad) or not target):
            with guard():
                if new:
                    api.create_snapshot(target, f"Macro forecasts for {rd.isoformat()} "
                                                f"from vintage {p['vintage']}",
                                        S.get("_user") or "", parent=payload["snapshot"])
                r = api.macro_apply({**payload, "snapshot": target})
            api.clear()
            st.success(f"Written into {target}: {r.get('message', '')}. Test it with a run, "
                       "then move it on under Config versions.", icon="✅")
