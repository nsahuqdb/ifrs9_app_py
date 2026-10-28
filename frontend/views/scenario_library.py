"""Scenario library: the pre-built scenarios, the supervisors' and your own,
and the builder. Nothing is priced here; Scenario stress prices on a run.

A scenario is shocks to a few main variables over Y1-Y5 -- Y1 being the
first forecast year of whichever run it is later priced on -- with the
linked effects moving the rest. The list sits on the left; the scenario
picked opens on the right in three tabs:

    Scenario            the historical event (or the publication, or the
                        basis), the data around it, the scenario narrative,
                        the variables set and why, how it reaches the
                        provision, limitations and sources
    Variables affected  each variable's shock, year by year, and how the
                        values were derived
    Transmission        how the shock travels from the main variables to the
                        others, in a graph, a sentence each and their parts

Edit a scenario, or start blank, to build your own; a new one needs the
same reasons before it can be saved. A library scenario is never changed:
an edited one is saved under a new name to the project's scenario database,
every save kept. A supervisor's new scenario -- the Fed's each February --
is imported from its published tables.
"""
import datetime as _dt

import pandas as pd
import streamlit as st

import api
import scenario_ui as su_
from ui import callout, caption, guard, page_setup, pill

S = st.session_state
H_ = su_.HELP
page_setup("Scenario library",
           "Pre-built, supervisory and your own scenarios: the event behind each, its "
           "narrative and the variables it moves. Nothing is priced here.")
su_.inject_css()
st.markdown("""
<style>
.st-key-libnav {gap: .1rem !important;}
.st-key-libnav .stButton > button > div {justify-content: flex-start; width: 100%;}
.st-key-libnav .stButton > button {justify-content: flex-start; text-align: left;
  background: transparent; border: 1px solid transparent; box-shadow: none;
  padding: .22rem .65rem; min-height: 1.9rem; color: var(--ink-2); font-weight: 500;
  border-radius: 8px;}
.st-key-libnav .stButton > button p {text-align: left; font-size: .87rem;}
.st-key-libnav .stButton > button:hover {background: var(--plum-50); color: var(--plum);
  border-color: transparent;}
.st-key-libnav [class*="st-key-libsel_"] .stButton > button {background: var(--plum-100);
  color: var(--plum); font-weight: 650; border-color: var(--plum-200);}
.st-key-libnav .stMarkdown, .st-key-libnav [data-testid="stMarkdownContainer"] {
  margin: 0 !important;}
.nav-h {font-size: .7rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--faint); padding: .85rem .65rem .25rem; line-height: 1rem;}
.scn-title {font-size: 1.22rem; font-weight: 700; color: var(--ink); letter-spacing: -.01em;
  line-height: 1.25; margin: 0;}
.scn-meta {display: flex; gap: .45rem; align-items: center; flex-wrap: wrap;
  color: var(--muted); font-size: .8rem; margin: .05rem 0 .1rem;}
.scn-desc {color: var(--ink-2); font-size: .93rem; margin: .1rem 0 .2rem;}
</style>""", unsafe_allow_html=True)

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
MODE = S.get("lib_mode", "browse")


def _preview(scn: dict) -> dict:
    keep = {k: scn.get(k) for k in ("name", "main", "linked", "restructured")}
    with guard():
        return api.scn_preview(keep)


def _vals(p: list, u: str) -> str:
    xs = [x for x in (p or []) if x is not None]
    if not xs:
        return ""
    s = ", ".join(su_.num(x, 1) for x in (p or []) if x is not None)
    return f"{s} {'pp' if u == 'pp' else '%'}"


