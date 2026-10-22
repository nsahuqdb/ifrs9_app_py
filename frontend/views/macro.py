"""Macro & scenarios: how the provision moves with the forecast and the weights.

Two books, shown apart because they price off different paths:

* internally rated (Business Finance, Off BS, Al Dhameen, Tasdeer) on the
  domestic forecast (non-oil GDP, and any other variable the model weights);
* externally rated (Investments, Banks and FIs) on GCC GDP growth.

A change shifts the variable by the same number of points in every forecast
year. The PD curves are rebuilt from the run's own frozen config and the book
repriced (ifrs9qdb.stress.mev_stress); the scenario weights are kept at the
run's unless asked to follow the new forecast.
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, fmt_table, guard, money, page_setup, pct, signed

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Macro & scenarios",
           "How the provision moves with the macro forecast and the scenario "
           "weights")

with guard():
    m = api.model_assumptions(run_id)
    rw = api.scenario_weights(run_id)
    sc = api.scope(run_id)

if not m.get("available") or not rw.get("ok"):
    st.info(m.get("reason") or rw.get("reason")
            or "This run has no saved config, so its PD curves cannot be rebuilt.")
    st.stop()

internal, external = sc["internal"], sc["external"]
fc = pd.DataFrame(m["mev_forecast"])
mw = pd.DataFrame(m["mev_weights"])
weight_of = mw.set_index("idx")["weight"].to_dict() if len(mw) else {}
# only the variables the model actually uses: a zero-weight one moves nothing
active = (fc[fc["idx"].map(lambda i: (weight_of.get(i) or 0) != 0)]
          if len(fc) else fc)
gcc = rw.get("gcc_forecast") or []


def _path(years, now, shift: float) -> None:
    """The path, this run's and stressed, one column a year."""
    t = pd.DataFrame([list(now), [v + shift for v in now]],
                     index=["This run", "Stressed"],
                     columns=[f"Year {int(y)}" for y in years])
    st.dataframe(t.style.format("{:.4g}"), use_container_width=True)


def _book_table(r: dict) -> None:
    """Before and after for each book and the whole book."""
    bp = pd.DataFrame(r["by_portfolio"])
    rows = []
    for name, pfs in (("Internally rated", internal), ("Externally rated", external)):
        part = bp[bp["portfolio"].isin(pfs)]
        if len(part):
            rows.append({"Book": name, "Provision now": part["before"].sum(),
                         "Stressed": part["after"].sum()})
    rows.append({"Book": "Whole book", "Provision now": bp["before"].sum(),
                 "Stressed": bp["after"].sum()})
    t = pd.DataFrame(rows)
    t["Change"] = t["Stressed"] - t["Provision now"]
    t["Change %"] = [100 * c / b if b else None
                     for c, b in zip(t["Change"], t["Provision now"])]
    show = t.assign(Change=t["Change"].map(signed))
    st.dataframe(fmt_table(show, money_cols=("Provision now", "Stressed"),
                           pct_cols=("Change %",)),
                 use_container_width=True, hide_index=True)
    with st.expander("By portfolio, and the customers that moved most"):
        st.dataframe(fmt_table(bp.rename(columns={
                         "portfolio": "Portfolio", "contracts": "Contracts",
                         "before": "Provision now", "after": "Stressed",
                         "change": "Change"}),
                         money_cols=("Contracts", "Provision now", "Stressed",
                                     "Change")),
                     use_container_width=True, hide_index=True)
        mv = pd.DataFrame(r.get("movers") or [])
        if len(mv):
            mv = mv[mv["change"].abs() >= 0.5].head(20)
            st.dataframe(fmt_table(mv[["customer", "portfolio", "rating", "stage",
                                       "ecl_before", "ecl_after", "change"]]
                                   .rename(columns={
                                       "customer": "Customer",
                                       "portfolio": "Portfolio",
                                       "rating": "Rating", "stage": "Stage",
                                       "ecl_before": "Provision now",
                                       "ecl_after": "Stressed",
                                       "change": "Change"}),
                                   money_cols=("Provision now", "Stressed",
                                               "Change")),
                         use_container_width=True, hide_index=True)


