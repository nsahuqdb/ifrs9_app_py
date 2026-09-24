"""The model configuration behind every run."""
import pandas as pd
import streamlit as st

import api
from ui import caption, guard, metric_row, page_setup, pct

page_setup("Model configuration",
           "What the engine is calibrated to. These change when the model "
           "changes, not per quarter, and a run freezes a copy of whatever it "
           "used.")

with guard():
    cfg = api.config()

s = cfg.get("summary", {})
if cfg.get("summary_error"):
    st.error(cfg["summary_error"])

ecl = s.get("ecl", {}) or {}
hz = s.get("horizons", {}) or {}
metric_row([
    ("TTC anchor PD", f"{s.get('ttc_anchor_pd', '—')}"),
    ("Forecast years", hz.get("n_forecasts", "—")),
    ("Max maturity", f"{hz.get('max_maturity', '—')} yrs"),
    ("LGD base", ecl.get("lgd_base", "—")),
    ("LGD floor", ecl.get("lgd_unsecured_floor", "—")),
])

st.subheader("Settings that change a reported number")
st.dataframe(pd.DataFrame([
    {"Setting": "ecl.stage3_method",
     "Value": ecl.get("stage3_method", "full_outstanding"),
     "Effect": "full_outstanding books Stage 3 at the on-balance amount, the "
               "QDB basis. zero reproduces LIC, which reports nothing."},
    {"Setting": "ecl.cap_ecl_at_exposure",
     "Value": str(ecl.get("cap_ecl_at_exposure", True)),
     "Effect": "Caps the provision at the balance. An EAD curve carrying "
               "undrawn commitments can otherwise exceed it."},
    {"Setting": "ecl.lgd_base / lgd_unsecured_floor",
     "Value": f"{ecl.get('lgd_base', 0.45)} / {ecl.get('lgd_unsecured_floor', 0.5)}",
     "Effect": "Raising the floor bites on SECURED lending: only contracts "
               "already at the floor move."},
]), use_container_width=True, hide_index=True)

st.subheader("Macroeconomic variables")
mev = pd.DataFrame(s.get("mev_components", []))
if len(mev):
    st.dataframe(mev, use_container_width=True, hide_index=True,
                 column_config={"variable": "Variable", "weight": "Model weight",
                                "coefficient": "Coefficient",
                                "intercept": "Intercept",
                                "standard_deviation": "Std dev"})
    zero = mev[pd.to_numeric(mev["weight"], errors="coerce") == 0]
    if len(zero):
        st.warning(
            "**" + ", ".join(zero["variable"]) + "** carry a model weight of "
            "zero, so shocking them changes nothing at all. That is the "
            "calibration, not a fault — but a property-price stress returning "
            "zero is not a broken tool.", icon="⚠️")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Macro forecast")
    fc = s.get("mev_forecasts", {})
    if fc:
        rows = [{"Year": y, **{f"MEV {i+1}": v for i, v in enumerate(vals)}}
                for y, vals in sorted(fc.items(), key=lambda kv: int(kv[0]))]
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)
        caption("Only years 1 and 2 of the first variable feed the scenario "
                "weights; later years change the PD curves but not the "
                "probabilities.")
with c2:
    st.subheader("Scenario weights")
    w = s.get("scenario_weights", {})
    if w:
        st.dataframe(
            pd.DataFrame({"Scenario": list(w), "Weight": [f"{v:.2%}" for v in w.values()]}),
            use_container_width=True, hide_index=True)
        caption("Computed from where the GDP forecast falls on the historical "
                "distribution; the values in the file are a rounded snapshot "
                "of that calculation.")

st.divider()
st.subheader("Edit")
st.caption("Saved only if the file still parses as YAML. A run freezes its own "
           "copy, so past runs are unaffected.")
name = st.selectbox("File", list(cfg.get("files", {})))
if name:
    text = st.text_area("Contents", cfg["files"][name], height=380,
                        label_visibility="collapsed")
    if st.button("Save", type="primary"):
        try:
            api.config_save(name, text)
            st.success(f"{name} saved.")
            api.config.clear()
        except api.BackendError as e:
            st.error(str(e))