def _text(t: str) -> None:
    st.markdown(f'<div class="scn-text">{su_.esc(t)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ list --
def _pick(sid: str) -> None:
    S["lib_sel"] = sid
    S["lib_mode"] = "browse"


def _to(mode: str) -> None:
    S["lib_mode"] = mode


def nav() -> None:
    st.button("New scenario", icon=":material/add:", use_container_width=True, key="lib_new",
              help="Start a blank scenario: its basis and narrative, then its shocks.",
              on_click=lambda: _start(None, "new"))
    cur = S.get("lib_sel") if MODE == "browse" else None
    with st.container(height=700, border=False, key="libnav"):
        for g, title in su_.GROUPS.items():
            items = [s for s in lib + saved if su_.group_of(s) == g]
            if not items and g not in ("saved", "supervisory"):
                continue
            st.markdown(f'<div class="nav-h">{title}</div>', unsafe_allow_html=True)
            for s in items:
                key = f"libsel_{s['id']}" if s["id"] == cur else f"libitem_{s['id']}"
                st.button(s["name"], key=key, use_container_width=True, on_click=_pick,
                          args=(s["id"],))
            if g == "supervisory":
                st.button("Import a Fed scenario", icon=":material/download:", key="lib_fed",
                          use_container_width=True, on_click=_to, args=("import",),
                          help=H_["fed"])
            if g == "saved" and not items:
                st.caption("None yet. Edit a scenario or start a new one.")
    st.caption(f"Linked effects estimated on macro data {su['vintage']}.", help=H_["shock"])


# ---------------------------------------------------------------- detail --
def _header(scn: dict) -> None:
    c = st.columns([6, 1.7], vertical_alignment="center")
    c[0].markdown(f'<div class="scn-title">{su_.esc(scn["name"])}</div>',
                  unsafe_allow_html=True)
    mine = bool(scn.get("saved"))
    if c[1].button("Edit" if mine else "Edit as new", icon=":material/edit:",
                   use_container_width=True, help=H_["edit"], key="lib_edit"):
        _start(scn, "mine" if mine else "library")
        st.rerun()
    tags = [pill(su_.CAT.get(scn["category"], "Own"), "plum"),
            pill(su_.REGION.get(scn.get("region"), "Qatar"), "muted")]
    if scn.get("tail"):
        tags.append(pill("Beyond the data", "warn"))
    meta = []
    if scn.get("source"):
        meta.append(su_.esc(scn["source"]))
    if mine:
        meta.append(f"saved by {su_.esc(scn.get('updated_by', ''))} on "
                    f"{str(scn.get('updated_at', ''))[:10]}")
        if scn.get("based_on") in ALL:
            meta.append(f"based on {su_.esc(ALL[scn['based_on']]['name'])}")
    st.markdown(f'<div class="scn-meta">{" ".join(tags)}<span>{" · ".join(meta)}</span></div>',
                unsafe_allow_html=True)
    if scn.get("description"):
        st.markdown(f'<div class="scn-desc">{su_.esc(scn["description"])}</div>',
                    unsafe_allow_html=True)


def _story(scn: dict, show_chart: bool = True) -> None:
    head = su_.first_heading(scn)
    hp = {"Historical event": H_["event"], "Published scenario": H_["published"]}.get(
        head, H_["basis"])
    if scn.get("history"):
        st.markdown(f"**{head}**", help=hp)
        _text(scn["history"])
    if show_chart and scn.get("episode") and scn["category"] in ("history", "current") \
            and not scn.get("saved"):
        with guard():
            h = api.scn_history(scn["id"])
        w = h.get("window") or [h["episode"][0], h["episode"][-1]]
        st.markdown(f"**Recorded data, {w[0]}–{w[1]}**", help=H_["history"])
        su_.history_grid(h["series"], h["episode"], LEVEL)
    if scn.get("narrative"):
        st.markdown("**Scenario narrative**", help=H_["narrative"])
        _text(scn["narrative"])
    why = scn.get("why") or {}
    rows = []
    for v, p in (scn.get("main") or {}).items():
        if not p or not any(x is not None for x in p):
            continue
        rows.append((LABEL.get(v, v), _vals(p, VARS.get(v, {}).get("unit", "")),
                     why.get(v, "")))
    if scn.get("restructured"):
        rows.append(("Deferral programme",
                     f"{100 * scn['restructured']:.0f}% of Stage 1", why.get("restructured", "")))
    if rows:
        st.markdown("**Variables set**", help=H_["variables_set"])
        st.markdown("".join(
            f'<div class="scn-var"><span class="nm">{su_.esc(a)}</span>'
            f'<span class="vals">{su_.esc(b)}</span><span class="why">{su_.esc(c)}</span></div>'
            for a, b, c in rows), unsafe_allow_html=True)
    if scn.get("translation"):
        st.markdown("**Translation**", help=H_["translation"])
        _text(scn["translation"])
    if scn.get("book"):
        st.markdown("**Provision calculation**", help=H_["provision"])
        _text(scn["book"])
    if scn.get("limits"):
        st.markdown("**Limitations**", help=H_["limits"])
        _text(scn["limits"])
    refs = scn.get("references") or []
    if refs:
        st.markdown("**Sources**", help=H_["sources"])
        st.markdown("\n".join(f"- [{r.get('title') or r.get('url')}]({r['url']})"
                              if r.get("url") else f"- {r.get('title')}" for r in refs))


def _affected(scn: dict, pv: dict) -> None:
    st.markdown("**Shock to each variable**", help=H_["shock"] + " " + H_["set"])
    su_.shock_grid(pv["paths"])
    su_.shock_table(pv["paths"], scn.get("refs") or {})
    if scn.get("restructured"):
        caption(f"Deferral programme: {100 * scn['restructured']:.0f}% of Stage 1 borrowers "
                "moved to Stage 2 in Y1.")
    if scn.get("saved") or not scn.get("refs"):
        return
    with guard():
        rows = api.scn_derivation(scn["id"])["rows"]
    if rows:
        st.markdown("**How the values were derived**", help=H_["derivation"])
        su_.derivation_table(rows)


def detail() -> None:
    ids = list(ALL)
    sid = S.get("lib_sel")
    if sid not in ALL:
        sid = S["lib_sel"] = ids[0]
    scn = ALL[sid]
    _header(scn)
    pv = _preview(scn)
    t1, t2, t3 = st.tabs(["Scenario", "Variables affected", "Transmission"])
    with t1:
        _story(scn)
    with t2:
        _affected(scn, pv)
    with t3:
        su_.transmission(pv.get("explain") or [], pv["paths"], pv.get("links") or [], ABOUT)


# --------------------------------------------------------------- builder --
TABLE = su_.MainTable(YCOLS, su_.variables(su["variables"]))
REGIONS = {"global": "Global", "gcc": "GCC", "qatar": "Qatar"}
TYPES = {"mine": "Own", "supervisory": "Supervisory"}


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
    S[f"bld_type_{v}"] = "supervisory" if scn.get("category") == "supervisory" else "mine"
    S[f"bld_source_{v}"] = scn.get("source", "")
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
           su_.WHY: st.column_config.TextColumn(width="large", help=H_["rationale"])}
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
    origin = b["origin_scn"] or {}
    return {"name": (S.get(f"bld_name_{ver}") or "").strip() or "New scenario",
            "category": S.get(f"bld_type_{ver}") or "mine",
            "source": (S.get(f"bld_source_{ver}") or "").strip(),
            "description": (S.get(f"bld_desc_{ver}") or "").strip(),
            "region": S.get(f"bld_region_{ver}") or "qatar",
            "history": (S.get(f"bld_hist_{ver}") or "").strip(),
            "narrative": (S.get(f"bld_narr_{ver}") or "").strip(),
            "book": (S.get(f"bld_book_{ver}") or "").strip(),
            "limits": (S.get(f"bld_lim_{ver}") or "").strip(),
            "translation": origin.get("translation", ""),
            "references": refs, "main": main, "shapes": shapes, "why": why,
            "linked": S.get(f"bld_linked_{ver}"), "restructured": restr,
            "based_on": b.get("origin_id") if b["origin"] != "mine" else origin.get("based_on")}


