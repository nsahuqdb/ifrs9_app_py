"""Portfolio view: every customer, its rating and stage, and its exposure and
ECL in each portfolio -- the layout of the team's portfolio report, internal
and external books together. Stage 1 first, then 2 and 3; the largest
exposure first within a stage. Downloadable as Excel."""
import io

import pandas as pd
import streamlit as st

import api
from ui import caption, grid, guard, metric_row, money, page_setup, pct

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Portfolio view",
           "Every customer with its exposure and ECL in each portfolio, Stage 1 "
           "first.")

c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
basis = c1.segmented_control(
    "Exposure", ["On + off balance", "On balance"], default="On + off balance",
    required=True, key="pv_basis",
    help="On + off balance: the balance plus guarantees and undrawn amounts "
         "(Exposure On Bal + Exposure Off Bal). On balance: Exposure On Bal only.")
with guard():
    pv = api.portfolio_view(run_id, "total" if basis == "On + off balance" else "on")
ports = pv.get("portfolios") or []
d = pd.DataFrame(pv.get("rows") or [])
if len(d) == 0:
    st.info("This run's report has no contracts.")
    st.stop()

# safe column keys for the grid; the portfolio names as the headers
exp_cols = [f"exp|{p}" for p in ports] + ["exp|Total"]
ecl_cols = [f"ecl|{p}" for p in ports] + ["ecl|Total"]
key = {c: f"e{i}" for i, c in enumerate(exp_cols)} | {c: f"c{i}" for i, c in enumerate(ecl_cols)}
label = ({key[f"exp|{p}"]: p for p in ports} | {key[f"ecl|{p}"]: p for p in ports}
         | {key["exp|Total"]: "Total exposure", key["ecl|Total"]: "Total ECL"})
show = d.rename(columns=key)[["customer", "customer_name", "rating", "stage",
                              *key.values()]]
show["stage"] = pd.to_numeric(show["stage"], errors="coerce").astype("Int64")

tot_exp, tot_ecl = float(d["exp|Total"].sum()), float(d["ecl|Total"].sum())
metric_row([("Customers", money(len(d))), ("Exposure", money(tot_exp)),
            ("ECL", money(tot_ecl)),
            ("Coverage", pct(100 * tot_ecl / tot_exp) if tot_exp else "—")])

AMT = "%,.0f"
cfg = {"customer": "Customer", "customer_name": "Customer name", "rating": "Rating",
       "stage": "Stage"}
cfg |= {k: st.column_config.NumberColumn(label[k], format=AMT) for k in key.values()}
total = {"customer": "Total", "customer_name": "", "rating": "", "stage": None}
total |= {key[c]: float(d[c].sum()) for c in exp_cols + ecl_cols}
grid(show, key=f"pv_{run_id}_{basis}", column_config=cfg, hide_index=True,
     groups={"Exposure": [key[c] for c in exp_cols], "ECL": [key[c] for c in ecl_cols]},
     pinned_bottom=[total], height=620, pin_left=("customer", "customer_name"))
caption("A customer's stage and rating are the customer's (its worst stage). Each "
        "portfolio column sums the customer's contracts in that portfolio. Click a "
        "column name to sort; ⋮ to filter.")


def _excel() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Portfolio view"
    info = ["Customer", "Customer name", "Rating", "Stage"]
    n_e, n_c = len(exp_cols), len(ecl_cols)
    head = PatternFill("solid", fgColor="5B1F6E")
    sub = PatternFill("solid", fgColor="EFE6F4")
    white, bold = Font(bold=True, color="FFFFFF"), Font(bold=True)
    thin = Side(style="thin", color="D0C4D9")
    ws.append([f"Portfolio view · {run_id} · exposure {basis.lower()}"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([""] * len(info) + ["Exposure"] + [""] * (n_e - 1) + ["ECL"] + [""] * (n_c - 1))
    ws.merge_cells(start_row=2, start_column=len(info) + 1, end_row=2,
                   end_column=len(info) + n_e)
    ws.merge_cells(start_row=2, start_column=len(info) + n_e + 1, end_row=2,
                   end_column=len(info) + n_e + n_c)
    ws.append(info + [label[key[c]] for c in exp_cols] + [label[key[c]] for c in ecl_cols])
    for row in (2, 3):
        for col in range(1, len(info) + n_e + n_c + 1):
            cell = ws.cell(row, col)
            cell.fill = head if row == 2 and col > len(info) else sub
            cell.font = white if row == 2 else bold
            cell.alignment = Alignment(horizontal="center", vertical="center",
                                       wrap_text=True)
            cell.border = Border(bottom=thin)
    for _, r in d.iterrows():
        st_ = r["stage"]
        ws.append([r["customer"], r["customer_name"] or "", r["rating"] or "",
                   None if pd.isna(st_) else int(st_)]
                  + [float(r[c]) for c in exp_cols] + [float(r[c]) for c in ecl_cols])
    last = ws.max_row
    ws.append(["Total", "", "", ""]
              + [f"=SUM({get_column_letter(len(info) + 1 + i)}4:"
                 f"{get_column_letter(len(info) + 1 + i)}{last})"
                 for i in range(n_e + n_c)])
    for col in range(1, len(info) + n_e + n_c + 1):
        c = ws.cell(last + 1, col)
        c.font = bold
        c.fill = sub
        c.border = Border(top=thin)
    for row in ws.iter_rows(min_row=4, max_row=last + 1, min_col=len(info) + 1):
        for c in row:
            c.number_format = "#,##0"
    widths = [14, 38, 12, 8] + [16] * (n_e + n_c)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "C4"
    ws.auto_filter.ref = f"A3:{get_column_letter(len(info) + n_e + n_c)}{last}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


c2.download_button("Download (.xlsx)", _excel(), icon=":material/download:",
                   file_name=f"Portfolio_view_{run_id}.xlsx", use_container_width=True,
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
