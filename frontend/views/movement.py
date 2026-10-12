"""Movement between two runs: why the provision moved.

For the whole book, or for one or more customers, facilities, account types,
segments, stages or ratings: each run's figures for the selection side by
side, then the waterfall between them. Every contract is repriced from the
previous run to the current one a cause at a time and shown as: derecognised,
new business, exposure change, stage migration, rating migration, macro
variable change, model change, LGD & collateral and overlay (methodology change
when the ECL settings or the engine version differ, and "Unexplained" only if
repricing leaves anything). The steps sum exactly to the closing provision
(ifrs9qdb.analytics.bridge). A contract counts in one group: the one it is in
now, or, if derecognised, the one it was in.
"""
import pandas as pd
import streamlit as st

import api
from ui import (callout, caption, card_header, fmt_table, guard, kpis, money,
                page_setup, pct, signed, waterfall)

S = st.session_state
run_id = S.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
compare_id = S.get("compare_id")
page_setup("Movement")
if not compare_id:
    st.info("Two runs are needed. Add another run to the runs folder.")
    st.stop()

LEVELS = {"book": "Whole book", "customer": "Customer", "facility": "Facility",
          "account_type": "Account type", "segment": "Segment", "stage": "Stage",
          "rating": "Rating"}
PLURAL = {"customer": "customers", "facility": "facilities",
          "account_type": "account types", "segment": "segments",
          "stage": "stages", "rating": "ratings"}
# The waterfall's steps, as they are shown. The engine prices more causes than
# this (ifrs9qdb.analytics.BRIDGE_COMPONENTS); several are folded together
# here so the chart reads as the steps a reviewer asks about:
#   key, label, the engine components it sums, shown even when zero
GROUPS = [
    ("derecognised", "Derecognised", ("derecognised",), True),
    ("new_business", "New business", ("new_business",), True),
    ("exposure", "Exposure change", ("exposure",), True),
    ("stage", "Stage migration", ("stage",), True),
    ("rating", "Rating migration", ("rating",), True),
    ("macro", "Macro variable change", ("macro",), True),
    ("model", "Model change", ("model",), True),
    ("methodology", "Methodology change", ("settings", "method"), False),
    ("pd_curves", "Macro and model change", ("pd_curves",), False),
    ("lgd", "LGD & collateral", ("lgd",), True),
    ("overlay", "Overlay", ("overlay",), True),
    ("other", "Unexplained", ("other",), False),
]
LABEL = {k: lab for k, lab, _, _ in GROUPS}
WHAT = {
    "derecognised": "In the previous run and not in this one, at its previous ECL.",
    "new_business": "New in this run, at its ECL.",
    "exposure": "Contracts in both runs: repayments, drawdowns and "
                "amortisation -- the balance, the EAD curve and the remaining "
                "term -- at the previous stage, rating, PD curves and LGD.",
    "stage": "Between 12-month and lifetime ECL, or into Stage 3 (booked at "
             "the outstanding balance).",
    "rating": "The new rating, on the previous run's PD curves.",
    "macro": "The macro inputs: MEV forecasts, scenario weights and "
             "severities, and the GDP history, on the previous model.",
    "model": "The macro PD model itself: its variables, coefficients, TTC "
             "anchor and PDs, and how the variables combine. Zero when the "
             "model did not change.",
    "methodology": "How the ECL is calculated rather than with what: the ECL "
                   "settings in model.yml (EAD fallback rules, Stage 3 method, "
                   "exposure cap) and, when the previous run was priced by an "
                   "earlier version of the engine, the change in the "
                   "calculation itself. Shown only when it is not zero.",
    "pd_curves": "Macro inputs and model together: one of the runs has no "
                 "saved config, so the two cannot be told apart.",
    "lgd": "Collateral, and so LGD, and the EIR.",
    "overlay": "The post-model management overlay.",
    "other": "Should be zero: what the repricing could not explain, and "
             "contracts that could not be repriced in both runs.",
}


def _grouped(df: pd.DataFrame) -> pd.DataFrame:
    """Add one column per shown step, summing the engine's components."""
    df = df.copy()
    for key, _, comps, _ in GROUPS:
        have = [c for c in comps if c in df.columns]
        df[f"g_{key}"] = df[have].sum(axis=1) if have else 0.0
    return df


def _shown_cols(df: pd.DataFrame) -> list[str]:
    """The step columns worth a column in a table: non-zero somewhere."""
    return [k for k, _, _, _ in GROUPS if df[f"g_{k}"].abs().sum() >= 0.5]


caption(f"**{compare_id}** (previous) → **{run_id}** (current)")
level = st.segmented_control("Compare", list(LEVELS), format_func=LEVELS.get,
                             default="book", required=True, key="mv_level",
                             width="stretch")
