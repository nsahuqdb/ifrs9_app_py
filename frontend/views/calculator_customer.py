"""ECL calculator: one customer's, or one contract's, provision as an Excel
workbook. Customer is the default level.

The workbook holds the run's inputs for the customer and every step from them
to the provision as a live formula -- staging with overrides, LGD from the
collateral, the PD curves calculated from the run's PD model (internal and
external scales), the EAD path, the ECL month by month -- and checks each
position against the report. Built by the backend
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
           "Pick a customer, or one contract, and download an Excel workbook that "
           "rebuilds its provision from the run's inputs with formulas, so the "
           "figures can be checked against the report.")

level = st.segmented_control("Level", ["Customer", "Contract"], default="Customer",
                             required=True, key="calc_level")


def _n(v) -> str:
    try:
        return f"QAR {float(v):,.0f}"
    except (TypeError, ValueError):
        return ""


if level == "Customer":
    with guard():
        cust = pd.DataFrame(api.calculator_customers(run_id))
    if len(cust) == 0:
        st.info("This run has no positions to export.")
        st.stop()

    def _label(i: int) -> str:
        r = cust.iloc[i]
        n = int(r["positions"])
        tail = f"({r['book']}, {n} position{'s' if n != 1 else ''})"
        if r.get("customer_name"):
            return f"{r['customer_name']} · {r['customer_id']} {tail}"
        return f"{r['customer_id']} {tail}"

    pick = st.selectbox("Customer", range(len(cust)), format_func=_label,
                        key=f"calc_cust_{run_id}",
                        help="Type to search by name or id. Largest exposure first.")
    cid = str(cust.iloc[pick]["customer_id"])
    contract = book = None
    who = cid
else:
    with guard():
        con = pd.DataFrame(api.calculator_contracts(run_id))
    if len(con) == 0:
        st.info("This run has no positions to export.")
        st.stop()

    def _clabel(i: int) -> str:
        r = con.iloc[i]
        src = (f" (source {r['contract_original']})"
               if r.get("contract_original") and r["contract_original"] != r["contract_id"]
               else "")
        name = r.get("customer_name") or r["customer_id"]
        return (f"{r['contract_id']}{src} · {name} · {r['product']} · "
                f"{_n(r['on_balance'])}")

    pick = st.selectbox("Contract", range(len(con)), format_func=_clabel,
                        key=f"calc_con_{run_id}",
                        help="Type to search by contract, customer name or product. "
                             "Largest exposure first.")
    row = con.iloc[pick]
    cid, contract, book = str(row["customer_id"]), str(row["contract_id"]), str(row["book"])
    who = contract
    caption("The workbook prices this contract. Its Facilities, Rating and Staging "
            "tabs also show the customer's other facilities, because the customer's "
            "worst facility sets the rating and any Stage 2 or 3 facility lifts the "
            "stage.")

with guard():
    found = api.customers(run_id, cid, spaces=False).get("found") or []
rows = pd.DataFrame(found)
if len(rows):
    cols = [c for c in ("customer", "contracts", "portfolios", "rating", "stage",
                        "exposure", "ecl", "coverage") if c in rows.columns]
    st.dataframe(fmt_table(rows[cols], money_cols=("exposure", "ecl"),
                           pct_cols=("coverage",)),
                 use_container_width=True, hide_index=True)
    caption(f"The customer's ECL in the report: {money(rows['ecl'].sum())} (the "
            "stage shown is the customer's worst). The workbook's Summary tab "
            "rebuilds the provision position by position and marks each OK or "
            "DIFFERS.")

key = f"calc_xlsx_{run_id}_{level}_{who}"
if st.button("Build the calculator", type="primary"):
    with st.spinner("Building the workbook…"):
        with guard():
            st.session_state[key] = api.calculator_workbook(
                run_id, cid, st.session_state.get("_user") or None,
                contract=contract, book=book)
if st.session_state.get(key):
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in who)
    st.download_button(
        "Download the workbook (.xlsx)", st.session_state[key],
        file_name=f"ECL_calculator_{run_id}_{'contract_' if contract else ''}{safe}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    caption("Tabs, from start to end: Summary, Facilities (the inputs), Rating (how "
            "each rating was set), Staging (the customer's stage and each "
            "facility's, with the reason), PD internal / PD external (the PD model "
            "and the scenario weights), PD curves, LGD, EAD, ECL. Blue cells are the "
            "run's inputs; black cells are formulas. Excel recalculates on opening.")
