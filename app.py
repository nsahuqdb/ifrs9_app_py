"""
IFRS 9 ECL — front end.

    uvicorn backend.main:app --reload --port 8000     # backend, first
    streamlit run app.py                              # then this

The two run as separate processes. This one draws; the backend calculates.
Nothing here imports the ifrs9qdb package, so the interface cannot disagree
with the API.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "frontend"))

import api  # noqa: E402
from ui import CSS  # noqa: E402

# The R app carried its identity in a coloured bar across the top. Streamlit's
# top navigation gives the tabs but no banner, so this supplies one.
BRAND = """
<div class="qdb-brand">
  <div class="qdb-brand-name">IFRS&nbsp;9 <span>ECL</span></div>
  <div class="qdb-brand-sub">Qatar Development Bank &middot; Financial Risk Management</div>
</div>
"""

st.set_page_config(
    page_title="IFRS 9 ECL",
    page_icon="◧",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(BRAND, unsafe_allow_html=True)

# Fail once, here, rather than on every page in turn.
try:
    h = api.health()
    runs = api.runs()
except api.BackendError as e:
    st.markdown(BRAND, unsafe_allow_html=True)
    st.error("Backend unavailable")
    st.code(str(e), language=None)
    st.stop()

with st.sidebar:
    st.markdown("### Run")

    # With no runs the analysis pages have nothing to show, but the pipeline
    # page is precisely what you need then, so the app must not stop here.
    if not runs:
        st.warning("No runs yet.")
        st.caption("Use **Run the pipeline** to build one from the source extracts.")
        # Show what it actually looked at rather than repeating the instructions
        # it has already followed.
        try:
            d = api.diagnose()
        except api.BackendError:
            d = None
        if d:
            st.caption("**IFRS9_RUNS_DIR**")
            st.code(d["IFRS9_RUNS_DIR"], language=None)
            st.caption("**Resolved to**")
            st.code(d["resolved_to"], language=None)
            st.caption(f"Exists: **{d['exists']}**  ·  backend cwd: `{d['working_directory']}`")
            if d.get("hint"):
                st.info(d["hint"], icon="💡")
            if d.get("entries"):
                st.caption("**Sub-folders seen**")
                for e in d["entries"][:12]:
                    mark = "✓" if e["accepted"] else "✗"
                    st.text(f"{mark} {e['name']}")
                    if not e["accepted"]:
                        st.caption(f"   {e.get('reason','')}")
                        if e.get("contains"):
                            st.caption(f"   contains: {', '.join(e['contains'])}")
        st.session_state["run_id"] = None
        st.session_state["compare_id"] = None

    with_report = [r for r in runs if r["has_report"]]
    if runs and not with_report:
        st.warning("No run has an ECL report yet.")
        st.caption("The pipeline writes the LIC input files; the ECL report "
                   "comes from pricing them.")
    ids = [r["run_id"] for r in with_report]
    if ids:
        run_id = st.selectbox("Run", ids)
        st.session_state["run_id"] = run_id
        current = next(r for r in with_report if r["run_id"] == run_id)
        if current.get("scenarios"):
            st.caption(f"{len(current['scenarios'])} scenario reports")
        others = [r for r in ids if r != run_id]
        st.session_state["compare_id"] = (
            st.selectbox("Compare against", others,
                         help="Used by the Movement page.") if others else None)
    else:
        st.session_state["run_id"] = None
        st.session_state["compare_id"] = None

    st.divider()
    if st.button("Reload from disk", use_container_width=True):
        api.clear()
        st.rerun()
    st.caption(f"engine {h['engine_version']} · {api.BACKEND}")

pages = {
    "Runs": [
        st.Page("frontend/views/runs.py", title="Browse runs",
                icon=":material/list_alt:"),
        st.Page("frontend/views/pipeline.py", title="Run the pipeline",
                icon=":material/play_circle:"),
        st.Page("frontend/views/approval.py", title="Approval queue",
                icon=":material/how_to_reg:"),
    ],
    "Config": [
        st.Page("frontend/views/snapshots.py", title="Config versions",
                icon=":material/inventory_2:"),
        st.Page("frontend/views/calculator.py", title="Calculator versions",
                icon=":material/deployed_code:"),
        st.Page("frontend/views/overlays.py", title="ECL overlays",
                icon=":material/tune:"),
        st.Page("frontend/views/suppressions.py", title="Validation suppressions",
                icon=":material/rule_folder:"),
        st.Page("frontend/views/config.py", title="Live configuration",
                icon=":material/settings:"),
        st.Page("frontend/views/assumptions.py", title="Model assumptions",
                icon=":material/function:"),
    ],
    "Portfolio": [
        st.Page("frontend/views/overview.py", title="Overview",
                icon=":material/dashboard:", default=True),
        st.Page("frontend/views/staging.py", title="Staging",
                icon=":material/layers:"),
        st.Page("frontend/views/concentration.py", title="Concentration",
                icon=":material/scatter_plot:"),
        st.Page("frontend/views/distributions.py", title="Distributions",
                icon=":material/bar_chart:"),
        st.Page("frontend/views/segments.py", title="Segments",
                icon=":material/grid_view:"),
        st.Page("frontend/views/risk.py", title="Risk parameters",
                icon=":material/monitoring:"),
        st.Page("frontend/views/scenarios.py", title="Scenarios",
                icon=":material/alt_route:"),
        st.Page("frontend/views/quality.py", title="Data quality",
                icon=":material/rule:"),
        st.Page("frontend/views/validation.py", title="Validation",
                icon=":material/verified:"),
    ],
    "Comparison": [
        st.Page("frontend/views/movement.py", title="Movement",
                icon=":material/timeline:"),
        st.Page("frontend/views/attribution.py", title="Attribution",
                icon=":material/insights:"),
        st.Page("frontend/views/migration.py", title="Migration",
                icon=":material/swap_horiz:"),
        st.Page("frontend/views/reconcile.py", title="Reconcile & export",
                icon=":material/compare_arrows:"),
    ],
    "Audit": [
        st.Page("frontend/views/audit.py", title="Audit log",
                icon=":material/history:"),
    ],
    "Stress testing": [
        st.Page("frontend/views/stress.py", title="Stress packages",
                icon=":material/bolt:"),
        st.Page("frontend/views/compare.py", title="Package comparison",
                icon=":material/compare:"),
        st.Page("frontend/views/sensitivity.py", title="Lever sensitivity",
                icon=":material/equalizer:"),
        st.Page("frontend/views/reverse.py", title="Reverse stress",
                icon=":material/search:"),
        st.Page("frontend/views/rollforward.py", title="Roll forward",
                icon=":material/fast_forward:"),
        st.Page("frontend/views/whatif.py", title="What-if",
                icon=":material/edit_note:"),
        st.Page("frontend/views/threshold.py", title="Staging threshold",
                icon=":material/tune:"),
        st.Page("frontend/views/macro.py", title="Macro path",
                icon=":material/public:"),
    ],
    "Help": [
        st.Page("frontend/views/assistant.py", title="Assistant",
                icon=":material/forum:"),
        st.Page("frontend/views/help.py", title="How this works",
                icon=":material/help:"),
    ],
}

st.navigation(pages, position="top").run()