def _missing(scn: dict) -> list:
    out = []
    for k, what in (("description", "a one-line description"),
                    ("history", "the historical event or basis"),
                    ("narrative", "the scenario narrative")):
        if not scn.get(k):
            out.append(what)
    if scn["category"] == "supervisory" and not scn.get("source"):
        out.append("the publisher (source)")
    if not scn["main"] and not scn["restructured"]:
        out.append("at least one main variable")
    out += [f"the rationale for {LABEL.get(v, v)}" for v, p in scn["main"].items()
            if any(x is not None for x in p) and not scn["why"].get(v)]
    return out


def builder() -> None:
    b = S["bld"]
    ver = S["bld_ver"]
    c = st.columns([6, 1.7], vertical_alignment="center")
    title = {"mine": "Edit scenario", "library": "New scenario from the library",
             "new": "New scenario", "fed": "New scenario"}.get(b["origin"], "New scenario")
    c[0].markdown(f'<div class="scn-title">{title}</div>', unsafe_allow_html=True)
    c[1].button("Cancel", icon=":material/close:", use_container_width=True, key="bld_cancel",
                on_click=_to, args=("browse",))
    if b["origin"] == "library":
        caption(f"A copy of {b['origin_name']}; the library keeps the original as it is.")

    c = st.columns([3, 1.4, 1.8])
    c[0].text_input("Name", key=f"bld_name_{ver}")
    c[1].segmented_control("Type", list(TYPES), format_func=TYPES.get, key=f"bld_type_{ver}",
                           help=H_["type"])
    c[2].segmented_control("Region", list(REGIONS), format_func=REGIONS.get,
                           key=f"bld_region_{ver}", help=H_["region"])
    c = st.columns([3, 2])
    c[0].text_input("One-line description", key=f"bld_desc_{ver}",
                    help="What the scenario is, in a sentence.")
    c[1].text_input("Source", key=f"bld_source_{ver}", help=H_["source"],
                    placeholder="e.g. ESRB, 2027 EU-wide stress test")
    c = st.columns(2)
    c[0].text_area("Historical event or basis", key=f"bld_hist_{ver}", height=150,
                   help=H_["basis"],
                   placeholder="The episode, event, publication or risk, and the evidence "
                               "for its size.")
    c[1].text_area("Scenario narrative", key=f"bld_narr_{ver}", height=150,
                   help=H_["narrative"],
                   placeholder="What starts it, how each main variable moves from Y1, and "
                               "what follows.")

    st.markdown("**Variables set**", help=H_["main_table"])
    _main_table(ver)
    c = st.columns([3, 2])
    c[1].number_input("Deferral programme: Stage 1 moved to Stage 2 (%)", 0.0, 100.0,
                      step=5.0, key=f"bld_restr_{ver}", help=H_["deferral"])

    with st.expander("Provision calculation, limitations and sources"):
        c = st.columns(2)
        c[0].text_area("Provision calculation", key=f"bld_book_{ver}", height=90,
                       help=H_["book_txt"])
        c[1].text_area("Limitations", key=f"bld_lim_{ver}", height=90, help=H_["limits"])
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
        st.markdown("**Linked variables**", help=H_["linked_pick"])
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
        t2, t3 = st.tabs(["Variables affected", "Transmission"])
        with t2:
            su_.shock_grid(pv["paths"])
            su_.shock_table(pv["paths"])
        with t3:
            su_.transmission(pv.get("explain") or [], pv["paths"], pv.get("links") or [],
                             ABOUT)
    else:
        st.info("Add a main variable to see what the scenario moves.")

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
    elif c[0].button("Save as new scenario", type="primary", disabled=bool(miss),
                     help=H_["edit"]):
        _save_new(scn)


