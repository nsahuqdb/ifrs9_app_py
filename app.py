"""
IFRS 9 ECL — front end.

    uvicorn backend.main:app --reload --port 8000     # backend, first
    streamlit run app.py                              # then this

The two run as separate processes. This one draws; the backend calculates.
Nothing here imports the ifrs9qdb package, so the interface cannot disagree
with the API.

The frame every page shares is drawn here: the logo and the menu on one bar,
and -- on the pages that read a run -- which run, chosen in the page's own
title row rather than in a sidebar that hides it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "frontend"))

import importlib  # noqa: E402

import api  # noqa: E402
import ui  # noqa: E402

# A running app keeps the api and ui modules it first imported: the pages are
# re-read on every rerun, these are not. After a code update a page could then
# call a function the old module does not have. Reload either when its file
# has changed since it was loaded.
for _mod in (api, ui):
    _mtime = Path(_mod.__file__).stat().st_mtime
    if getattr(_mod, "_loaded_mtime", _mtime) != _mtime:
        importlib.reload(_mod)
    _mod._loaded_mtime = _mtime

st.set_page_config(
    page_title="IFRS 9 ECL",
    page_icon=str(ui.ASSETS / "favicon.png"),
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.logo(str(ui.ASSETS / "logo.png"), size="large")
ui.inject_css()
S = st.session_state

# Fail once, here, rather than on every page in turn.
try:
    h = api.health()
    runs = api.runs()
except api.BackendError as e:
    ui.backend_down(str(e), api.BACKEND)
    st.stop()
S["_user"] = h.get("user") or ""
S["_engine"] = h.get("engine_version") or ""
ui.header_badge(S["_user"], S["_engine"], api.BACKEND)
with_report = [r for r in runs if r.get("has_report")]
ids = [r["run_id"] for r in with_report]

P = "frontend/views/"
pages = {
    "Runs": [
        st.Page(P + "pipeline.py", title="Run the pipeline",
                icon=":material/play_circle:"),
        st.Page(P + "runs.py", title="Browse runs", icon=":material/list_alt:"),
        # Whether a run is safe to sign is a question about the run, asked
        # before approving it, so it sits with the runs rather than the book.
        st.Page(P + "validation.py", title="Validation", icon=":material/verified:"),
        st.Page(P + "approval.py", title="Approval queue",
                icon=":material/how_to_reg:"),
    ],
    # The book in one run, as priced. What-ifs are stress tests.
    "Portfolio": [
        # The landing page. Before the first run it says so and links to Run
        # the pipeline (ui.no_runs); a fixed default keeps every page's URL
        # the same whether or not runs exist.
        st.Page(P + "overview.py", title="Overview", icon=":material/dashboard:",
                default=True),
        st.Page(P + "staging.py", title="Staging", icon=":material/layers:"),
        st.Page(P + "risk.py", title="Risk parameters", icon=":material/monitoring:"),
        st.Page(P + "concentration.py", title="Concentration",
                icon=":material/scatter_plot:"),
        st.Page(P + "segments.py", title="Segments", icon=":material/grid_view:"),
        st.Page(P + "scenarios.py", title="Scenarios", icon=":material/alt_route:"),
        st.Page(P + "quality.py", title="Data quality", icon=":material/rule:"),
        st.Page(P + "calculator_customer.py", title="ECL calculator",
                icon=":material/calculate:"),
    ],
    # Two runs side by side. Why the provision moved is Movement alone: the
    # bridge reprices every contract with the pipeline's own ECL function, so
    # there is no second attribution here to disagree with it.
    "Comparison": [
        st.Page(P + "movement.py", title="Movement", icon=":material/timeline:"),
        st.Page(P + "migration.py", title="Migration", icon=":material/swap_horiz:"),
        st.Page(P + "reconcile.py", title="Reconcile & export",
                icon=":material/compare_arrows:"),
    ],
    # One stress function behind every page (ifrs9qdb.stress.apply_stress):
    # a stress test names who it reaches and what changes, so a what-if on
    # named customers, a staging-policy change and a standard package are all
    # stress tests; the sensitivity pages move its levers one at a time.
    "Stress testing": [
        st.Page(P + "stress.py", title="Stress test", icon=":material/bolt:"),
        st.Page(P + "sensitivity.py", title="Sensitivity",
                icon=":material/equalizer:"),
        st.Page(P + "macro.py", title="Macro & scenarios", icon=":material/public:"),
        st.Page(P + "rollforward.py", title="Roll forward",
                icon=":material/fast_forward:"),
    ],
    "Governance": [
        st.Page(P + "snapshots.py", title="Config versions",
                icon=":material/inventory_2:"),
        st.Page(P + "calculator.py", title="Calculator versions",
                icon=":material/deployed_code:"),
        st.Page(P + "overlays.py", title="ECL overlays", icon=":material/tune:"),
        st.Page(P + "suppressions.py", title="Validation suppressions",
                icon=":material/rule_folder:"),
        st.Page(P + "config.py", title="Live configuration",
                icon=":material/settings:"),
        st.Page(P + "assumptions.py", title="Model assumptions",
                icon=":material/function:"),
        st.Page(P + "audit.py", title="Audit log", icon=":material/history:"),
    ],
    "Help": [
        st.Page(P + "assistant.py", title="Assistant", icon=":material/forum:"),
        st.Page(P + "help.py", title="How this works", icon=":material/help:"),
    ],
}

# Which pages read a run, and which compare two. The picker is drawn in the
# page's title row (ui.page_setup); a page that needs a run is not opened
# without one.
NEEDS_RUN = {"Overview", "Staging", "Concentration", "Segments",
             "Risk parameters", "Scenarios", "Data quality", "Validation",
             "Stress test", "Sensitivity", "Macro & scenarios", "Roll forward",
             "Model assumptions", "ECL calculator"}
COMPARES = {"Movement", "Migration", "Reconcile & export"}
OPTIONAL_RUN = {"ECL overlays", "Assistant", "Audit log"}

nav = st.navigation(pages, position="top")
# The menu holding the page on screen is marked like the page in its list.
ui.mark_section(next((i for i, ps in enumerate(pages.values())
                      if any(p.title == nav.title for p in ps)), None))

if S.get("run_id") not in ids:
    S["run_id"] = ids[0] if ids else None
others = [i for i in ids if i != S["run_id"]]
if S.get("compare_id") not in others:
    S["compare_id"] = others[0] if others else None

mode = ("compare" if nav.title in COMPARES or nav.title == "Audit log"
        else "run" if nav.title in NEEDS_RUN | OPTIONAL_RUN else None)
S["_runbar"] = {"mode": mode, "runs": with_report} if mode and ids else None

if (nav.title in NEEDS_RUN | COMPARES) and not ids:
    ui.no_runs(nav.title, runs, pages["Runs"][0])
    st.stop()

nav.run()
