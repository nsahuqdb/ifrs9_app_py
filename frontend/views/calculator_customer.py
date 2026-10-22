"""ECL calculator: one customer's provision as an Excel workbook.

The workbook holds the run's inputs for the customer and every step from them
to the provision as a live formula -- staging with overrides, LGD from the
collateral, the run's monthly PD curves, the EAD path, the ECL month
by month -- and checks each position against the report. Built by the backend
(ifrs9qdb.calc_workbook); each export is written to the audit log.
"""
import pandas as pd
import streamlit as st

import api
from ui import caption, fmt_table, guard, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("ECL calculator",
           "Pick a customer and download an Excel workbook that rebuilds its "
           "provision from the run's inputs with formulas, so the figures can "
           "be checked against the report.")

with guard():
    cust = pd.DataFrame(api.calculator_customers(run_id))
if len(cust) == 0:
    st.info("This run has no positions to export.")
    st.stop()


def _label(i: int) -> str:
    r = cust.iloc[i]
    name = f" — {r['customer_name']}" if r.get("customer_name") else ""
    return (f"{r['customer_id']}{name} ({r['book']}, {int(r['positions'])} "
            f"position{'s' if int(r['positions']) != 1 else ''})")


pick = st.selectbox("Customer", range(len(cust)), format_func=_label,
                    key=f"calc_cust_{run_id}",
                    help="Type to search by id or name. Largest exposure first.")
cid = str(cust.iloc[pick]["customer_id"])

with guard():
    found = api.customers(run_id, cid, spaces=False).get("found") or []
rows = pd.DataFrame(found)
if len(rows):
    cols = [c for c in ("customer", "contracts", "portfolios", "rating", "stage",
                        "exposure", "ecl", "coverage") if c in rows.columns]
    st.dataframe(fmt_table(rows[cols], money_cols=("exposure", "ecl"),
                           pct_cols=("coverage",)),
                 use_container_width=True, hide_index=True)
    caption(f"ECL in the report: {money(rows['ecl'].sum())} (the stage shown "
            "is the customer's worst). The workbook's Summary tab rebuilds the "
            "provision position by position and marks each OK or DIFFERS.")

key = f"calc_xlsx_{run_id}_{cid}"
if st.button("Build the calculator", type="primary"):
    with st.spinner("Building the workbook…"):
        with guard():
            st.session_state[key] = api.calculator_workbook(
                run_id, cid, st.session_state.get("_user") or None)
if st.session_state.get(key):
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in cid)
    st.download_button(
        "Download the workbook (.xlsx)", st.session_state[key],
        file_name=f"ECL_calculator_{run_id}_{safe}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    caption("Tabs: Summary, Settings, Lines (inputs), Overrides, Staging, LGD, "
            "PD, EAD, ECL. Blue cells are the "
            "run's inputs; black cells are formulas. Excel recalculates on "
            "opening.")
