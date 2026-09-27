"""Any two segmentations crossed.

The overview breaks the book down one way at a time. A committee asking
"where is the Stage 2 exposure concentrated" wants two at once, and the cell
that answers it is usually not the one anybody expected.
"""
import pandas as pd
import streamlit as st

import api
from ui import (bar, caption, fmt_table, guard, metric_row, money,
                page_setup, pct)

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected. Build one on **Run the pipeline**, or point the "
            "backend at a folder of existing runs.", icon="👈")
    st.stop()
page_setup("Segments", "Two breakdowns at once")

DIMENSIONS = ["portfolio", "stage", "rating", "account_type"]
VALUES = {"ecl": "Provision", "exposure": "Exposure",
          "coverage": "Coverage %", "contracts": "Contracts"}

a, b, c = st.columns(3)
rows = a.selectbox("Rows", DIMENSIONS, index=0, key="seg_rows")
cols = b.selectbox("Columns", DIMENSIONS, index=1, key="seg_cols")
value = c.selectbox("Value", list(VALUES), index=0,
                    format_func=lambda k: VALUES[k], key="seg_value")

if rows == cols:
    st.info("Pick two different breakdowns.")
    st.stop()

with guard():
    cells = pd.DataFrame(api.segments(run_id, rows, cols, value))

if len(cells) == 0:
    st.info("Nothing to cross on those two.")
    st.stop()

if value != "coverage":
    metric_row([
        ("Total", money(cells["value"].sum())),
        ("Cells", money(len(cells))),
        ("Largest cell", money(cells["value"].max())),
    ])
    caption("The cells conserve the report: an empty combination is absent "
            "rather than zero, because nobody in a segment and nothing in it "
            "are different facts.")

# The API sends an empty cell as JSON null, which arrives as the object None
# and would print as "None". Coerced to NaN so na_rep can say "—" instead.
cells["value"] = pd.to_numeric(cells["value"], errors="coerce")
piv = cells.pivot(index="row", columns="col", values="value")
fmt = "{:,.2f}%" if value == "coverage" else "{:,.0f}"
# Formatted, not colour-scaled: a gradient here would pull matplotlib into an
# app that draws everything else with plotly, for a cue the numbers already
# give.
st.dataframe(piv.style.format(fmt, na_rep="—"), use_container_width=True)

bar(cells.assign(cell=[f"{r} · {c}" for r, c in zip(cells["row"], cells["col"])])
    .nlargest(15, "value"), "cell", "value",
    title=f"Largest cells — {VALUES[value]}",
    dp=2 if value == "coverage" else 0)

with st.expander("Every cell, with its exposure and contract count"):
    st.dataframe(fmt_table(cells, money_cols=("exposure", "ecl", "contracts")),
                 use_container_width=True, hide_index=True)