forecast_tab, weights_tab = st.tabs(["Macro forecast", "Scenario weights"])

# ------------------------------------------------------------ the forecast --
with forecast_tab:
    left, right = st.columns(2)
    shock = {}
    with left:
        st.markdown("**Internally rated**")
        caption(", ".join(internal))
        for idx, g in active.groupby("idx", sort=True):
            label = g["label"].iloc[0]
            shock[str(idx)] = st.slider(f"{label}: change in every year (points)",
                                        -5.0, 5.0, 0.0, 0.25, key=f"mac_i{idx}")
            _path(g["year"], g["value"].to_numpy(), shock[str(idx)])
    with right:
        st.markdown("**Externally rated**")
        caption(", ".join(external) or "None in this run")
        gcc_shock = 0.0
        if gcc and external:
            gcc_shock = st.slider("GCC GDP growth: change in every year (points)",
                                  -5.0, 5.0, 0.0, 0.25, key="mac_gcc")
            _path(range(1, len(gcc) + 1), gcc, gcc_shock)

    keep = st.radio("Scenario weights",
                    ["Keep this run's", "Recalculate from the new forecast"],
                    horizontal=True, key="mac_keep") == "Keep this run's"
    shocked = {k: v for k, v in shock.items() if v}
    key = ("f", run_id, tuple(sorted(shocked.items())), gcc_shock, keep)
    if st.button("Reprice", type="primary", key="mac_go",
                 disabled=not (shocked or gcc_shock)):
        with guard(), st.spinner("Rebuilding the PD curves and repricing…"):
            S["mac_res"] = (key, api.mev_stress(
                run_id, [], shocked, "hold" if keep else "auto",
                gcc_shock=gcc_shock))
    res = S.get("mac_res")
    if res and res[0] == key:
        _book_table(res[1])

# ------------------------------------------------------------- the weights --
with weights_tab:
    names = list(rw["internal"])
    own_i, own_e = rw["internal"], rw.get("external") or {}
    caption("This run's weights. External is the average over the forecast "
            "years (it is set year by year from GCC growth). Change any and "
            "reprice; weights are scaled to add up to 100%.")
    cols = st.columns([2] + [1] * len(names))
    cols[0].markdown("&nbsp;")
    for c, n in zip(cols[1:], names):
        c.markdown(f"**{n}**")

    def _row(label: str, own: dict, tag: str) -> dict:
        cs = st.columns([2] + [1] * len(names), vertical_alignment="center")
        cs[0].markdown(label)
        out = {}
        for c, n in zip(cs[1:], names):
            v = c.number_input(n, 0.0, 100.0, round(100 * own.get(n, 0.0), 2),
                               0.5, format="%.2f", key=f"mac_w{tag}_{run_id}_{n}",
                               label_visibility="collapsed")
            # an input left at its starting value is the run's own, exactly
            out[n] = own.get(n, 0.0) if v == round(100 * own.get(n, 0.0), 2) else v / 100
        return out

    w_int = _row("Internally rated", own_i, "i")
    w_ext = _row("Externally rated", own_e, "e") if own_e and external else {}
    changed_i = any(abs(w_int[n] - own_i[n]) > 1e-12 for n in names)
    changed_e = bool(w_ext) and any(abs(w_ext[n] - own_e.get(n, 0.0)) > 1e-12
                                    for n in names)
    ok = sum(w_int.values()) > 0 and (not w_ext or sum(w_ext.values()) > 0)
    key = ("w", run_id, tuple(round(v, 8) for v in w_int.values()),
           tuple(round(v, 8) for v in w_ext.values()) if changed_e else ())
    if st.button("Reprice", type="primary", key="mac_wgo",
                 disabled=not ok or not (changed_i or changed_e)):
        with guard(), st.spinner("Rebuilding the PD curves and repricing…"):
            S["mac_wres"] = (key, api.mev_stress(
                run_id, [], {}, "custom", w_int if changed_i else None,
                external_weights=w_ext if changed_e else None))
    res = S.get("mac_wres")
    if res and res[0] == key:
        _book_table(res[1])
