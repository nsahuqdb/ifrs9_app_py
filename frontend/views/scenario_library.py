"""Scenario library: the pre-built scenarios and the saved ones, and the
builder. Nothing is priced here; Scenario stress prices on a run.

A scenario is shocks to a few main variables over Y1-Y5 -- Y1 being the
first forecast year of whichever run it is later priced on -- with the
linked effects moving the rest. Each scenario carries its reasons: what it
captures, how it unfolds, why each main variable is set and how its numbers
were sized, and its sources. Pick one to read them, see the episode behind
it in the data and its shocks year by year, and why each linked variable
moves. Edit it -- or start blank -- to build your own; a new scenario needs
the same reasons before it can be saved. A library scenario is never
changed: an edited one is saved under a new name to the project's scenario
database, every save kept.
"""
import pandas as pd
import streamlit as st

import api
import scenario_ui as su_
from ui import callout, caption, guard, page_setup, pill

S = st.session_state
H_ = su_.HELP
page_setup("Scenario library",
           "Pre-built scenarios and your own: what each captures, how it unfolds and "
           "what it moves. Edit any of them to build a new one.")

with st.spinner("Fitting the linked effects on the macro data…"):
    with guard():
        su = api.scn_setup()
H = int(su["horizon"])
YCOLS = [su_.YL(j + 1) for j in range(H)]
VARS = {v["variable"]: v for v in su["variables"]}
LABEL = {k: v["label"] for k, v in VARS.items()}
ABOUT = {k: v.get("about", "") for k, v in VARS.items()}
LEVEL = su_.level_units(su["variables"])
lib = su["library"]
saved = su["saved"]
ALL = {s["id"]: s for s in lib + saved}
st.caption(f"Shocks in Y1–Y{H} · linked effects estimated on macro data {su['vintage']}",
           help=H_["shock"])


def _preview(scn: dict) -> dict:
    keep = {k: scn.get(k) for k in ("name", "main", "linked", "restructured")}
    with guard():
        return api.scn_preview(keep)


def _sources(refs: list) -> None:
    if not refs:
        return
    st.markdown("**Sources**", help=H_["sources"])
    for r in refs:
        t = r.get("title") or r.get("url") or ""
        st.markdown(f"- [{t}]({r['url']})" if r.get("url") else f"- {t}")


# ---------------------------------------------------------------- builder --
TABLE = su_.MainTable(YCOLS, su_.variables(su["variables"]))
REGIONS = {"global": "Global", "gcc": "GCC", "qatar": "Qatar"}


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
    S[f"bld_region_{v}"] = scn.get("region") or "qatar"
    S[f"bld_hist_{v}"] = scn.get("history", "")
    S[f"bld_narr_{v}"] = scn.get("narrative", "")
    S[f"bld_book_{v}"] = scn.get("book", "")
    S[f"bld_lim_{v}"] = scn.get("limits", "")
    S[f"bld_restr_{v}"] = 100.0 * float(scn.get("restructured") or 0.0)
    S[f"bld_linked_{v}"] = scn.get("linked")
    S[f"bld_src_{v}"] = pd.DataFrame(scn.get("references") or [], columns=["title", "url"])
    S["lib_mode"] = "build"