if level != "book":
    caption(f"A contract counts in the {LEVELS[level].lower()} it is in now "
            "(a derecognised one in the one it left), so Previous ECL is what "
            "these contracts had in the previous run"
            + (f", not the previous run's total for that {LEVELS[level].lower()}."
               if level in ("stage", "rating", "segment", "account_type") else "."))


def _by_table(lv: str) -> None:
    with guard():
        by = pd.DataFrame(api.bridge_by(compare_id, run_id, lv))
    if len(by) == 0:
        st.info("Nothing to break down.")
        return
    by = _grouped(by)
    steps = _shown_cols(by)
    cols = ["label", "opening"] + [f"g_{k}" for k in steps] + ["closing", "change"]
    names = {"label": LEVELS[lv], "opening": "Previous ECL",
             "closing": "Current ECL", "change": "Change",
             **{f"g_{k}": LABEL[k] for k in steps}}
    show = by[cols].rename(columns=names)
    st.dataframe(fmt_table(show, money_cols=[c for c in show.columns
                                             if c != LEVELS[lv]]),
                 hide_index=True, width="stretch")


members: list[str] = []
if level != "book":
    with guard():
        opts = api.bridge_members(compare_id, run_id, level)
    if not opts:
        st.info("Nothing at this level in either run.")
        st.stop()
    labels = {str(o["value"]): f"{o['label']}  ·  ECL {money(o['ecl_a'])} → "
              f"{money(o['ecl_b'])} ({signed(o['change'])})" for o in opts}
    members = st.multiselect(
        f"Which {PLURAL[level]}", list(labels), format_func=labels.get,
        key=f"mv_members_{level}",
        placeholder="Type an id or a name — largest move first")
    if not members:
        caption(f"Every {LEVELS[level].lower()} below, each with its own "
                "waterfall in one row. Choose one or more above to see the "
                "detail.")
        _by_table(level)
        st.stop()

with guard():
    b = api.bridge(compare_id, run_id, level, tuple(sorted(members)))


# ----------------------------------------------------- before and after ----
def _stage_mix(p: dict) -> str:
    mix = p.get("stage_exposure") or {}
    tot = sum(mix.values())
    if not tot:
        return ""
    return " · ".join(f"S{k} {100 * v / tot:.0f}%" for k, v in sorted(mix.items()))


def _ratings(p: dict) -> str:
    rs = p.get("ratings") or []
    if len(rs) <= 1:
        return ""
    # shares of the selection's whole exposure, not of the ratings listed
    tot = p.get("exposure") or sum(r["exposure"] for r in rs) or 1
    return " · ".join(f"{r['rating']} {100 * r['exposure'] / tot:.0f}%" for r in rs[:3])


def _side(title: str, sub: str, p: dict) -> None:
    with st.container(border=True):
        card_header(title, None, right=sub)
        single = p.get("contracts", 0) == 1
        kpis([("Exposure", money(p.get("exposure")), "",
               f"off balance {money(p.get('exposure_off'))}"),
              ("ECL", money(p.get("ecl")), "plum",
               f"coverage {pct(p.get('coverage'))}"
               + (f" · overlay {money(p.get('overlay'))}" if p.get("overlay") else "")),
              ("Rating", p.get("rating") or "—", "", _ratings(p)),
              ("Stage", "—" if p.get("worst_stage") is None else
               (f"Stage {p['worst_stage']}" if single else f"worst {p['worst_stage']}"),
               "", _stage_mix(p))])
        kpis([("PD, lifetime", pct(None if p.get("pd") is None else 100 * p["pd"])),
              ("LGD", pct(None if p.get("lgd") is None else 100 * p["lgd"])),
              ("Contracts", money(p.get("contracts")), "",
               f"{money(p.get('customers'))} customer(s)"),
              ("Days past due", "—" if p.get("dpd_max") is None
               else f"{p['dpd_max']:,.0f}", "", "the most, across the contracts")])


runs = b.get("runs") or {}
c1, c2 = st.columns(2)
with c1:
    _side("Previous run", f"{compare_id} · {runs.get('a', {}).get('extract_date') or ''}",
          b["before"])
with c2:
    _side("Current run", f"{run_id} · {runs.get('b', {}).get('extract_date') or ''}",
          b["after"])

move = b["closing"] - b["opening"]
kpis([("Previous ECL", money(b["opening"]), "plum"),
      ("Current ECL", money(b["closing"]), "plum"),
      ("Movement", signed(move), "err" if move > 0 else "ok" if move < 0 else ""),
      ("% change", pct(100 * move / b["opening"]) if b["opening"] else "—")])

# ----------------------------------------------------------- waterfall -----
steps = pd.DataFrame(b["steps"])
changes = b.get("changes") or {}


