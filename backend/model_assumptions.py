"""The model assumptions a run was priced with.

One row per assumption: what is assumed, the value this run used (read from
the run's frozen config, config_used/, where the value is a setting; fixed by
the method otherwise) and the section of the ECL methodology that explains
it. Nothing here is calculated afresh: the values are the ones the run read.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pandas as pd
import yaml

# the engine's defaults when model.yml leaves a setting out (EclConfig)
_DEFAULTS = {"lgd_base": 0.45, "lgd_unsecured_floor": 0.5,
             "stage3_method": "full_outstanding", "cap_ecl_at_exposure": True}


def _sec(ch: str, sec: str) -> str:
    return f"/help_ecl?ch={quote(ch)}&sec={quote(sec)}"


def _pct(x, d: int = 2) -> str:
    try:
        v = float(x) * 100
    except (TypeError, ValueError):
        return "—"
    t = f"{v:.{d}f}"
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t + "%"


def _num(x) -> str:
    try:
        return f"{float(x):.15g}"
    except (TypeError, ValueError):
        return "—"


def _yaml(p: Path) -> dict:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _csv(p: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(p)
    except (OSError, ValueError):
        return pd.DataFrame()


def key_assumptions(run_path, weights: dict | None = None) -> list[dict]:
    """[{area, assumption, value, source, link}] for a run, in the order of
    the methodology."""
    from ifrs9qdb.analytics.model_view import config_used
    cu = config_used(run_path)
    if cu is None:
        return []
    cfg, static = Path(cu["config"]), Path(cu["static"])
    model = _yaml(cfg / "model.yml")
    inputs = _yaml(cfg / "model_inputs.yml")
    ecl = {**_DEFAULTS, **(model.get("ecl") or {})}
    hz = model.get("horizons") or {}
    th = _csv(static / "staging_thresholds.csv")
    thv = dict(zip(th.get("key", []), th.get("value", []))) if len(th) else {}
    sev = _csv(static / "scenario_severity.csv")
    coll = _csv(static / "collateral_types.csv")

    rows: list[dict] = []

    def add(area, assumption, value, source, ch, sec):
        rows.append({"area": area, "assumption": assumption, "value": value,
                     "source": source, "link": _sec(ch, sec)})

    st6 = ("6. Staging", "6.1 The rule")
    dpd2 = thv.get("dpd_stage2_threshold_days", "—")
    add("Staging", "Stage 3: customer's worst days past due above 90, or default flag",
        "90 days", "fixed by the method", *st6)
    add("Staging", "Stage 2: days past due above the threshold (up to 90)",
        f"{dpd2} days", "staging_thresholds.csv", *st6)
    add("Staging", "Stage 2: watchlist, restructured or any local flag; Tasdeer "
        "collectively assessed", "yes", "fixed by the method", *st6)
    add("Staging", "Contagion: one Stage 2 or 3 contract moves the customer's "
        "Stage 1 contracts to Stage 2", "yes", "fixed by the method", *st6)
    add("Staging", "No SICR test against origination PD or rating",
        "not applied", "the extract has no origination data", *st6)

    pd7 = "7. Probability of default"
    m_int = next((m for m in (model.get("models") or {}).values()
                  if str(m.get("rating_type")) == "Internal"), {})
    act = [c for c in m_int.get("mev_components") or [] if float(c.get("weight") or 0) > 0]
    if act:
        c = act[0]
        add("PD", "Internal model: logistic regression of the yearly default rate "
            "on the macro variable",
            f"{c.get('variable')}: α = {_num(c.get('intercept'))}, "
            f"β = {_num(c.get('coefficient'))}", "model.yml", pd7, "7.1 The internal model (lending)")
        add("PD", "Scenario shift: severity z × standard deviation of the variable",
            f"σ = {_num(c.get('standard_deviation'))}", "model.yml", pd7, "7.2 Five scenarios")
    if len(sev):
        add("PD", "Five scenarios and their severity z",
            ", ".join(f"{r.scenario} {float(r.severity_z):+.4f}"
                      for r in sev.itertuples()),
            "scenario_severity.csv", pd7, "7.2 Five scenarios")
    add("PD", "Long-run default rate (TTC anchor)", _pct(model.get("ttc_anchor_pd"), 4),
        "model.yml ttc_anchor_pd", pd7, "7.3 Scaling factor")
    nf = hz.get("n_forecasts", "—")
    mx = hz.get("max_maturity", "—")
    add("PD", "Forecast years, then reversion to the TTC PD (log space)",
        f"{nf} forecast years; TTC by year {mx}", "model.yml horizons", pd7,
        "7.4 Point-in-time PD and reversion to TTC")
    wmode = (inputs.get("internal_scenario_weights") or {}).get("mode", "—")
    if weights and weights.get("internal"):
        wtxt = " / ".join(_pct(v) for v in weights["internal"].values())
        add("PD", "Scenario weights, internal scale (Significant Downturn → "
            "Significant Uptrend)", f"{wtxt} ({wmode})", "model_inputs.yml", pd7,
            "7.6 Scenario weights (internal scale)")
    emode = (inputs.get("external_scenario_weights") or {}).get("mode", "—")
    if weights and weights.get("external"):
        wtxt = " / ".join(_pct(v) for v in weights["external"].values())
        add("PD", "Scenario weights, external scale (average of the forecast years)",
            f"{wtxt} ({emode})", "model_inputs.yml", pd7,
            "7.7 The external model (investments)")
    add("PD", "External model: GCC real GDP growth, Basel asset correlation "
        "R = 24% falling to 12% as PD rises", "yes", "fixed by the method", pd7,
        "7.7 The external model (investments)")
    add("PD", "Yearly marginal PD spread evenly over its 12 months", "yes",
        "fixed by the method", pd7, "7.8 The monthly cumulative PD curve")

    ead = "8. Exposure at default"
    fb = ecl.get("ead_fallback") or {}
    rules = "; ".join(f"{r.get('portfolio') or 'any'} type {r.get('payment_type')}: "
                      f"{r.get('shape')}" for r in fb.get("rules") or [])
    add("EAD", "Exposure from the repayment schedule: balance before each "
        "instalment", "yes", "fixed by the method", ead, "8.1 From the repayment schedule")
    add("EAD", "Contracts without a schedule: shape by portfolio and payment type",
        (rules + "; " if rules else "") + f"otherwise {fb.get('default', 'bullet')}",
        "model.yml ecl.ead_fallback", ead,
        "8.2 Fallback shapes for contracts without a schedule")
    add("EAD", "Off-balance: the extract's amount is priced as it is (no CCF in "
        "the engine)", "yes", "fixed by the method", ead, "8.3 Off-balance products")
    ext = thv.get("maturity_extension_days")
    if ext is not None:
        add("EAD", "Facility past maturity: maturity moved forward",
            f"{ext} days", "staging_thresholds.csv", "4. Preparing the contracts",
            "4.4 Maturity")
    add("EAD", "Horizon: Stage 1 twelve months, Stage 2 the remaining life",
        "12 months / life", "fixed by the method", ead, "8.4 Horizon")

    lgd = "9. Loss given default"
    add("LGD", "Unsecured LGD", _pct(ecl["lgd_base"]), "model.yml ecl.lgd_base",
        lgd, lgd)
    add("LGD", "Minimum unsecured share of the balance", _pct(ecl["lgd_unsecured_floor"]),
        "model.yml ecl.lgd_unsecured_floor", lgd, lgd)
    if len(coll) and "haircut_general" in coll.columns:
        hc = coll.assign(h=pd.to_numeric(coll["haircut_general"], errors="coerce"))
        counted = hc[hc["h"] < 1]
        txt = ", ".join(f"{str(r.description).strip().capitalize()} {_pct(r.h, 0)}"
                        for r in counted.itertuples())
        add("LGD", "Collateral haircuts (net = value × allocation × (1 − haircut))",
            (txt + "; " if txt else "") + "all other types 100%",
            "collateral_types.csv", lgd, lgd)

    e10 = "10. ECL by stage"
    add("ECL", "Discounting monthly at the contract's EIR", "yes",
        "fixed by the method", e10, "10.1 Stage 1 and Stage 2")
    add("ECL", "ECL capped at the balance",
        "yes" if ecl["cap_ecl_at_exposure"] else "no",
        "model.yml ecl.cap_ecl_at_exposure", e10, "10.2 The exposure cap")
    add("ECL", "Stage 3 provision",
        "full outstanding balance" if ecl["stage3_method"] == "full_outstanding"
        else "zero (as LIC)", "model.yml ecl.stage3_method", e10, "10.3 Stage 3")
    return rows