def _main_table(ver: int) -> None:
    b = S["bld"]
    t = b["table"]
    unit_help = "In the variable's own unit: " + "; ".join(
        f"{LABEL[v]} {su_.unit(VARS[v]['unit'])} (1 sd = {VARS[v]['sd']:.1f})" for v in VARS)
    cfg = {"Variable": st.column_config.SelectboxColumn(options=list(LABEL.values()),
                                                        required=True, width="medium"),
           "Shape": st.column_config.SelectboxColumn(
               options=list(su_.SHAPES.values()), width="small",
               help="One year: the shock in Y1. Recovers: back to nothing over 'Over years'. "
                    "Held: every year. Year by year: type each year; a blank year is left "
                    "to the linked effects."),
           "Size": st.column_config.NumberColumn(format="%.2f", help=unit_help),
           "Over years": st.column_config.NumberColumn(min_value=1, max_value=H, step=1,
                                                       width="small",
                                                       help="For Recovers: years to fade."),
           "Why": st.column_config.TextColumn(width="large", help=H_["why_col"])}
    for y in YCOLS:
        cfg[y] = st.column_config.NumberColumn(format="%+.2f", width="small",
                                               help=f"The shock in {y}.")
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
    main, shapes, why = TABLE.to_main(b["table"])
    restr = float(S.get(f"bld_restr_{ver}") or 0.0) / 100.0
    if restr:
        why["restructured"] = (b["origin_scn"] or {}).get("why", {}).get("restructured", "")
    src = S.get(f"bld_src_{ver}")
    refs = [] if src is None else [
        {"title": str(r.get("title") or "").strip(), "url": str(r.get("url") or "").strip()}
        for r in pd.DataFrame(src).to_dict("records")
        if str(r.get("title") or "").strip() or str(r.get("url") or "").strip()]
    return {"name": (S.get(f"bld_name_{ver}") or "").strip() or "New scenario",
            "description": (S.get(f"bld_desc_{ver}") or "").strip(),
            "region": S.get(f"bld_region_{ver}") or "qatar",
            "history": (S.get(f"bld_hist_{ver}") or "").strip(),
            "narrative": (S.get(f"bld_narr_{ver}") or "").strip(),
            "book": (S.get(f"bld_book_{ver}") or "").strip(),
            "limits": (S.get(f"bld_lim_{ver}") or "").strip(),
            "references": refs, "main": main, "shapes": shapes, "why": why,
            "linked": S.get(f"bld_linked_{ver}"), "restructured": restr,
            "category": "mine",
            "based_on": b.get("origin_id") if b["origin"] != "mine"
            else (b["origin_scn"] or {}).get("based_on")}


def _missing(scn: dict) -> list:
    out = []
    for k, what in (("description", "a one-line description"),
                    ("history", "what it captures"), ("narrative", "how it unfolds")):
        if not scn.get(k):
            out.append(what)
    if not scn["main"] and not scn["restructured"]:
        out.append("at least one main variable")
    out += [f"why {LABEL.get(v, v)} is set" for v, p in scn["main"].items()
            if any(x is not None for x in p) and not scn["why"].get(v)]
    return out


def _numbers(s: dict) -> tuple:
    main = {v: tuple(None if x is None else round(float(x), 6) for x in (p + [None] * H)[:H])
            for v, p in (s.get("main") or {}).items() if p and any(x is not None for x in p)}
    lk = s.get("linked")
    return (tuple(sorted(main.items())), None if lk is None else tuple(sorted(lk)),
            round(float(s.get("restructured") or 0.0), 6))