def _saved(out: dict) -> None:
    api.scn_setup.clear()
    S["lib_sel"] = out["id"]
    S["lib_mode"] = "browse"
    S["_flash"] = f"Saved {out['name']}."
    st.rerun()


def _save_new(scn: dict) -> None:
    with guard():
        out = api.scn_save_new(scn)
    _saved(out)


# ---------------------------------------------------------------- import --
FED_FILES = {"baseline_domestic": ("3a", "baseline_domestic"),
             "baseline_international": ("3b", "baseline_international"),
             "adverse_domestic": ("4a", "severely_adverse_domestic"),
             "adverse_international": ("4b", "severely_adverse_international")}


def _which(name: str) -> str | None:
    n = name.lower().replace(" ", "_").replace("-", "_")
    for k, (code, words) in FED_FILES.items():
        if f"table_{code}" in n or words in n:
            return k
    return None


def fed_import() -> None:
    c = st.columns([6, 1.7], vertical_alignment="center")
    c[0].markdown('<div class="scn-title">Import a Fed scenario</div>', unsafe_allow_html=True)
    c[1].button("Cancel", icon=":material/close:", use_container_width=True, key="fed_cancel",
                on_click=_to, args=("browse",))
    st.markdown('<div class="scn-desc">The Federal Reserve publishes its stress test scenarios '
                'every February. Download them by year, or upload the four tables saved from '
                'its site; the scenario is translated to world GDP and the US rate and saved '
                'under Supervisory.</div>', unsafe_allow_html=True)
    today = _dt.date.today()
    c = st.columns([1.2, 2.2, 3.6], vertical_alignment="bottom")
    # the Fed publishes in February: before then, last year's is the latest
    year = c[0].number_input("Year", 2020, 2100, today.year if today.month >= 2
                             else today.year - 1, step=1, key="fed_year", help=H_["fed"])
    go = c[1].button("Download from the Fed", icon=":material/download:", type="primary",
                     use_container_width=True, key="fed_go")
    up = c[2].file_uploader("Or upload the four tables (CSV)", type=["csv"],
                            accept_multiple_files=True, key="fed_up",
                            help="Table 3A and 3B (baseline, domestic and international) and "
                                 "4A and 4B (severely adverse) from the Fed's stress test page.")
    tables = {}
    for f in up or []:
        k = _which(f.name)
        if k:
            tables[k] = f.getvalue().decode("utf-8-sig", "replace")
    if up:
        got = [k for k in FED_FILES if k in tables]
        caption(f"Recognised {len(got)} of 4 tables"
                + (f": missing {', '.join(k.replace('_', ' ') for k in FED_FILES if k not in tables)}."
                   if len(got) < 4 else "."))
    if go or (up and len(tables) == 4 and S.get("fed_last") != (year, tuple(sorted(tables)))):
        try:
            with st.spinner("Reading the Fed's tables…"):
                S["fed_res"] = api.scn_fed(int(year), tables or None)
            S["fed_last"] = (year, tuple(sorted(tables)))
        except api.BackendError as e:
            S.pop("fed_res", None)
            callout("err", str(e))
    res = S.get("fed_res")
    if not res:
        return
    scn = res["scenario"]
    st.divider()
    _header({**scn, "id": "_fed"})
    pv = _preview(scn)
    t1, t2, t3 = st.tabs(["Scenario", "Variables affected", "Transmission"])
    with t1:
        _story(scn, show_chart=False)
    with t2:
        st.markdown("**Shock to each variable**", help=H_["shock"] + " " + H_["set"])
        su_.shock_grid(pv["paths"])
        su_.shock_table(pv["paths"])
    with t3:
        su_.transmission(pv.get("explain") or [], pv["paths"], pv.get("links") or [], ABOUT)
    if st.button("Save to the library", type="primary", icon=":material/save:", key="fed_save"):
        S.pop("fed_res", None)
        _save_new(scn)


# ------------------------------------------------------------------ page --
left, right = st.columns([1, 3.3], gap="large")
with left:
    nav()
with right:
    if MODE == "build" and "bld" in S:
        builder()
    elif MODE == "import":
        fed_import()
    else:
        detail()
