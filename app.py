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

import api  # noqa: E402
import ui  # noqa: E402

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
        st.Page(P + "approval.py", title="Approval queue",
                icon=":material/how_to_reg:"),
    ],
    "Portfolio": [
        # The landing page. Before the first run it says so and links to Run
        # the pipeline (ui.no_runs); a fixed default keeps every page's URL
        # the same whether or not runs exist.
        st.Page(P + "overview.py", title="Overview", icon=":material/dashboard:",
                default=True),
        st.Page(P + "staging.py", title="Staging", icon=":material/layers:"),
        st.Page(P + "concentration.py", title="Concentration",
                icon=":material/scatter_plot:"),
        st.Page(P + "distributions.py", title="Distributions",
                icon=":material/bar_chart:"),
        st.Page(P + "segments.py", title="Segments", icon=":material/grid_view:"),
        st.Page(P + "risk.py", title="Risk parameters", icon=":material/monitoring:"),
        st.Page(P + "scenarios.py", title="Scenarios", icon=":material/alt_route:"),
        st.Page(P + "quality.py", title="Data quality", icon=":material/rule:"),
        st.Page(P + "validation.py", title="Validation", icon=":material/verified:"),
    ],
    "Comparison": [
        st.Page(P + "movement.py", title="Movement", icon=":material/timeline:"),
        st.Page(P + "attribution.py", title="Attribution", icon=":material/insights:"),
        st.Page(P + "migration.py", title="Migration", icon=":material/swap_horiz:"),
        st.Page(P + "reconcile.py", title="Reconcile & export",
                icon=":material/compare_arrows:"),
    ],
    "Stress testing": [
        st.Page(P + "stress.py", title="Stress packages", icon=":material/bolt:"),
        st.Page(P + "compare.py", title="Package comparison",
                icon=":material/compare:"),
        st.Page(P + "sensitivity.py", title="Lever sensitivity",
                icon=":material/equalizer:"),
        st.Page(P + "reverse.py", title="Reverse stress", icon=":material/search:"),
        st.Page(P + "rollforward.py", title="Roll forward",
                icon=":material/fast_forward:"),
        st.Page(P + "whatif.py", title="What-if", icon=":material/edit_note:"),
        st.Page(P + "threshold.py", title="Staging threshold", icon=":material/tune:"),
        st.Page(P + "macro.py", title="Macro path", icon=":material/public:"),
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
NEEDS_RUN = {"Overview", "Staging", "Concentration", "Distributions", "Segments",
             "Risk parameters", "Scenarios", "Data quality", "Validation",
             "Stress packages", "Package comparison", "Lever sensitivity",
             "Reverse stress", "Roll forward", "What-if", "Staging threshold",
             "Macro path", "Model assumptions"}
COMPARES = {"Movement", "Attribution", "Migration", "Reconcile & export"}
OPTIONAL_RUN = {"ECL overlays", "Assistant", "Audit log"}

nav = st.navigation(pages, position="top")

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