def builder() -> None:
    b = S["bld"]
    ver = S["bld_ver"]
    if st.button("Library", icon=":material/arrow_back:"):
        S["lib_mode"] = "browse"
        st.rerun()
    if b["origin"] == "library":
        callout("info", f"Started from **{b['origin_name']}**. The library keeps it as it is; "
                        "yours is saved as a new scenario.")

    st.markdown("**About the scenario**", help=H_["story"])
    c = st.columns([3, 2])
    c[0].text_input("Name", key=f"bld_name_{ver}")
    c[1].segmented_control("Where the shock starts", list(REGIONS), format_func=REGIONS.get,
                           key=f"bld_region_{ver}", help=H_["region"])
    st.text_input("One-line description", key=f"bld_desc_{ver}",
                  help="What the scenario is, in a sentence.")
    c = st.columns(2)
    c[0].text_area("What it captures", key=f"bld_hist_{ver}", height=150, help=H_["captures"],
                   placeholder="The episode, event or risk, and the evidence for its size.")
    c[1].text_area("How it unfolds", key=f"bld_narr_{ver}", height=150, help=H_["narrative"],
                   placeholder="What starts it, how each main variable moves from Y1, "
                               "and what follows.")

    st.markdown("**Main variables** — the shocks you set", help=H_["main_table"])
    _main_table(ver)
    c = st.columns([3, 2])
    c[1].number_input("Deferral programme: Stage 1 moved to Stage 2 (%)", 0.0, 100.0,
                      step=5.0, key=f"bld_restr_{ver}", help=H_["deferral"])

    with st.expander("More: how it reaches the book, what to keep in mind, sources"):
        c = st.columns(2)
        c[0].text_area("How it reaches the provision", key=f"bld_book_{ver}", height=90,
                       help=H_["book_txt"])
        c[1].text_area("Keep in mind", key=f"bld_lim_{ver}", height=90, help=H_["limits"])
        st.markdown("Sources", help=H_["sources"])
        S[f"bld_src_{ver}"] = st.data_editor(
            S[f"bld_src_{ver}"], key=f"bld_srced_{ver}", num_rows="dynamic",
            use_container_width=True, hide_index=True,
            column_config={"title": st.column_config.TextColumn("Title", width="large"),
                           "url": st.column_config.LinkColumn("Link", width="large")})

    scn = _scenario_from_builder(ver)
    if scn["main"] or scn["restructured"]:
        pv = _preview(scn)
        rec = pv["recommended"]
        st.markdown("**Linked effects** — what moves with the main variables",
                    help=H_["linked_pick"])
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
        if idle:
            caption(f"Not reached by the main variables, so not moved: {', '.join(idle)}.")
        st.markdown(f"**Shocks, Y1–Y{H}**", help=H_["shock"] + " " + H_["set"])
        su_.path_grid(pv["paths"])
        su_.show_path_table(pv["paths"])
        with st.expander("Why each linked variable moves"):
            st.caption("Each value is the sum of its drivers' parts.", help=H_["why"])
            su_.explain_tables(pv.get("explain") or [], pv["paths"], ABOUT)
    else:
        st.info("Add a main variable to see what the scenario moves.")

    # saving: a library scenario is copied, a saved one gets a new version
    st.divider()
    miss = _missing(scn)
    if miss:
        caption("To save, add " + "; ".join(miss) + ".")
    origin = b["origin_scn"] or {}
    c = st.columns([2, 2, 2, 4])
    if b["origin"] == "mine":
        if c[0].button("Save", type="primary", disabled=bool(miss),
                       help="A new version of this scenario; the earlier ones are kept."):
            with guard():
                out = api.scn_save_version(b["origin_id"], scn)
            _saved(out)
        if c[1].button("Save as new", disabled=bool(miss)):
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
        if c[0].button("Save as new scenario", type="primary", disabled=bool(miss),
                       help=H_["edit"]):
            _save_new(scn)


def _saved(out: dict) -> None:
    api.scn_setup.clear()
    S["lib_sel"] = out["id"]
    S["lib_cat"] = "Saved"
    S["lib_mode"] = "browse"
    S["_flash"] = f"Saved {out['name']}."
    st.rerun()


def _save_new(scn: dict) -> None:
    with guard():
        out = api.scn_save_new(scn)
    _saved(out)


# ----------------------------------------------------------------- browse --
FILTERS = {"All": lambda s: True,
           "Global": lambda s: s["category"] in ("history", "current")
           and s.get("region") == "global",
           "GCC & Qatar": lambda s: s["category"] not in ("mine", "supervisory")
           and s.get("region") in ("gcc", "qatar"),
           "Supervisory": lambda s: s["category"] == "supervisory",
           "What-if": lambda s: s["category"] == "hypothetical",
           "Saved": lambda s: s["category"] == "mine"}
FILTER_HELP = ("Global: past episodes that started in the world economy. GCC & Qatar: "
               "episodes and what-ifs that start in the region. Supervisory: scenarios "
               "published by supervisors. What-if: built from recorded episodes, not "
               "events in themselves. Saved: your own.")


def _story(scn: dict) -> None:
    mine = scn["category"] == "mine"
    if scn.get("history"):
        st.markdown("**What it captures**" if mine else "**What happened**",
                    help=H_["captures"] if mine else "From the sources listed below.")
        st.markdown(scn["history"])
    if scn.get("narrative"):
        st.markdown("**How it unfolds**", help=H_["narrative"])
        st.markdown(scn["narrative"])
    why = {k: v for k, v in (scn.get("why") or {}).items() if v}
    if why:
        st.markdown("**Why each main variable is set**", help=H_["why_col"])
        for v, txt in why.items():
            name = "Deferral programme" if v == "restructured" else LABEL.get(v, v)
            st.markdown(f"- **{name}.** {txt}")
    if scn.get("translation"):
        st.markdown("**How it is translated**",
                    help="A supervisory scenario's variables are not all ours; this is how "
                         "they were mapped onto the variables here.")
        st.markdown(scn["translation"])
    if scn.get("book"):
        st.markdown("**How it reaches the provision**", help=H_["book"])
        st.markdown(scn["book"])
    if scn.get("limits"):
        st.markdown("**Keep in mind**", help=H_["limits"])
        st.markdown(scn["limits"])
    _sources(scn.get("references") or [])


