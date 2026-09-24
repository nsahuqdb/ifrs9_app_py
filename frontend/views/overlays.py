"""Management adjustments applied after the model."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, money, page_setup

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run selected.", icon="👈")
    st.stop()

page_setup("Overlays",
           "Applied after the engine, never in place of it. The report keeps "
           "the model figure, the overlay amount and the final figure side by "
           "side, and every overlay records what it moved and why.")

with guard():
    existing = api.overlays()

st.info(
    "**Stage 3 is never touched** — those provisions are booked manually "
    "outside the tool, and an overlay on top would double-count. "
    "**At most one overlay per contract**: overlapping overlays are rejected "
    "rather than compounded, because the order of application would otherwise "
    "decide the provision.", icon="ℹ️")

st.subheader("Define")
default = pd.DataFrame(existing) if existing else pd.DataFrame([{
    "id": "OV1", "type": "uplift_pct", "value": 0.15, "level": "contract",
    "stage": "2", "portfolio": "", "rationale": "", "approved_by": "",
    "enabled": True}])
for c in ("id", "type", "value", "level", "stage", "portfolio", "rationale",
          "approved_by", "enabled"):
    if c not in default.columns:
        default[c] = "" if c not in ("enabled", "value") else (True if c == "enabled" else 0.0)
default = default[["enabled", "id", "type", "value", "level", "stage",
                   "portfolio", "rationale", "approved_by"]]
default["stage"] = default["stage"].astype(str)
default["portfolio"] = default["portfolio"].astype(str)

edited = st.data_editor(
    default, num_rows="dynamic", use_container_width=True, hide_index=True,
    column_config={
        "enabled": st.column_config.CheckboxColumn("On", width="small"),
        "id": "Id",
        "type": st.column_config.SelectboxColumn(
            "Type", options=["uplift_pct", "higher_of", "absolute_add"]),
        "value": st.column_config.NumberColumn("Value", format="%.4f"),
        "level": st.column_config.SelectboxColumn(
            "Level", options=["contract", "customer"]),
        "stage": "Stages (e.g. 1,2)", "portfolio": "Portfolios (comma sep)",
        "rationale": "Rationale (required)", "approved_by": "Approved by"})

caption("uplift_pct scales the model figure · higher_of sets a floor as a "
        "fraction of exposure · absolute_add spreads a fixed total pro rata by "
        "exposure. Every overlay needs a rationale — an adjustment nobody can "
        "trace is indistinguishable from an error.")

if st.button("Preview", type="primary"):
    specs = []
    for _, r in edited.iterrows():
        if not str(r["id"]).strip():
            continue
        specs.append({
            "id": str(r["id"]), "type": str(r["type"]),
            "value": float(r["value"] or 0), "level": str(r["level"]),
            "rationale": str(r["rationale"] or ""),
            "approved_by": str(r["approved_by"] or ""),
            "enabled": bool(r["enabled"]),
            "stage": [int(x) for x in str(r["stage"]).replace(" ", "").split(",")
                      if x.isdigit()],
            "portfolio": [x.strip() for x in str(r["portfolio"]).split(",")
                          if x.strip()],
        })
    if not specs:
        st.warning("Nothing to apply.")
        st.stop()
    with guard():
        res = api.overlay_preview(run_id, specs)
    if not res.get("ok"):
        for e in res.get("errors", []):
            st.error(e)
        if res.get("contracts"):
            st.caption("Contracts matched more than once: "
                       + ", ".join(map(str, res["contracts"])))
        st.stop()

    metric_row([
        ("Model ECL", money(res["ecl_model_total"])),
        ("Overlay", money(res["overlay_total"])),
        ("Final ECL", money(res["ecl_final_total"])),
        ("Contracts touched", money(res["contracts_touched"])),
    ])
    st.subheader("Audit trail")
    st.dataframe(pd.DataFrame(res["audit"]), use_container_width=True,
                 hide_index=True)
    caption("Nothing has been written. This is what the overlays would do.")
