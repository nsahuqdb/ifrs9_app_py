"""Parameter stress: move the model's parameters directly -- PD, LGD,
ratings, stages, exposure, the macro forecast and the scenario weights --
and reprice the run.

Four views of the same repricing, one at a time:

    Stress test           who is stressed and what moves (stress.py)
    Lever sensitivity     each lever on its own, to a target, the staging
                          threshold (sensitivity.py)
    Forecast and weights  the PD model's forecast and the IFRS 9 scenario
                          weights (macro.py)
    Roll forward          the provision in n months if nothing else changes
                          (rollforward.py)

Scenario stress -- a macro scenario carried through its linked effects -- is
its own page.
"""
import runpy
from pathlib import Path

import streamlit as st

from ui import page_setup

S = st.session_state
if not S.get("run_id"):
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Parameter stress",
           "Change PD, LGD, ratings, stages or exposure directly and reprice the run")

VIEWS = {"Stress test": "stress.py", "Lever sensitivity": "sensitivity.py",
         "Forecast and weights": "macro.py", "Roll forward": "rollforward.py"}
S.setdefault("ps_view", "Stress test")
st.segmented_control("View", list(VIEWS), key="ps_view", label_visibility="collapsed")
view = S.get("ps_view") or "Stress test"
S["_embedded"] = True
try:
    runpy.run_path(str(Path(__file__).parent / VIEWS[view]), run_name="__main__")
finally:
    S["_embedded"] = False