def _shocks(scn: dict, pv: dict) -> None:
    st.markdown(f"**Shocks, Y1–Y{H}**", help=H_["shock"] + " " + H_["set"])
    su_.path_grid(pv["paths"])
    su_.show_path_table(pv["paths"], scn.get("refs") or {})
    if scn.get("restructured"):
        caption(f"Deferral programme: {100 * scn['restructured']:.0f}% of Stage 1 borrowers "
                "moved to Stage 2 in Y1.")
    if scn["category"] == "mine":
        return
    with guard():
        d = pd.DataFrame(api.scn_derivation(scn["id"])["rows"])
    if not len(d):
        return
    st.markdown("**How each shock was derived**", help=H_["derivation"])
    rows = []
    for _, r in d.iterrows():
        u = su_.unit(r["unit"])
        if r["rule"] == "source":
            how = "from the source"
        elif r["rule"] == "then":
            how = "held at the new level"
        elif r["rule"] == "actual":
            how = f"recorded {r['recorded']:+.2f}{'%' if u == '%' else ''} in {int(r['year'])}"
        else:
            how = (f"{r['recorded']:.2f} in {int(r['year'])} less "
                   f"{r['reference']:.2f} in {int(r['reference_year'])}")
        rows.append({"Variable": r["label"], "Unit": u, "Y": su_.YL(int(r["y"])),
                     "Shock": r["shock"], "How": how})
    st.dataframe(pd.DataFrame(rows).style.format({"Shock": "{:+.2f}"}),
                 use_container_width=True, hide_index=True)


def browse() -> None:
    S.setdefault("lib_cat", "All")
    st.pills("Show", list(FILTERS), key="lib_cat", help=FILTER_HELP)
    want = S.get("lib_cat") or "All"
    left, right = st.columns([1, 2.6], gap="large")
    with left:
        items = [s for s in lib + saved if FILTERS[want](s)]
        if not items:
            st.caption("No saved scenarios yet. Edit one from the library, or start a new one.")
        else:
            ids = [s["id"] for s in items]
            if S.get("lib_sel") not in ids:
                S["lib_sel"] = ids[0]
            st.radio("Scenario", ids, key="lib_sel", label_visibility="collapsed",
                     format_func=lambda i: ALL[i]["name"])
        if st.button("New scenario", icon=":material/add:", use_container_width=True,
                     help="Start a blank scenario: its reasons, then its shocks."):
            _start(None, "new")
            st.rerun()
    with right:
        sid = S.get("lib_sel")
        if not sid or sid not in ALL:
            return
        scn = ALL[sid]
        tags = pill(su_.CAT.get(scn["category"], "Saved"), "info")
        tags += " " + pill(su_.REGION.get(scn.get("region"), "Qatar"), "muted")
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
        if st.button("Edit" if scn["category"] == "mine" else "Edit as a new scenario",
                     icon=":material/edit:", help=H_["edit"]):
            _start(scn, "mine" if scn["category"] == "mine" else "library")
            st.rerun()

        pv = _preview(scn)
        has_hist = bool(scn.get("episode")) and scn["category"] in ("history", "current")
        names = ["Story", f"Shocks Y1–Y{H}", "Why each variable moves"]
        if has_hist:
            names.insert(1, "How it unfolded")
        tabs = dict(zip(names, st.tabs(names)))
        with tabs["Story"]:
            _story(scn)
        if has_hist:
            with tabs["How it unfolded"]:
                with guard():
                    h = api.scn_history(sid)
                e = h["episode"]
                span = f"{e[0]}" if e[-1] == e[0] else f"{e[0]}–{e[-1]}"
                st.markdown(f"**The macro data around {span}**", help=H_["history"])
                su_.history_grid(h["series"], e, LEVEL)
        with tabs[f"Shocks Y1–Y{H}"]:
            _shocks(scn, pv)
        with tabs["Why each variable moves"]:
            st.markdown("**What moves each linked variable, year by year**", help=H_["why"])
            su_.explain_tables(pv.get("explain") or [], pv["paths"], ABOUT)


if S.get("lib_mode") == "build" and "bld" in S:
    builder()
else:
    browse()
