"""Roll forward: the provision in n months if nothing else changes."""
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup, pct

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Roll forward",
           "The provision in n months if nothing changes but time: same "
           "contracts, same ratings, same stages.")

c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
months = c1.slider("Months", 3, 60, 12, 3)
run = c2.button("Roll forward", type="primary")

if not run:
    st.markdown(
        "Three things change as time passes:\n"
        "- **Balance**: each contract repays along its own schedule.\n"
        "- **PD**: the months that have passed without a default are no "
        "longer at risk.\n"
        "- **Maturity**: contracts that mature in the window drop out.")
    st.stop()

with guard():
    r = api.rollforward(run_id, months)

metric_row([
    ("Provision today", money(r["before"])),
    (f"In {months} months", money(r["after"])),
    ("Change", money(r["delta"])),
    ("% change", pct(100 * r["delta"] / max(r["before"], 1))),
    ("Contracts matured", money(r["matured"])),
])
metric_row([
    ("Exposure today", money(r["exposure_before"])),
    (f"Exposure in {months} months", money(r["exposure_after"])),
])