amount = dict(zip(steps["key"], steps["amount"]))
split = bool(b.get("split"))
rows = [steps[steps["key"] == "opening"].iloc[0].to_dict()]
for key, label, comps, always in GROUPS:
    a = float(sum(amount.get(c, 0.0) for c in comps))
    if key == "macro" and not split:
        continue                       # its move is in "Macro and model change"
    show_it = always or abs(a) >= (1.0 if key == "other" else 0.5)
    if show_it:
        rows.append({"key": key, "label": label, "amount": a, "kind": "delta"})
rows.append(steps[steps["key"] == "closing"].iloc[0].to_dict())
shown = pd.DataFrame(rows)
waterfall(shown, zoom=True)
caption("Each contract is repriced from the previous run to this one a cause "
        "at a time, in the order shown, so the bars sum exactly to the current "
        f"ECL (residual {b['residual']:.2f})."
        + ("" if changes.get("model_changed")
           else " The PD model did not change, so Model change is zero."))
for n in b.get("notes") or []:
    callout("info", n)

tbl = shown[shown["kind"] == "delta"].copy()
tbl["% of previous"] = [100 * a / b["opening"] if b["opening"] else None
                        for a in tbl["amount"]]
tbl["What it is"] = tbl["key"].map(WHAT)
st.dataframe(fmt_table(tbl[["label", "amount", "% of previous", "What it is"]]
                       .rename(columns={"label": "Step", "amount": "Amount"}),
                       money_cols=("Amount",), pct_cols=("% of previous",)),
             hide_index=True, width="stretch",
             column_config={"What it is": st.column_config.TextColumn(width="large")})

with st.expander("What changed in the model, the macro inputs and the ECL settings"):
    if not changes.get("known"):
        st.write("A run has no frozen config, so this cannot be said.")
    else:
        for part, flag, title in (("model", "model_changed", "PD model"),
                                  ("macro", "macro_changed", "Macro inputs"),
                                  ("settings", "settings_changed", "ECL settings")):
            st.markdown(f"**{title}** — "
                        + ("changed" if changes.get(flag) else "unchanged"))
            items = changes.get(part) or []
            if items:
                st.dataframe(pd.DataFrame(items).astype(str).rename(
                    columns={"item": "What", "before": "Previous", "after": "Current"}),
                    hide_index=True, width="stretch")

# ----------------------------------------------------------- the detail ----
tabs = ["Contracts behind it"]
if level != "book":
    tabs.append(f"Every {LEVELS[level].lower()}")
else:
    tabs.append("By segment")
tabs.append("Arrivals and departures")
t = st.tabs(tabs)

with t[0]:
    ct = pd.DataFrame(b.get("contracts") or [])
    if len(ct) == 0:
        st.info("No contracts.")
    else:
        caption("Largest moves first. Each row's causes sum to its change.")
        ct = _grouped(ct)
        comp = _shown_cols(ct)
        # the stage and rating moves, as text, beside the components of the
        # same names (Stage migration, Rating migration)
        ct["stage_move"] = [f"{'' if pd.isna(x) else int(x)} → {'' if pd.isna(y) else int(y)}"
                            for x, y in zip(ct["stage_a"], ct["stage_b"])]
        ct["rating_move"] = [f"{x or ''} → {y or ''}" for x, y in
                             zip(ct["rating_a"].fillna(""), ct["rating_b"].fillna(""))]
        ct["customer"] = ct["customer_b"].fillna(ct["customer_a"])
        text = {"contract": "Contract", "customer": "Customer", "name": "Name",
                "status": "Status", "stage_move": "Stage", "rating_move": "Rating"}
        cols = list(text) + ["ecl_a", "ecl_b", "change"] + [f"g_{k}" for k in comp]
        show = ct[cols].rename(columns={**text, "ecl_a": "ECL previous",
                                        "ecl_b": "ECL current", "change": "Change",
                                        **{f"g_{k}": LABEL[k] for k in comp}})
        st.dataframe(fmt_table(show, money_cols=[c for c in show.columns
                                                 if c not in text.values()]),
                     hide_index=True, width="stretch")

with t[1]:
    _by_table(level if level != "book" else "segment")

with t[2]:
    with guard():
        f = api.flows(compare_id, run_id, "portfolio")
    fl = pd.DataFrame(f["flows"])
    if len(fl) == 0:
        st.info("No contracts arrived or left between these two runs.")
    else:
        caption("New business and derecognition are the steps that are not about "
                "the existing book changing. Their coverage is the column to read: "
                "business arriving at a higher coverage than the book it joins "
                "moves the headline on its own.")
        st.dataframe(fmt_table(fl, money_cols=("contracts", "exposure", "ecl"),
                               pct_cols=("coverage",)),
                     hide_index=True, width="stretch")
