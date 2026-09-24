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
           "A mechanical roll of the existing book. The contracts are "
           "untouched; only the reporting date moves, so this isolates time "
           "decay from any credit view.")

c1, c2 = st.columns([1, 3])
months = c1.slider("Months", 3, 60, 12, 3)
run = c2.button("Roll forward", type="primary")

if not run:
    with st.expander("What moves, and why all three matter"):
        st.markdown(
            "- **Balance** advances along each contract's own EAD curve — "
            "elapsed months are dropped, so the balance is what the schedule "
            "reaches at that date, not today's.\n"
            "- **PD** becomes conditional on surviving those months: "
            "`(cumPD(k+t) − cumPD(k)) / (1 − cumPD(k))`. Reusing the original "
            "curve charges for a default already known not to have happened.\n"
            "- **Term**: contracts maturing inside the window have run off and "
            "carry no provision.\n\n"
            "On a worked example, forgetting the conditional PD understates by "
            "55% and forgetting to advance the balance overstates by 280%. "
            "This is also **not** the same as shortening maturity, which keeps "
            "today's balance and squeezes the remaining repayments into less "
            "time."
        )
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
st.info(f"Exposure falls from **{money(r['exposure_before'])}** to "
        f"**{money(r['exposure_after'])}** as the book amortises, and "
        f"**{money(r['matured'])}** contracts run off entirely.", icon="ℹ️")
caption("Comparing this with the actual next-quarter run separates what time "
        "did from what credit did.")
