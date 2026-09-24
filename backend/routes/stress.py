"""Stress and what-if endpoints.

Loading a run's engine inputs is the slow part - the eighteen CSVs, the PD and
EAD curves - so it is cached per run. The pricing itself is fast.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .runs import _output_dir
from ifrs9qdb.analytics import normalise
from ifrs9qdb.inputs import load_engine_inputs
from ifrs9qdb.stress import (
    Rule, StressSpec, apply_stress, match_rules, mev_stress, reprice_rules,
    reverse_stress_all, roll_forward, staging_threshold,
    staging_threshold_sweep, tornado, TORNADO_LEVERS,
)

router = APIRouter(tags=["stress"])
RUNS_DIR = Path(os.environ.get("IFRS9_RUNS_DIR", "runs"))


@lru_cache(maxsize=8)
def _load(run_id: str):
    out = _output_dir(RUNS_DIR / run_id)
    if out is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    inputs = load_engine_inputs(out)
    if not inputs.ok:
        raise HTTPException(400, f"Engine inputs missing: {', '.join(inputs.missing)}")
    report_path = out / "FinalEclReport.csv"
    if not report_path.is_file():
        raise HTTPException(404, f"No ECL report for run {run_id!r}")
    return inputs, normalise(pd.read_csv(report_path, low_memory=False))


def _records(df):
    if df is None or len(df) == 0:
        return []
    return df.replace({float("nan"): None}).to_dict(orient="records")


@router.get("/stress/{run_id}/scope")
def scope(run_id: str) -> dict:
    """Portfolios available, and which price against the internal PD curves.

    Externally-rated portfolios do not resolve against those curves, so a
    stress leaves them untouched. They are excluded by default and named, so
    that is visible rather than surprising.
    """
    inputs, report = _load(run_id)
    return {
        "internal": inputs.internal_portfolios(),
        "external": inputs.external_portfolios(),
        "all": sorted(report["portfolio"].dropna().unique().tolist()),
        "levers": TORNADO_LEVERS,
    }


class SpecIn(BaseModel):
    name: str = "Stress"
    portfolios: list[str] = Field(default_factory=list)
    dpd_threshold: float = 60
    contagion: bool = True
    tasdeer_collective: bool = True
    watchlist_triggers: bool = True
    local_triggers: bool = True
    pd_multiplier: float = 1.0
    lgd_base: float = 0.45
    lgd_floor: float = 0.5
    collateral_pct: float = 100.0
    exposure_pct: float = 100.0
    rating_notches: int = 0
    maturity_years: float = 0.0
    default_top_n: int = 0


@router.post("/stress/{run_id}/apply")
def apply(run_id: str, spec: SpecIn) -> dict:
    inputs, report = _load(run_id)
    s = StressSpec(**spec.model_dump())
    if not s.portfolios:
        s.portfolios = inputs.internal_portfolios()
    r = apply_stress(inputs, report, s)
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not apply the stress."))
    return {
        "name": r["name"], "before": r["before"], "after": r["after"],
        "delta": r["delta"], "priced": r["priced"], "moved": r["moved"],
        "customers_moved": r["customers_moved"], "defaulted": r["defaulted"],
        "by_portfolio": _records(r["by_portfolio"]),
        "by_customer": _records(r["by_customer"].head(50)),
    }


@router.get("/stress/{run_id}/rollforward")
def rollforward(run_id: str, months: int = 12) -> dict:
    inputs, report = _load(run_id)
    r = roll_forward(inputs, report, months, inputs.internal_portfolios())
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not roll forward."))
    return r


@router.get("/stress/{run_id}/tornado")
def tornado_run(run_id: str) -> dict:
    inputs, report = _load(run_id)
    t = tornado(inputs, report,
                StressSpec(name="tornado", portfolios=inputs.internal_portfolios()))
    return {"base": t.attrs.get("base"), "levers": _records(t)}


@router.get("/stress/{run_id}/reverse")
def reverse(run_id: str, target_pct: float = 25.0) -> list[dict]:
    inputs, report = _load(run_id)
    out = reverse_stress_all(inputs, report, target_pct,
                             StressSpec(name="reverse",
                                        portfolios=inputs.internal_portfolios()))
    return _records(out)


# --------------------------------------------------- staging and macro -----
@router.get("/stress/{run_id}/threshold-sweep")
def threshold_sweep(run_id: str, thresholds: str = "0,15,30,45,60,75,90") -> dict:
    """Reprice the book at each candidate Stage 2 DPD threshold.

    Rarely a straight line: most of the book is staged by watchlist,
    restructuring and contagion rather than by days past due, so lowering the
    threshold moves far less than people expect. The reference row is whatever
    policy the run itself used.
    """
    inputs, report = _load(run_id)
    try:
        values = [float(t) for t in thresholds.split(",") if t.strip()]
    except ValueError as exc:
        raise HTTPException(400, f"thresholds must be numbers: {exc}") from exc
    if not values:
        raise HTTPException(400, "give at least one threshold")

    out = _output_dir(RUNS_DIR / run_id)
    used = staging_threshold(out)
    if used not in values:
        values = sorted(values + [used])
    sweep = staging_threshold_sweep(
        inputs, report, thresholds=values, reference=used,
        base=StressSpec(name="sweep", portfolios=inputs.internal_portfolios()))
    if len(sweep) == 0:
        raise HTTPException(400, "Nothing could be repriced for this run.")
    return {"run_threshold": used, "rows": _records(sweep)}


class MevIn(BaseModel):
    """An edit to the macro path. Cells are set first, then shocks applied."""
    cells: list[dict] = Field(default_factory=list,
                              description="rows of {year, idx, value}")
    shock: dict[str, float] = Field(default_factory=dict,
                                    description="MEV index (1-based) -> delta")
    weight_mode: str = "auto"
    weights: dict[str, float] | None = None


@router.post("/stress/{run_id}/mev")
def mev(run_id: str, body: MevIn) -> dict:
    """Reprice on a different macroeconomic path.

    The whole PD chain is rebuilt from the run's own frozen config, so the
    shift factors, the scenario curves and the monthly StPD all follow from
    the new path as they would in a real run.
    """
    inputs, report = _load(run_id)
    out = _output_dir(RUNS_DIR / run_id)
    cells = pd.DataFrame(body.cells) if body.cells else None
    try:
        r = mev_stress(inputs, report, out, mev_new=cells,
                       shock={int(k): v for k, v in body.shock.items()},
                       weight_mode=body.weight_mode, weights=body.weights)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not reprice."))
    return {
        "before": r["before"], "after": r["after"], "delta": r["delta"],
        "priced": r["priced"], "weight_mode": r["weight_mode"],
        "by_portfolio": _records(r["by_portfolio"]),
        "movers": _records(r["movers"].head(50)),
        "path": _records(r["path"]),
    }


class RuleIn(BaseModel):
    """One what-if rule: who it applies to, and what changes for them."""
    label: str = "Rule 1"
    customers: list[str] = Field(default_factory=list)
    portfolios: list[str] = Field(default_factory=list)
    stages: list[int] = Field(default_factory=list)
    stage_to: int | None = None
    rating_notches: int = 0
    collateral_pct: float = 100.0
    exposure_pct: float = 100.0
    maturity_years: float = 0.0
    pd_scenario: str = ""


class RulesIn(BaseModel):
    rules: list[RuleIn] = Field(default_factory=list)


@router.post("/stress/{run_id}/whatif/match")
def whatif_match(run_id: str, body: RulesIn) -> dict:
    """Who each rule claims, and which contracts two of them claim.

    Separate from applying them, so a conflict can be seen and resolved before
    anything is priced.
    """
    _, report = _load(run_id)
    if not body.rules:
        raise HTTPException(400, "give at least one rule")
    m = match_rules(report, [Rule(**r.model_dump()) for r in body.rules])
    assignment = m["assignment"]
    labels = [r.label for r in body.rules]
    counts = [{"rule": labels[j],
               "contracts": int((assignment == j).fillna(False).sum())}
              for j in range(len(labels))]
    return {"matched": int(assignment.notna().sum()),
            "contracts": int(len(report)),
            "by_rule": counts,
            "conflicts": _records(m["conflicts"])}


@router.post("/stress/{run_id}/whatif")
def whatif(run_id: str, body: RulesIn) -> dict:
    """Apply the rules and reprice. Rules do not stack."""
    inputs, report = _load(run_id)
    if not body.rules:
        raise HTTPException(400, "give at least one rule")
    r = reprice_rules(inputs, report, [Rule(**x.model_dump()) for x in body.rules])
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not reprice."))
    return {
        "before": r["before"], "after": r["after"], "delta": r["delta"],
        "priced": r["priced"], "matched": r["matched"],
        "by_rule": _records(r["by_rule"]),
        "conflicts": _records(r["conflicts"]),
        "movers": _records(r["movers"].head(50)),
    }
