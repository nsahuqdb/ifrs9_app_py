"""A config's macro inputs, filled from the macro store when asked.

After a refresh of the store, a rating model's variables -- whichever
model.yml gives it -- can be taken from the latest vintage, forecast and
history together, and written into a draft config version with nothing typed
by hand. The scenario weights of a model filled move to automatic (worked
out at run time) unless kept. What is not ticked stays as it is in the file,
and every file can still be edited by hand. Nothing here names a variable:
a model change needs no change to this page. Drawn on the Macro data page
and on a draft under Config versions.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import api
from ui import caption, guard

S = st.session_state
TABS = {"forecast": "Forecast", "history": "History"}


def quarter_end(today: dt.date | None = None) -> dt.date:
    """The last day of the quarter before today's."""
    td = today or dt.date.today()
    return dt.date(td.year, 3 * ((td.month - 1) // 3) + 1, 1) - dt.timedelta(days=1)


def choose(key: str) -> dict:
    """Which models to fill and whose weights to keep."""
    with guard():
        models = api.macro_models()["models"]
    chosen, keep = [], []
    for k, label in models.items():
        c = st.columns([1, 2])
        if c[0].checkbox(f"{label} model", True, key=f"{key}_{k}",
                         help="Every variable of this model (model.yml) that the store "
                              "holds: its forecast and its history."):
            chosen.append(k)
            if c[1].checkbox("Keep the current scenario weights", False,
                             key=f"{key}_{k}_keep",
                             help="Unticked: the weights go to automatic, worked out at run "
                                  "time from the history and forecast. Ticked: they stay as "
                                  "they are in the file."):
                keep.append(k)
    return {"models": chosen, "keep_weights": keep}


def ask(payload: dict, key: str) -> dict | None:
    """The proposal for ``payload``, asked for on a button and kept while
    the inputs stay the same; a change of what is ticked asks again."""
    def base(p):
        return {k: v for k, v in p.items() if k not in ("models", "keep_weights")}

    got = S.get(key)
    again = bool(got and got[0] != payload and base(got[0]) == base(payload))
    if not payload.get("models"):
        caption("Tick a model to fill.")
        return None
    if st.button("Propose", type="primary", key=f"{key}_go") or again:
        with st.spinner("Reading the store…"):
            with guard():
                S[key] = (payload, api.macro_propose(payload))
    got = S.get(key)
    return got[1] if got and got[0] == payload else None


def show(p: dict) -> list:
    """What moves: the weights, then the forecast and the history. Returns
    the checks that failed."""
    y = p["years"]
    caption(f"Forecast {y[0]}–{y[-1]} from vintage {p['vintage']} "
            f"({str(p.get('release', ''))[:10]}) · {p['changed']:,} values change."
            + (f" Not in the store for these years, so kept as they are: "
               f"{', '.join(p['kept'])}." if p.get("kept") else ""))
    for w in p.get("warnings") or []:
        st.warning(w, icon="⚠️")
    bad = [x["check"] for x in p.get("checks") or [] if not x["ok"]]
    if bad:
        st.error("Failed: " + "; ".join(bad))
    for w in p.get("weights") or []:
        st.markdown(f"**{w['model']}**: scenario weights {w['current']} → automatic, "
                    "worked out at run time from the history and forecast.")
    for tab, k in zip(st.tabs(list(TABS.values())), TABS):
        with tab:
            t = pd.DataFrame(p.get(k) or [])
            if not len(t):
                caption("Nothing moves." if k == "history" else "Nothing filled.")
                continue
            st.dataframe(t, use_container_width=True, hide_index=True,
                         height=min(38 + 35 * len(t), 420))
    if not p.get("changed"):
        st.info("The ticked models already hold what the store has: nothing to write.",
                icon="ℹ️")
    return bad


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
    """The update for one draft: the reporting date, the models, the
    proposal, and the write into that same draft."""
    key = f"mf_{label}"
    rd = st.columns([1, 3])[0].date_input("Reporting date", quarter_end(), key=f"{key}_rd")
    payload = {"reporting_date": rd.isoformat(), "snapshot": label, **choose(key)}
    p = ask(payload, key)
    if p:
        bad = show(p)
        write(p, payload, label, key=key, disabled=bool(bad) or not p.get("changed"))
