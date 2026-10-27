"""Scenario library: the pre-built scenarios and the saved ones, and the
builder.

Pick a scenario to read what it is, see how the episode behind it unfolded
(for a historical one), what it sets and what the linked effects move with
it, against the store's baseline. Edit it -- or start blank -- to build your
own: set the main variables and their shapes; the linked variables follow
and cannot be edited, though you choose which of them move. A library
scenario is never changed: an edited one is saved under a new name. Saved
scenarios go to the project's scenario database, every save kept.
"""
import pandas as pd
import streamlit as st

import api
import scenario_ui as su_
from ui import callout, caption, guard, page_setup, pill

S = st.session_state
page_setup("Scenario library",
           "Pre-built scenarios and your own: what each sets, the history behind it "
           "and what it moves. Edit any of them to build a new one.")

with st.spinner("Fitting the linked effects on the macro data…"):
    with guard():
        su = api.scn_setup()
H, Y0 = int(su["horizon"]), int(su["first_year"])
years = list(range(Y0, Y0 + H))
VARS = {v["variable"]: v for v in su["variables"]}
LABEL = {k: v["label"] for k, v in VARS.items()}
lib = su["library"]
saved = su["saved"]
ALL = {s["id"]: s for s in lib + saved}
caption(f"Year 1 is {Y0} · macro data {su['vintage']} · every number is a change from "
        "the baseline forecast")


def _preview(scn: dict) -> dict:
    with guard():
        return api.scn_preview(scn, None, Y0)


# ---------------------------------------------------------------- builder --
YCOLS = [str(y) for y in years]
TABLE = su_.MainTable(years, su_.variables(su["variables"]))
LABEL_OF = TABLE.label
VAR_OF = TABLE.var


def _start(scn: dict | None, kind: str) -> None:
    """Open the builder on a copy of ``scn`` (or blank)."""
    scn = scn or {}
    S["bld"] = {"table": TABLE.from_scenario(scn), "gen": 0, "origin": kind,
                "origin_id": scn.get("id"), "origin_name": scn.get("name"),
                "origin_scn": scn}
    S["bld_ver"] = S.get("bld_ver", 0) + 1
    v = S["bld_ver"]
    S[f"bld_name_{v}"] = scn.get("name", "") if kind == "mine" else (
        f"{scn['name']} (edited)" if scn else "")
    S[f"bld_desc_{v}"] = scn.get("description", "")
    S[f"bld_restr_{v}"] = 100.0 * float(scn.get("restructured") or 0.0)
    S[f"bld_linked_{v}"] = scn.get("linked")
    S["lib_mode"] = "build"


def _main_table(ver: int) -> None:
    b = S["bld"]
    t = b["table"]
    unit_help = "; ".join(f"{LABEL[v]} in {su_.unit(VARS[v]['unit'])}" for v in VARS)
    cfg = {"Variable": st.column_config.SelectboxColumn(options=list(LABEL.values()),
                                                        required=True, width="medium"),
           "Shape": st.column_config.SelectboxColumn(
               options=list(su_.SHAPES.values()), width="small",
               help="One year: the move in year 1. Recovers: back to nothing over "
                    "'Over years'. Held: every year. Year by year: type each year; a "
                    "blank year is left to the linked effects."),
           "Size": st.column_config.NumberColumn(format="%.2f", help=unit_help),
           "Over years": st.column_config.NumberColumn(min_value=1, max_value=H, step=1,
                                                       width="small")}
    for y in YCOLS:
        cfg[y] = st.column_config.NumberColumn(format="%+.2f", width="small")
    got = st.data_editor(t, key=f"bld_ed_{ver}_{b['gen']}", num_rows="dynamic",
                         use_container_width=True, hide_index=True, column_config=cfg)
    settled, dup = TABLE.settle(got, t)
    for v in dup:
        st.toast(f"{LABEL[v]} is already a main variable.")
    if su_.canon(settled) != su_.canon(t):
        b["table"] = settled
        b["gen"] += 1
        st.rerun()


