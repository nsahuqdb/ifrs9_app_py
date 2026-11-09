"""Portfolio view: one row per customer -- id, name, rating, stage -- with the
exposure and ECL of its contracts in each portfolio and the totals. Stage 1
first, then 2 and 3; the largest exposure first within a stage. Downloadable
as Excel."""
import io

import pandas as pd
import streamlit as st

import api
from ui import caption, grid, guard, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Portfolio view", "Each customer's exposure and ECL by portfolio.")

with guard():
    pv = api.portfolio_view(run_id)
ports = pv.get("portfolios") or []
d = pd.DataFrame(pv.get("rows") or [])
if len(d) == 0:
    st.info("This run's report has no contracts.")
    st.stop()

exp_cols = [f"exp|{p}" for p in ports] + ["exp|Total"]
ecl_cols = [f"ecl|{p}" for p in ports] + ["ecl|Total"]
# plain keys for the table; the portfolio names are the headers
key = {c: f"e{i}" for i, c in enumerate(exp_cols)} | {c: f"c{i}" for i, c in enumerate(ecl_cols)}
label = ({key[f"exp|{p}"]: p for p in ports} | {key[f"ecl|{p}"]: p for p in ports}
         | {key["exp|Total"]: "Total exposure", key["ecl|Total"]: "Total ECL"})
show = d.rename(columns=key)[["customer", "customer_name", "rating", "stage",
                              *key.values()]]
show["stage"] = pd.to_numeric(show["stage"], errors="coerce").astype("Int64")

cfg = {"customer": "Customer", "customer_name": "Customer name", "rating": "Rating",
       "stage": "Stage"}
cfg |= {k: st.column_config.NumberColumn(label[k], format="%,.0f") for k in key.values()}
total = {"customer": "Total", "customer_name": "", "rating": "", "stage": None}
total |= {key[c]: float(d[c].sum()) for c in exp_cols + ecl_cols}


def _excel() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    info = ["Customer", "Customer name", "Rating", "Stage"]
    n_e, n_c, n_i = len(exp_cols), len(ecl_cols), 4
    wb = Workbook()
    ws = wb.active
    ws.title = "Portfolio view"
    ws.append([""] * n_i + ["Exposure"] + [""] * (n_e - 1) + ["ECL"] + [""] * (n_c - 1))
    ws.merge_cells(start_row=1, start_column=n_i + 1, end_row=1, end_column=n_i + n_e)
    ws.merge_cells(start_row=1, start_column=n_i + n_e + 1, end_row=1,
                   end_column=n_i + n_e + n_c)
    ws.append(info + [label[key[c]] for c in exp_cols] + [label[key[c]] for c in ecl_cols])
    fill = PatternFill("solid", fgColor="EFE6F4")
    for row in (1, 2):
        for col in range(1, n_i + n_e + n_c + 1):
            cell = ws.cell(row, col)
            cell.font = Font(bold=True)
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for _, r in d.iterrows():
        s = r["stage"]
        ws.append([r["customer"], r["customer_name"] or "", r["rating"] or "",
                   None if pd.isna(s) else int(s)]
                  + [float(r[c]) for c in exp_cols + ecl_cols])
    last = ws.max_row
    ws.append(["Total", "", "", ""] + [
        f"=SUM({get_column_letter(n_i + 1 + i)}3:{get_column_letter(n_i + 1 + i)}{last})"
        for i in range(n_e + n_c)])
    for col in range(1, n_i + n_e + n_c + 1):
        ws.cell(last + 1, col).font = Font(bold=True)
    for row in ws.iter_rows(min_row=3, max_row=last + 1, min_col=n_i + 1):
        for c in row:
            c.number_format = "#,##0"
    for i, w in enumerate([14, 38, 12, 8] + [16] * (n_e + n_c), start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "C3"
    ws.auto_filter.ref = f"A2:{get_column_letter(n_i + n_e + n_c)}{last}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


st.download_button("Download (.xlsx)", _excel(), icon=":material/download:",
                   file_name=f"Portfolio_view_{run_id}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
grid(show, key=f"pv_{run_id}", column_config=cfg, hide_index=True,
     groups={"Exposure": [key[c] for c in exp_cols], "ECL": [key[c] for c in ecl_cols]},
     pinned_bottom=[total], height=640, pin_left=("customer", "customer_name"))
caption(f"{len(d):,} customers. Exposure is the report's on-balance exposure. Stage "
        "and rating are the customer's.")
