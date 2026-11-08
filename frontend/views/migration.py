"""Who moved between two runs, on stage and on rating -- and drill down.

Counted as CUSTOMERS, because rating and stage are customer attributes at QDB:
a contract view counts one customer once per facility and inflates every cell
by that customer's facility count. Each tab splits by rating scale (internal,
external) and lists every move with what its customers carried in the previous
run and now; select a move to see the customers in it. What the moves cost,
cause by cause, is on Movement (Stage migration and Rating migration).
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pct

S = st.session_state
run_id = S.get("run_id")
compare_id = S.get("compare_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
if not compare_id:
    st.info("Two runs are needed. Add another run to the runs folder.")
    st.stop()
page_setup("Migration", f"{compare_id} → {run_id}")
caption("Customers, not contracts: stage and rating are set per customer. Select "
        "a move to see its customers. What each move cost is on Movement.")

with guard():
    m = api.migration(compare_id, run_id)

AMT = st.column_config.NumberColumn(format="%,.0f")
MOVE_CFG = {c: AMT for c in ("Exposure, previous", "Exposure, now", "ECL, previous",
                             "ECL, now", "Change in ECL")}


def _customers(scale: str) -> pd.DataFrame:
    with guard():
        return pd.DataFrame(api.migration_customers(compare_id, run_id, scale))


def _moves(cust: pd.DataFrame, a: str, b: str, label) -> pd.DataFrame:
    """One row per move (a cell of the matrix): its customers and what they
    carried in each run."""
    g = (cust.groupby([a, b], dropna=True)
         .agg(customers=("customer", "size"), exposure_prev=("exposure_prev", "sum"),
              exposure=("exposure_curr", "sum"), ecl_prev=("ecl_prev", "sum"),
              ecl=("ecl_curr", "sum"))
         .reset_index())
    g["Move"] = [label(x, y) for x, y in zip(g[a], g[b])]
    g["Change in ECL"] = g["ecl"] - g["ecl_prev"]
    return g


def _move_table(g: pd.DataFrame, key: str):
    """The moves, selectable; returns the selected row or None."""
    show = g[["Move", "customers", "exposure_prev", "exposure", "ecl_prev", "ecl",
              "Change in ECL"]].rename(columns={
                  "customers": "Customers", "exposure_prev": "Exposure, previous",
                  "exposure": "Exposure, now", "ecl_prev": "ECL, previous",
                  "ecl": "ECL, now"})
    ev = st.dataframe(show, hide_index=True, on_select="rerun",
                      selection_mode="single-row", key=key, column_config=MOVE_CFG)
    rows = ev.selection.rows if ev and ev.selection else []
    return g.iloc[rows[0]] if rows else None


def _drill(sub: pd.DataFrame, title: str) -> None:
    st.markdown(f"**{title}** · {len(sub):,} customer{'s' if len(sub) != 1 else ''}")
    show = sub.rename(columns={
        "customer": "Customer", "customer_name": "Customer name",
        "portfolios": "Portfolio", "contracts": "Contracts",
        "rating_prev": "Rating, previous", "rating_curr": "Rating, now",
        "stage_prev": "Stage, previous", "stage_curr": "Stage, now",
        "exposure_prev": "Exposure, previous", "exposure_curr": "Exposure, now",
        "ecl_prev": "ECL, previous", "ecl_curr": "ECL, now",
        "ecl_change": "Change in ECL"})
    st.dataframe(show, hide_index=True, column_config=MOVE_CFG,
                 height=min(520, 40 + 34 * max(len(show), 1)))
    caption("Exposure and ECL are each run's figures for the customer; the change "
            "is everything that moved for it -- stage, rating, repayments, curves.")


def _matrix(cust: pd.DataFrame, a: str, b: str, levels: list, name: str) -> None:
    piv = (cust.pivot_table(index=a, columns=b, values="customer", aggfunc="count")
           .fillna(0).astype(int))
    piv = piv.reindex(index=[x for x in levels if x in piv.index],
                      columns=[x for x in levels if x in piv.columns], fill_value=0)
    piv.index = [name(x) for x in piv.index]
    piv.columns = [name(x) for x in piv.columns]
    piv.index.name = "Previous ↓ / now →"
    st.dataframe(piv, hide_index=False)


# ================================================================ stage ======
stage_tab, rating_tab = st.tabs(["Stage", "Rating"])
with stage_tab:
    scales = ["All"] + [s for s in ("Internal", "External")
                        if (m.get("stage_by_scale") or {}).get(s)]
    sc = st.segmented_control("Rating scale", scales, default="All", required=True,
                              key="mig_stage_scale")
    cust = _customers(sc)
    if len(cust) == 0:
        st.info("No customer appears in both runs.")
    else:
        cust = cust.dropna(subset=["stage_prev", "stage_curr"])
        sp, sn = cust["stage_prev"].astype(int), cust["stage_curr"].astype(int)
        cust = cust.assign(stage_prev=sp, stage_curr=sn)
        metric_row([("Customers in both runs", money(len(cust))),
                    ("Changed stage", money(int((sp != sn).sum()))),
                    ("Deteriorated", money(int((sn > sp).sum()))),
                    ("Improved", money(int((sn < sp).sum())))])
        st.markdown("**From / to**: customers; rows are the previous run's stage, "
                    "columns this run's.")
        _matrix(cust, "stage_prev", "stage_curr", [1, 2, 3], lambda x: f"Stage {x}")
        st.markdown("**Moves**: select one to see its customers")
        g = _moves(cust, "stage_prev", "stage_curr",
                   lambda x, y: f"Stage {x} → Stage {y}" if x != y
                   else f"Stage {x} (no change)")
        pick = _move_table(g, f"mig_stage_moves_{sc}")
        if pick is not None:
            sub = cust[(cust["stage_prev"] == pick["stage_prev"])
                       & (cust["stage_curr"] == pick["stage_curr"])]
            _drill(sub, f"{pick['Move']} "
                        f"({sc.lower() + ' scale' if sc != 'All' else 'both scales'})")

# ================================================================ rating =====
with rating_tab:
    by_scale = m.get("rating_by_scale") or {}
    if not by_scale:
        st.info("No rating appears in both runs.")
    else:
        names = [n for n in ("Internal", "External") if n in by_scale]
        sc = st.segmented_control("Rating scale", names, default=names[0],
                                  required=True, key="mig_rating_scale")
        caption("A scale at a time: an upgrade is only meaningful along a scale's own "
                "order (best grade first).")
        part = by_scale[sc]
        levels = part.get("levels") or []
        cust = _customers(sc)
        cust = cust[cust["rating_prev"].isin(levels) & cust["rating_curr"].isin(levels)] \
            if levels and len(cust) else cust
        if len(cust) == 0:
            st.info("No customer on this scale is rated in both runs.")
        else:
            rank = {r: i for i, r in enumerate(levels)}
            rp = cust["rating_prev"].map(rank)
            rn = cust["rating_curr"].map(rank)
            metric_row([("Upgraded", money(int((rn < rp).sum()))),
                        ("Stable", money(int((rn == rp).sum()))),
                        ("Downgraded", money(int((rn > rp).sum()))),
                        ("Downgrade rate", pct(100 * (rn > rp).sum() / max(len(cust), 1)))])
            st.markdown("**From / to**: customers; rows are the previous run's rating, "
                        "columns this run's, best grade first.")
            _matrix(cust, "rating_prev", "rating_curr", levels, str)
            st.markdown("**Moves**: select one to see its customers")
            g = _moves(cust, "rating_prev", "rating_curr",
                       lambda x, y: f"{x} → {y}" if x != y else f"{x} (no change)")
            g = g.assign(_a=g["rating_prev"].map(rank), _b=g["rating_curr"].map(rank))
            g["Direction"] = ["Stable" if a == b else ("Downgraded" if b > a else "Upgraded")
                              for a, b in zip(g["_a"], g["_b"])]
            g = g.sort_values(["_a", "_b"]).reset_index(drop=True)
            g["Move"] = [m_ if d == "Stable" else f"{m_} ({d.lower()})"
                         for m_, d in zip(g["Move"], g["Direction"])]
            pick = _move_table(g, f"mig_rating_moves_{sc}")
            if pick is not None:
                sub = cust[(cust["rating_prev"] == pick["rating_prev"])
                           & (cust["rating_curr"] == pick["rating_curr"])]
                _drill(sub, f"{pick['Move']} ({sc.lower()} scale)")