def _scenario_from_builder(ver: int) -> dict:
    b = S["bld"]
    main, shapes = TABLE.to_main(b["table"])
    return {"name": (S.get(f"bld_name_{ver}") or "").strip() or "New scenario",
            "description": S.get(f"bld_desc_{ver}") or "", "main": main, "shapes": shapes,
            "linked": S.get(f"bld_linked_{ver}"),
            "restructured": float(S.get(f"bld_restr_{ver}") or 0.0) / 100.0,
            "category": "mine", "based_on": b.get("origin_id") if b["origin"] != "mine"
            else (b["origin_scn"] or {}).get("based_on")}


def _numbers(s: dict) -> tuple:
    main = {v: tuple(None if x is None else round(float(x), 6) for x in (p + [None] * H)[:H])
            for v, p in (s.get("main") or {}).items() if p and any(x is not None for x in p)}
    lk = s.get("linked")
    return (tuple(sorted(main.items())), None if lk is None else tuple(sorted(lk)),
            round(float(s.get("restructured") or 0.0), 6))


def builder() -> None:
    b = S["bld"]
    ver = S["bld_ver"]
    top = st.columns([1, 5])
    if top[0].button("Library", icon=":material/arrow_back:"):
        S["lib_mode"] = "browse"
        st.rerun()
    c = st.columns([2, 4])
    c[0].text_input("Name", key=f"bld_name_{ver}")
    c[1].text_input("What it describes", key=f"bld_desc_{ver}")
    if b["origin"] in ("library",):
        callout("info", f"Started from **{b['origin_name']}**. The library keeps it as it "
                        "is; yours is saved as a new scenario.")

    st.markdown("**Main variables** — the ones you set, as a change from the baseline")
    _main_table(ver)
    c = st.columns([3, 2])
    c[0].caption("Add a row for another variable. Change the shape or size and the years "
                 "follow; type in a year and the row becomes year by year. A blank year "
                 "is left to the linked effects.")
    c[1].number_input("Deferral programme: Stage 1 moved to Stage 2 (%)", 0.0, 100.0,
                      step=5.0, key=f"bld_restr_{ver}",
                      help="The share of Stage 1 borrowers a payment-deferral programme "
                           "moves to Stage 2 on top of the rating effect. In 2020 it was "
                           "about 72% of QDB's.")

    scn = _scenario_from_builder(ver)
    if not scn["main"] and not scn["restructured"]:
        st.info("Add a main variable to see what the scenario moves.")
        return
    pv = _preview(scn)
    rec = pv["recommended"]
    st.markdown("**Linked effects** — what moves with them")
    others = [v for v in VARS if v not in scn["main"]]
    cur = S.get(f"bld_linked_{ver}")
    default = [v for v in (rec if cur is None else cur) if v in others]
    pick = st.multiselect("Variables that move with the main ones", others, default,
                          format_func=LABEL.get, key=f"bld_linkpick_{ver}",
                          label_visibility="collapsed")
    new_linked = None if set(pick) == set(rec) and cur is None else pick
    if new_linked != cur:
        S[f"bld_linked_{ver}"] = new_linked
        st.rerun()
    idle = [LABEL[v] for v in pick if v not in rec]
    caption("Their paths come from the linked effects, estimated on the macro data; "
            "they cannot be typed in. To set one yourself, make it a main variable."
            + (f" Not reached by the main variables, so unmoved: {', '.join(idle)}."
               if idle else ""))
    su_.path_grid(pv["paths"])
    su_.show_path_table(pv["paths"], years)
    if any(p.get("beyond_data") for p in pv["paths"]):
        caption("Circled years: a linked effect is carried beyond the largest move in "
                "the data it was estimated on.")

    # saving: a library scenario is copied, a saved one gets a new version
    st.divider()
    origin = b["origin_scn"] or {}
    changed = _numbers(scn) != _numbers(origin) if origin else True
    c = st.columns([2, 2, 2, 4])
    if b["origin"] == "mine":
        if c[0].button("Save", type="primary", disabled=not changed and
                       scn["name"] == origin.get("name") and
                       scn["description"] == origin.get("description", "")):
            with guard():
                out = api.scn_save_version(b["origin_id"], scn)
            api.scn_setup.clear()
            S["lib_sel"] = out["id"]
            S["lib_mode"] = "browse"
            S["_flash"] = f"Saved {out['name']}."
            st.rerun()
        if c[1].button("Save as new"):
            _save_new(scn)
        if c[2].button("Delete", help="Hide it from the library; its versions are kept."):
            with guard():
                api.scn_delete(b["origin_id"])
            api.scn_setup.clear()
            S.pop("lib_sel", None)
            S["lib_mode"] = "browse"
            S["_flash"] = f"Deleted {origin.get('name')}."
            st.rerun()
    else:
        if c[0].button("Save as new scenario", type="primary"):
            _save_new(scn)


