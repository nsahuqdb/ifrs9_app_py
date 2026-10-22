"""Stress-testing endpoints, one stress function behind all of them.

A package, a what-if on named customers and a staging-policy change are all
``apply_stress`` with a different scope and levers; several are several calls
to /apply, and the lever sensitivity, the reverse stress and the threshold
sweep price through it too.
Loading a run's engine inputs is the slow part -- the eighteen CSVs, the PD
and EAD curves -- so it is cached per run. The pricing itself is fast.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .runs import _output_dir
from ifrs9qdb.analytics import normalise, scenario_files
from ifrs9qdb.inputs import load_engine_inputs
from ifrs9qdb.stress import (
    StressSpec, apply_stress, mev_stress, read_packages,
    reverse_stress_all, roll_forward, scenario_weights_sensitivity,
    staging_threshold, staging_threshold_sweep, standard_packages, tornado,
    write_packages, TORNADO_LEVERS,
)

router = APIRouter(tags=["stress"])
from ..settings import RUNS_DIR, STRESS_PACKAGES_FILE  # noqa: E402


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
    """What a stress can reach and what it starts from: the portfolios (and
    which price against the internal PD curves), the scenarios the run wrote
    curves for, the run's own staging threshold and LGD parameters, the
    standard packages and the levers the sensitivity moves."""
    inputs, report = _load(run_id)
    internal = inputs.internal_portfolios()
    out = _output_dir(RUNS_DIR / run_id)
    return {
        "internal": internal,
        "external": inputs.external_portfolios(),
        "all": sorted(report["portfolio"].dropna().unique().tolist()),
        "scenarios": sorted(scenario_files(out)),
        "run_threshold": staging_threshold(out),
        "lgd_base": inputs.ctx.lgd_base,
        "lgd_floor": inputs.ctx.lgd_floor,
        "standard": [p.to_dict() for p in standard_packages(internal)],
        "levers": TORNADO_LEVERS,
    }


class SpecIn(BaseModel):
    """One stress: who it reaches (portfolios AND stages AND customers, an
    empty list not narrowing it) and what changes. A blank threshold or LGD
    parameter is the run's own."""
    name: str = "Stress"
    portfolios: list[str] = Field(default_factory=list)
    stages: list[int] = Field(default_factory=list)
    customers: list[str] = Field(default_factory=list)
    dpd_threshold: float | None = None
    contagion: bool = True
    tasdeer_collective: bool = True
    watchlist_triggers: bool = True
    local_triggers: bool = True
    stage_to: int | None = None
    default_top_n: int = 0
    pd_multiplier: float = 1.0
    pd_scenario: str = ""
    rating_notches: int = 0
    lgd_base: float | None = None
    lgd_floor: float | None = None
    collateral_pct: float = 100.0
    exposure_pct: float = 100.0
    maturity_years: float = 0.0


def _spec(p: SpecIn) -> StressSpec:
    return StressSpec.from_dict(p.model_dump())


@router.post("/stress/{run_id}/apply")
def apply(run_id: str, spec: SpecIn) -> dict:
    inputs, report = _load(run_id)
    r = apply_stress(inputs, report, _spec(spec))
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not apply the stress."))
    return {
        "name": r["name"], "before": r["before"], "after": r["after"],
        "delta": r["delta"], "priced": r["priced"], "scoped": r["scoped"],
        "moved": r["moved"], "customers_moved": r["customers_moved"],
        "defaulted": r["defaulted"], "notes": r["notes"],
        "by_portfolio": _records(r["by_portfolio"]),
        "migration": _records(r["migration"]),
        "by_customer": _records(r["by_customer"].head(50)),
    }


class PackagesIn(BaseModel):
    packages: list[SpecIn] = Field(default_factory=list)


@router.get("/stress/packages")
def packages_saved() -> list[dict]:
    """The saved packages: the project's config/stress_packages.yml, which
    the R app reads and writes too."""
    return [p.to_dict() for p in read_packages(STRESS_PACKAGES_FILE)]


@router.put("/stress/packages")
def packages_save(body: PackagesIn) -> dict:
    p = write_packages([_spec(x) for x in body.packages], STRESS_PACKAGES_FILE)
    return {"saved": len(body.packages), "path": str(p)}


# ------------------------------------------------------------ sensitivity --
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
    sweep = staging_threshold_sweep(
        inputs, report, thresholds=values,
        base=StressSpec(name="sweep", portfolios=inputs.internal_portfolios()))
    if len(sweep) == 0:
        raise HTTPException(400, "Nothing could be repriced for this run.")
    return {"run_threshold": sweep.attrs["reference"], "rows": _records(sweep)}


# ---------------------------------------------------------- time and macro --
@router.get("/stress/{run_id}/rollforward")
def rollforward(run_id: str, months: int = 12) -> dict:
    inputs, report = _load(run_id)
    r = roll_forward(inputs, report, months, inputs.internal_portfolios())
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not roll forward."))
    return r


class MevIn(BaseModel):
    """An edit to the macro path and the scenario weights. Cells are set
    first, then shocks applied; ``custom`` weights are the internal scale's."""
    cells: list[dict] = Field(default_factory=list,
                              description="rows of {year, idx, value}")
    shock: dict[str, float] = Field(default_factory=dict,
                                    description="MEV index (1-based) -> delta")
    weight_mode: str = "auto"
    weights: dict[str, float] | None = None
    external_weights: dict[str, float] | None = None
    gcc_shock: float = Field(0.0, description="points onto GCC growth, every "
                                               "country and forecast year")


@router.post("/stress/{run_id}/mev")
def mev(run_id: str, body: MevIn) -> dict:
    """Reprice on a different macroeconomic path or scenario weighting.

    The whole PD chain is rebuilt from the run's own frozen config, so the
    shift factors, the scenario curves and the monthly StPD all follow from
    the new path and weights as they would in a real run.
    """
    inputs, report = _load(run_id)
    out = _output_dir(RUNS_DIR / run_id)
    cells = pd.DataFrame(body.cells) if body.cells else None
    try:
        r = mev_stress(inputs, report, out, mev_new=cells,
                       shock={int(k): v for k, v in body.shock.items()},
                       weight_mode=body.weight_mode, weights=body.weights,
                       external_weights=body.external_weights,
                       gcc_shock=body.gcc_shock)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not reprice."))
    return {
        "before": r["before"], "after": r["after"], "delta": r["delta"],
        "provision": r.get("provision"), "note": r.get("note"),
        "priced": r["priced"], "weight_mode": r["weight_mode"],
        "weights_used": r.get("weights_used"),
        "by_portfolio": _records(r["by_portfolio"]),
        "movers": _records(r["movers"].head(50)),
        "path": _records(r["path"]),
    }


class WeightsIn(BaseModel):
    weights: dict[str, float] | None = None


@router.post("/stress/{run_id}/weights-sensitivity")
def weights_sensitivity(run_id: str, body: WeightsIn, shift: float = 0.10) -> list[dict]:
    """Moving ``shift`` of probability onto each scenario in turn, each
    repriced as ``/mev`` does with custom weights."""
    inputs, report = _load(run_id)
    out = _output_dir(RUNS_DIR / run_id)
    return _records(scenario_weights_sensitivity(inputs, report, out,
                                                 body.weights, shift))
