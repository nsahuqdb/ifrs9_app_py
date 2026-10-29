"""A config's macro inputs, filled from the macro store when asked.

After a refresh of the store, the figures a config takes from it -- the
non-oil GDP forecast, the GCC growth and nominal GDP paths, the history files
behind the scenario weights, and the explicit weights themselves -- can be
proposed from the latest vintage and written into a draft config version,
with nothing typed by hand. Each is ticked on its own: what is not ticked
stays as it is in the file, so weights fixed by hand or a forecast entered
for a test are kept; the weights are unticked unless chosen. Every value
that moves is listed before anything is written. Drawn on the Macro data
page and on a draft under Config versions; the files can still be edited by
hand there.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money

S = st.session_state
SECTIONS = {"Forecast": "Forecasts", "History": "Non-oil GDP history",
            "Scenario weights": "Scenario weights"}
FILES = {"gcc_real_gdp_growth.csv": "GCC real GDP growth history",
         "gcc_gdp_current_prices.csv": "GCC nominal GDP history"}


def quarter_end(today: dt.date | None = None) -> dt.date:
    """The last day of the quarter before today's."""
    td = today or dt.date.today()
    return dt.date(td.year, 3 * ((td.month - 1) // 3) + 1, 1) - dt.timedelta(days=1)


HELP = {"weights": "Unticked: the explicit weights in the file stay as they are, fixed "
                   "by hand or not. Ticked: they are replaced by the V2 weights of the "
                   "history and forecast, unrounded. With mode auto the run works the "
                   "weights out itself either way.",
        "nonoil_forecast": "Unticked: the non-oil forecast in the file stays as it is, "
                           "in whatever unit it was entered.",
        "nonoil_history": "Every year of non_oil_gdp_history.csv the source has revised, "
                          "and the years it now has before the forecast.",
        "gcc_history": "gcc_real_gdp_growth.csv and gcc_gdp_current_prices.csv, the "
                       "same way."}


def choose(key: str) -> list:
    """What to fill: one tick per part, the weights unticked unless chosen."""
    with guard():
        pp = api.macro_parts()
    st.markdown("**What to fill from the store**")
    cols = st.columns(len(pp["parts"]))
    return [k for c, (k, label) in zip(cols, pp["parts"].items())
            if c.checkbox(label, k in pp["default"], key=f"{key}_{k}", help=HELP.get(k))]


def ask(payload: dict, key: str) -> dict | None:
    """The proposal for ``payload``, asked for on a button and kept while
    the inputs stay the same; a change of what is ticked asks again."""
    base = {k: v for k, v in payload.items() if k != "parts"}
    got = S.get(key)
    again = bool(got and got[0] != payload and
                 {k: v for k, v in got[0].items() if k != "parts"} == base)
    if not payload.get("parts"):
        caption("Tick at least one part to fill.")
        return None
    if st.button("Propose", type="primary", key=f"{key}_go") or again:
        with st.spinner("Reading the store…"):
            with guard():
                S[key] = (payload, api.macro_propose(payload))
    got = S.get(key)
    return got[1] if got and got[0] == payload else None


def show(p: dict) -> list:
    """The proposal: the rule, every value that moves, the checks. Returns
    the checks that failed."""
    st.markdown(f"**{p['rule']}**")
    metric_row([("Vintage", p["vintage"]), ("Values that change", money(p["changed"])),
                ("Non-oil GDP from", p["nonoil"]["series_id"] or "the file, as it is")])
    for w in p.get("warnings") or []:
        st.warning(w, icon="⚠️")
    bad = [x["check"] for x in p.get("checks") or [] if not x["ok"]]
    if bad:
        st.error("Failed: " + "; ".join(bad))
    ch = pd.DataFrame(p.get("changes") or [])
    if len(ch):
        present = [s for s in SECTIONS if (ch["section"] == s).any()]
        for tab, sec in zip(st.tabs([SECTIONS[s] for s in present]), present):
            with tab:
                t = ch[ch["section"] == sec].drop(columns="section")
                if sec == "Scenario weights":
                    t = t.drop(columns="year").assign(item=t["item"].str.replace(
                        "Internal: ", "", regex=False)).rename(columns={"item": "scenario"})
                    w = p.get("weights", {}).get("internal", {})
                    caption(_weights_note(w.get("mode", "")))
                else:
                    t["year"] = t["year"].astype(int)
                if sec == "History":
                    t = t.drop(columns="item")
                st.dataframe(t, use_container_width=True, hide_index=True,
                             height=min(38 + 35 * len(t), 420))
                if sec == "History":
                    caption("The years the source has revised, and the ones it now has "
                            "before the forecast. The file keeps its first year.")
    parts = p.get("parts") or []
    hn = p.get("history_nonoil") or {}
    lines = [f"Non-oil GDP history: {hn.get('added', 0)} year(s) added, "
             f"{hn.get('revised', 0)} revised"] if "nonoil_history" in parts else []
    for f, h in (p.get("history_gcc") or {}).items():
        if "gcc_history" in parts:
            big = f" (largest revision {h['largest']:.6g})" if h.get("revised") else ""
            lines.append(f"{FILES.get(f, f)}: {h.get('added', 0)} row(s) added, "
                         f"{h.get('revised', 0)} revised{big}")
    if lines:
        caption(" · ".join(lines) + ".")
    if not p.get("changed"):
        st.info("Nothing ticked differs from the store: there is nothing to write.",
                icon="ℹ️")
    return bad


def _weights_note(mode: str) -> str:
    if mode == "explicit":
        return ("The config's mode is explicit: the run uses these weights. They replace "
                "the ones in the file, unrounded: the V2 weights of the history and "
                "forecast the config will hold.")
    return ("The config's mode is auto: the run works the weights out itself from the "
            "history and forecast. Only the explicit copy kept in the file changes.")


def write(p: dict, payload: dict, target: str, new_from: str | None = None,
          new: bool = False, key: str = "mf", disabled: bool = False) -> None:
    """The button that writes the proposal into ``target``, a draft; with
    ``new`` it first makes that draft from ``new_from`` (None: the live
    config)."""
    if st.button("Write into the draft", disabled=disabled or not target, key=f"{key}_write"):
        with guard():
            if new:
                api.create_snapshot(target, f"Macro inputs for {payload['reporting_date']} "
                                            f"from vintage {p['vintage']}",
                                    S.get("_user") or "", parent=new_from)
            r = api.macro_apply({**payload, "snapshot": target})
        api.clear()
        S.pop(key, None)
        st.success(f"Written into {target}: {r.get('message', '')}. Test it with a run, "
                   "then move it on under Config versions.", icon="✅")


def draft_panel(label: str) -> None:
    """The update for one draft: the reporting date, the proposal, and the
    write into that same draft."""
    key = f"mf_{label}"
    c = st.columns([2, 1, 3])
    rd = c[0].date_input("Reporting date", quarter_end(), key=f"{key}_rd")
    fy = c[1].number_input("First forecast year", 0, 2100, 0, 1, key=f"{key}_fy",
                           help="0: the first year the store does not confirm.")
    payload = {"reporting_date": rd.isoformat(), "snapshot": label,
               "first_year": int(fy) or None, "parts": choose(key)}
    p = ask(payload, key)
    if p:
        bad = show(p)
        write(p, payload, label, key=key, disabled=bool(bad) or not p.get("changed"))