def _save_new(scn: dict) -> None:
    with guard():
        out = api.scn_save_new(scn)
    api.scn_setup.clear()
    S["lib_sel"] = out["id"]
    S["lib_cat"] = "Saved"
    S["lib_mode"] = "browse"
    S["_flash"] = f"Saved {out['name']}."
    st.rerun()


# ----------------------------------------------------------------- browse --
def browse() -> None:
    left, right = st.columns([1, 2.6], gap="large")
    with left:
        cats = ["All", "History", "Supervisory", "What-if", "Saved"]
        S.setdefault("lib_cat", "All")
        st.segmented_control("Show", cats, key="lib_cat", label_visibility="collapsed")
        want = S.get("lib_cat") or "All"
        items = [s for s in lib + saved
                 if want == "All" or su_.CAT.get(s["category"]) == want
                 or (want == "History" and s["category"] == "current")]
        if not items:
            st.caption("No saved scenarios yet. Edit one from the library, or start a new one.")
        else:
            ids = [s["id"] for s in items]
            if S.get("lib_sel") not in ids:
                S["lib_sel"] = ids[0]
            st.radio("Scenario", ids, key="lib_sel", label_visibility="collapsed",
                     format_func=lambda i: ALL[i]["name"])
        if st.button("New scenario", icon=":material/add:", use_container_width=True):
            _start(None, "new")
            st.rerun()
    with right:
        sid = S.get("lib_sel")
        if not sid or sid not in ALL:
            return
        scn = ALL[sid]
        tags = pill(su_.CAT.get(scn["category"], "Saved"), "info")
        if scn.get("tail"):
            tags += " " + pill("Beyond the data", "warn")
        st.markdown(f"### {scn['name']}")
        st.markdown(tags, unsafe_allow_html=True)
        if scn.get("description"):
            st.markdown(scn["description"])
        meta = []
        if scn.get("source"):
            meta.append(f"Source: {scn['source']}")
        if scn["category"] == "mine":
            meta.append(f"Saved by {scn.get('updated_by', '')} on "
                        f"{str(scn.get('updated_at', ''))[:10]}")
            if scn.get("based_on") and scn["based_on"] in ALL:
                meta.append(f"Based on {ALL[scn['based_on']]['name']}")
        if meta:
            caption(" · ".join(meta))
        if scn.get("translation"):
            caption(f"How it is translated: {scn['translation']}")
        b = st.columns([2, 2, 4])
        if b[0].button("Edit" if scn["category"] == "mine" else "Edit as a new scenario",
                       icon=":material/edit:", use_container_width=True):
            _start(scn, "mine" if scn["category"] == "mine" else "library")
            st.rerun()
        if b[1].button("Price on the run", icon=":material/calculate:",
                       use_container_width=True, disabled=not S.get("run_id")):
            S["scn_pick"] = sid
            st.switch_page("frontend/views/scenario_stress.py")

        if scn.get("episode") and scn["category"] in ("history", "current"):
            with guard():
                h = api.scn_history(sid)
            e = h["episode"]
            st.markdown(f"**How it unfolded** — {e[0]}" + (f"–{e[-1]}" if e[-1] != e[0] else "")
                        + " shaded; the variables the scenario sets in plum")
            su_.history_grid(h["series"], e)
        pv = _preview(scn)
        st.markdown(f"**The scenario from {Y0}** — baseline dashed; set in plum, "
                    "linked in teal")
        su_.path_grid(pv["paths"])
        su_.show_path_table(pv["paths"], years, scn.get("refs") or None)
        if scn.get("restructured"):
            caption(f"Deferral programme: {100 * scn['restructured']:.0f}% of Stage 1 "
                    "borrowers moved to Stage 2.")
        if any(p.get("beyond_data") for p in pv["paths"]):
            caption("Circled years: a linked effect is carried beyond the largest move in "
                    "the data it was estimated on.")


if S.get("lib_mode") == "build" and "bld" in S:
    builder()
else:
    browse()
