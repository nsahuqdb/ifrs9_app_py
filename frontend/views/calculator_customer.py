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
from ui import caption, guard, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("ECL calculator",
           "Pick a customer, or one contract, and download an Excel workbook that "
           "rebuilds its provision from the run's inputs with formulas, so the "
           "figures can be checked against the report.")

BOOK = {"Internal": "Lending", "External": "Investments"}
TABLE_CFG = {c: st.column_config.NumberColumn(format="%,.0f")
             for c in ("Exposure", "ECL")}
TABLE_CFG["Coverage"] = st.column_config.NumberColumn(format="%.2f%%")


def _n(v) -> str:
    try:
        return f"QAR {float(v):,.0f}"
    except (TypeError, ValueError):
        return ""


def _txt(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def _stage(v) -> str:
    try:
        return f"Stage {int(float(v))}"
    except (TypeError, ValueError):
        return ""


level = st.segmented_control("Level", ["Customer", "Contract"], default="Customer",
                             required=True, key="calc_level")
with guard():
    con = pd.DataFrame(api.calculator_contracts(run_id))
if len(con) == 0:
    st.info("This run has no positions to export.")
    st.stop()
con["customer_name"] = con["customer_name"].fillna("").astype(str)

cols = st.columns([1.3, 3, 3] if level == "Contract" else [1.3, 6],
                  vertical_alignment="bottom")
scales = [s for s, b in BOOK.items() if (con["book"] == b).any()]
scale = cols[0].segmented_control(
    "Rating", scales, default=scales[0], required=True, key=f"calc_scale_{run_id}",
    help="Internal: the lending book, rated on QDB's scale. External: "
         "investments, rated by the agencies.")
book = BOOK[scale]

# the customers of that book, largest exposure first
inbook = con[con["book"] == book]
cust = (inbook.groupby("customer_id", as_index=False)
        .agg(customer_name=("customer_name", lambda s: next((x for x in s if x), "")),
             positions=("contract_id", "size"), on_balance=("on_balance", "sum"))
        .sort_values("on_balance", ascending=False).reset_index(drop=True))


def _label(i: int) -> str:
    r = cust.iloc[i]
    n = int(r["positions"])
    tail = f"{n} {'contract' if n == 1 else 'contracts'}"
    return (f"{r['customer_name']} · {r['customer_id']} ({tail})" if r["customer_name"]
            else f"{r['customer_id']} ({tail})")


pick = cols[1].selectbox("Customer", range(len(cust)), format_func=_label,
                         key=f"calc_cust_{run_id}_{scale}",
                         help="Type to search by name or id. Largest exposure first.")
cid = str(cust.iloc[pick]["customer_id"])
cname = cust.iloc[pick]["customer_name"]
mine = inbook[inbook["customer_id"] == cid].reset_index(drop=True)

if level == "Contract":
    def _clabel(i: int) -> str:
        r = mine.iloc[i]
        src = (f" (source {r['contract_original']})"
               if _txt(r.get("contract_original")) and r["contract_original"] != r["contract_id"]
               else "")
        return f"{r['contract_id']}{src} · {_txt(r['product'])} · {_n(r['on_balance'])}"

    k = cols[2].selectbox("Contract", range(len(mine)), format_func=_clabel,
                          key=f"calc_con_{run_id}_{scale}_{cid}",
                          help="The customer's contracts in this book, largest first.")
    row = mine.iloc[k]
    contract, who = str(row["contract_id"]), str(row["contract_id"])
    shown = pd.DataFrame([{
        "Contract": contract,
        "Contract (source id)": _txt(row.get("contract_original")),
        "Customer": cid, "Customer name": cname,
        "Product": _txt(row.get("product")), "Portfolio": _txt(row.get("portfolio")),
        "Rating": _txt(row.get("rating")), "Stage": _stage(row.get("stage")),
        "Exposure": row.get("exposure"), "ECL": row.get("ecl"),
        "Coverage": row.get("coverage")}])
    st.dataframe(shown, hide_index=True, column_config=TABLE_CFG)
    caption("The workbook shows this contract only. What the customer's other "
            "facilities contribute -- its worst days past due, a Tasdeer or Al "
            "Dhameen facility -- is given as a value on the Rating and Staging tabs.")
else:
    contract, who = None, cid
    book = None                     # the customer's whole provision, every book
    with guard():
        allc = pd.DataFrame(api.calculator_customers(run_id))
    r = allc[allc["customer_id"].astype(str) == cid]
    r = r.iloc[0] if len(r) else pd.Series(dtype=object)
    both = " + " in _txt(r.get("book"))
    shown = pd.DataFrame([{
        "Customer": cid, "Customer name": cname or _txt(r.get("customer_name")),
        "Contracts": r.get("contracts", r.get("positions")),
        "Portfolio": _txt(r.get("portfolios")), "Rating": _txt(r.get("rating")),
        "Stage": _stage(r.get("stage")), "Exposure": r.get("exposure"),
        "ECL": r.get("ecl"), "Coverage": r.get("coverage")}])
    st.dataframe(shown, hide_index=True, column_config=TABLE_CFG)
    caption("From the report; the stage is the customer's. The workbook's Summary "
            "tab rebuilds the provision position by position and marks each OK or "
            "DIFFERS."
            + (" This customer is in both books: the workbook covers both."
               if both else ""))

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
    caption("Tabs, start to end: Summary, Facilities (the inputs), Rating (how the "
            "customer's rating was set), Staging (the customer's stage and why), PD, "
            "LGD, EAD, ECL; each opens with its result. The assumptions and the PD "
            "calculation are on hidden tabs (right-click a tab, Unhide). Blue cells "
            "are the run's inputs; black cells are formulas.")
